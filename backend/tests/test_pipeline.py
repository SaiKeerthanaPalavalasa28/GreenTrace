"""Runner + upload API integration: real PDFs, real database, fake LLM, synchronous queue."""

import uuid
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models import AuditLog, Bill, Extraction, Facility, FacilityAccount
from app.pipeline import queue as queue_mod
from app.pipeline.errors import ExtractionError
from app.pipeline.runner import process_bill
from app.storage import LocalStorage, get_storage
from tests.conftest import bill_pdf, map_account, register, upload
from tests.helpers import ELECTRICITY_BILL, FakeExtractor, make_image_pdf

# ---------------------------------------------------------------- upload checks

def test_upload_batch_mixed_outcomes(api):
    client, headers, fid = api
    good = bill_pdf(tag="a")
    results = upload(
        client, headers, fid,
        ("april.pdf", good),
        ("april-copy.pdf", good),
        ("notes.txt", b"hello"),
        ("fake.pdf", b"<html>not a pdf</html>"),
    )
    outcomes = [(r["filename"], r["outcome"]) for r in results]
    assert outcomes == [("april.pdf", "queued"), ("april-copy.pdf", "duplicate"),
                        ("notes.txt", "rejected"), ("fake.pdf", "rejected")]
    assert "Same file as april.pdf" in results[1]["reason"]

    again = upload(client, headers, fid, ("april-again.pdf", good))
    assert again[0]["outcome"] == "duplicate"
    assert again[0]["bill_id"] == results[0]["bill_id"]
    assert "Already uploaded as april.pdf" in again[0]["reason"]


def test_upload_size_limit(api, monkeypatch):
    from app.config import get_settings

    client, headers, fid = api
    monkeypatch.setattr(get_settings(), "max_upload_mb", 0)
    r = upload(client, headers, fid, ("big.pdf", bill_pdf()))
    assert r[0]["outcome"] == "rejected" and "larger than" in r[0]["reason"]


def test_upload_to_other_orgs_facility_is_404(api):
    client, headers, fid = api
    other = register(client, email="x@globex.example.com", org="Globex")
    r = client.post("/api/bills/upload", headers=other, data={"facility_id": fid},
                    files=[("files", ("a.pdf", bill_pdf(), "application/pdf"))])
    assert r.status_code == 404


# ---------------------------------------------------------------- processing outcomes

def test_first_bill_of_new_account_goes_to_review(api):
    client, headers, fid = api
    bill_id = upload(client, headers, fid, ("april.pdf", bill_pdf()))[0]["bill_id"]
    detail = client.get(f"/api/bills/{bill_id}", headers=headers).json()
    assert detail["bill"]["status"] == "needs_review"
    assert detail["bill"]["utility_type"] == "electricity"
    issues = [i["code"] for i in detail["extraction"]["validation_issues_json"]]
    assert issues == ["account_unmapped"]
    e = detail["extraction"]
    assert e["quantity"] == "12500.000000" and e["unit"] == "kWh"
    assert e["text_method"] == "pdfplumber" and e["model_used"] == "fake-model"
    assert e["raw_text_snippet"] == "Units Consumed (kWh): 12,500"


def test_known_account_clean_bill_is_auto_approved_and_audited(api, engine):
    client, headers, fid = api
    map_account(engine, fid)
    bill_id = upload(client, headers, fid, ("april.pdf", bill_pdf()))[0]["bill_id"]
    assert client.get(f"/api/bills/{bill_id}", headers=headers).json()["bill"]["status"] == "approved"

    audit = client.get("/api/audit", headers=headers, params={"entity_id": bill_id}).json()
    assert [a["action"] for a in audit] == ["calculate", "auto_approve", "upload"]
    assert audit[1]["actor"] == "system"
    assert audit[1]["after_json"]["llm_output"]["quantity"] == "12500"
    # April 2024 is FY2024-25 for CEA: 12.5 MWh x 710 kg CO2/MWh
    assert audit[0]["after_json"]["kgco2e"] == "8875.000000"


def test_scanned_bill_without_ocr_fails_with_reason_and_batch_continues(api, monkeypatch):
    import pytesseract

    def missing(*a, **k):
        raise pytesseract.TesseractNotFoundError()

    monkeypatch.setattr(pytesseract, "image_to_string", missing)
    client, headers, fid = api
    results = upload(client, headers, fid,
                     ("scan.pdf", make_image_pdf(ELECTRICITY_BILL)),
                     ("broken.pdf", b"%PDF-1.4 truncated garbage"),
                     ("april.pdf", bill_pdf()))
    statuses = client.get("/api/bills/status", headers=headers,
                          params={"ids": ",".join(r["bill_id"] for r in results)}).json()
    by_id = {s["id"]: s for s in statuses}
    scan, broken, good = (by_id[r["bill_id"]] for r in results)
    assert scan["status"] == "failed" and "Tesseract is not installed" in scan["failure_reason"]
    assert broken["status"] == "failed" and "could not be read as a PDF" in broken["failure_reason"]
    assert good["status"] == "needs_review"


