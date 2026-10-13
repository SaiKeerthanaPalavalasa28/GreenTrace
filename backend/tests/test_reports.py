"""Inspector report: snapshot contents, PDF content, reproducibility, verification, API.
Uses the dashboard fixture (same hand-checked figures: FY2023-24 total 15.866 t)."""

import hashlib
import io
import json
import uuid

import pdfplumber
import pytest
from sqlalchemy.orm import sessionmaker

from app.models import Report
from app.reports.pdf import render_pdf
from app.reports.snapshot import snapshot_sha256
from app.storage import LocalStorage, get_storage
from tests.conftest import register
from tests.test_dashboard import FY23, add_bill, org_data  # noqa: F401  (fixture)


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(tmp_path / "files")


@pytest.fixture
def api(org_data, storage):  # noqa: F811
    from app.main import app

    app.dependency_overrides[get_storage] = lambda: storage
    return org_data


def create(client, headers, **body):
    r = client.post("/api/reports", headers=headers, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def pdf_text(data: bytes) -> str:
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


def test_generate_report_snapshot_and_pdf(api, engine):
    client, headers, _ = api
    rep = create(client, headers, period_start=FY23["period_start"], period_end=FY23["period_end"])
    assert rep["reporting_period_label"] == "FY2023-24"
    assert rep["is_draft"] is True and rep["status"] == "draft"  # one bill awaiting review
    s = rep["summary"]
    assert (s["total_t"], s["scope1_t"], s["scope2_t"]) == ("15.866", "5.615", "10.251")
    assert s["bills_included"] == 3 and s["bills_excluded"] == 1

    with sessionmaker(bind=engine)() as db:
        snap = db.get(Report, uuid.UUID(rep["id"])).snapshot_json
    assert snapshot_sha256(snap) == rep["snapshot_sha256"]
    assert len(snap["records"]) == 3  # A, March part of B, C (April part of B is next year)
    assert {f["key"] for f in snap["factors"]} == {"IN-CEA-GRID-FY2023-24", "IN-IPCC2006-NATGAS-MFG"}
    assert [b["reason"] for b in snap["excluded_bills"]] == ["awaiting review"]
    assert all(isinstance(r["kgco2e"], str) for r in snap["records"])  # never floats

    pdf = client.get(f"/api/reports/{rep['id']}/download", headers=headers)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert hashlib.sha256(pdf.content).hexdigest() == rep["pdf_sha256"]
    assert "DRAFT.pdf" in pdf.headers["content-disposition"]
    text = pdf_text(pdf.content)
    for expected in ["Acme Ltd", "FY2023-24", "15.866", "5.615", "10.251", "Executive summary", "Methodology",
                     "IN-CEA-GRID-FY2023-24", "Appendix A", "Appendix B", "Appendix C", "awaiting review",
                     "location-based", "9,087.500", rep["id"]]:
        assert expected in text, expected


def test_snapshot_download_is_canonical_json(api):
    client, headers, _ = api
    rep = create(client, headers, **FY23)
    r = client.get(f"/api/reports/{rep['id']}/snapshot", headers=headers)
    assert r.headers["content-type"] == "application/json"
    assert hashlib.sha256(r.content).hexdigest() == rep["snapshot_sha256"]
    assert json.loads(r.content)["report_id"] == rep["id"]


def test_verify_detects_tampering(api, storage, engine):
    client, headers, _ = api
    rep = create(client, headers, **FY23)
    ok = client.post(f"/api/reports/{rep['id']}/verify", headers=headers).json()
    assert ok["pdf_matches_recorded_hash"] and ok["snapshot_matches_recorded_hash"] and ok["rerender_matches"]

    with sessionmaker(bind=engine)() as db:
        key = db.get(Report, uuid.UUID(rep["id"])).file_path
    storage.save_file(key, storage.read(key) + b"% tampered")
    bad = client.post(f"/api/reports/{rep['id']}/verify", headers=headers).json()
    assert bad["pdf_matches_recorded_hash"] is False and bad["rerender_matches"] is True


def test_report_reproduces_after_data_changes(api, engine):
    client, headers, _ = api
    rep = create(client, headers, **FY23)
    # Change live data: approve a correction on a new bill and add an org factor that changes results.
    r = client.post("/api/factors", headers=headers, json={
        "factor_key": "ACME-GREEN", "utility_type": "electricity", "region": "IN", "per_unit": "kWh",
        "published": [{"gas": "CO2e", "value": "0.1", "mass_unit": "kg"}], "source_name": "PPA",
        "source_url": "https://example.org", "publication_year": 2023, "valid_from": "2023-04-01", "valid_to": "2024-03-31"})
    assert r.status_code == 201
    new = create(client, headers, **FY23)
    assert new["summary"]["total_t"] != rep["summary"]["total_t"]
    # The old report is still exactly reproducible from its snapshot.
    v = client.post(f"/api/reports/{rep['id']}/verify", headers=headers).json()
    assert v["rerender_matches"] and v["pdf_matches_recorded_hash"]


def test_complete_period_is_final(api):
    client, headers, _ = api
    rep = create(client, headers, period_start="2024-04-01", period_end="2025-03-31")
    assert rep["is_draft"] is False and rep["status"] == "final"
    assert rep["summary"]["total_t"] == "1.065"
    text = pdf_text(client.get(f"/api/reports/{rep['id']}/download", headers=headers).content)
    assert "COMPLETE" in text and "DRAFT" not in text


def test_custom_label_and_validation(api):
    client, headers, _ = api
    rep = create(client, headers, period_start="2024-01-01", period_end="2024-03-31")
    assert rep["reporting_period_label"] == "Jan 2024 to Mar 2024"
    assert create(client, headers, period_start="2024-01-01", period_end="2024-03-31", label="Q4 FY24")["reporting_period_label"] == "Q4 FY24"
    for body in [{"period_start": "2024-01-02", "period_end": "2024-03-31"},
                 {"period_start": "2024-01-01", "period_end": "2024-03-30"},
                 {"period_start": "2024-04-01", "period_end": "2024-03-31"}]:
        assert client.post("/api/reports", headers=headers, json=body).status_code == 422


def test_reports_are_org_scoped(api):
    client, headers, _ = api
    rep = create(client, headers, **FY23)
    other = register(client, email="x@globex.example.com", org="Globex")
    for path in ["", "/download", "/snapshot"]:
        assert client.get(f"/api/reports/{rep['id']}{path}", headers=other).status_code == 404
    assert client.post(f"/api/reports/{rep['id']}/verify", headers=other).status_code == 404
    assert client.get("/api/reports", headers=other).json() == []
    assert [r["id"] for r in client.get("/api/reports", headers=headers).json()] == [rep["id"]]


def test_render_is_deterministic_and_handles_empty_period(api, engine):
    client, headers, _ = api
    rep = create(client, headers, period_start="2020-01-01", period_end="2020-12-31")
    with sessionmaker(bind=engine)() as db:
        snap = db.get(Report, uuid.UUID(rep["id"])).snapshot_json
    assert render_pdf(snap) == render_pdf(snap)
    text = pdf_text(render_pdf(snap))
    assert "No factors used" in text and "0.000" in text


def test_corrections_appear_in_appendix_b(api, engine):
    from datetime import date

    from app.models import Extraction, Facility, User

    client, headers, ids = api
    with sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)() as db:
        user = db.query(User).filter(User.email == "admin@acme.example.com").one()
        fac = db.get(Facility, uuid.UUID(ids["pune"]))
        bill = add_bill(db, user.org_id, user.id, fac, "electricity", date(2023, 5, 1), date(2023, 5, 31), "1000", "kWh")
        e = db.query(Extraction).filter(Extraction.bill_id == bill.id).one()
        e.corrections_json = {"quantity": {"before": "10000.000000", "after": "1000.000000"}}
        e.reviewed_by = user.id
        db.commit()
    rep = create(client, headers, **FY23)
    text = pdf_text(client.get(f"/api/reports/{rep['id']}/download", headers=headers).content)
    assert "Manual corrections" in text and "10,000" in text and "admin@acme.example.com" in text
