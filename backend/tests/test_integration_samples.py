"""End to end over the sample bills in samples/ (see samples/manifest.json):
upload a batch per organization -> extraction -> validation -> review/approve -> calculation
-> dashboard -> report + verify.

The LLM is replaced by a "perfect reader" that returns the values printed on each bill (the
manifest's expected_extraction), matched by the account number found in the PDF's text. Every
other step is real: PDF text extraction, the snippet-on-page check, validation rules, the
calculation against seeded factors, aggregation and the PDF report. Expected emissions are
hand-worked in the manifest, independently of the engine.
"""

import io
import json
import uuid
import shutil
from decimal import Decimal
from pathlib import Path

import pdfplumber
import pytest

from app.config import get_settings
from tests.conftest import register, upload
from tests.helpers import FakeExtractor

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
MANIFEST = json.loads((SAMPLES / "manifest.json").read_text(encoding="utf-8"))
HAS_TESSERACT = bool(shutil.which("tesseract") or get_settings().tesseract_cmd)


def perfect_reader():
    """Several bills share an account (one per month), so identify the bill by its account
    number AND its consumption text both being in the document."""
    from app.pipeline.validate import _normalize

    def read(document_text: str):
        text = _normalize(document_text)
        matches = [b for b in MANIFEST["bills"]
                   if b["expected_extraction"]["account_number"].lower() in text
                   and _normalize(b["expected_extraction"]["source_snippet"]) in text]
        assert len(matches) == 1, f"perfect reader: {len(matches)} sample bills match this document"
        return matches[0]["expected_extraction"]

    return read


@pytest.fixture
def reader(fake_llm):
    fake_llm.responses = [perfect_reader()]
    return fake_llm


def run_org(api, engine, code: str):
    client, _, _ = api
    org = MANIFEST["organizations"][code]
    headers = register(client, email=f"admin@{code.lower()}.example.com", org=f"Sample {code}",
                       region=next(iter(org["region_by_facility"].values())).split("-")[0])
    # Fiscal year: India April-March, others calendar year.
    me = client.get("/api/auth/me", headers=headers).json()
    if org["fiscal_year_start_month"] != me["organization"]["fiscal_year_start_month"]:
        _set_fiscal_year(engine, me["organization"]["id"], org["fiscal_year_start_month"])
    facilities = {}
    for name, region in org["region_by_facility"].items():
        r = client.post("/api/facilities", headers=headers, json={"name": name, "region": region})
        assert r.status_code == 201, r.text
        facilities[name] = r.json()["id"]

    bills = [b for b in MANIFEST["bills"] if b["org"] == code]
    ids = {}
    for facility, fid in facilities.items():
        batch = [b for b in bills if b["facility"] == facility]
        results = upload(client, headers, fid, *[(Path(b["file"]).name, (SAMPLES / b["file"]).read_bytes()) for b in batch])
        for b, res in zip(batch, results):
            assert res["outcome"] == "queued", res
            ids[b["file"]] = res["bill_id"]
    return client, headers, bills, ids


def _set_fiscal_year(engine, org_id, month):
    from sqlalchemy.orm import sessionmaker

    from app.models import Organization

    with sessionmaker(bind=engine)() as db:
        db.get(Organization, uuid.UUID(org_id)).fiscal_year_start_month = month
        db.commit()


def approve_all(client, headers, bills, ids):
    for b in bills:
        d = client.get(f"/api/bills/{ids[b['file']]}", headers=headers).json()
        if d["bill"]["status"] != "needs_review":
            continue
        r = client.post(f"/api/extractions/{d['extraction']['id']}/approve", headers=headers,
                        json={"note": "Checked against the sample bill"})
        assert r.status_code == 200, (b["file"], r.text)


