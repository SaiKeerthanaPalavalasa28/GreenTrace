"""Review queue: corrections, approval (with account mapping and calculation), rejection,
reopening, concurrency guard, page images."""

import pytest

from tests.conftest import bill_pdf, map_account, register, upload
from tests.helpers import llm_json


@pytest.fixture
def pending(api):
    """One bill in review (new account -> account_unmapped)."""
    client, headers, fid = api
    bill_id = upload(client, headers, fid, ("april.pdf", bill_pdf()))[0]["bill_id"]
    detail = client.get(f"/api/bills/{bill_id}", headers=headers).json()
    assert detail["bill"]["status"] == "needs_review"
    return client, headers, fid, detail


def post(client, headers, path, **body):
    return client.post(f"/api/{path}", headers=headers, json=body)


def codes(detail):
    return [i["code"] for i in detail["extraction"]["validation_issues_json"]]


# ---------------------------------------------------------------- queue

def test_queue_and_counts(pending):
    client, headers, _, detail = pending
    (item,) = client.get("/api/review", headers=headers).json()
    assert item["bill_id"] == detail["bill"]["id"]
    assert item["issue_codes"] == ["account_unmapped"] and item["blocking_codes"] == []
    assert client.get("/api/review/counts", headers=headers).json() == {
        "needs_review": 1, "failed": 0, "calculation_errors": 0}


# ---------------------------------------------------------------- approve

def test_approve_learns_account_and_calculates(pending, engine):
    client, headers, fid, detail = pending
    e = detail["extraction"]
    r = post(client, headers, f"extractions/{e['id']}/approve", note="Checked against the PDF",
             expected_updated_at=detail["bill"]["updated_at"])
    assert r.status_code == 200, r.text
    assert r.json()["bill"]["status"] == "approved"
    assert r.json()["extraction"]["reviewed_by"] is not None

    trace = client.get(f"/api/bills/{detail['bill']['id']}/trace", headers=headers).json()
    assert trace["total_kgco2e"] == "8875.000000"
    assert trace["records"][0]["calculation_trace_json"]["extraction"]["approval"] == "human"

    # The account is now mapped: the next bill from it is auto-approved.
    nxt = upload(client, headers, fid, ("may.pdf", bill_pdf(tag="may")))[0]["bill_id"]
    # (same period as April in this fixture -> overlap flagged, which is correct)
    assert "account_unmapped" not in codes(client.get(f"/api/bills/{nxt}", headers=headers).json())

    audit = client.get("/api/audit", headers=headers, params={"entity_id": detail["bill"]["id"]}).json()
    approval = next(a for a in audit if a["action"] == "approve")
    assert approval["after_json"]["acknowledged_issues"] == ["account_unmapped"]
    assert approval["after_json"]["account_mapping"]["action"] == "created"
    assert approval["after_json"]["note"] == "Checked against the PDF"


def test_correct_then_approve_keeps_original_values_and_audits(pending):
    client, headers, _, detail = pending
    e = detail["extraction"]
    r = post(client, headers, f"extractions/{e['id']}/correct", reason="Misread digit",
             changes={"quantity": "12600", "billing_period_end": "2024-04-29"})
    assert r.status_code == 200, r.text
    corrected = r.json()["extraction"]
    assert corrected["quantity"] == "12600.000000" and corrected["billing_period_end"] == "2024-04-29"
    assert corrected["corrections_json"] == {
        "quantity": {"before": "12500.000000", "after": "12600.000000"},
        "billing_period_end": {"before": "2024-04-30", "after": "2024-04-29"},
    }
    # Correct again: "before" still holds what the model read.
    r = post(client, headers, f"extractions/{e['id']}/correct", changes={"quantity": "12650"})
    assert r.json()["extraction"]["corrections_json"]["quantity"] == {"before": "12500.000000", "after": "12650.000000"}
    # Model-level history is kept; the field rules were re-run.
    assert "account_unmapped" in codes(r.json())

    r = post(client, headers, f"extractions/{e['id']}/approve")
    assert r.status_code == 200
    trace = client.get(f"/api/bills/{detail['bill']['id']}/trace", headers=headers).json()
    t = trace["records"][0]["calculation_trace_json"]
    assert t["quantity"]["value"] == "12650"
    assert t["extraction"]["corrections"]["quantity"]["before"] == "12500.000000"
    assert trace["total_kgco2e"] == "8981.500000"  # 12.65 MWh x 710

    audit = client.get("/api/audit", headers=headers, params={"entity_id": e["id"]}).json()
    first = audit[-1]
    assert first["action"] == "correct"
    assert first["before_json"] == {"quantity": "12500.000000", "billing_period_end": "2024-04-30"}
    assert first["after_json"]["reason"] == "Misread digit"


