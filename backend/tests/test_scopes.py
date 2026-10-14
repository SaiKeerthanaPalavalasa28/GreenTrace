"""Scope tabs: roles, org sign-up emails, PDF analysis + flags, zones, report."""

import pytest

from app import mailer
from app.api import auth as auth_api
from app.storage import LocalStorage, get_storage
from app.main import app
from tests.conftest import register
from tests.helpers import make_text_pdf


@pytest.fixture(autouse=True)
def local_storage(tmp_path):
    app.dependency_overrides[get_storage] = lambda: LocalStorage(tmp_path / "files")
    yield
    app.dependency_overrides.pop(get_storage, None)


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "mail_configured", lambda: True)
    monkeypatch.setattr(auth_api, "mail_configured", lambda: True)
    monkeypatch.setattr(auth_api, "send_mail", lambda to, subject, text, html=None: sent.append((to, subject, text)))
    return sent


ORG = {"org_name": "Green Co", "admin_email": "admin@green.example.com", "manager_email": "mgr@green.example.com",
       "auditor_email": "aud@green.example.com"}


def signup_and_login(client, outbox):
    r = client.post("/api/auth/register-org", json=ORG)
    assert r.status_code == 201, r.text
    creds = {}
    for to, _, text in outbox:
        pw = next(l.split("Password:")[1].strip() for l in text.splitlines() if l.startswith("Password:"))
        tok = client.post("/api/auth/login", json={"email": to, "password": pw})
        assert tok.status_code == 200, (to, tok.text)
        creds[to.split("@")[0]] = {"Authorization": f"Bearer {tok.json()['access_token']}"}
    return creds


def upload(client, headers, scope, lines, name="doc.pdf"):
    pdf = make_text_pdf([lines])
    return client.post(f"/api/scopes/{scope}/documents", headers=headers, files=[("files", (name, pdf, "application/pdf"))])


def test_org_signup_emails_each_role_its_own_password(client, outbox):
    creds = signup_and_login(client, outbox)
    assert [to for to, _, _ in outbox] == [ORG["admin_email"], ORG["manager_email"], ORG["auditor_email"]]
    pws = [next(l for l in t.splitlines() if l.startswith("Password:")) for _, _, t in outbox]
    assert len(set(pws)) == 3
    roles = {k: client.get("/api/auth/me", headers=h).json()["user"]["role"] for k, h in creds.items()}
    assert roles == {"admin": "admin", "mgr": "manager", "aud": "auditor"}
    # each email names only its own login
    assert ORG["manager_email"] not in outbox[0][2]


def test_signup_fails_without_mail_and_creates_nothing(client, monkeypatch):
    monkeypatch.setattr(auth_api, "mail_configured", lambda: False)
    assert client.post("/api/auth/register-org", json=ORG).status_code == 503


def test_admin_mail_failure_rolls_back(client, monkeypatch):
    monkeypatch.setattr(auth_api, "mail_configured", lambda: True)

    def boom(*a, **k):
        raise mailer.MailError("smtp down")

    monkeypatch.setattr(auth_api, "send_mail", boom)
    assert client.post("/api/auth/register-org", json=ORG).status_code == 502
    monkeypatch.setattr(auth_api, "send_mail", lambda *a, **k: None)
    assert client.post("/api/auth/register-org", json=ORG).status_code == 201  # not blocked by a half-created org


def test_direct_signup_can_be_disabled(client, monkeypatch):
    monkeypatch.setattr(auth_api.get_settings(), "allow_direct_signup", False)
    r = client.post("/api/auth/register", json={"org_name": "X", "email": "x@x.example.com", "password": "long-enough-pw"})
    assert r.status_code == 404


def test_only_admin_can_edit(client, outbox):
    c = signup_and_login(client, outbox)
    lines = ["Electricity bill 01/03/2025", "Units consumed: 5,000 kWh"]
    for who in ("mgr", "aud"):
        assert upload(client, c[who], 2, lines).status_code == 403
        assert client.put("/api/scopes/budgets", headers=c[who], json={"scope2_budget_t": 5}).status_code == 403
        assert client.post("/api/facilities", headers=c[who], json={"name": "F", "region": "IN"}).status_code == 403
        assert client.get("/api/scopes/summary", headers=c[who]).status_code == 200
    assert upload(client, c["admin"], 2, lines).status_code == 201


