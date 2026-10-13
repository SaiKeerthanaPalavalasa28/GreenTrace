"""Calculation engine: unit conversion, factor selection, pro-rating, emission math.

Expected values are worked out by hand in the comments, using the seeded factors:
  IN  electricity  CEA FY2023-24  727 kg CO2/MWh    (2023-04-01 .. 2024-03-31)
  IN  electricity  CEA FY2024-25  710 kg CO2/MWh    (2024-04-01 .. 2025-03-31)
  UK  electricity  DESNZ 2025     0.177 kg CO2e/kWh  / 2026: 0.13096
  UK  natural gas  DESNZ 2025     0.18296 kg CO2e/kWh, 2.06672 kg CO2e/m3
  US  natural gas  EPA Hub        53.1145 kg CO2e/MMBtu, 0.05449534 kg CO2e/scf (2024-01-01 ..)
  IN  natural gas  IPCC 2006      56154.5 kg CO2e/TJ (2006-01-01 ..)
"""

import dataclasses
import random
import uuid
from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from app.calc.engine import CalcInput, CalculationError, calculate
from app.calc.factors import FactorData, FactorSelectionError, parent_region, select_factor
from app.calc.prorate import PeriodError, reporting_year_label, split_period
from app.calc.service import to_factor_data
from app.factor_service import build_factor, spec_from_seed_row
from app.seed import read_rows

ORG = uuid.uuid4()


@pytest.fixture(scope="module")
def seeded() -> list[FactorData]:
    return [to_factor_data(build_factor(spec_from_seed_row(r), created_by="seed")) for r in read_rows()]


def custom(key, *, utility="electricity", region="XX", unit="kWh", value="1", start=date(2020, 1, 1),
           end=None, org=None, superseded=False, scope=None, version=1) -> FactorData:
    return FactorData(
        id=uuid.uuid4(), factor_key=key, version=version, org_id=org, utility_type=utility, region=region,
        unit=unit, kgco2e_per_unit=D(value), ghg_basis="CO2e",
        scope=scope if scope is not None else (2 if utility == "electricity" else 1),
        source_name="test", source_url="https://example.org", publication_year=2025,
        valid_from=start, valid_to=end, superseded=superseded,
    )


def inp(**kw) -> CalcInput:
    base = dict(utility_type="electricity", region="IN", period_start=date(2024, 1, 1),
                period_end=date(2024, 1, 31), unit="kWh", quantity=D("12500"), org_id=ORG,
                fiscal_year_start_month=4)
    return CalcInput(**{**base, **kw})


# ================================================================ pro-rating

