"""Calculation persistence: records + traces, recalculation on factor changes, idempotency,
failure handling, and the trace / recalculate endpoints."""

import uuid
from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from app.calc.factor_derivation import PublishedComponent
from app.calc.service import calculate_bill, current_records, recalculate
from app.enums import BillStatus
from app.factor_service import SEED_PATH, FactorSpec, add_factor
from app.models import AuditLog, Bill, EmissionRecord, Extraction, Facility, Organization, User
from app.seed import load_seed
from tests.conftest import bill_pdf, map_account, upload


def make_bill(db, *, region="IN", utility="electricity", start=date(2024, 1, 1), end=date(2024, 1, 31),
              quantity="12500", unit="kWh", status=BillStatus.approved, org=None, fy=4) -> Bill:
    if org is None:
        org = Organization(name=f"Org {uuid.uuid4().hex[:6]}", reporting_framework="BRSR",
                           default_region=region, fiscal_year_start_month=fy)
        db.add(org)
        db.flush()
    user = User(org_id=org.id, email=f"{uuid.uuid4().hex[:8]}@example.com", password_hash="x", role="admin")
    facility = Facility(org_id=org.id, name=f"Site {uuid.uuid4().hex[:6]}", region=region)
    db.add_all([user, facility])
    db.flush()
    bill = Bill(org_id=org.id, facility_id=facility.id, original_filename="bill.pdf", file_path="x",
                file_hash=uuid.uuid4().hex, file_size=1, utility_type=utility, status=status, uploaded_by=user.id)
    db.add(bill)
    db.flush()
    db.add(Extraction(bill_id=bill.id, billing_period_start=start, billing_period_end=end,
                      quantity=D(quantity) if quantity else None, unit=unit, raw_text_snippet="Units: 12,500",
                      page_number=1, confidence=0.99, model_used="fake"))
    db.flush()
    return bill


def org_factor(db, org_id, key, value, *, region="IN", start=date(2025, 4, 1), end=date(2026, 3, 31), version=1):
    return add_factor(db, FactorSpec(
        key=key, version=version, utility_type="electricity", region=region, per_unit="kWh",
        published=[PublishedComponent("CO2e", D(value), "kg")], source_name="test", source_url="https://example.org",
        publication_year=2025, valid_from=start, valid_to=end, org_id=org_id), actor="test")


def total(db, bill) -> D:
    return sum((D(r.kgco2e) for r in current_records(db, bill.id)), D(0))


# ---------------------------------------------------------------- service

def test_calculate_creates_records_with_full_trace(seeded_db):
    db = seeded_db
    bill = make_bill(db)
    assert calculate_bill(db, bill, actor="test", reason="test") == "calculated"
    (rec,) = current_records(db, bill.id)
    assert (D(rec.kgco2e), D(rec.normalized_quantity), rec.normalized_unit, rec.scope) == (D("9087.5"), D("12.5"), "MWh", 2)
    t = rec.calculation_trace_json
    assert t["bill"]["file_sha256"] == bill.file_hash and t["bill"]["facility_region"] == "IN"
    assert t["extraction"]["source_snippet"] == "Units: 12,500"
    assert t["extraction"]["approval"].startswith("automatic")
    assert t["factor"]["key"] == "IN-CEA-GRID-FY2023-24"
    assert t["formula"].endswith("= 9087.5 kg CO2")
    assert bill.calculation_error is None


def test_cross_year_bill_stores_one_record_per_segment(seeded_db):
    db = seeded_db
    bill = make_bill(db, start=date(2024, 3, 16), end=date(2024, 4, 15), quantity="3100")
    calculate_bill(db, bill, actor="test", reason="test")
    recs = current_records(db, bill.id)
    assert [(r.allocation_start, r.allocation_end, D(r.kgco2e)) for r in recs] == [
        (date(2024, 3, 16), date(2024, 3, 31), D("1163.2")), (date(2024, 4, 1), date(2024, 4, 15), D("1065"))]
    assert D(recs[0].allocation_fraction) == D("0.516129032258")  # 16/31