def test_llm_failure_marks_bill_failed(api, fake_llm):
    client, headers, fid = api
    fake_llm.responses = [ExtractionError("Could not reach the extraction model.")]
    bill_id = upload(client, headers, fid, ("april.pdf", bill_pdf()))[0]["bill_id"]
    bill = client.get(f"/api/bills/{bill_id}", headers=headers).json()["bill"]
    assert bill["status"] == "failed"
    assert bill["failure_reason"] == "Could not reach the extraction model."


def test_unexpected_error_is_contained(api, fake_llm):
    client, headers, fid = api
    fake_llm.responses = [RuntimeError("boom: internal detail")]
    bill_id = upload(client, headers, fid, ("april.pdf", bill_pdf()))[0]["bill_id"]
    bill = client.get(f"/api/bills/{bill_id}", headers=headers).json()["bill"]
    assert bill["status"] == "failed"
    assert "Unexpected error" in bill["failure_reason"] and "boom" not in bill["failure_reason"]


def test_reprocess_keeps_old_extraction(api, engine, fake_llm):
    client, headers, fid = api
    bill_id = upload(client, headers, fid, ("april.pdf", bill_pdf()))[0]["bill_id"]
    map_account(engine, fid)
    r = client.post(f"/api/bills/{bill_id}/reprocess", headers=headers)
    assert r.status_code == 200
    assert client.get(f"/api/bills/{bill_id}", headers=headers).json()["bill"]["status"] == "approved"

    Session = sessionmaker(bind=engine)
    with Session() as db:
        rows = db.scalars(select(Extraction).where(Extraction.bill_id == uuid.UUID(bill_id))).all()
        assert sorted(e.is_current for e in rows) == [False, True]

    # Approved bills can't be reprocessed (that would bypass review history).
    assert client.post(f"/api/bills/{bill_id}/reprocess", headers=headers).status_code == 409


def test_overlapping_period_flagged_as_possible_duplicate(api, engine):
    client, headers, fid = api
    map_account(engine, fid)
    first = upload(client, headers, fid, ("april.pdf", bill_pdf(tag="original")))[0]["bill_id"]
    second = upload(client, headers, fid, ("april-rescan.pdf", bill_pdf(tag="rescanned")))[0]["bill_id"]
    assert client.get(f"/api/bills/{first}", headers=headers).json()["bill"]["status"] == "approved"
    detail = client.get(f"/api/bills/{second}", headers=headers).json()
    assert detail["bill"]["status"] == "needs_review"
    assert "overlapping_period" in [i["code"] for i in detail["extraction"]["validation_issues_json"]]


def test_process_bill_ignores_bills_not_waiting(db, seeded_db, storage):
    # e.g. a duplicate enqueue after the bill was already approved
    called = []
    process_bill(uuid.uuid4(), session_factory=lambda: db, extractor=FakeExtractor(lambda t: called.append(t)),
                 storage=storage)
    assert called == []


# ---------------------------------------------------------------- read endpoints

def test_list_detail_file_and_org_scoping(api):
    client, headers, fid = api
    pdf = bill_pdf()
    bill_id = upload(client, headers, fid, ("april.pdf", pdf))[0]["bill_id"]

    items = client.get("/api/bills", headers=headers).json()
    assert len(items) == 1
    assert items[0]["facility_name"] == "Pune Plant"
    assert items[0]["billing_period_end"] == "2024-04-30" and items[0]["issue_count"] == 1
    assert client.get("/api/bills", headers=headers, params={"status": "approved"}).json() == []

    f = client.get(f"/api/bills/{bill_id}/file", headers=headers)
    assert f.status_code == 200 and f.content == pdf
    assert f.headers["content-type"] == "application/pdf"

    other = register(client, email="x@globex.example.com", org="Globex")
    assert client.get(f"/api/bills/{bill_id}", headers=other).status_code == 404
    assert client.get(f"/api/bills/{bill_id}/file", headers=other).status_code == 404
    assert client.get("/api/bills/status", headers=other, params={"ids": bill_id}).json() == []
    assert client.post(f"/api/bills/{bill_id}/reprocess", headers=other).status_code == 404