def test_scope2_extraction_and_total(client, outbox):
    h = signup_and_login(client, outbox)["admin"]
    r = upload(client, h, 2, ["Electricity bill 01/03/2025", "Units consumed: 5,000 kWh", "Common area 1,200.5 kWh"])
    doc = r.json()["results"][0]["document"]
    assert [round(i["native_qty"], 1) for i in doc["items"]] == [5000, 1200.5]
    assert doc["total_kg_co2e"] == pytest.approx(6200.5 * 0.71)  # default region IN grid factor
    assert doc["risk"] == "clear"


def test_scope1_and_scope3_categories(client, outbox):
    h = signup_and_login(client, outbox)["admin"]
    d1 = upload(client, h, 1, ["Fuel log 2025", "Diesel for generator: 1,000 litres", "Natural gas 2,000 m3"], "s1.pdf").json()["results"][0]["document"]
    assert d1["total_kg_co2e"] == pytest.approx(1000 * 2.68 + 2000 * 2.04)
    d3 = upload(client, h, 3, ["Travel 2025", "Flight Delhi-Mumbai 1,150 km", "Hotel stay 3 nights", "Waste to landfill 2 tonnes"], "s3.pdf").json()["results"][0]["document"]
    assert d3["total_kg_co2e"] == pytest.approx(1150 * 0.15 + 3 * 15 + 2000 * 0.45)


def test_suspicious_documents_are_flagged(client, outbox):
    h = signup_and_login(client, outbox)["admin"]
    codes = lambda d: {f["code"] for f in d["flags"]}  # noqa: E731
    wrong = upload(client, h, 1, ["Bill 2025", "Electricity 4,000 kWh"], "w.pdf").json()["results"][0]["document"]
    assert "wrong_scope" in codes(wrong) and wrong["risk"] == "high"
    neg = upload(client, h, 2, ["Bill 2025", "Units consumed -500 kWh", "Units consumed 100 kWh"], "n.pdf").json()["results"][0]["document"]
    assert "negative_value" in codes(neg) and neg["risk"] == "high"
    big = upload(client, h, 2, ["Bill 2025", "Units consumed 900,000,000 kWh"], "b.pdf").json()["results"][0]["document"]
    assert "implausible_size" in codes(big)
    mism = upload(client, h, 2, ["Bill 2025", "Units consumed 100 kWh", "Units consumed 200 kWh", "Total consumption 500 kWh"], "m.pdf").json()["results"][0]["document"]
    assert "total_mismatch" in codes(mism)
    ok_total = upload(client, h, 2, ["Bill 2025", "Units consumed 100 kWh", "Units consumed 200 kWh", "Total consumption 300 kWh"], "t.pdf").json()["results"][0]["document"]
    assert "total_mismatch" not in codes(ok_total) and ok_total["total_kg_co2e"] == pytest.approx(300 * 0.71)
    dup = upload(client, h, 2, ["Bill 2025", "Units consumed 100 kWh", "Units consumed 100 kWh"], "d.pdf").json()["results"][0]["document"]
    assert "duplicate_line" in codes(dup)
    empty = upload(client, h, 2, ["hello world nothing to see here at all, truly nothing here"], "e.pdf").json()["results"][0]["document"]
    assert "no_activity_data" in codes(empty)


def test_duplicate_file_and_non_pdf_rejected(client, outbox):
    h = signup_and_login(client, outbox)["admin"]
    pdf = make_text_pdf([["Bill 2025", "Units consumed 100 kWh"]])  # same bytes twice (builds embed a timestamp)
    send = lambda: client.post("/api/scopes/2/documents", headers=h, files=[("files", ("a.pdf", pdf, "application/pdf"))])  # noqa: E731
    assert send().json()["results"][0]["outcome"] == "ok"
    assert send().json()["results"][0]["outcome"] == "rejected"
    r = client.post("/api/scopes/2/documents", headers=h, files=[("files", ("a.pdf", b"not a pdf", "application/pdf"))])
    assert r.json()["results"][0]["outcome"] == "rejected"
    assert client.post("/api/scopes/4/documents", headers=h, files=[]).status_code == 422


def test_history_spike_flag(client, outbox):
    h = signup_and_login(client, outbox)["admin"]
    for n in range(3):
        upload(client, h, 2, ["Bill 2025", f"Units consumed {1000 + n} kWh"], f"h{n}.pdf")
    spike = upload(client, h, 2, ["Bill 2025", "Units consumed 50,000 kWh"], "spike.pdf").json()["results"][0]["document"]
    assert {"spike_vs_history", "outlier_line"} <= {f["code"] for f in spike["flags"]}


