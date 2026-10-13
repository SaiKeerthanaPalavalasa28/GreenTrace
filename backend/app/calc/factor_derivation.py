"""Turn an emission factor as printed by its publisher into kg CO2e per unit.

Publishers print factors in different forms: tCO2/MWh (CEA), lb CO2e/MWh (eGRID),
kg CO2 + g CH4 + g N2O per mmBtu (EPA Hub), kg/TJ per gas (IPCC). The denominator unit is
kept as published; only the mass unit is converted and, when gases are listed separately,
they are weighted by a GWP set. The result carries a human-readable derivation for the trace.
"""

from dataclasses import dataclass
from decimal import Decimal, localcontext

from app.calc.units import PRECISION, UnitError, dimension, convert
from app.enums import GhgBasis

GASES = ("CO2", "CH4", "N2O", "CO2e")


@dataclass(frozen=True)
class PublishedComponent:
    gas: str  # CO2 | CH4 | N2O | CO2e
    value: Decimal
    mass_unit: str  # kg | g | t | lb


@dataclass(frozen=True)
class DerivedFactor:
    kgco2e_per_unit: Decimal
    ghg_basis: GhgBasis
    derivation: str


class FactorDerivationError(ValueError):
    pass


def derive(
    components: list[PublishedComponent],
    per_unit: str,
    gwp: dict[str, Decimal] | None = None,
    gwp_name: str | None = None,
) -> DerivedFactor:
    if not components:
        raise FactorDerivationError("At least one published value is required")
    gases = [c.gas for c in components]
    if len(set(gases)) != len(gases):
        raise FactorDerivationError(f"Duplicate gas in published values: {gases}")
    for c in components:
        if c.gas not in GASES:
            raise FactorDerivationError(f"Unknown gas {c.gas!r}")
        if not isinstance(c.value, Decimal) or c.value < 0:
            raise FactorDerivationError(f"{c.gas} value must be a non-negative Decimal")
        try:
            if dimension(c.mass_unit) != "mass":
                raise FactorDerivationError(f"{c.mass_unit!r} is not a mass unit")
        except UnitError as e:
            raise FactorDerivationError(str(e)) from None
    try:
        dimension(per_unit)
    except UnitError as e:
        raise FactorDerivationError(str(e)) from None

    if "CO2e" in gases:
        if len(components) != 1:
            raise FactorDerivationError("A CO2e value cannot be combined with individual gases")
        c = components[0]
        kg = convert(c.value, c.mass_unit, "kg")
        return DerivedFactor(
            kg,
            GhgBasis.CO2e,
            f"{c.value} {c.mass_unit} CO2e/{per_unit} as published"
            + ("" if c.mass_unit == "kg" else f" x {convert(Decimal(1), c.mass_unit, 'kg')} kg/{c.mass_unit}")
            + f" = {_fmt(kg)} kg CO2e/{per_unit}",
        )

    if gases == ["CO2"]:
        c = components[0]
        kg = convert(c.value, c.mass_unit, "kg")
        return DerivedFactor(
            kg,
            GhgBasis.CO2,
            f"{c.value} {c.mass_unit} CO2/{per_unit} as published (CO2 only, no CH4/N2O)"
            + ("" if c.mass_unit == "kg" else f" x {convert(Decimal(1), c.mass_unit, 'kg')} kg/{c.mass_unit}")
            + f" = {_fmt(kg)} kg CO2/{per_unit}",
        )

    if gwp is None:
        raise FactorDerivationError("Several gases are listed separately; a GWP set is required")
    if "CO2" not in gases:
        raise FactorDerivationError("Multi-gas factor must include CO2")
    total = Decimal(0)
    terms = []
    with localcontext() as ctx:
        ctx.prec = PRECISION
        for c in components:
            if c.gas not in gwp:
                raise FactorDerivationError(f"GWP set has no value for {c.gas}")
            kg = convert(c.value, c.mass_unit, "kg")
            total += kg * gwp[c.gas]
            terms.append(f"{c.value} {c.mass_unit} {c.gas} x GWP {gwp[c.gas]}")
    return DerivedFactor(
        total,
        GhgBasis.CO2e,
        " + ".join(terms)
        + f" (GWP set: {gwp_name or 'unnamed'}; masses converted to kg) = {_fmt(total)} kg CO2e/{per_unit}",
    )


def _fmt(d: Decimal) -> str:
    return format(d.normalize(), "f")