class TestSplitPeriod:
    def test_single_month(self):
        segs = split_period(date(2024, 1, 1), date(2024, 1, 31))
        assert [(s.start, s.end, s.days) for s in segs] == [(date(2024, 1, 1), date(2024, 1, 31), 31)]

    def test_two_months(self):
        segs = split_period(date(2024, 3, 16), date(2024, 4, 15))
        assert [(s.start, s.end, s.days) for s in segs] == [
            (date(2024, 3, 16), date(2024, 3, 31), 16), (date(2024, 4, 1), date(2024, 4, 15), 15)]

    def test_quarter_and_leap_february(self):
        segs = split_period(date(2024, 1, 1), date(2024, 3, 31))
        assert [s.days for s in segs] == [31, 29, 31]

    def test_cross_calendar_year(self):
        segs = split_period(date(2025, 12, 20), date(2026, 1, 10))
        assert [(s.start, s.days) for s in segs] == [(date(2025, 12, 20), 12), (date(2026, 1, 1), 10)]

    def test_single_day(self):
        assert [s.days for s in split_period(date(2024, 5, 5), date(2024, 5, 5))] == [1]

    def test_starts_on_first_and_ends_on_first(self):
        segs = split_period(date(2024, 1, 1), date(2024, 2, 1))
        assert [(s.start, s.end) for s in segs] == [(date(2024, 1, 1), date(2024, 1, 31)), (date(2024, 2, 1), date(2024, 2, 1))]

    def test_extra_boundaries_inside_only(self):
        segs = split_period(date(2025, 1, 1), date(2025, 1, 31),
                            [date(2025, 1, 15), date(2024, 12, 1), date(2025, 1, 1), date(2025, 2, 1)])
        assert [(s.start, s.end) for s in segs] == [(date(2025, 1, 1), date(2025, 1, 14)), (date(2025, 1, 15), date(2025, 1, 31))]

    def test_end_before_start(self):
        with pytest.raises(PeriodError):
            split_period(date(2024, 2, 1), date(2024, 1, 1))

    def test_missing_dates(self):
        with pytest.raises(PeriodError):
            split_period(None, date(2024, 1, 1))

    def test_segments_partition_the_period_exactly(self):
        rng = random.Random(42)
        for _ in range(300):
            start = date(2022, 1, 1) + timedelta(days=rng.randrange(1500))
            end = start + timedelta(days=rng.randrange(200))
            extra = [start + timedelta(days=rng.randrange(1, 250)) for _ in range(rng.randrange(3))]
            segs = split_period(start, end, extra)
            assert segs[0].start == start and segs[-1].end == end
            assert sum(s.days for s in segs) == (end - start).days + 1
            for a, b in zip(segs, segs[1:]):
                assert b.start == a.end + timedelta(days=1)
            assert all(s.start.month == s.end.month and s.start.year == s.end.year for s in segs)


@pytest.mark.parametrize(("d", "fy", "label"), [
    (date(2024, 3, 31), 4, "FY2023-24"), (date(2024, 4, 1), 4, "FY2024-25"),
    (date(2025, 1, 15), 4, "FY2024-25"), (date(2025, 1, 15), 1, "2025"), (date(2025, 6, 30), 7, "FY2024-25"),
])
def test_reporting_year_label(d, fy, label):
    assert reporting_year_label(d, fy) == label


# ================================================================ factor selection

