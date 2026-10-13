"""Dashboard aggregation. Expected values worked by hand (FY = April-March, India):

  A Pune     electricity Jan 2024        12,500 kWh x 727/MWh          = 9,087.5  kg  (scope 2)
  B Pune     electricity 16 Mar-15 Apr   3,100 kWh: Mar 16/31 @727     = 1,163.2  kg  (FY2023-24)
                                                    Apr 15/31 @710     = 1,065.0  kg  (FY2024-25)
  C Chennai  natural gas Feb 2024        100 GJ = 0.1 TJ x 56,154.5    = 5,615.45 kg  (scope 1)
  D Chennai  electricity Jan 2024        needs review                  -> excluded, counted pending
  E Pune     electricity Feb 2024        rejected                      -> ignored
  F Pune     electricity Jun 2025        approved, no factor           -> calculation error (FY2025-26)

FY2023-24: scope 2 = 10,250.7 kg -> 10.251 t; scope 1 = 5,615.45 kg -> 5.615 t; total 15,866.15 kg -> 15.866 t
"""

import uuid
from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy.orm import sessionmaker

from app.calc.service import calculate_bill
from app.enums import BillStatus
from app.models import Bill, Extraction, Facility, Organization, User
from tests.conftest import register

FY23 = {"period_start": "2023-04-01", "period_end": "2024-03-31"}


def add_bill(db, org_id, user_id, facility, utility, start, end, qty, unit, status=BillStatus.approved):
    bill = Bill(org_id=org_id, facility_id=facility.id, original_filename=f"{facility.name}-{start}.pdf", file_path="x",
                file_hash=uuid.uuid4().hex, file_size=1, utility_type=utility, status=status, uploaded_by=user_id)
    db.add(bill)
    db.flush()
    db.add(Extraction(bill_id=bill.id, billing_period_start=start, billing_period_end=end, quantity=D(qty), unit=unit,
                      raw_text_snippet="x", page_number=1, confidence=0.99))
    db.flush()
    calculate_bill(db, bill, actor="test", reason="test")
    return bill


@pytest.fixture
def org_data(client, engine):
    headers = register(client)
    me = client.get("/api/auth/me", headers=headers).json()
    org_id, user_id = uuid.UUID(me["organization"]["id"]), uuid.UUID(me["user"]["id"])
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with Session() as db:
        pune = Facility(org_id=org_id, name="Pune", region="IN")
        chennai = Facility(org_id=org_id, name="Chennai", region="IN")
        db.add_all([pune, chennai])
        db.flush()
        add_bill(db, org_id, user_id, pune, "electricity", date(2024, 1, 1), date(2024, 1, 31), "12500", "kWh")
        add_bill(db, org_id, user_id, pune, "electricity", date(2024, 3, 16), date(2024, 4, 15), "3100", "kWh")
        add_bill(db, org_id, user_id, chennai, "natural_gas", date(2024, 2, 1), date(2024, 2, 29), "100", "GJ")
        add_bill(db, org_id, user_id, chennai, "electricity", date(2024, 1, 1), date(2024, 1, 31), "999", "kWh",
                 status=BillStatus.needs_review)
        add_bill(db, org_id, user_id, pune, "electricity", date(2024, 2, 1), date(2024, 2, 29), "999", "kWh",
                 status=BillStatus.rejected)
        f = add_bill(db, org_id, user_id, pune, "electricity", date(2025, 6, 1), date(2025, 6, 30), "100", "kWh")
        assert f.calculation_error
        db.commit()
        return client, headers, {"pune": str(pune.id), "chennai": str(chennai.id)}