def test_correcting_back_to_original_clears_correction(pending):
    client, headers, _, detail = pending
    eid = detail["extraction"]["id"]
    post(client, headers, f"extractions/{eid}/correct", changes={"quantity": "1"})
    r = post(client, headers, f"extractions/{eid}/correct", changes={"quantity": "12500"})
    assert r.json()["extraction"]["corrections_json"] is None


def test_blocking_issues_prevent_approval(pending):
    client, headers, _, detail = pending
    eid = detail["extraction"]["id"]
    r = post(client, headers, f"extractions/{eid}/approve", changes={"unit": "litres"})
    assert r.status_code == 422
    assert r.json()["detail"]["issues"][0]["code"] == "unit_not_allowed"
    # Atomic: the failed approval did not save the bad correction either.
    d = client.get(f"/api/bills/{detail['bill']['id']}", headers=headers).json()
    assert d["extraction"]["unit"] == "kWh" and d["bill"]["status"] == "needs_review"
    r = post(client, headers, f"extractions/{eid}/correct", changes={"unit": "litres"})
    assert r.json()["extraction"]["blocking_codes"] == ["unit_not_allowed"]


def test_meter_reading_bill_can_be_fixed_and_approved(api, fake_llm):
    client, headers, fid = api
    fake_llm.responses = [llm_json(quantity=None, meter_readings={"previous": "45210", "current": "57710", "multiplier": None},
                                   source_snippet="Previous Reading: 45210   Current Reading: 57710   MF: 1")]
    bill_id = upload(client, headers, fid, ("april.pdf", bill_pdf()))[0]["bill_id"]
    d = client.get(f"/api/bills/{bill_id}", headers=headers).json()
    assert "multiplier_not_printed" in codes(d)
    r = post(client, headers, f"extractions/{d['extraction']['id']}/approve", changes={"meter_multiplier": "1"})
    assert r.status_code == 200, r.text
    assert client.get(f"/api/bills/{bill_id}/trace", headers=headers).json()["total_kgco2e"] == "8875.000000"


def test_unknown_utility_must_be_set_before_approval(api, fake_llm):
    client, headers, fid = api
    fake_llm.responses = [llm_json(utility_type="unknown")]
    bill_id = upload(client, headers, fid, ("april.pdf", bill_pdf()))[0]["bill_id"]
    eid = client.get(f"/api/bills/{bill_id}", headers=headers).json()["extraction"]["id"]
    assert post(client, headers, f"extractions/{eid}/approve").status_code == 422
    r = post(client, headers, f"extractions/{eid}/approve", changes={"utility_type": "electricity"})
    assert r.status_code == 200, r.text
    assert r.json()["bill"]["utility_type"] == "electricity"


def test_approval_without_factor_records_calculation_error(pending):
    client, headers, _, detail = pending
    eid = detail["extraction"]["id"]
    r = post(client, headers, f"extractions/{eid}/approve",
             changes={"billing_period_start": "2025-06-01", "billing_period_end": "2025-06-30"})
    assert r.status_code == 200
    assert r.json()["bill"]["status"] == "approved"
    assert "covers 2025-06-01" in r.json()["bill"]["calculation_error"]
    assert client.get("/api/review/counts", headers=headers).json()["calculation_errors"] == 1


