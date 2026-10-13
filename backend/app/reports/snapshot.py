"""The report snapshot: every fact the PDF shows, frozen as JSON at generation time.

The PDF is rendered from the snapshot alone (never from the live database), so a stored
snapshot reproduces its report exactly, even after bills are corrected or factors versioned.
Numbers are decimal strings; nothing in the snapshot is a float.
"""

import hashlib
import json
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calc.engine import ENGINE_VERSION, kg_to_tonnes
from app.calc.prorate import reporting_year_label
from app.dashboard import Filters, status_counts
from app.enums import BillStatus
from app.models import Bill, EmissionFactor, EmissionRecord, Extraction, Facility, Organization, User

SCHEMA_VERSION = 1


def canonical_json(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()


def snapshot_sha256(data: dict) -> str:
    return hashlib.sha256(canonical_json(data)).hexdigest()


def _kg(d) -> str:
    return str(Decimal(d))


def build_snapshot(db: Session, *, org: Organization, user: User, report_id: uuid.UUID,
                   period_start: date, period_end: date, label: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    rows = db.execute(
        select(EmissionRecord, Extraction, Bill, Facility, EmissionFactor)
        .join(Extraction, Extraction.id == EmissionRecord.extraction_id)
        .join(Bill, Bill.id == Extraction.bill_id)
        .join(Facility, Facility.id == Bill.facility_id)
        .join(EmissionFactor, EmissionFactor.id == EmissionRecord.emission_factor_id)
        .where(
            Bill.org_id == org.id,
            Bill.status == BillStatus.approved,
            EmissionRecord.is_current.is_(True),
            EmissionRecord.allocation_start >= period_start,
            EmissionRecord.allocation_end <= period_end,
        )
        .order_by(Facility.name, Bill.utility_type, EmissionRecord.allocation_start, Bill.original_filename)
    ).all()

    reviewer_ids = {e.reviewed_by for _, e, _, _, _ in rows if e.reviewed_by}
    reviewers = {u.id: u for u in db.scalars(select(User).where(User.id.in_(reviewer_ids)))} if reviewer_ids else {}

    records, factors = [], {}
    for rec, e, bill, facility, f in rows:
        t = rec.calculation_trace_json
        reviewer = reviewers.get(e.reviewed_by)
        records.append({
            "record_id": str(rec.id),
            "bill_id": str(bill.id),
            "file_name": bill.original_filename,
            "file_sha256": bill.file_hash,
            "facility": facility.name,
            "facility_region": facility.region,
            "utility_type": bill.utility_type,
            "scope": rec.scope,
            "billing_period": [e.billing_period_start.isoformat(), e.billing_period_end.isoformat()],
            "allocation": [rec.allocation_start.isoformat(), rec.allocation_end.isoformat()],
            "allocation_fraction": t["allocation"]["fraction"],
            "month": rec.allocation_start.strftime("%Y-%m"),
            "bill_quantity": t["quantity"]["value"],
            "bill_unit": t["quantity"]["unit"],
            "quantity_source": t["quantity"]["source"],
            "normalized_quantity": _kg(rec.normalized_quantity),
            "normalized_unit": rec.normalized_unit,
            "factor_id": str(f.id),
            "kgco2e": _kg(rec.kgco2e),
            "ghg_basis": f.ghg_basis,
            "formula": t["formula"],
            "page_number": e.page_number,
            "approval": "human" if e.reviewed_by else "automatic",
            "reviewed_by": reviewer.email if reviewer else None,
            "reviewed_at": e.reviewed_at.isoformat() if e.reviewed_at else None,
            "corrections": e.corrections_json or {},
        })
        factors[str(f.id)] = {
            "id": str(f.id), "key": f.factor_key, "version": f.version, "owner": "organization" if f.org_id else "global",
            "utility_type": f.utility_type, "region": f.region, "scope": f.scope,
            "kgco2e_per_unit": _kg(f.kgco2e_per_unit), "unit": f.unit, "ghg_basis": f.ghg_basis,
            "source_name": f.source_name, "source_url": f.source_url, "publication_year": f.publication_year,
            "valid_from": f.valid_from.isoformat(), "valid_to": f.valid_to.isoformat() if f.valid_to else None,
            "derivation": f.derivation, "superseded": f.superseded_by is not None,
        }

    excluded = _excluded_bills(db, org.id, period_start, period_end)
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "report_id": str(report_id),
        "generated_at": now.isoformat(),
        "generated_by": {"id": str(user.id), "email": user.email, "name": user.full_name},
        "organization": {
            "id": str(org.id), "name": org.name, "reporting_framework": org.reporting_framework,
            "default_region": org.default_region, "fiscal_year_start_month": org.fiscal_year_start_month,
        },
        "period": {"start": period_start.isoformat(), "end": period_end.isoformat(), "label": label},
        "engine_version": ENGINE_VERSION,
        "records": records,
        "factors": sorted(factors.values(), key=lambda f: (f["utility_type"], f["region"], f["valid_from"], f["key"])),
        "excluded_bills": excluded,
    }
    snapshot["summary"] = summarize_snapshot(snapshot)
    return snapshot


def _excluded_bills(db: Session, org_id: uuid.UUID, start: date, end: date) -> list[dict]:
    """Bills that may belong to the period but are not in the totals (same rule as the dashboard)."""
    counts = status_counts(db, Filters(org_id, start, end))
    if not any(counts.values()):
        return []
    q = (
        select(Bill, Facility.name, Extraction)
        .join(Facility, Facility.id == Bill.facility_id)
        .outerjoin(Extraction, (Extraction.bill_id == Bill.id) & Extraction.is_current.is_(True))
        .where(Bill.org_id == org_id, Bill.status.not_in([BillStatus.rejected]))
        .order_by(Facility.name, Bill.original_filename)
    )
    out = []
    for bill, facility_name, e in db.execute(q).all():
        if bill.status == BillStatus.approved and not bill.calculation_error:
            continue
        s, en = (e.billing_period_start, e.billing_period_end) if e else (None, None)
        if s and en and not (s <= end and start <= en):
            continue
        reason = {
            BillStatus.needs_review: "awaiting review",
            BillStatus.uploaded: "processing",
            BillStatus.processing: "processing",
            BillStatus.failed: f"extraction failed: {bill.failure_reason}",
        }.get(bill.status, f"not calculated: {bill.calculation_error}")
        out.append({"bill_id": str(bill.id), "file_name": bill.original_filename, "facility": facility_name,
                    "status": bill.status, "billing_period": [s.isoformat(), en.isoformat()] if s and en else None,
                    "reason": reason})
    return out


def summarize_snapshot(snapshot: dict) -> dict:
    """Aggregates derived purely from snapshot records (exact Decimal kg, tonnes rounded once)."""
    zero = Decimal(0)
    scope = defaultdict(lambda: zero)
    month = defaultdict(lambda: defaultdict(lambda: zero))
    facility = defaultdict(lambda: defaultdict(lambda: zero))
    basis = defaultdict(lambda: zero)
    bills, human = set(), set()
    for r in snapshot["records"]:
        kg = Decimal(r["kgco2e"])
        scope[r["scope"]] += kg
        month[r["month"]][r["scope"]] += kg
        facility[r["facility"]][r["scope"]] += kg
        basis[r["ghg_basis"]] += kg
        bills.add(r["bill_id"])
        if r["approval"] == "human":
            human.add(r["bill_id"])
    total = scope[1] + scope[2]

    start = date.fromisoformat(snapshot["period"]["start"])
    end = date.fromisoformat(snapshot["period"]["end"])
    months, d = [], start
    while d <= end:
        key = f"{d.year:04d}-{d.month:02d}"
        months.append({"month": key, "scope1_kg": str(month[key][1]), "scope2_kg": str(month[key][2]),
                       "total_kg": str(month[key][1] + month[key][2])})
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)

    return {
        "total_kg": str(total),
        "scope1_kg": str(scope[1]),
        "scope2_kg": str(scope[2]),
        "total_t": str(kg_to_tonnes(total)),
        "scope1_t": str(kg_to_tonnes(scope[1])),
        "scope2_t": str(kg_to_tonnes(scope[2])),
        "co2_only_kg": str(basis.get("CO2", zero)),
        "bills_included": len(bills),
        "bills_human_reviewed": len(human),
        "bills_excluded": len(snapshot["excluded_bills"]),
        "is_draft": len(snapshot["excluded_bills"]) > 0,
        "monthly": months,
        "by_facility": [
            {"facility": name, "scope1_kg": str(v[1]), "scope2_kg": str(v[2]), "total_kg": str(v[1] + v[2])}
            for name, v in sorted(facility.items(), key=lambda kv: -(kv[1][1] + kv[1][2]))
        ],
        "reporting_year": reporting_year_label(start, snapshot["organization"]["fiscal_year_start_month"]),
    }