@pytest.mark.parametrize("code", ["IN", "UK", "US"])
def test_samples_end_to_end(api, engine, reader, code):
    client, headers, bills, ids = run_org(api, engine, code)

    # --- extraction + validation
    for b in bills:
        d = client.get(f"/api/bills/{ids[b['file']]}", headers=headers).json()
        if b["requires_ocr"] and not HAS_TESSERACT:
            assert d["bill"]["status"] == "failed" and "Tesseract" in d["bill"]["failure_reason"], b["file"]
            continue
        codes = {i["code"] for i in d["extraction"]["validation_issues_json"]}
        # A perfect reading of a clean bill raises nothing but "new account" (first time an account is seen);
        # the snippet check passes because the quoted text really is on the cited page.
        allowed = {"account_unmapped"} | ({"snippet_not_found", "quantity_not_in_snippet"} if b["requires_ocr"] else set())
        assert codes <= allowed, (b["file"], codes)
        assert d["bill"]["status"] == "needs_review"
        assert d["extraction"]["page_number"] == b["expected_extraction"]["page_number"]

    approve_all(client, headers, bills, ids)

    # --- per-bill emissions match the hand-worked manifest exactly
    expected_total = Decimal(0)
    for b in bills:
        if b["requires_ocr"] and not HAS_TESSERACT:
            continue
        trace = client.get(f"/api/bills/{ids[b['file']]}/trace", headers=headers).json()
        assert trace["bill"]["status"] == "approved" and trace["bill"]["calculation_error"] is None, b["file"]
        assert Decimal(trace["total_kgco2e"]) == Decimal(b["expected_kgco2e"]), (b["file"], b["expected_working"])
        expected_total += Decimal(b["expected_kgco2e"])

    # --- dashboard over a window covering every sample period
    dash = client.get("/api/dashboard", headers=headers,
                      params={"period_start": "2023-01-01", "period_end": "2026-12-31"}).json()
    assert Decimal(dash["totals"]["kgco2e"]) == expected_total
    assert dash["completeness"]["is_partial"] is (code == "IN" and not HAS_TESSERACT)

    # --- report: every included sample is listed, and it verifies
    rep = client.post("/api/reports", headers=headers, json={"period_start": "2023-01-01", "period_end": "2026-12-31"}).json()
    assert Decimal(rep["summary"]["total_kg"]) == expected_total
    pdf = client.get(f"/api/reports/{rep['id']}/download", headers=headers).content
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        text = "\n".join(p.extract_text() or "" for p in doc.pages)
    flat = text.replace("\n", "")  # long file names may wrap inside a table cell
    for b in bills:
        assert Path(b["file"]).name in flat, b["file"]
    v = client.post(f"/api/reports/{rep['id']}/verify", headers=headers).json()
    assert v["pdf_matches_recorded_hash"] and v["snapshot_matches_recorded_hash"] and v["rerender_matches"]


def test_cross_year_samples_split_by_reporting_year(api, engine, reader):
    """The India cross-FY bill lands in two financial years; the UK one in two calendar years."""
    client, headers, bills, ids = run_org(api, engine, "IN")
    approve_all(client, headers, bills, ids)
    fy24 = client.get("/api/dashboard", headers=headers, params={"period_start": "2024-04-01", "period_end": "2025-03-31"}).json()
    assert fy24["totals"]["kgco2e"] == "4260.000000"  # April part of the cross-FY bill only

    client, headers, bills, ids = run_org(api, engine, "UK")
    approve_all(client, headers, bills, ids)
    y2026 = client.get("/api/dashboard", headers=headers, params={"period_start": "2026-01-01", "period_end": "2026-12-31"}).json()
    assert y2026["totals"]["kgco2e"] == "183.344000"  # January 2026 part at the 2026 DESNZ factor


def test_reuploading_samples_is_detected_as_duplicate(api, engine, reader):
    client, headers, bills, ids = run_org(api, engine, "US")
    fid = client.get("/api/facilities", headers=headers).json()[0]["id"]
    again = upload(client, headers, fid, *[(Path(b["file"]).name, (SAMPLES / b["file"]).read_bytes()) for b in bills])
    assert {r["outcome"] for r in again} == {"duplicate"}


def test_manifest_snippets_are_on_the_cited_pages():
    """Guards the samples themselves: each ground-truth snippet is real text from its page."""
    from app.pipeline.text import extract_text

    for b in MANIFEST["bills"]:
        if b["requires_ocr"]:
            continue
        pages = extract_text((SAMPLES / b["file"]).read_bytes()).pages
        e = b["expected_extraction"]
        assert e["source_snippet"] in pages[e["page_number"] - 1], b["file"]
