import uuid
from datetime import date
from decimal import Decimal as D

import pytest

from app.calc.quantity import effective_quantity
from app.pipeline.schema import LLMExtraction
from app.pipeline.validate import HistoryPoint, ValidationContext, validate
from tests.helpers import ELECTRICITY_BILL, llm_json

PAGES = ["\n".join(ELECTRICITY_BILL)]
FACILITY = uuid.uuid4()


def ctx(**kw) -> ValidationContext:
    base = dict(today=date(2026, 10, 13), confidence_threshold=0.85, max_period_days=95,
                outlier_ratio=3.0, outlier_min_history=3, facility_id=FACILITY, mapped_facility_id=FACILITY)
    return ValidationContext(**{**base, **kw})


def run(pages=PAGES, context=None, **overrides):
    x = LLMExtraction.model_validate(llm_json(**overrides))
    return validate(x, pages, context or ctx())


def codes(result) -> set[str]:
    return {i.code for i in result.issues}


def test_clean_bill_passes():
    r = run()
    assert r.passed, r.issues
    assert r.quantity == D(12500) and r.canonical_unit == "kWh"


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"confidence": 0.84}, "low_confidence"),
        ({"utility_type": "unknown"}, "utility_unknown"),
        ({"multiple_meters_or_line_items": True}, "multiple_meters"),
        ({"read_type": "estimated"}, "estimated_read"),
        ({"notes": "Includes solar export credit"}, "model_notes"),
        ({"unit": None}, "unit_missing"),
        ({"unit": "units"}, "unit_not_allowed"),
        ({"unit": "litres"}, "unit_not_allowed"),
        ({"unit": "m3"}, "unit_utility_mismatch"),
        ({"billing_period_start": None}, "period_missing"),
        ({"billing_period_end": "2024-03-31"}, "period_order"),
        ({"billing_period_end": "2024-04-01", "billing_period_start": "2024-04-01"}, "period_order"),
        ({"billing_period_start": "2024-01-01"}, "period_too_long"),
        ({"billing_period_start": "2026-10-01", "billing_period_end": "2026-10-31"}, "period_in_future"),
        ({"quantity": "0", "source_snippet": "Units Consumed (kWh): 12,500"}, "quantity_not_positive"),
        ({"account_number": None}, "account_missing"),
        ({"source_snippet": "Units Consumed (kWh): 99,999"}, "snippet_not_found"),
        ({"page_number": 2}, "snippet_page_invalid"),
        ({"quantity": "12000"}, "quantity_not_in_snippet"),
    ],
)
def test_each_rule_sends_to_review(overrides, expected):
    r = run(**overrides)
    assert expected in codes(r), r.issues
    assert not r.passed


def test_period_exactly_at_limit_is_ok():
    # 2024-01-27 .. 2024-04-30 inclusive = 95 days
    r = run(billing_period_start="2024-01-27", meter_readings={"previous": None, "current": None, "multiplier": None})
    assert "period_too_long" not in codes(r)
    r = run(billing_period_start="2024-01-26")
    assert "period_too_long" in codes(r)


def test_indian_number_format_in_snippet():
    pages = ["Units Consumed: 1,23,456 kWh"]
    r = run(pages=pages, quantity="123456", source_snippet="Units Consumed: 1,23,456 kWh",
            meter_readings={"previous": None, "current": None, "multiplier": None})
    assert r.passed, r.issues


def test_snippet_whitespace_and_case_tolerant():
    r = run(source_snippet="units   consumed (KWH):\n12,500")
    assert "snippet_not_found" not in codes(r)


def test_snippet_found_on_other_page_says_where():
    pages = ["Cover page with enough text to be meaningful", PAGES[0]]
    r = run(pages=pages, page_number=1)
    issue = next(i for i in r.issues if i.code == "snippet_not_found")
    assert "appears on page 2" in issue.message


def test_quantity_from_meter_readings():
    r = run(quantity=None, source_snippet="Previous Reading: 45210   Current Reading: 57710   MF: 1")
    assert r.passed, r.issues
    assert r.quantity == D(12500)
    assert r.quantity_formula == "(57710 - 45210) x 1 = 12500"


def test_meter_readings_not_on_page_flagged():
    r = run(quantity=None, meter_readings={"previous": "1", "current": "9", "multiplier": "1"},
            source_snippet="Previous Reading: 45210   Current Reading: 57710   MF: 1")
    assert "readings_not_on_page" in codes(r)


def test_account_mapping_rules():
    assert "account_unmapped" in codes(run(context=ctx(mapped_facility_id=None)))
    assert "account_other_facility" in codes(run(context=ctx(mapped_facility_id=uuid.uuid4())))


def test_overlapping_bill_flagged():
    assert "overlapping_period" in codes(run(context=ctx(overlapping_bill_ids=[uuid.uuid4()])))


def _history(qty_per_30_days: str, n=3, unit="kWh"):
    return [HistoryPoint(D(qty_per_30_days), unit, 30) for _ in range(n)]


def test_outlier_needs_enough_history():
    assert "outlier" not in codes(run(context=ctx(history=_history("100", n=2))))


def test_outlier_high_and_low():
    assert "outlier" in codes(run(context=ctx(history=_history("1000"))))  # 12.5x
    assert "outlier" in codes(run(context=ctx(history=_history("400000"))))  # 0.03x
    assert "outlier" not in codes(run(context=ctx(history=_history("12500"))))


def test_outlier_compares_across_units_of_same_dimension():
    # 12.5 MWh per 30 days == 12,500 kWh per 30 days
    assert "outlier" not in codes(run(context=ctx(history=_history("12.5", unit="MWh"))))


def test_gas_bill_in_volume_unit_ok():
    pages = ["Mahanagar Gas Ltd  BP No 100200300  Gas consumed: 850 SCM  Period 01/04/2024 - 30/04/2024"]
    r = run(pages=pages, utility_type="natural_gas", unit="SCM", quantity="850", account_number="100200300",
            source_snippet="Gas consumed: 850 SCM", meter_readings={"previous": None, "current": None, "multiplier": None})
    assert r.passed, r.issues
    assert r.canonical_unit == "m3"


# ---- effective_quantity

def test_effective_quantity_cases():
    assert effective_quantity(D(5), None, None, None).value == D(5)
    q = effective_quantity(D(5), D(10), D(20), D(1))
    assert [c for c, _ in q.issues] == ["meter_mismatch"]
    q = effective_quantity(None, D(10), D(20), D(40))
    assert q.value == D(400) and not q.issues
    q = effective_quantity(None, D(10), D(20), None)
    assert q.value == D(10) and [c for c, _ in q.issues] == ["multiplier_not_printed"]
    q = effective_quantity(None, D(20), D(10), D(1))
    assert q.value is None and [c for c, _ in q.issues] == ["meter_rollover"]
    q = effective_quantity(None, None, D(10), None)
    assert q.value is None and [c for c, _ in q.issues] == ["quantity_missing"]