# ---------------------------------------------------------------- account mapping conflicts

def test_account_belonging_to_other_facility(api, engine):
    client, headers, fid = api
    other_fid = client.post("/api/facilities", headers=headers, json={"name": "Chennai Plant", "region": "IN"}).json()["id"]
    map_account(engine, other_fid)
    bill_id = upload(client, headers, fid, ("april.pdf", bill_pdf()))[0]["bill_id"]
    d = client.get(f"/api/bills/{bill_id}", headers=headers).json()
    assert "account_other_facility" in codes(d)
    eid = d["extraction"]["id"]

    r = post(client, headers, f"extractions/{eid}/approve")
    assert r.status_code == 409
    assert r.json()["detail"]["issues"][0]["facility_name"] == "Chennai Plant"

    # Option A: the bill really is Chennai's -> move it; the issue disappears.
    r = post(client, headers, f"extractions/{eid}/correct", changes={"facility_id": other_fid})
    assert "account_other_facility" not in codes(r.json())
    assert r.json()["facility_name"] == "Chennai Plant"
    assert post(client, headers, f"extractions/{eid}/approve").status_code == 200


def test_remap_account_explicitly(api, engine):
    client, headers, fid = api
    other_fid = client.post("/api/facilities", headers=headers, json={"name": "Chennai Plant", "region": "IN"}).json()["id"]
    map_account(engine, other_fid)
    bill_id = upload(client, headers, fid, ("april.pdf", bill_pdf()))[0]["bill_id"]
    eid = client.get(f"/api/bills/{bill_id}", headers=headers).json()["extraction"]["id"]
    r = post(client, headers, f"extractions/{eid}/approve", remap_account=True)
    assert r.status_code == 200
    audit = client.get("/api/audit", headers=headers, params={"entity_id": bill_id}).json()
    mapping = next(a for a in audit if a["action"] == "approve")["after_json"]["account_mapping"]
    assert mapping["action"] == "remapped" and mapping["to_facility_id"] == fid


# ---------------------------------------------------------------- reject / reopen

def test_reject_requires_reason_and_excludes_bill(pending):
    client, headers, _, detail = pending
    eid = detail["extraction"]["id"]
    assert post(client, headers, f"extractions/{eid}/reject", reason="").status_code == 422
    r = post(client, headers, f"extractions/{eid}/reject", reason="Duplicate of the March bill")
    assert r.status_code == 200 and r.json()["bill"]["status"] == "rejected"
    assert client.get("/api/review", headers=headers).json() == []
    assert post(client, headers, f"extractions/{eid}/approve").status_code == 409


def test_reopen_removes_emissions_until_reapproved(pending):
    client, headers, _, detail = pending
    bill_id, eid = detail["bill"]["id"], detail["extraction"]["id"]
    post(client, headers, f"extractions/{eid}/approve")
    assert client.get(f"/api/bills/{bill_id}/trace", headers=headers).json()["total_kgco2e"] == "8875.000000"

    r = post(client, headers, f"bills/{bill_id}/reopen", reason="Supplier issued a revised bill")
    assert r.status_code == 200 and r.json()["bill"]["status"] == "needs_review"
    trace = client.get(f"/api/bills/{bill_id}/trace", headers=headers).json()
    assert trace["records"] == [] and len(trace["superseded_records"]) == 1
    assert r.json()["extraction"]["reviewed_by"] is None

    r = post(client, headers, f"extractions/{eid}/approve", changes={"quantity": "13000"})
    assert r.status_code == 200
    assert client.get(f"/api/bills/{bill_id}/trace", headers=headers).json()["total_kgco2e"] == "9230.000000"