def test_recalculation_is_idempotent(seeded_db):
    db = seeded_db
    bill = make_bill(db)
    calculate_bill(db, bill, actor="test", reason="first")
    assert calculate_bill(db, bill, actor="test", reason="again") == "unchanged"
    assert len(db.scalars(select(EmissionRecord)).all()) == 1
    assert recalculate(db, actor="test", reason="bulk") == {"calculated": 0, "unchanged": 1, "error": 0}


def test_missing_factor_records_error_and_contributes_nothing(seeded_db):
    db = seeded_db
    bill = make_bill(db, start=date(2025, 6, 1), end=date(2025, 6, 30))  # no CEA factor after FY2024-25
    assert calculate_bill(db, bill, actor="test", reason="test") == "error"
    assert "covers 2025-06-01" in bill.calculation_error
    assert current_records(db, bill.id) == []
    assert bill.status == BillStatus.approved

    # Adding the missing factor and recalculating fixes it.
    org_factor(db, bill.org_id, "ACME-IN-FY2025-26", "0.7")
    assert recalculate(db, actor="test", reason="factor added", org_id=bill.org_id)["calculated"] == 1
    assert bill.calculation_error is None
    assert total(db, bill) == D("8750")  # 12,500 kWh x 0.7


def test_new_factor_version_triggers_recalculation_and_keeps_history(seeded_db):
    db = seeded_db
    bill = make_bill(db, start=date(2025, 6, 1), end=date(2025, 6, 30))
    v1 = org_factor(db, bill.org_id, "ACME-IN-FY2025-26", "0.7")
    calculate_bill(db, bill, actor="test", reason="test")
    first_ids = {r.id for r in current_records(db, bill.id)}

    org_factor(db, bill.org_id, "ACME-IN-FY2025-26", "0.8", version=2)
    stats = recalculate(db, actor="test", reason="v2", org_id=bill.org_id)
    assert stats == {"calculated": 1, "unchanged": 0, "error": 0}
    assert total(db, bill) == D("10000")
    assert v1.superseded_by is not None
    old = db.scalars(select(EmissionRecord).where(EmissionRecord.id.in_(first_ids))).all()
    assert all(not r.is_current for r in old)  # kept for audit, not deleted
    db.flush()
    log = db.scalars(select(AuditLog).where(AuditLog.entity_id == str(bill.id), AuditLog.action == "recalculate")).one()
    assert log.before_json["kgco2e"] == "8750.000000" and log.after_json["kgco2e"] == "10000.000000"


def test_org_factor_takes_precedence_after_recalculation(seeded_db):
    db = seeded_db
    bill = make_bill(db)
    calculate_bill(db, bill, actor="test", reason="test")
    org_factor(db, bill.org_id, "ACME-GREEN-TARIFF", "0.1", start=date(2023, 4, 1), end=date(2024, 3, 31))
    recalculate(db, actor="test", reason="org factor", org_id=bill.org_id)
    (rec,) = current_records(db, bill.id)
    assert D(rec.kgco2e) == D("1250")
    assert rec.calculation_trace_json["factor"]["owner"] == "organization"


def test_unapproved_bill_has_records_retired(seeded_db):
    db = seeded_db
    bill = make_bill(db)
    calculate_bill(db, bill, actor="test", reason="test")
    bill.status = BillStatus.rejected
    calculate_bill(db, bill, actor="test", reason="rejected")
    assert current_records(db, bill.id) == []
    assert db.scalars(select(EmissionRecord)).one().is_current is False


def test_error_after_success_retires_stale_records(seeded_db):
    db = seeded_db
    bill = make_bill(db)
    calculate_bill(db, bill, actor="test", reason="test")
    db.scalars(select(Extraction).where(Extraction.bill_id == bill.id)).one().unit = "units"
    assert calculate_bill(db, bill, actor="test", reason="unit changed") == "error"
    assert current_records(db, bill.id) == []


