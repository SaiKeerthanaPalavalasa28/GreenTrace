"""The emission calculation. Pure, deterministic, Decimal-only.

    kg CO2e = quantity x (segment days / period days) x unit conversion x factor

All intermediate values keep full precision (34 significant digits); results are rounded
once, at the end, to 6 decimal places (1 mg) with banker's rounding. Every segment carries
a JSON trace with each input, its source and each step, so a figure can be re-derived by hand.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, localcontext

from app.calc.factors import FactorData, FactorSelectionError, factor_boundaries, select_factor
from app.calc.prorate import PeriodError, period_days, reporting_year_label, reporting_year_start, split_period
from app.calc.quantity import effective_quantity
from app.calc.units import PRECISION, UNITS, canonical_unit, conversion_factor
from app.enums import SCOPE_BY_UTILITY, UtilityType

ENGINE_VERSION = "1.0"
RESULT_QUANTUM = Decimal("0.000001")
FRACTION_QUANTUM = Decimal("0.000000000001")


class CalculationError(ValueError):
    """The bill can't be calculated as it stands. The message is shown to users."""


@dataclass(frozen=True)
class CalcInput:
    utility_type: str
    region: str
    period_start: date | None
    period_end: date | None
    unit: str | None
    quantity: Decimal | None
    meter_previous: Decimal | None = None
    meter_current: Decimal | None = None
    meter_multiplier: Decimal | None = None
    org_id: uuid.UUID | None = None
    fiscal_year_start_month: int = 1


@dataclass(frozen=True)
class SegmentResult:
    start: date
    end: date
    days: int
    fraction: Decimal  # rounded, for storage/display; the math uses days/total exactly
    quantity: Decimal  # bill unit, before normalization (full precision)
    normalized_quantity: Decimal  # in the factor's unit, rounded to 6 dp
    normalized_unit: str
    kgco2e: Decimal  # rounded to 6 dp
    scope: int
    factor: FactorData
    trace: dict


@dataclass(frozen=True)
class CalcResult:
    total_quantity: Decimal
    unit: str
    total_days: int
    segments: list[SegmentResult]

    @property
    def kgco2e(self) -> Decimal:
        return sum((s.kgco2e for s in self.segments), Decimal(0))


def kg_to_tonnes(kg: Decimal, places: int = 3) -> Decimal:
    """For display and reports: tonnes rounded half-even to `places` decimals."""
    return (kg / 1000).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_EVEN)


def _q(d: Decimal, quantum: Decimal) -> Decimal:
    return d.quantize(quantum, rounding=ROUND_HALF_EVEN)


def _s(d: Decimal) -> str:
    """Decimal as a plain string for traces (no exponent notation)."""
    return format(d.normalize(), "f")


