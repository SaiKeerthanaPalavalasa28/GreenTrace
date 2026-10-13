"""Dashboard aggregation. Totals include current emission records of APPROVED bills only, and
the response always says how many bills are not (yet) in them, so a partial total can't be
mistaken for a final one.

Sums are done in Python with Decimal (in kg), then converted to tonnes once, so totals are
exact and independent of the database's numeric handling.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.calc.engine import kg_to_tonnes
from app.calc.prorate import reporting_year_label, reporting_year_start
from app.enums import BillStatus
from app.models import Bill, EmissionFactor, EmissionRecord, Extraction, Facility, Organization

DONUT_SLICES = 3  # top facilities shown as slices; the rest fold into "Other"


@dataclass
class Filters:
    org_id: uuid.UUID
    period_start: date
    period_end: date
    facility_id: uuid.UUID | None = None
    utility_type: str | None = None


def reporting_years(db: Session, org: Organization, today: date) -> list[dict]:
    """Reporting years that have emission records, plus the current one, newest first."""
    fy = org.fiscal_year_start_month
    rows = db.scalars(
        select(EmissionRecord.allocation_start)
        .join(Extraction, Extraction.id == EmissionRecord.extraction_id)
        .join(Bill, Bill.id == Extraction.bill_id)
        .where(Bill.org_id == org.id, EmissionRecord.is_current.is_(True))
    )
    with_data = {reporting_year_start(d, fy) for d in rows}
    out = []
    for s in sorted(with_data | {reporting_year_start(today, fy)}, reverse=True):
        end = date(s.year + 1, s.month, 1) - timedelta(days=1)
        out.append({"label": reporting_year_label(s, fy), "start": s, "end": end, "has_data": s in with_data})
    return out


def _months(start: date, end: date) -> list[str]:
    out, d = [], date(start.year, start.month, 1)
    while d <= end:
        out.append(f"{d.year:04d}-{d.month:02d}")
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return out


def _t(kg: Decimal) -> str:
    return str(kg_to_tonnes(kg))


def _pct(part: Decimal, whole: Decimal) -> str | None:
    if whole == 0:
        return None
    return str((part * 100 / whole).quantize(Decimal("0.1"), rounding=ROUND_HALF_EVEN))


def summarize(db: Session, f: Filters) -> dict:
    # ---- approved, calculated emissions inside the period
    q = (
        select(EmissionRecord, Bill.facility_id, Bill.utility_type, EmissionFactor.ghg_basis)
        .join(Extraction, Extraction.id == EmissionRecord.extraction_id)
        .join(Bill, Bill.id == Extraction.bill_id)
        .join(EmissionFactor, EmissionFactor.id == EmissionRecord.emission_factor_id)
        .where(
            Bill.org_id == f.org_id,
            Bill.status == BillStatus.approved,
            EmissionRecord.is_current.is_(True),
            # Records are month segments, so each lies wholly inside or outside a month-aligned period.
            EmissionRecord.allocation_start >= f.period_start,
            EmissionRecord.allocation_end <= f.period_end,
        )
    )
    if f.facility_id:
        q = q.where(Bill.facility_id == f.facility_id)
    if f.utility_type:
        q = q.where(Bill.utility_type == f.utility_type)

    zero = Decimal(0)
    by_scope: dict[int, Decimal] = defaultdict(lambda: zero)
    by_month: dict[str, dict[int, Decimal]] = defaultdict(lambda: defaultdict(lambda: zero))
    by_facility: dict[uuid.UUID, Decimal] = defaultdict(lambda: zero)
    by_basis: dict[str, Decimal] = defaultdict(lambda: zero)
    included_bills: set[uuid.UUID] = set()  # by current extraction (one per bill)
    for rec, facility_id, _utility, basis in db.execute(q).all():
        kg = Decimal(rec.kgco2e)
        by_scope[rec.scope] += kg
        by_month[rec.allocation_start.strftime("%Y-%m")][rec.scope] += kg
        by_facility[facility_id] += kg
        by_basis[basis] += kg
        included_bills.add(rec.extraction_id)
    total = sum(by_scope.values(), zero)

    names = dict(db.execute(select(Facility.id, Facility.name).where(Facility.org_id == f.org_id)).all())
    facilities = sorted(by_facility.items(), key=lambda kv: (-kv[1], names.get(kv[0], "")))
    facility_rows = [
        {"facility_id": fid, "name": names.get(fid, "?"), "tco2e": _t(kg), "share_pct": _pct(kg, total)}
        for fid, kg in facilities
    ]
    donut = [
        {"key": str(fid), "name": names.get(fid, "?"), "tco2e": _t(kg), "share_pct": _pct(kg, total)}
        for fid, kg in facilities[:DONUT_SLICES]
    ]
    rest = sum((kg for _, kg in facilities[DONUT_SLICES:]), zero)
    if rest:
        n = len(facilities) - DONUT_SLICES
        donut.append({"key": "other", "name": f"Other ({n} facilities)", "tco2e": _t(rest), "share_pct": _pct(rest, total)})

    monthly = []
    for m in _months(f.period_start, f.period_end):
        s1, s2 = by_month[m][1], by_month[m][2]
        monthly.append({"month": m, "scope1_tco2e": _t(s1), "scope2_tco2e": _t(s2), "total_tco2e": _t(s1 + s2)})

    counts = status_counts(db, f)
    excluded = sum(counts.values())

    return {
        "period": {"start": f.period_start, "end": f.period_end},
        "totals": {
            "tco2e": _t(total),
            "scope1_tco2e": _t(by_scope[1]),
            "scope2_tco2e": _t(by_scope[2]),
            "scope1_share_pct": _pct(by_scope[1], total),
            "scope2_share_pct": _pct(by_scope[2], total),
            "kgco2e": str(total),
            # Each figure is rounded from exact kg, so displayed parts can differ from the
            # displayed total by 0.001 t; the UI then shows a rounding note.
            "parts_sum_differs": kg_to_tonnes(by_scope[1]) + kg_to_tonnes(by_scope[2]) != kg_to_tonnes(total),
        },
        "bills": {"included": len(included_bills), **counts},
        "completeness": {
            "is_partial": excluded > 0,
            "excluded_bills": excluded,
        },
        "ghg_basis": {
            # CEA grid factors cover CO2 only; reports must say so.
            "co2_only_tco2e": _t(by_basis.get("CO2", zero)),
            "co2e_tco2e": _t(by_basis.get("CO2e", zero)),
        },
        "monthly": monthly,
        "by_facility": facility_rows,
        "facility_donut": donut,
    }


def status_counts(db: Session, f: Filters) -> dict[str, int]:
    """Bills NOT counted in the totals that may belong to this period. A bill whose period
    is unknown (not yet extracted, failed, or missing dates) is counted: it might belong."""
    q = (
        select(Bill.status, Bill.calculation_error, Extraction.billing_period_start, Extraction.billing_period_end)
        .outerjoin(Extraction, (Extraction.bill_id == Bill.id) & Extraction.is_current.is_(True))
        .where(Bill.org_id == f.org_id)
    )
    if f.facility_id:
        q = q.where(Bill.facility_id == f.facility_id)
    if f.utility_type:
        q = q.where(or_(Bill.utility_type == f.utility_type, Bill.utility_type.is_(None)))

    counts = {"pending_review": 0, "processing": 0, "failed": 0, "calculation_errors": 0}
    for status, calc_error, start, end in db.execute(q).all():
        in_period = start is None or end is None or (start <= f.period_end and f.period_start <= end)
        if not in_period:
            continue
        if status == BillStatus.needs_review:
            counts["pending_review"] += 1
        elif status in (BillStatus.uploaded, BillStatus.processing):
            counts["processing"] += 1
        elif status == BillStatus.failed:
            counts["failed"] += 1
        elif status == BillStatus.approved and calc_error:
            counts["calculation_errors"] += 1
    return counts
