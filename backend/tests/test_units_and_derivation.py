from decimal import Decimal as D

import pytest

from app.calc.factor_derivation import FactorDerivationError, PublishedComponent, derive
from app.calc.units import UnitError, canonical_unit, convert


@pytest.mark.parametrize(
    ("value", "frm", "to", "expected"),
    [
        ("1", "MWh", "kWh", "1000"),
        ("1", "MMBtu", "GJ", "1.05505585262"),
        ("10", "therm", "MMBtu", "1"),
        ("1000", "scf", "Mcf", "1"),
        ("1", "ccf", "m3", "2.8316846592"),
        ("1", "lb", "kg", "0.45359237"),
        ("3.6", "MJ", "kWh", "1"),
    ],
)
def test_convert_exact(value, frm, to, expected):
    assert convert(D(value), frm, to) == D(expected)


def test_convert_rejects_cross_dimension_and_floats():
    with pytest.raises(UnitError, match="volume vs energy"):
        convert(D(1), "m3", "kWh")
    with pytest.raises(UnitError, match="unknown unit"):
        convert(D(1), "kWh", "furlongs")
    with pytest.raises(TypeError):
        convert(1.0, "kWh", "MWh")


@pytest.mark.parametrize(
    ("label", "expected"),
    [("KWH", "kWh"), ("kWh", "kWh"), ("Therms", "therm"), ("m³", "m3"), ("SCM", "m3"),
     ("MMBTU", "MMBtu"), ("CCF", "ccf"), ("units", None), ("bananas", None), (None, None)],
)
def test_canonical_unit(label, expected):
    assert canonical_unit(label) == expected


def test_derive_rejects_mixing_co2e_with_gases():
    with pytest.raises(FactorDerivationError, match="cannot be combined"):
        derive([PublishedComponent("CO2e", D(1), "kg"), PublishedComponent("CH4", D(1), "g")], "kWh")


def test_derive_rejects_unknown_gwp_gas():
    with pytest.raises(FactorDerivationError, match="no value for N2O"):
        derive([PublishedComponent("CO2", D(1), "kg"), PublishedComponent("N2O", D(1), "g")],
               "MMBtu", gwp={"CO2": D(1), "CH4": D(28)}, gwp_name="partial")


def test_derive_co2_only_keeps_basis():
    d = derive([PublishedComponent("CO2", D("0.716"), "t")], "MWh")
    assert d.kgco2e_per_unit == D("716.000")
    assert d.ghg_basis == "CO2"
    assert "CO2 only" in d.derivation


@pytest.mark.parametrize(("components", "per_unit", "message"), [
    ([], "kWh", "At least one"),
    ([PublishedComponent("CO2", D(1), "kg"), PublishedComponent("CO2", D(2), "kg")], "kWh", "Duplicate gas"),
    ([PublishedComponent("SF6", D(1), "kg")], "kWh", "Unknown gas"),
    ([PublishedComponent("CO2", D(-1), "kg")], "kWh", "non-negative"),
    ([PublishedComponent("CO2", 1.0, "kg")], "kWh", "non-negative Decimal"),
    ([PublishedComponent("CO2", D(1), "kWh")], "kWh", "not a mass unit"),
    ([PublishedComponent("CO2", D(1), "stone")], "kWh", "Unknown unit"),
    ([PublishedComponent("CO2", D(1), "kg")], "furlong", "Unknown unit"),
    ([PublishedComponent("CH4", D(1), "g"), PublishedComponent("N2O", D(1), "g")], "kWh", "must include CO2"),
])
def test_derive_validation(components, per_unit, message):
    gwp = {"CO2": D(1), "CH4": D(28), "N2O": D(265)}
    with pytest.raises(FactorDerivationError, match=message):
        derive(components, per_unit, gwp, "AR5")


def test_derive_co2e_in_pounds():
    d = derive([PublishedComponent("CO2e", D("770.9"), "lb")], "MWh")
    assert d.kgco2e_per_unit == D("349.674358033")
    assert "x 0.45359237 kg/lb" in d.derivation