def get(client, headers, **params):
    r = client.get("/api/dashboard", headers=headers, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_totals_scopes_and_completeness(org_data):
    client, headers, _ = org_data
    d = get(client, headers, **FY23)
    assert d["totals"] == {
        "tco2e": "15.866", "scope1_tco2e": "5.615", "scope2_tco2e": "10.251",
        "scope1_share_pct": "35.4", "scope2_share_pct": "64.6", "kgco2e": "15866.150000",
        "parts_sum_differs": False,  # 5.615 + 10.251 = 15.866
    }
    assert d["bills"] == {"included": 3, "pending_review": 1, "processing": 0, "failed": 0, "calculation_errors": 0}
    assert d["completeness"] == {"is_partial": True, "excluded_bills": 1}
    assert d["ghg_basis"] == {"co2_only_tco2e": "10.251", "co2e_tco2e": "5.615"}


def test_rounding_note_when_parts_do_not_sum(client, engine):
    # Scope 1: 1,000.4 kg -> 1.000 t ; Scope 2: 1,000.4 kg -> 1.000 t ; total 2,000.8 kg -> 2.001 t
    headers = register(client)
    me = client.get("/api/auth/me", headers=headers).json()
    org_id, user_id = uuid.UUID(me["organization"]["id"]), uuid.UUID(me["user"]["id"])
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with Session() as db:
        fac = Facility(org_id=org_id, name="Site", region="UK")
        db.add(fac)
        db.flush()
        # UK 2025: gas 0.18296/kWh, electricity 0.177/kWh
        add_bill(db, org_id, user_id, fac, "natural_gas", date(2025, 1, 1), date(2025, 1, 31), str(D("1000.4") / D("0.18296")), "kWh")
        add_bill(db, org_id, user_id, fac, "electricity", date(2025, 1, 1), date(2025, 1, 31), str(D("1000.4") / D("0.177")), "kWh")
        db.commit()
    t = get(client, headers, period_start="2025-01-01", period_end="2025-01-31")["totals"]
    assert (t["scope1_tco2e"], t["scope2_tco2e"], t["tco2e"]) == ("1.000", "1.000", "2.001")
    assert t["parts_sum_differs"] is True


def test_monthly_series_covers_every_month(org_data):
    client, headers, _ = org_data
    monthly = get(client, headers, **FY23)["monthly"]
    assert [m["month"] for m in monthly] == ["2023-04", "2023-05", "2023-06", "2023-07", "2023-08", "2023-09",
                                             "2023-10", "2023-11", "2023-12", "2024-01", "2024-02", "2024-03"]
    by = {m["month"]: m for m in monthly}
    assert by["2024-01"] == {"month": "2024-01", "scope1_tco2e": "0.000", "scope2_tco2e": "9.088", "total_tco2e": "9.088"}
    assert by["2024-02"]["scope1_tco2e"] == "5.615" and by["2024-02"]["scope2_tco2e"] == "0.000"
    assert by["2024-03"]["scope2_tco2e"] == "1.163"
    assert by["2023-04"]["total_tco2e"] == "0.000"


def test_cross_year_bill_counts_in_each_year(org_data):
    client, headers, _ = org_data
    d = get(client, headers, period_start="2024-04-01", period_end="2025-03-31")
    assert d["totals"]["scope2_tco2e"] == "1.065"  # April part of bill B only
    assert d["bills"]["included"] == 1


def test_facility_breakdown_and_donut(org_data):
    client, headers, ids = org_data
    d = get(client, headers, **FY23)
    assert [(f["name"], f["tco2e"], f["share_pct"]) for f in d["by_facility"]] == [
        ("Pune", "10.251", "64.6"), ("Chennai", "5.615", "35.4")]
    assert [s["name"] for s in d["facility_donut"]] == ["Pune", "Chennai"]


def test_donut_folds_tail_into_other(client, engine):
    headers = register(client)
    me = client.get("/api/auth/me", headers=headers).json()
    org_id, user_id = uuid.UUID(me["organization"]["id"]), uuid.UUID(me["user"]["id"])
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with Session() as db:
        for i, qty in enumerate(["5000", "4000", "3000", "2000", "1000"]):
            fac = Facility(org_id=org_id, name=f"Site {i}", region="IN")
            db.add(fac)
            db.flush()
            add_bill(db, org_id, user_id, fac, "electricity", date(2024, 1, 1), date(2024, 1, 31), qty, "kWh")
        db.commit()
    donut = get(client, headers, **FY23)["facility_donut"]
    assert [s["name"] for s in donut] == ["Site 0", "Site 1", "Site 2", "Other (2 facilities)"]
    assert donut[-1]["tco2e"] == "2.181"  # 3,000 kWh x 0.727


def test_filters(org_data):
    client, headers, ids = org_data
    gas = get(client, headers, utility_type="natural_gas", **FY23)
    assert gas["totals"]["tco2e"] == "5.615" and gas["totals"]["scope2_tco2e"] == "0.000"
    assert gas["bills"]["pending_review"] == 0  # the pending bill is electricity
    pune = get(client, headers, facility_id=ids["pune"], **FY23)
    assert pune["totals"]["tco2e"] == "10.251" and pune["bills"]["pending_review"] == 0
    chennai = get(client, headers, facility_id=ids["chennai"], **FY23)
    assert chennai["bills"]["pending_review"] == 1


def test_calculation_errors_flagged_in_their_period(org_data):
    client, headers, _ = org_data
    d = get(client, headers, period_start="2025-04-01", period_end="2026-03-31")
    assert d["totals"]["tco2e"] == "0.000"
    assert d["bills"]["calculation_errors"] == 1 and d["completeness"]["is_partial"] is True


def test_empty_period(org_data):
    client, headers, _ = org_data
    d = get(client, headers, period_start="2020-01-01", period_end="2020-12-31")
    assert d["totals"]["tco2e"] == "0.000" and d["totals"]["scope1_share_pct"] is None
    assert d["completeness"] == {"is_partial": False, "excluded_bills": 0}


@pytest.mark.parametrize("params", [
    {"period_start": "2023-04-02", "period_end": "2024-03-31"},
    {"period_start": "2023-04-01", "period_end": "2024-03-30"},
    {"period_start": "2024-04-01", "period_end": "2024-03-31"},
    {"period_start": "2010-01-01", "period_end": "2024-12-31"},
])
def test_period_validation(org_data, params):
    client, headers, _ = org_data
    assert client.get("/api/dashboard", headers=headers, params=params).status_code == 422


def test_periods_endpoint(org_data):
    client, headers, _ = org_data
    p = client.get("/api/dashboard/periods", headers=headers).json()
    labels = [y["label"] for y in p["years"]]
    assert {"FY2023-24", "FY2024-25"} <= set(labels)
    assert labels == sorted(labels, reverse=True)
    fy23 = next(y for y in p["years"] if y["label"] == "FY2023-24")
    assert (fy23["start"], fy23["end"], fy23["has_data"]) == ("2023-04-01", "2024-03-31", True)
    assert p["default"] == "FY2024-25"  # latest year with approved emissions


def test_other_org_sees_nothing(org_data):
    client, _, _ = org_data
    other = register(client, email="x@globex.example.com", org="Globex")
    d = get(client, other, **FY23)
    assert d["totals"]["tco2e"] == "0.000" and d["by_facility"] == [] and d["bills"]["pending_review"] == 0


def test_bills_list_period_filter(org_data):
    client, headers, _ = org_data
    items = client.get("/api/bills", headers=headers, params={**FY23, "utility_type": "electricity"}).json()
    # A, B (overlaps), D (pending), E (rejected) - not F (2025) and not C (gas)
    assert len(items) == 4
