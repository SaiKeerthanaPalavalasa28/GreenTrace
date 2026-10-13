"""Validation rules applied by code to every LLM extraction. Any issue sends the bill to the
review queue; nothing here rejects a bill outright, because a human can fix the data.

Pure functions: everything the rules need from the database arrives in ValidationContext.
"""

import re
import statistics
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal

from app.calc.quantity import effective_quantity
from app.calc.units import BILL_UNITS, UNITS, canonical_unit, convert
from app.pipeline.schema import LLMExtraction

# Electricity is always billed in energy; gas may be energy or volume.
_ALLOWED_DIMENSIONS = {"electricity": {"energy"}, "natural_gas": {"energy", "volume"}}
_BASE_UNIT = {"energy": "MJ", "volume": "m3"}


@dataclass
class Issue:
    code: str
    message: str
    field: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class HistoryPoint:
    """An earlier approved bill of the same facility and utility, for the outlier check."""

    quantity: Decimal
    unit: str
    days: int


@dataclass
class ValidationContext:
    today: date
    confidence_threshold: float
    max_period_days: int
    outlier_ratio: float
    outlier_min_history: int
    facility_id: uuid.UUID | None = None
    # Facility the extracted account number is mapped to; None if the account is new.
    mapped_facility_id: uuid.UUID | None = None
    history: list[HistoryPoint] = field(default_factory=list)
    overlapping_bill_ids: list[uuid.UUID] = field(default_factory=list)


@dataclass
class ValidationResult:
    issues: list[Issue]
    canonical_unit: str | None
    quantity: Decimal | None  # effective quantity (printed, or from meter readings)
    quantity_formula: str

    @property
    def passed(self) -> bool:
        return not self.issues


# Issues that make a bill impossible to calculate. A reviewer must fix these before approving;
# every other issue is a warning the reviewer acknowledges by approving.
BLOCKING_CODES = frozenset({
    "utility_unknown", "unit_missing", "unit_not_allowed", "unit_utility_mismatch",
    "period_missing", "period_order", "quantity_missing", "quantity_not_positive", "meter_rollover",
})
# Issues about the model's reading of the PDF. They are recorded once at extraction time and
# kept for audit; human corrections re-run only the field rules.
LLM_LEVEL_CODES = frozenset({
    "low_confidence", "multiple_meters", "estimated_read", "model_notes", "snippet_missing",
    "snippet_page_invalid", "snippet_not_found", "quantity_not_in_snippet", "readings_not_on_page",
})


@dataclass
class Fields:
    """The values the field rules check: from the LLM, or as corrected by a reviewer."""

    utility_type: str
    unit: str | None
    billing_period_start: date | None
    billing_period_end: date | None
    quantity: Decimal | None
    meter_previous: Decimal | None
    meter_current: Decimal | None
    meter_multiplier: Decimal | None
    account_number: str | None

    @classmethod
    def from_llm(cls, x: LLMExtraction) -> "Fields":
        mr = x.meter_readings
        return cls(x.utility_type, x.unit, x.billing_period_start, x.billing_period_end, x.quantity,
                   mr.previous, mr.current, mr.multiplier, x.account_number)


def validate(x: LLMExtraction, pages: list[str], ctx: ValidationContext) -> ValidationResult:
    """All rules: what the model reported about the PDF, then the field rules."""
    issues: list[Issue] = []

    def add(code: str, message: str, fld: str | None = None) -> None:
        issues.append(Issue(code, message, fld))

    if x.confidence < ctx.confidence_threshold:
        add("low_confidence", f"Model confidence {x.confidence:.2f} is below {ctx.confidence_threshold:.2f}", "confidence")
    if x.multiple_meters_or_line_items:
        add("multiple_meters", "Bill has several meters or consumption lines; confirm the total", "quantity")
    if x.read_type == "estimated":
        add("estimated_read", "Meter reading is estimated; confirm it should be reported", "read_type")
    if x.notes:
        add("model_notes", f"Model noted: {x.notes}", "notes")

    result = validate_fields(Fields.from_llm(x), ctx)
    # The snippet must really be on the bill (guards against hallucinated values).
    q_source = effective_quantity(x.quantity, x.meter_readings.previous, x.meter_readings.current,
                                  x.meter_readings.multiplier).source
    _check_snippet(x, pages, q_source, add)
    result.issues = issues + result.issues
    return result


