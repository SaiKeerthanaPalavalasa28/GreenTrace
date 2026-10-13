"""Database side of the calculation: load factors, store emission records with their trace,
and recalculate when inputs change. The math itself is in engine.py.

Records are never edited or deleted. A recalculation that changes anything marks the old
records is_current=False and adds new ones; a recalculation that changes nothing is a no-op.
"""

import logging
import uuid
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import audit
from app.calc.engine import CalcInput, CalculationError, calculate
from app.calc.factors import FactorData
from app.enums import BillStatus
from app.models import Bill, EmissionFactor, EmissionRecord, Extraction, Facility, Organization

log = logging.getLogger(__name__)


def to_factor_data(f: EmissionFactor) -> FactorData:
    return FactorData(
        id=f.id, factor_key=f.factor_key, version=f.version, org_id=f.org_id,
        utility_type=f.utility_type, region=f.region, unit=f.unit,
        kgco2e_per_unit=Decimal(f.kgco2e_per_unit), ghg_basis=f.ghg_basis, scope=f.scope,
        source_name=f.source_name, source_url=f.source_url, publication_year=f.publication_year,
        valid_from=f.valid_from, valid_to=f.valid_to, derivation=f.derivation,
        superseded=f.superseded_by is not None,
    )


def load_candidates(db: Session, org_id: uuid.UUID, utility_type: str) -> list[FactorData]:
    rows = db.scalars(select(EmissionFactor).where(
        EmissionFactor.utility_type == utility_type,
        or_(EmissionFactor.org_id.is_(None), EmissionFactor.org_id == org_id),
    ))
    return [to_factor_data(f) for f in rows]


def current_extraction(db: Session, bill_id: uuid.UUID) -> Extraction | None:
    return db.scalars(
        select(Extraction).where(Extraction.bill_id == bill_id, Extraction.is_current.is_(True))
    ).first()


def current_records(db: Session, bill_id: uuid.UUID) -> list[EmissionRecord]:
    return list(db.scalars(
        select(EmissionRecord)
        .join(Extraction, Extraction.id == EmissionRecord.extraction_id)
        .where(Extraction.bill_id == bill_id, EmissionRecord.is_current.is_(True))
        .order_by(EmissionRecord.allocation_start)
    ))


def _retire(db: Session, records: list[EmissionRecord]) -> None:
    for r in records:
        r.is_current = False
    db.flush()  # sessions don't autoflush; later queries in this transaction must see it


def _summary(records) -> dict:
    return {
        "record_ids": [str(r.id) for r in records],
        "kgco2e": str(sum((Decimal(r.kgco2e) for r in records), Decimal(0))),
        "factors": sorted({str(r.emission_factor_id) for r in records}),
    }


def calculate_bill(db: Session, bill: Bill, *, actor: str, reason: str) -> str:
    """(Re)calculate an approved bill. Returns "calculated", "unchanged", or "error".
    Does not commit."""
    old = current_records(db, bill.id)
    extraction = current_extraction(db, bill.id)
    if bill.status != BillStatus.approved or extraction is None:
        if old:
            _retire(db, old)
            audit.record(db, actor=actor, action="retire_emissions", entity="bill", entity_id=bill.id,
                         org_id=bill.org_id, before=_summary(old), after={"reason": reason})
        bill.calculation_error = None
        return "unchanged" if not old else "calculated"

    facility = db.get(Facility, bill.facility_id)
    org = db.get(Organization, bill.org_id)
    inp = CalcInput(
        utility_type=bill.utility_type or "",
        region=facility.region,
        period_start=extraction.billing_period_start,
        period_end=extraction.billing_period_end,
        unit=extraction.unit,
        quantity=_dec(extraction.quantity),
        meter_previous=_dec(extraction.meter_previous),
        meter_current=_dec(extraction.meter_current),
        meter_multiplier=_dec(extraction.meter_multiplier),
        org_id=bill.org_id,
        fiscal_year_start_month=org.fiscal_year_start_month,
    )
    try:
        result = calculate(inp, load_candidates(db, bill.org_id, inp.utility_type) if inp.utility_type else [])
    except CalculationError as e:
        if old:
            _retire(db, old)  # stale numbers must not stay in reported totals
        changed = bill.calculation_error != str(e) or bool(old)
        bill.calculation_error = str(e)
        if changed:
            audit.record(db, actor=actor, action="calculation_failed", entity="bill", entity_id=bill.id,
                         org_id=bill.org_id, before=_summary(old) if old else None,
                         after={"error": str(e), "reason": reason})
        return "error"

    new_sig = sorted((s.factor.id, s.start, s.end, s.kgco2e) for s in result.segments)
    old_sig = sorted((r.emission_factor_id, r.allocation_start, r.allocation_end, Decimal(r.kgco2e)) for r in old)
    if old and old_sig == new_sig and all(r.extraction_id == extraction.id for r in old):
        bill.calculation_error = None
        return "unchanged"

    _retire(db, old)
    bill_trace = {
        "bill": {
            "id": str(bill.id),
            "file_name": bill.original_filename,
            "file_sha256": bill.file_hash,
            "facility": facility.name,
            "facility_region": facility.region,
            "uploaded_at": bill.uploaded_at.isoformat(),
        },
        "extraction": {
            "id": str(extraction.id),
            "page_number": extraction.page_number,
            "source_snippet": extraction.raw_text_snippet,
            "text_method": extraction.text_method,
            "model_used": extraction.model_used,
            "confidence": extraction.confidence,
            "account_number": extraction.account_number,
            "reviewed_by": str(extraction.reviewed_by) if extraction.reviewed_by else None,
            "reviewed_at": extraction.reviewed_at.isoformat() if extraction.reviewed_at else None,
            "approval": "human" if extraction.reviewed_by else "automatic (all validation rules passed)",
            "corrections": extraction.corrections_json,
        },
    }
    new = []
    for s in result.segments:
        rec = EmissionRecord(
            extraction_id=extraction.id,
            emission_factor_id=s.factor.id,
            allocation_start=s.start,
            allocation_end=s.end,
            allocation_fraction=s.fraction,
            normalized_quantity=s.normalized_quantity,
            normalized_unit=s.normalized_unit,
            kgco2e=s.kgco2e,
            scope=s.scope,
            calculation_trace_json={**bill_trace, **s.trace},
        )
        db.add(rec)
        new.append(rec)
    db.flush()
    bill.calculation_error = None
    audit.record(db, actor=actor, action="recalculate" if old else "calculate", entity="bill", entity_id=bill.id,
                 org_id=bill.org_id, before=_summary(old) if old else None,
                 after={**_summary(new), "reason": reason})
    return "calculated"


def recalculate(db: Session, *, actor: str, reason: str, org_id: uuid.UUID | None = None,
                utility_type: str | None = None) -> dict[str, int]:
    """Recalculate approved bills (optionally one org / utility). Idempotent: bills whose
    result is unchanged are left alone. Does not commit."""
    q = select(Bill).where(Bill.status == BillStatus.approved)
    if org_id is not None:
        q = q.where(Bill.org_id == org_id)
    if utility_type is not None:
        q = q.where(Bill.utility_type == utility_type)
    stats = {"calculated": 0, "unchanged": 0, "error": 0}
    for bill in db.scalars(q).all():
        stats[calculate_bill(db, bill, actor=actor, reason=reason)] += 1
    if stats["calculated"] or stats["error"]:
        log.info("Recalculated (%s): %s", reason, stats)
    return stats


def _dec(v) -> Decimal | None:
    return None if v is None else Decimal(v)