class TestSelectFactor:
    def sel(self, factors, **kw):
        args = dict(utility_type="electricity", region="IN", on_date=date(2024, 1, 15), bill_unit="kWh", org_id=ORG)
        return select_factor(factors, **{**args, **kw})

    def test_picks_factor_valid_on_date(self, seeded):
        assert self.sel(seeded).factor.factor_key == "IN-CEA-GRID-FY2023-24"
        assert self.sel(seeded, on_date=date(2024, 4, 1)).factor.factor_key == "IN-CEA-GRID-FY2024-25"
        assert self.sel(seeded, on_date=date(2024, 3, 31)).factor.factor_key == "IN-CEA-GRID-FY2023-24"

    def test_no_factor_for_date_fails_loudly_and_lists_what_exists(self, seeded):
        with pytest.raises(FactorSelectionError) as e:
            self.sel(seeded, on_date=date(2025, 6, 1))
        msg = str(e.value)
        assert "covers 2025-06-01" in msg and "IN-CEA-GRID-FY2024-25" in msg and "never used as a substitute" in msg

    def test_unknown_region(self, seeded):
        with pytest.raises(FactorSelectionError, match="region 'FR'"):
            self.sel(seeded, region="FR")

    def test_parent_region_used_only_when_exact_region_has_no_factors(self, seeded):
        s = self.sel(seeded, utility_type="natural_gas", region="US-CAMX", bill_unit="MMBtu", on_date=date(2025, 1, 1))
        assert (s.factor.factor_key, s.region_match) == ("US-EPA-HUB-NATGAS-MMBTU", "parent")

    def test_no_parent_fallback_when_exact_region_lacks_this_date(self):
        factors = [custom("CHILD", region="XX-A", end=date(2023, 12, 31)), custom("PARENT", region="XX")]
        assert self.sel(factors, region="XX-A", on_date=date(2023, 6, 1)).factor.factor_key == "CHILD"
        with pytest.raises(FactorSelectionError, match="region 'XX-A' covers 2024-06-01"):
            self.sel(factors, region="XX-A", on_date=date(2024, 6, 1))

    def test_exact_region_for_egrid_subregion(self, seeded):
        s = self.sel(seeded, region="US-CAMX", on_date=date(2024, 6, 1))
        assert (s.factor.factor_key, s.region_match) == ("US-EGRID2023-CAMX", "exact")

    def test_parent_region(self):
        assert parent_region("US-CAMX") == "US"
        assert parent_region("IN") is None

    def test_org_factor_beats_global(self):
        g = custom("GLOBAL", region="XX")
        o = custom("ORG", region="XX", org=ORG)
        s = self.sel([g, o], region="XX")
        assert (s.factor.factor_key, s.owner) == ("ORG", "organization")

    def test_other_orgs_factors_invisible(self):
        with pytest.raises(FactorSelectionError):
            self.sel([custom("OTHER", region="XX", org=uuid.uuid4())], region="XX")

    def test_superseded_ignored(self):
        old = custom("K", region="XX", value="1", superseded=True)
        new = custom("K", region="XX", value="2", version=2)
        assert self.sel([old, new], region="XX").factor.kgco2e_per_unit == D(2)

    def test_unit_compatibility_and_exact_preference(self, seeded):
        args = dict(utility_type="natural_gas", region="UK", on_date=date(2025, 3, 1))
        assert self.sel(seeded, bill_unit="kWh", **args).factor.factor_key == "UK-DESNZ-NATGAS-KWH-2025"
        assert self.sel(seeded, bill_unit="m3", **args).factor.factor_key == "UK-DESNZ-NATGAS-M3-2025"
        assert self.sel(seeded, bill_unit="therm", **args).factor.factor_key == "UK-DESNZ-NATGAS-KWH-2025"
        us = dict(utility_type="natural_gas", region="US", on_date=date(2025, 3, 1))
        assert self.sel(seeded, bill_unit="ccf", **us).factor.factor_key == "US-EPA-HUB-NATGAS-SCF"
        assert self.sel(seeded, bill_unit="therm", **us).factor.factor_key == "US-EPA-HUB-NATGAS-MMBTU"

    def test_volume_bill_with_only_energy_factors_fails(self, seeded):
        with pytest.raises(FactorSelectionError, match="calorific value"):
            self.sel(seeded, utility_type="natural_gas", region="IN", bill_unit="m3")

    def test_ambiguous_fails(self):
        a, b = custom("A", region="XX"), custom("B", region="XX")
        with pytest.raises(FactorSelectionError, match="Ambiguous"):
            self.sel([a, b], region="XX")

    def test_two_compatible_units_without_exact_match_is_ambiguous(self):
        a, b = custom("A", region="XX", unit="kWh"), custom("B", region="XX", unit="MWh")
        with pytest.raises(FactorSelectionError, match="Ambiguous"):
            self.sel([a, b], region="XX", bill_unit="GJ")
        assert self.sel([a, b], region="XX", bill_unit="MWh").factor.factor_key == "B"

    def test_open_ended_validity(self):
        f = custom("OPEN", region="XX", start=date(2006, 1, 1), end=None)
        assert self.sel([f], region="XX", on_date=date(2099, 1, 1)).factor.factor_key == "OPEN"
        with pytest.raises(FactorSelectionError):
            self.sel([f], region="XX", on_date=date(2005, 12, 31))


# ================================================================ calculation

def kg(result) -> D:
    return result.kgco2e