def validate_fields(f: Fields, ctx: ValidationContext) -> ValidationResult:
    issues: list[Issue] = []

    def add(code: str, message: str, fld: str | None = None) -> None:
        issues.append(Issue(code, message, fld))

    if f.utility_type not in _ALLOWED_DIMENSIONS:
        add("utility_unknown", "Could not tell whether this is an electricity or gas bill", "utility_type")

    # --- unit
    unit = canonical_unit(f.unit)
    if f.unit is None:
        add("unit_missing", "No unit found", "unit")
    elif unit is None or unit not in BILL_UNITS:
        add("unit_not_allowed", f"Unit {f.unit!r} is not one of: {', '.join(sorted(BILL_UNITS))}", "unit")
        unit = None
    elif f.utility_type in _ALLOWED_DIMENSIONS and UNITS[unit].dimension not in _ALLOWED_DIMENSIONS[f.utility_type]:
        add("unit_utility_mismatch", f"{f.unit} is not a valid unit for {f.utility_type.replace('_', ' ')}", "unit")

    # --- billing period
    start, end = f.billing_period_start, f.billing_period_end
    days = None
    if start is None or end is None:
        add("period_missing", "Billing period start or end not found", "billing_period_start")
    elif end <= start:
        add("period_order", f"Billing period end {end} is not after start {start}", "billing_period_end")
    else:
        days = (end - start).days + 1  # inclusive of both dates
        if days > ctx.max_period_days:
            add("period_too_long", f"Billing period is {days} days (limit {ctx.max_period_days})", "billing_period_end")
    if end is not None and end > ctx.today:
        add("period_in_future", f"Billing period ends in the future ({end})", "billing_period_end")

    # --- quantity
    q = effective_quantity(f.quantity, f.meter_previous, f.meter_current, f.meter_multiplier)
    for code, msg in q.issues:
        add(code, msg, "quantity")
    if q.value is not None and q.value <= 0:
        add("quantity_not_positive", f"Consumption {q.value} must be greater than zero", "quantity")

    # --- account / facility
    if not f.account_number:
        add("account_missing", "No account number found; the facility can't be confirmed", "account_number")
    elif ctx.facility_id is not None:
        if ctx.mapped_facility_id is None:
            add("account_unmapped", f"Account {f.account_number} has not been seen before; confirm the facility", "account_number")
        elif ctx.mapped_facility_id != ctx.facility_id:
            add("account_other_facility", f"Account {f.account_number} belongs to a different facility", "account_number")

    if ctx.overlapping_bill_ids:
        add("overlapping_period",
            f"Billing period overlaps {len(ctx.overlapping_bill_ids)} other bill(s) for this facility; possible duplicate",
            "billing_period_start")

    # --- outlier vs facility history
    if q.value is not None and q.value > 0 and unit is not None and days:
        _check_outlier(q.value, unit, days, ctx, add)

    return ValidationResult(issues, unit, q.value, q.formula)


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _numbers_in(s: str) -> set[Decimal]:
    out = set()
    for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", s):
        try:
            out.add(Decimal(m.group().replace(",", "")))
        except ArithmeticError:
            pass
    return out


def _check_snippet(x: LLMExtraction, pages: list[str], quantity_source: str, add) -> None:
    snippet = _normalize(x.source_snippet)
    if not snippet:
        add("snippet_missing", "Model gave no source snippet", "source_snippet")
        return
    if x.page_number > len(pages):
        add("snippet_page_invalid", f"Cited page {x.page_number} does not exist (bill has {len(pages)})", "page_number")
        return
    page_text = _normalize(pages[x.page_number - 1])
    if snippet not in page_text:
        other = [i + 1 for i, p in enumerate(pages) if snippet in _normalize(p)]
        where = f"; it appears on page {other[0]}" if other else ""
        add("snippet_not_found", f"Source snippet not found on cited page {x.page_number}{where}", "source_snippet")
        return
    if quantity_source == "printed" and x.quantity not in _numbers_in(x.source_snippet):
        add("quantity_not_in_snippet", f"Quantity {x.quantity} does not appear in the source snippet", "quantity")
    if quantity_source == "meter_readings":
        nums = _numbers_in(pages[x.page_number - 1])
        mr = x.meter_readings
        missing = [str(v) for v in (mr.previous, mr.current) if v not in nums]
        if missing:
            add("readings_not_on_page", f"Meter reading(s) {', '.join(missing)} not found on page {x.page_number}", "quantity")


def _check_outlier(value: Decimal, unit: str, days: int, ctx: ValidationContext, add) -> None:
    dim = UNITS[unit].dimension
    base = _BASE_UNIT[dim]
    rates = [
        convert(h.quantity, h.unit, base) / h.days
        for h in ctx.history
        if h.unit in UNITS and UNITS[h.unit].dimension == dim and h.days > 0
    ]
    if len(rates) < ctx.outlier_min_history:
        return
    median = statistics.median(rates)
    if median <= 0:
        return
    ratio = (convert(value, unit, base) / days) / median
    limit = Decimal(str(ctx.outlier_ratio))
    if ratio > limit or ratio < 1 / limit:
        add("outlier",
            f"Daily consumption is {ratio:.2f}x this facility's median over {len(rates)} earlier bills",
            "quantity")