def calculate(inp: CalcInput, factors: list[FactorData]) -> CalcResult:
    for name in ("quantity", "meter_previous", "meter_current", "meter_multiplier"):
        v = getattr(inp, name)
        if v is not None and not isinstance(v, Decimal):
            raise TypeError(f"{name} must be Decimal, got {type(v).__name__}")

    if inp.utility_type not in UtilityType.__members__:
        raise CalculationError(f"Unknown utility type {inp.utility_type!r}; set it before approving")
    scope = SCOPE_BY_UTILITY[UtilityType(inp.utility_type)]

    unit = canonical_unit(inp.unit)
    if unit is None or unit not in UNITS:
        raise CalculationError(f"Unit {inp.unit!r} is not recognized")

    q = effective_quantity(inp.quantity, inp.meter_previous, inp.meter_current, inp.meter_multiplier)
    if q.value is None:
        raise CalculationError("No consumption quantity: " + "; ".join(m for _, m in q.issues))
    if q.value <= 0:
        raise CalculationError(f"Consumption must be greater than zero (got {q.value})")
    total = q.value

    try:
        segments = split_period(
            inp.period_start, inp.period_end,
            factor_boundaries(factors, inp.utility_type, inp.period_start, inp.period_end)
            if inp.period_start and inp.period_end else [],
        )
    except PeriodError as e:
        raise CalculationError(str(e)) from None
    total_days = period_days(inp.period_start, inp.period_end)

    results = []
    for seg in segments:
        try:
            sel = select_factor(factors, utility_type=inp.utility_type, region=inp.region,
                                on_date=seg.start, bill_unit=unit, org_id=inp.org_id)
        except FactorSelectionError as e:
            raise CalculationError(str(e)) from None
        f = sel.factor
        if not f.covers(seg.end):  # can't happen given factor_boundaries; guard anyway
            raise CalculationError(f"Factor {f.factor_key} does not cover the whole segment {seg.start}..{seg.end}")
        if f.scope != scope:
            raise CalculationError(f"Factor {f.factor_key} is scope {f.scope} but {inp.utility_type} is scope {scope}")

        with localcontext() as ctx:
            ctx.prec = PRECISION
            seg_qty = total * seg.days / total_days
            conv = conversion_factor(unit, f.unit)
            normalized = seg_qty * conv
            kg = normalized * f.kgco2e_per_unit
        kg_r = _q(kg, RESULT_QUANTUM)
        norm_r = _q(normalized, RESULT_QUANTUM)
        fraction = _q(Decimal(seg.days) / Decimal(total_days), FRACTION_QUANTUM)

        prorated = len(segments) > 1
        trace = {
            "engine_version": ENGINE_VERSION,
            "quantity": {
                "value": _s(total),
                "unit": unit,
                "unit_as_extracted": inp.unit,
                "source": q.source,
                "derivation": q.formula,
            },
            "allocation": {
                "billing_period": [inp.period_start.isoformat(), inp.period_end.isoformat()],
                "billing_period_days": total_days,
                "segment": [seg.start.isoformat(), seg.end.isoformat()],
                "segment_days": seg.days,
                "fraction": f"{seg.days}/{total_days}",
                "prorated": prorated,
                "method": (
                    "Billing period split at calendar-month and emission-factor boundaries; quantity "
                    "allocated by day count, assuming uniform consumption."
                    if prorated else "Whole billing period in one month; no pro-rating."
                ),
                "reporting_year": reporting_year_label(seg.start, inp.fiscal_year_start_month),
                "crosses_reporting_year": len({
                    reporting_year_start(s.start, inp.fiscal_year_start_month) for s in segments
                }) > 1,
                "segment_quantity": _s(seg_qty),
                "segment_quantity_rounded": _s(_q(seg_qty, RESULT_QUANTUM)),
            },
            "normalization": {
                "from_unit": unit,
                "to_unit": f.unit,
                "multiply_by": _s(conv),
                "definition": (
                    "same unit" if unit == f.unit
                    else f"{UNITS[unit].definition}; {UNITS[f.unit].definition}"
                ),
                "result": _s(normalized),
            },
            "factor": {
                "id": str(f.id),
                "key": f.factor_key,
                "version": f.version,
                "kgco2e_per_unit": _s(f.kgco2e_per_unit),
                "unit": f.unit,
                "ghg_basis": f.ghg_basis,
                "scope": f.scope,
                "region": f.region,
                "region_match": sel.region_match,
                "owner": sel.owner,
                "valid_from": f.valid_from.isoformat(),
                "valid_to": f.valid_to.isoformat() if f.valid_to else None,
                "source_name": f.source_name,
                "source_url": f.source_url,
                "publication_year": f.publication_year,
                "derivation": f.derivation,
            },
            "formula": (
                f"{_s(total)} {unit} x {seg.days}/{total_days} days"
                + (f" x {_s(conv)} {f.unit}/{unit}" if unit != f.unit else "")
                + f" x {_s(f.kgco2e_per_unit)} kg {f.ghg_basis}/{f.unit} = {_s(kg_r)} kg {f.ghg_basis}"
            ),
            "result": {
                "kgco2e": _s(kg_r),
                "unrounded": _s(kg),
                "rounding": "6 decimal places, round half to even",
                "ghg_basis": f.ghg_basis,
                "scope": scope,
                "scope_basis": "Scope 2, location-based (purchased electricity)" if scope == 2
                else "Scope 1 (stationary combustion of natural gas)",
            },
        }
        results.append(SegmentResult(seg.start, seg.end, seg.days, fraction, seg_qty, norm_r, f.unit,
                                     kg_r, scope, f, trace))
    return CalcResult(total, unit, total_days, results)