def test_reopen_is_admin_only(pending):
    client, headers, _, detail = pending
    post(client, headers, f"extractions/{detail['extraction']['id']}/approve")
    client.post("/api/users", headers=headers, json={"email": "m@acme.example.com", "password": "member-password-1"})
    token = client.post("/api/auth/login", json={"email": "m@acme.example.com", "password": "member-password-1"}).json()
    member = {"Authorization": f"Bearer {token['access_token']}"}
    assert post(client, member, f"bills/{detail['bill']['id']}/reopen", reason="no").status_code == 403


def test_approved_bill_cannot_be_corrected_directly(pending):
    client, headers, _, detail = pending
    eid = detail["extraction"]["id"]
    post(client, headers, f"extractions/{eid}/approve")
    r = post(client, headers, f"extractions/{eid}/correct", changes={"quantity": "1"})
    assert r.status_code == 409 and "Reopen it first" in r.json()["detail"]


# ---------------------------------------------------------------- guards

def test_stale_edit_is_refused(pending):
    client, headers, _, detail = pending
    eid, seen = detail["extraction"]["id"], detail["bill"]["updated_at"]
    assert post(client, headers, f"extractions/{eid}/correct", changes={"quantity": "12600"},
                expected_updated_at=seen).status_code == 200
    r = post(client, headers, f"extractions/{eid}/approve", expected_updated_at=seen)  # based on the old view
    assert r.status_code == 409 and "Someone else changed" in r.json()["detail"]


def test_replaced_extraction_is_refused(pending):
    client, headers, _, detail = pending
    client.post(f"/api/bills/{detail['bill']['id']}/reprocess", headers=headers)
    r = post(client, headers, f"extractions/{detail['extraction']['id']}/approve")
    assert r.status_code == 409 and "replaced by a newer one" in r.json()["detail"]


@pytest.mark.parametrize(("changes", "message"), [
    ({"quantity": "twelve"}, "quantity"),
    ({"quantity": "1.0000001"}, "quantity"),
    ({"billing_period_start": "31/04/2024"}, "billing_period_start"),
    ({"read_type": "guessed"}, "read_type"),
    ({"total_co2": "5"}, "can't be corrected"),
    ({"utility_type": "water"}, "utility_type"),
    ({"facility_id": "not-a-uuid"}, "facility_id"),
])
def test_invalid_corrections(pending, changes, message):
    client, headers, _, detail = pending
    r = post(client, headers, f"extractions/{detail['extraction']['id']}/correct", changes=changes)
    assert r.status_code in (404, 422) and message in r.text


def test_numbers_must_be_strings(pending):
    client, headers, _, detail = pending
    r = post(client, headers, f"extractions/{detail['extraction']['id']}/correct", changes={"quantity": 12600.5})
    assert r.status_code == 422


def test_cross_org_review_is_404(pending):
    client, headers, fid, detail = pending
    other = register(client, email="x@globex.example.com", org="Globex")
    eid = detail["extraction"]["id"]
    assert post(client, other, f"extractions/{eid}/approve").status_code == 404
    assert post(client, other, f"extractions/{eid}/reject", reason="nope").status_code == 404
    assert client.get("/api/review", headers=other).json() == []
    other_fac = client.post("/api/facilities", headers=other, json={"name": "G", "region": "UK"}).json()["id"]
    r = post(client, headers, f"extractions/{eid}/correct", changes={"facility_id": other_fac})
    assert r.status_code == 404


# ---------------------------------------------------------------- page image

def test_page_image_with_highlight(pending):
    client, headers, _, detail = pending
    r = client.get(f"/api/bills/{detail['bill']['id']}/pages/1", headers=headers)
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.content.startswith(b"\x89PNG")
    assert r.headers["x-highlight"] == "found" and r.headers["x-page-count"] == "1"
    r = client.get(f"/api/bills/{detail['bill']['id']}/pages/1", headers=headers, params={"highlight": False})
    assert r.headers["x-highlight"] == "none"
    assert client.get(f"/api/bills/{detail['bill']['id']}/pages/2", headers=headers).status_code == 404
