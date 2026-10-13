"""Human review: correct, approve, reject, reopen.

Corrections change the current extraction in place. The value the model originally read is
kept in corrections_json ({field: {"before": original, "after": latest}}) and every change is
written to the audit log with the reviewer and time. After a correction the field rules run
again (the model-level flags from extraction time stay, as history).
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.calc.service import calculate_bill
from app.enums import BillStatus, UtilityType
from app.models import Bill, Extraction, Facility, FacilityAccount, User
from app.pipeline.runner import build_context
from app.pipeline.validate import BLOCKING_CODES, LLM_LEVEL_CODES, Fields, validate_fields


class ReviewError(ValueError):
    """Shown to the reviewer. `status` is the HTTP status the API should use."""

    def __init__(self, message: str, status: int = 422, details: list | None = None):
        super().__init__(message)
        self.status = status
        self.details = details


def _text(max_len: int):
    def parse(v) -> str:
        v = str(v).strip()
        if len(v) > max_len:
            raise ValueError
        return v
    return parse


def _decimal(v) -> Decimal:
    if isinstance(v, float):
        raise ValueError  # send numbers as strings so they stay exact
    d = Decimal(str(v).strip().replace(",", ""))
    if not d.is_finite() or d.as_tuple().exponent < -6:
        raise ValueError  # stored with 6 decimal places; never round a reviewer's number silently
    return d.quantize(Decimal("0.000001"))


def _read_type(v) -> str:
    if v not in ("actual", "estimated", "unknown"):
        raise ValueError
    return v


# Fields a reviewer may correct on the extraction, with their parsers.
EXTRACTION_FIELDS = {
    "provider_name": _text(200),
    "account_number": _text(100),
    "billing_period_start": date.fromisoformat,
    "billing_period_end": date.fromisoformat,
    "quantity": _decimal,
    "unit": _text(20),
    "meter_previous": _decimal,
    "meter_current": _decimal,
    "meter_multiplier": _decimal,
    "read_type": _read_type,
}
BILL_FIELDS = {"utility_type", "facility_id"}


def _jsonable(v):
    if isinstance(v, (Decimal, uuid.UUID)):
        return str(v)
    if isinstance(v, date):
        return v.isoformat()
    return v


def _parse(field: str, value):
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    try:
        return EXTRACTION_FIELDS[field](value)
    except (ValueError, TypeError, ArithmeticError):
        raise ReviewError(f"{field}: {value!r} is not valid") from None


def load_for_review(db: Session, org_id: uuid.UUID, extraction_id: uuid.UUID,
                    expected_updated_at: datetime | None) -> tuple[Bill, Extraction]:
    e = db.get(Extraction, extraction_id)
    bill = db.get(Bill, e.bill_id) if e else None
    if e is None or bill is None or bill.org_id != org_id:
        raise ReviewError("Extraction not found", 404)
    if not e.is_current:
        raise ReviewError("This extraction has been replaced by a newer one; reload the bill", 409)
    if expected_updated_at is not None and _naive(bill.updated_at) != _naive(expected_updated_at):
        raise ReviewError("Someone else changed this bill while you were reviewing it; reload to see their changes", 409)
    return bill, e


def _naive(dt: datetime) -> datetime:
    # SQLite drops tz info; compare instants consistently.
    return dt.astimezone(UTC).replace(tzinfo=None) if dt.tzinfo else dt


def apply_corrections(db: Session, bill: Bill, e: Extraction, changes: dict, user: User, reason: str | None) -> dict:
    """Apply reviewer changes, re-run the field rules, and audit. Returns the changed fields."""
    if bill.status != BillStatus.needs_review:
        raise ReviewError(f"Only bills in review can be corrected (this one is '{bill.status}'). Reopen it first.", 409)
    unknown = set(changes) - set(EXTRACTION_FIELDS) - BILL_FIELDS
    if unknown:
        raise ReviewError(f"These fields can't be corrected: {', '.join(sorted(unknown))}")

    changed: dict[str, dict] = {}
    for field, raw in changes.items():
        if field == "utility_type":
            if raw not in UtilityType.__members__:
                raise ReviewError("utility_type must be electricity or natural_gas")
            before, after = bill.utility_type, raw
        elif field == "facility_id":
            try:
                fid = uuid.UUID(str(raw))
            except ValueError:
                raise ReviewError("facility_id is not valid") from None
            facility = db.get(Facility, fid)
            if facility is None or facility.org_id != bill.org_id:
                raise ReviewError("Facility not found", 404)
            before, after = bill.facility_id, fid
        else:
            before, after = getattr(e, field), _parse(field, raw)
            if isinstance(before, Decimal) and isinstance(after, Decimal) and before == after:
                continue  # 12500.000000 vs "12500" is no change
        if before == after:
            continue
        changed[field] = {"before": _jsonable(before), "after": _jsonable(after)}
        if field == "utility_type":
            bill.utility_type = after
        elif field == "facility_id":
            bill.facility_id = after
        else:
            setattr(e, field, after)

    if not changed:
        return {}

    # Keep the model's original value as "before" across repeated corrections.
    history = dict(e.corrections_json or {})
    for field, ch in changed.items():
        original = history.get(field, {}).get("before", ch["before"])
        history[field] = {"before": original, "after": ch["after"]}
        if history[field]["before"] == history[field]["after"]:
            del history[field]  # corrected back to what the model read
    e.corrections_json = history or None

    revalidate(db, bill, e)
    bill.updated_at = datetime.now(UTC)
    db.flush()
    audit.record(db, actor=str(user.id), action="correct", entity="extraction", entity_id=e.id,
                 org_id=bill.org_id, before={k: v["before"] for k, v in changed.items()},
                 after={**{k: v["after"] for k, v in changed.items()}, "reason": reason, "bill_id": str(bill.id)})
    return changed


def fields_of(bill: Bill, e: Extraction) -> Fields:
    return Fields(bill.utility_type or "unknown", e.unit, e.billing_period_start, e.billing_period_end, e.quantity,
                  e.meter_previous, e.meter_current, e.meter_multiplier, e.account_number)


def revalidate(db: Session, bill: Bill, e: Extraction, today: date | None = None) -> list[dict]:
    fields = fields_of(bill, e)
    ctx = build_context(db, bill, fields, today or date.today())
    result = validate_fields(fields, ctx)
    kept = [i for i in (e.validation_issues_json or []) if i["code"] in LLM_LEVEL_CODES]
    e.validation_issues_json = kept + [i.to_dict() for i in result.issues]
    if result.canonical_unit and e.unit != result.canonical_unit:
        e.unit = result.canonical_unit
    return e.validation_issues_json


def approve(db: Session, bill: Bill, e: Extraction, user: User, *, remap_account: bool = False,
            note: str | None = None) -> None:
    if bill.status != BillStatus.needs_review:
        raise ReviewError(f"Only bills in review can be approved (this one is '{bill.status}')", 409)
    issues = revalidate(db, bill, e)
    blocking = [i for i in issues if i["code"] in BLOCKING_CODES]
    if blocking:
        raise ReviewError("Fix these before approving: " + "; ".join(i["message"] for i in blocking), 422, blocking)

    mapping_change = None
    if e.account_number and bill.utility_type:
        mapping = db.scalars(select(FacilityAccount).where(
            FacilityAccount.org_id == bill.org_id, FacilityAccount.utility_type == bill.utility_type,
            FacilityAccount.account_number == e.account_number)).first()
        if mapping is None:
            db.add(FacilityAccount(org_id=bill.org_id, facility_id=bill.facility_id,
                                   utility_type=bill.utility_type, account_number=e.account_number))
            mapping_change = {"account": e.account_number, "facility_id": str(bill.facility_id), "action": "created"}
        elif mapping.facility_id != bill.facility_id:
            if not remap_account:
                other = db.get(Facility, mapping.facility_id)
                raise ReviewError(
                    f"Account {e.account_number} is assigned to facility '{other.name}'. Either change this bill's "
                    f"facility, or confirm that the account has moved to this facility.", 409,
                    [{"code": "account_other_facility", "facility_id": str(other.id), "facility_name": other.name}])
            mapping_change = {"account": e.account_number, "from_facility_id": str(mapping.facility_id),
                              "to_facility_id": str(bill.facility_id), "action": "remapped"}
            mapping.facility_id = bill.facility_id

    before = {"status": bill.status}
    now = datetime.now(UTC)
    bill.status = BillStatus.approved
    bill.updated_at = now
    e.reviewed_by = user.id
    e.reviewed_at = now
    db.flush()
    audit.record(db, actor=str(user.id), action="approve", entity="bill", entity_id=bill.id, org_id=bill.org_id,
                 before=before, after={"status": bill.status, "extraction_id": str(e.id), "note": note,
                                       "acknowledged_issues": [i["code"] for i in issues],
                                       "account_mapping": mapping_change})
    calculate_bill(db, bill, actor=str(user.id), reason="approved by reviewer")


def reject(db: Session, bill: Bill, e: Extraction, user: User, reason: str) -> None:
    if bill.status != BillStatus.needs_review:
        raise ReviewError(f"Only bills in review can be rejected (this one is '{bill.status}')", 409)
    if not reason or len(reason.strip()) < 3:
        raise ReviewError("Give a reason for rejecting the bill")
    before = {"status": bill.status}
    now = datetime.now(UTC)
    bill.status = BillStatus.rejected
    bill.updated_at = now
    e.reviewed_by = user.id
    e.reviewed_at = now
    db.flush()
    audit.record(db, actor=str(user.id), action="reject", entity="bill", entity_id=bill.id, org_id=bill.org_id,
                 before=before, after={"status": bill.status, "reason": reason.strip()})
    calculate_bill(db, bill, actor=str(user.id), reason="rejected by reviewer")  # retires any records


def reopen(db: Session, bill: Bill, user: User, reason: str) -> None:
    """Send an approved or rejected bill back to review. Its emissions leave the totals until re-approved."""
    if bill.status not in (BillStatus.approved, BillStatus.rejected):
        raise ReviewError(f"Only approved or rejected bills can be reopened (this one is '{bill.status}')", 409)
    if not reason or len(reason.strip()) < 3:
        raise ReviewError("Give a reason for reopening the bill")
    e = db.scalars(select(Extraction).where(Extraction.bill_id == bill.id, Extraction.is_current.is_(True))).first()
    if e is None:
        raise ReviewError("This bill has no extraction to review", 409)
    before = {"status": bill.status, "reviewed_by": str(e.reviewed_by) if e.reviewed_by else None}
    bill.status = BillStatus.needs_review
    bill.updated_at = datetime.now(UTC)
    e.reviewed_by = None
    e.reviewed_at = None
    db.flush()
    calculate_bill(db, bill, actor=str(user.id), reason="reopened for review")
    revalidate(db, bill, e)
    audit.record(db, actor=str(user.id), action="reopen", entity="bill", entity_id=bill.id, org_id=bill.org_id,
                 before=before, after={"status": bill.status, "reason": reason.strip()})