class TestCalculate:
    def test_simple_month(self, seeded):
        # 12,500 kWh = 12.5 MWh x 727 = 9,087.5 kg CO2
        r = calculate(inp(), seeded)
        assert kg(r) == D("9087.5")
        (s,) = r.segments
        assert (s.normalized_quantity, s.normalized_unit, s.scope, s.fraction) == (D("12.5"), "MWh", 2, D(1))
        assert s.factor.factor_key == "IN-CEA-GRID-FY2023-24"

    def test_bill_in_mwh_needs_no_conversion(self, seeded):
        r = calculate(inp(unit="MWh", quantity=D("12.5")), seeded)
        assert kg(r) == D("9087.5")
        assert r.segments[0].trace["normalization"]["definition"] == "same unit"

    def test_cross_financial_year_uses_each_years_factor(self, seeded):
        # 3,100 kWh over 16 Mar - 15 Apr 2024 (31 days):
        #   16 days FY2023-24: 1,600 kWh = 1.6 MWh x 727 = 1,163.2
        #   15 days FY2024-25: 1,500 kWh = 1.5 MWh x 710 = 1,065.0   total 2,228.2
        r = calculate(inp(period_start=date(2024, 3, 16), period_end=date(2024, 4, 15), quantity=D(3100)), seeded)
        assert [(s.days, s.kgco2e, s.factor.factor_key) for s in r.segments] == [
            (16, D("1163.2"), "IN-CEA-GRID-FY2023-24"), (15, D("1065.0"), "IN-CEA-GRID-FY2024-25")]
        assert kg(r) == D("2228.2")
        t = r.segments[0].trace["allocation"]
        assert t["prorated"] and t["crosses_reporting_year"] and t["fraction"] == "16/31"
        assert t["reporting_year"] == "FY2023-24"
        assert r.segments[1].trace["allocation"]["reporting_year"] == "FY2024-25"

    def test_cross_calendar_year_uk(self, seeded):
        # 3,100 kWh, 15 Dec 2025 - 14 Jan 2026 (31 days): 17 days @ 0.177 + 14 days @ 0.13096
        #   1,700 x 0.177 = 300.9 ; 1,400 x 0.13096 = 183.344 ; total 484.244
        r = calculate(inp(region="UK", period_start=date(2025, 12, 15), period_end=date(2026, 1, 14),
                          quantity=D(3100), fiscal_year_start_month=1), seeded)
        assert [s.kgco2e for s in r.segments] == [D("300.9"), D("183.344")]
        assert r.segments[0].trace["allocation"]["reporting_year"] == "2025"
        assert r.segments[1].trace["allocation"]["reporting_year"] == "2026"

    def test_quarterly_bill_split_by_month(self, seeded):
        # 9,000 kWh over Q1 2025 (90 days): 3,100 / 2,800 / 3,100 kWh x 0.177
        r = calculate(inp(region="UK", period_start=date(2025, 1, 1), period_end=date(2025, 3, 31),
                          quantity=D(9000)), seeded)
        assert [s.kgco2e for s in r.segments] == [D("548.7"), D("495.6"), D("548.7")]
        assert kg(r) == D(9000) * D("0.177")

    def test_non_terminating_split_rounds_each_segment_and_sums_correctly(self, seeded):
        # 100 kWh gas over 31 Jan - 2 Feb 2025: 1/3 and 2/3 of 18.296 kg
        #   6.098666.. -> 6.098667 ; 12.197333.. -> 12.197333 ; sum 18.296000
        r = calculate(inp(utility_type="natural_gas", region="UK", period_start=date(2025, 1, 31),
                          period_end=date(2025, 2, 2), quantity=D(100)), seeded)
        assert [s.kgco2e for s in r.segments] == [D("6.098667"), D("12.197333")]
        assert kg(r) == D("18.296")
        assert r.segments[0].fraction == D("0.333333333333")
        assert r.segments[0].trace["result"]["unrounded"].startswith("6.0986666666")

    def test_leap_february(self, seeded):
        # 2,900 kWh over Feb 2024 (29 days) -> 2.9 MWh x 727 = 2,108.3
        r = calculate(inp(period_start=date(2024, 2, 1), period_end=date(2024, 2, 29), quantity=D(2900)), seeded)
        assert len(r.segments) == 1 and r.total_days == 29 and kg(r) == D("2108.3")

    def test_therms_to_mmbtu(self, seeded):
        # 1,000 therms = 100 MMBtu x 53.1145 = 5,311.45 kg CO2e, Scope 1
        r = calculate(inp(utility_type="natural_gas", region="US", unit="therms", quantity=D(1000),
                          period_start=date(2025, 1, 1), period_end=date(2025, 1, 31)), seeded)
        s = r.segments[0]
        assert (s.normalized_quantity, s.normalized_unit, s.kgco2e, s.scope) == (D(100), "MMBtu", D("5311.45"), 1)
        assert "100,000 Btu" in s.trace["normalization"]["definition"]

    def test_ccf_to_scf(self, seeded):
        # 100 ccf = 10,000 scf x 0.05449534 = 544.9534
        r = calculate(inp(utility_type="natural_gas", region="US", unit="CCF", quantity=D(100),
                          period_start=date(2025, 1, 1), period_end=date(2025, 1, 31)), seeded)
        assert kg(r) == D("544.9534") and r.segments[0].normalized_unit == "scf"

    def test_scm_with_uk_m3_factor(self, seeded):
        # 850 SCM treated as m3: 850 x 2.06672 = 1,756.712
        r = calculate(inp(utility_type="natural_gas", region="UK", unit="SCM", quantity=D(850),
                          period_start=date(2025, 4, 1), period_end=date(2025, 4, 30)), seeded)
        assert kg(r) == D("1756.712")

    def test_gj_with_ipcc_per_tj_factor(self, seeded):
        # 100 GJ = 0.1 TJ x 56,154.5 = 5,615.45
        r = calculate(inp(utility_type="natural_gas", unit="GJ", quantity=D(100)), seeded)
        assert kg(r) == D("5615.45") and r.segments[0].normalized_quantity == D("0.1")

    def test_mmbtu_bill_with_ipcc_tj_factor(self, seeded):
        # 10 MMBtu = 0.0105505585262 TJ x 56,154.5 = 592.4615..
        r = calculate(inp(utility_type="natural_gas", unit="MMBtu", quantity=D(10)), seeded)
        assert kg(r) == (D("0.0105505585262") * D("56154.5")).quantize(D("0.000001"))

    def test_meter_reading_quantity(self, seeded):
        # (57,710 - 45,210) x 1 = 12,500 kWh
        r = calculate(inp(quantity=None, meter_previous=D(45210), meter_current=D(57710), meter_multiplier=D(1)), seeded)
        assert kg(r) == D("9087.5")
        q = r.segments[0].trace["quantity"]
        assert q["source"] == "meter_readings" and q["derivation"] == "(57710 - 45210) x 1 = 12500"

    def test_volume_bill_without_volume_factor_fails(self, seeded):
        with pytest.raises(CalculationError, match="calorific value"):
            calculate(inp(utility_type="natural_gas", unit="SCM", quantity=D(850)), seeded)

    def test_bill_running_past_factor_coverage_fails_entirely(self, seeded):
        # Dec 2026 is covered, Jan 2027 is not: no partial result.
        with pytest.raises(CalculationError, match="covers 2027-01-01"):
            calculate(inp(region="UK", period_start=date(2026, 12, 15), period_end=date(2027, 1, 14)), seeded)

    def test_factor_boundary_mid_month_splits_bill(self):
        a = custom("A", region="XX", value="1", end=date(2025, 1, 14))
        b = custom("B", region="XX", value="2", start=date(2025, 1, 15))
        # 310 kWh over Jan 2025: 14 days @1 + 17 days @2 = 140 + 340 = 480
        r = calculate(inp(region="XX", period_start=date(2025, 1, 1), period_end=date(2025, 1, 31), quantity=D(310)), [a, b])
        assert [(s.days, s.kgco2e) for s in r.segments] == [(14, D(140)), (17, D(340))]

    def test_superseded_factor_boundaries_ignored(self):
        old = custom("K", region="XX", value="9", end=date(2025, 1, 14), superseded=True)
        new = custom("K", region="XX", value="1", version=2)
        r = calculate(inp(region="XX", period_start=date(2025, 1, 1), period_end=date(2025, 1, 31), quantity=D(31)), [old, new])
        assert len(r.segments) == 1 and kg(r) == D(31)

    @pytest.mark.parametrize(("changes", "message"), [
        ({"quantity": None}, "No consumption quantity"),
        ({"quantity": D(0)}, "greater than zero"),
        ({"quantity": D(-5)}, "greater than zero"),
        ({"unit": "units"}, "not recognized"),
        ({"unit": None}, "not recognized"),
        ({"utility_type": "unknown"}, "Unknown utility type"),
        ({"period_end": date(2023, 12, 1)}, "before start"),
        ({"period_start": None}, "required"),
        ({"quantity": None, "meter_previous": D(10), "meter_current": D(5)}, "rollover"),
    ])
    def test_invalid_inputs_raise(self, seeded, changes, message):
        with pytest.raises(CalculationError, match=message):
            calculate(inp(**changes), seeded)

    def test_floats_rejected(self, seeded):
        with pytest.raises(TypeError, match="Decimal"):
            calculate(inp(quantity=12500.0), seeded)

    def test_factor_with_wrong_scope_rejected(self):
        f = custom("BAD", region="XX", scope=1)
        with pytest.raises(CalculationError, match="scope 1"):
            calculate(inp(region="XX"), [f])

    def test_trace_is_complete_and_formula_matches_result(self, seeded):
        s = calculate(inp(), seeded).segments[0]
        t = s.trace
        assert set(t) == {"engine_version", "quantity", "allocation", "normalization", "factor", "formula", "result"}
        assert t["formula"] == "12500 kWh x 31/31 days x 0.001 MWh/kWh x 727 kg CO2/MWh = 9087.5 kg CO2"
        assert t["factor"]["source_url"].startswith("https://cea.nic.in")
        assert t["factor"]["ghg_basis"] == "CO2" and t["result"]["ghg_basis"] == "CO2"
        assert t["result"]["scope_basis"].startswith("Scope 2, location-based")
        assert t["factor"]["region_match"] == "exact" and t["factor"]["owner"] == "global"

    def test_deterministic(self, seeded):
        a, b = calculate(inp(), seeded), calculate(inp(), list(reversed(seeded)))
        assert [dataclasses.replace(s, factor=None) for s in a.segments] == [dataclasses.replace(s, factor=None) for s in b.segments]

    def test_prorated_segments_sum_to_whole_bill(self, seeded):
        # Property: over many random periods, segment kg sum to the unsplit total within rounding.
        rng = random.Random(7)
        flat = [custom("FLAT", region="XX", value="0.7317")]
        for _ in range(200):
            start = date(2024, 1, 1) + timedelta(days=rng.randrange(700))
            end = start + timedelta(days=rng.randrange(95))
            qty = D(rng.randrange(1, 10_000_000)) / 100
            r = calculate(inp(region="XX", period_start=start, period_end=end, quantity=qty), flat)
            exact = qty * D("0.7317")
            assert abs(kg(r) - exact) <= D("0.000001") * len(r.segments)
            assert sum(s.quantity for s in r.segments) == pytest.approx(qty, abs=D("1e-20"))


@pytest.mark.parametrize(("kg_value", "tonnes"), [
    ("8875.000000", "8.875"), ("0.0005", "0.000"), ("1500.5", "1.500"), ("1501.5", "1.502"), ("999999.9996", "1000.000"),
])
def test_kg_to_tonnes_half_even(kg_value, tonnes):
    from app.calc.engine import kg_to_tonnes

    assert str(kg_to_tonnes(D(kg_value))) == tonnes