def test_zones_summary_report_and_edit(client, outbox):
    h = signup_and_login(client, outbox)["admin"]
    doc = upload(client, h, 2, ["Bill 2025", "Units consumed 10,000 kWh"]).json()["results"][0]["document"]  # 7.1 t
    s = client.get("/api/scopes/summary", headers=h).json()
    assert s["total"]["zone"] == "unset"

    def zone_with_budget(t):
        return client.put("/api/scopes/budgets", headers=h, json={"scope2_budget_t": t}).json()["scopes"][1]

    assert zone_with_budget(100)["zone"] == "green"
    assert zone_with_budget(9)["zone"] == "moderate"   # 7.1/9 = 79%
    sc = zone_with_budget(7.5)                           # 94.7%
    assert sc["zone"] == "danger" and sc["remaining_t"] == pytest.approx(0.4, abs=0.01)
    assert zone_with_budget(5)["remaining_t"] < 0         # exceeded stays danger
    total = client.get("/api/scopes/summary", headers=h).json()["total"]
    assert total["zone"] == "danger" and total["used_t"] == pytest.approx(7.1)

    r = client.patch(f"/api/scopes/documents/{doc['id']}/items/0", headers=h, json={"quantity": 1000})
    assert r.json()["total_kg_co2e"] == pytest.approx(710) and "manually_edited" in {f["code"] for f in r.json()["flags"]}
    assert client.get(f"/api/scopes/documents/{doc['id']}/file", headers=h).content.startswith(b"%PDF")

    rep = client.get("/api/scopes/report", headers=h).json()
    assert rep["headline"] and rep["suggestions"]
    assert any("Scope 1" in x["title"] for x in rep["suggestions"])  # scope 1 has no evidence
    pdf = client.get("/api/scopes/report.pdf", headers=h)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    assert client.delete(f"/api/scopes/documents/{doc['id']}", headers=h).status_code == 204
    assert client.get("/api/scopes/2/documents", headers=h).json() == []


def test_org_isolation(client, outbox):
    a = signup_and_login(client, outbox)["admin"]
    doc = upload(client, a, 2, ["Bill 2025", "Units consumed 100 kWh"]).json()["results"][0]["document"]
    b = register(client, email="other@other.example.com", org="Other")
    assert client.get(f"/api/scopes/documents/{doc['id']}/file", headers=b).status_code == 404
    assert client.delete(f"/api/scopes/documents/{doc['id']}", headers=b).status_code == 404
    assert client.get("/api/scopes/2/documents", headers=b).json() == []


SAMPLES = {  # file -> (scope it belongs to, expected native quantity in the bill's own unit)
    "in-pune-electricity-2024-01.pdf": (2, 14250), "in-pune-electricity-2024-03-cross-fy.pdf": (2, 12400),
    "in-chennai-electricity-2024-02-meter-readings.pdf": (2, 19200),  # (183410-182450) x MF 20
    "in-chennai-gas-2024-02-mmbtu.pdf": (1, 650), "in-chennai-electricity-2023-12-two-pages.pdf": (2, 15800),
    "uk-london-electricity-2025-12-cross-year.pdf": (2, 3100), "uk-london-gas-2025-03.pdf": (1, 18500),
    "us-sf-electricity-2024-06.pdf": (2, 42000), "us-sf-gas-2024-11-therms.pdf": (1, 1200),
}


@pytest.mark.parametrize("name", SAMPLES)
def test_real_bill_formats_land_in_the_right_scope(name):
    from pathlib import Path
    from app import scope_analysis as sa
    data = (Path(__file__).resolve().parents[2] / "samples" / "bills" / name).read_bytes()
    scope, qty = SAMPLES[name]
    ok = sa.analyse(data, scope, "IN", [], None)
    assert [i["quantity"] for i in ok["items"]] == [qty] and ok["total_kg_co2e"] > 0
    assert not {f["code"] for f in ok["flags"]} & {"wrong_scope", "no_activity_data", "reading_mismatch"}
    for other in {1, 2, 3} - {scope}:
        res = sa.analyse(data, other, "IN", [], None)
        assert res["items"] == []
        wrong = next(f for f in res["flags"] if f["code"] == "wrong_scope")
        assert f"Scope {scope}" in wrong["message"]
