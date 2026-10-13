"""Unit registry and exact conversions. Pure functions, Decimal only.

Energy converts via megajoules, volume via cubic metres, mass via kilograms. Conversion
across dimensions (e.g. m3 of gas -> MMBtu) needs a heating value and is deliberately
not possible here.
"""

from dataclasses import dataclass
from decimal import Decimal, localcontext

# Precision for intermediate conversion results (some, e.g. MJ -> kWh, don't terminate).
PRECISION = 34


@dataclass(frozen=True)
class UnitDef:
    symbol: str
    dimension: str  # "energy" | "volume" | "mass"
    to_base: Decimal  # multiply by this to get the dimension's base unit
    definition: str  # citation of the constant, shown in calculation traces


# International Table Btu: 1 Btu = 1055.05585262 J (exact by definition).
_BTU_MJ = Decimal("0.00105505585262")
# 1 ft = 0.3048 m exactly, so 1 ft3 = 0.028316846592 m3 exactly.
_FT3_M3 = Decimal("0.028316846592")

UNITS: dict[str, UnitDef] = {
    u.symbol: u
    for u in [
        UnitDef("MJ", "energy", Decimal(1), "base unit"),
        UnitDef("kWh", "energy", Decimal("3.6"), "1 kWh = 3.6 MJ (exact)"),
        UnitDef("MWh", "energy", Decimal("3600"), "1 MWh = 3600 MJ (exact)"),
        UnitDef("GJ", "energy", Decimal("1000"), "1 GJ = 1000 MJ (exact)"),
        UnitDef("TJ", "energy", Decimal("1000000"), "1 TJ = 1,000,000 MJ (exact)"),
        UnitDef("MMBtu", "energy", _BTU_MJ * 1_000_000, "1 MMBtu = 10^6 Btu(IT); 1 Btu(IT) = 1055.05585262 J"),
        UnitDef("therm", "energy", _BTU_MJ * 100_000, "1 therm = 100,000 Btu(IT); 1 Btu(IT) = 1055.05585262 J"),
        UnitDef("m3", "volume", Decimal(1), "base unit"),
        UnitDef("scf", "volume", _FT3_M3, "1 ft3 = 0.028316846592 m3 (exact)"),
        UnitDef("ccf", "volume", _FT3_M3 * 100, "1 ccf = 100 ft3"),
        UnitDef("Mcf", "volume", _FT3_M3 * 1000, "1 Mcf = 1000 ft3"),
        UnitDef("kg", "mass", Decimal(1), "base unit"),
        UnitDef("g", "mass", Decimal("0.001"), "1 g = 0.001 kg (exact)"),
        UnitDef("t", "mass", Decimal("1000"), "1 tonne = 1000 kg (exact)"),
        UnitDef("lb", "mass", Decimal("0.45359237"), "1 lb = 0.45359237 kg (exact, international pound)"),
    ]
}

# Units a bill quantity may be reported in (validation rule). Mass units are for factors only.
BILL_UNITS = frozenset({"kWh", "MWh", "therm", "m3", "scf", "ccf", "Mcf", "MMBtu", "GJ"})

_ALIASES = {
    "kwh": "kWh",
    "kw-h": "kWh",
    "units": None,  # Indian bills often say "units" (= kWh) but it's ambiguous; send to review
    "mwh": "MWh",
    "gj": "GJ",
    "tj": "TJ",
    "mj": "MJ",
    "mmbtu": "MMBtu",
    "mmbtus": "MMBtu",
    "therm": "therm",
    "therms": "therm",
    "thm": "therm",
    "m3": "m3",
    "m³": "m3",
    "cubic metres": "m3",
    "cubic meters": "m3",
    # Standard cubic metre. Treated as m3; standard reference conditions vary by supplier.
    "scm": "m3",
    "sm3": "m3",
    "scf": "scf",
    "cf": "scf",
    "ft3": "scf",
    "cubic feet": "scf",
    "ccf": "ccf",
    "hcf": "ccf",
    "mcf": "Mcf",
}


class UnitError(ValueError):
    pass


def canonical_unit(label: str | None) -> str | None:
    """Map a unit label as printed on a bill to a registry symbol, or None if unrecognized."""
    if label is None:
        return None
    key = label.strip().lower().replace(" (gross cv)", "").rstrip(".")
    if label.strip() in UNITS:
        return label.strip()
    return _ALIASES.get(key)


def dimension(unit: str) -> str:
    try:
        return UNITS[unit].dimension
    except KeyError:
        raise UnitError(f"Unknown unit {unit!r}") from None


def convertible(from_unit: str, to_unit: str) -> bool:
    return from_unit in UNITS and to_unit in UNITS and dimension(from_unit) == dimension(to_unit)


def convert(value: Decimal, from_unit: str, to_unit: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError("convert() requires Decimal input")
    if from_unit == to_unit:
        return value
    if not convertible(from_unit, to_unit):
        raise UnitError(
            f"Cannot convert {from_unit!r} to {to_unit!r}: "
            f"{_dim_or_unknown(from_unit)} vs {_dim_or_unknown(to_unit)}"
        )
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return value * UNITS[from_unit].to_base / UNITS[to_unit].to_base


def conversion_factor(from_unit: str, to_unit: str) -> Decimal:
    return convert(Decimal(1), from_unit, to_unit)


def _dim_or_unknown(unit: str) -> str:
    return UNITS[unit].dimension if unit in UNITS else "unknown unit"