def test_seed_correction_recalculates_existing_bills(db, tmp_path):
    load_seed(db)
    bill = make_bill(db, region="UK", start=date(2025, 3, 1), end=date(2025, 3, 31), quantity="1000", fy=1)
    calculate_bill(db, bill, actor="test", reason="test")
    db.commit()
    assert total(db, bill) == D("177")  # 1,000 kWh x 0.177

    text = SEED_PATH.read_text(encoding="utf-8") + '''
  # TODO: verify against latest published edition
  - key: UK-DESNZ-ELEC-2025
    version: 2
    utility_type: electricity
    region: UK
    per_unit: kWh
    published:
      - {gas: CO2e, value: "0.2", mass_unit: kg}
    source_name: "test correction"
    source_url: "https://example.org"
    publication_year: 2025
    valid_from: 2025-01-01
    valid_to: 2025-12-31
'''
    path = tmp_path / "seed.yaml"
    path.write_text(text, encoding="utf-8")
    stats = load_seed(db, path)
    assert stats["recalculation"]["calculated"] == 1
    assert total(db, bill) == D("200")


# ---------------------------------------------------------------- API

def test_trace_and_list_endpoints(api, engine):
    client, headers, fid = api
    map_account(engine, fid)
    bill_id = upload(client, headers, fid, ("april.pdf", bill_pdf()))[0]["bill_id"]

    trace = client.get(f"/api/bills/{bill_id}/trace", headers=headers).json()
    assert trace["total_kgco2e"] == "8875.000000"  # April 2024: 12.5 MWh x 710
    assert trace["total_tco2e"] == "8.875"
    (rec,) = trace["records"]
    t = rec["calculation_trace_json"]
    assert t["bill"]["file_name"] == "april.pdf"
    assert t["factor"]["key"] == "IN-CEA-GRID-FY2024-25"
    assert t["formula"] == "12500 kWh x 30/30 days x 0.001 MWh/kWh x 710 kg CO2/MWh = 8875 kg CO2"
    assert trace["superseded_records"] == []

    (item,) = client.get("/api/bills", headers=headers).json()
    assert item["kgco2e"] == "8875.000000" and item["tco2e"] == "8.875" and item["calculation_error"] is None


def test_org_factor_via_api_recalculates_and_trace_shows_history(api, engine):
    client, headers, fid = api
    map_account(engine, fid)
    bill_id = upload(client, headers, fid, ("april.pdf", bill_pdf()))[0]["bill_id"]
    r = client.post("/api/factors", headers=headers, json={
        "factor_key": "ACME-PPA", "utility_type": "electricity", "region": "IN", "per_unit": "kWh",
        "published": [{"gas": "CO2e", "value": "0.05", "mass_unit": "kg"}], "source_name": "PPA certificate",
        "source_url": "https://example.org/ppa", "publication_year": 2024,
        "valid_from": "2024-04-01", "valid_to": "2025-03-31"})
    assert r.status_code == 201, r.text
    trace = client.get(f"/api/bills/{bill_id}/trace", headers=headers).json()
    assert trace["total_kgco2e"] == "625.000000"  # 12,500 x 0.05
    assert [x["kgco2e"] for x in trace["superseded_records"]] == ["8875.000000"]


def test_recalculate_endpoint_admin_only(api):
    client, headers, fid = api
    r = client.post("/api/bills/recalculate", headers=headers)
    assert r.status_code == 200 and r.json() == {"calculated": 0, "unchanged": 0, "error": 0}
    client.post("/api/users", headers=headers, json={"email": "m@acme.example.com", "password": "member-password-1"})
    token = client.post("/api/auth/login", json={"email": "m@acme.example.com", "password": "member-password-1"}).json()
    assert client.post("/api/bills/recalculate", headers={"Authorization": f"Bearer {token['access_token']}"}).status_code == 403


def test_trace_is_org_scoped(api):
    from tests.conftest import register

    client, headers, fid = api
    bill_id = upload(client, headers, fid, ("april.pdf", bill_pdf()))[0]["bill_id"]
    other = register(client, email="x@globex.example.com", org="Globex")
    assert client.get(f"/api/bills/{bill_id}/trace", headers=other).status_code == 404
