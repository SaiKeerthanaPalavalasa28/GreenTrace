from tests.conftest import register

NEW_FACTOR = {
    "factor_key": "ACME-PPA-WIND-2025",
    "utility_type": "electricity",
    "region": "IN",
    "per_unit": "kWh",
    "published": [{"gas": "CO2e", "value": "0.0", "mass_unit": "kg"}],
    "source_name": "Supplier-specific factor from PPA certificate",
    "source_url": "https://example.org/ppa-cert.pdf",
    "publication_year": 2025,
    "valid_from": "2025-04-01",
    "valid_to": "2026-03-31",
}


def test_list_factors_and_regions(client, admin_headers):
    factors = client.get("/api/factors", headers=admin_headers).json()
    assert len(factors) == 40
    assert all(f["superseded_by"] is None for f in factors)
    cea = next(f for f in factors if f["factor_key"] == "IN-CEA-GRID-FY2023-24")
    assert cea["kgco2e_per_unit"] == "727.000000000000"  # Decimals are serialized as strings
    assert cea["published_json"]["values"] == [{"gas": "CO2", "value": "0.727", "mass_unit": "t"}]

    gas = client.get("/api/factors", headers=admin_headers, params={"utility_type": "natural_gas", "region": "UK"}).json()
    assert {f["factor_key"] for f in gas} == {
        "UK-DESNZ-NATGAS-KWH-2025", "UK-DESNZ-NATGAS-M3-2025",
        "UK-DESNZ-NATGAS-KWH-2026", "UK-DESNZ-NATGAS-M3-2026",
    }

    regions = client.get("/api/factors/regions", headers=admin_headers).json()
    assert {"IN", "UK", "US", "US-CAMX"} <= set(regions)

    assert client.get("/api/factors/gwp-sets", headers=admin_headers).json()["AR5"]["values"]["CH4"] == "28"


def test_admin_creates_and_versions_org_factor(client, admin_headers):
    r = client.post("/api/factors", headers=admin_headers, json=NEW_FACTOR)
    assert r.status_code == 201, r.text
    v1 = r.json()
    assert v1["version"] == 1 and v1["scope"] == 2 and v1["org_id"] is not None

    r = client.post(f"/api/factors/{v1['id']}/versions", headers=admin_headers, json={
        "published": [{"gas": "CO2e", "value": "0.012", "mass_unit": "kg"}],
        "reason": "Certificate reissued with lifecycle emissions",
    })
    assert r.status_code == 201, r.text
    v2 = r.json()
    assert v2["version"] == 2
    assert v2["kgco2e_per_unit"].startswith("0.012")
    assert v2["valid_to"] == "2026-03-31"  # carried over
    assert "Certificate reissued" in v2["notes"]

    history = client.get(f"/api/factors/{v2['id']}/history", headers=admin_headers).json()
    assert [h["version"] for h in history] == [2, 1]
    assert history[1]["superseded_by"] == v2["id"]

    # Can't branch from a superseded version.
    r = client.post(f"/api/factors/{v1['id']}/versions", headers=admin_headers,
                    json={"notes": "x", "reason": "stale edit"})
    assert r.status_code == 409


def test_global_factors_cannot_be_versioned_via_api(client, admin_headers):
    cea = client.get("/api/factors", headers=admin_headers, params={"region": "IN", "utility_type": "electricity"}).json()[0]
    r = client.post(f"/api/factors/{cea['id']}/versions", headers=admin_headers,
                    json={"notes": "edit", "reason": "trying to edit a global factor"})
    assert r.status_code == 403


def test_float_values_and_bad_units_rejected(client, admin_headers):
    body = {**NEW_FACTOR, "published": [{"gas": "CO2e", "value": 0.1, "mass_unit": "kg"}]}
    assert client.post("/api/factors", headers=admin_headers, json=body).status_code == 422

    body = {**NEW_FACTOR, "per_unit": "kg"}
    r = client.post("/api/factors", headers=admin_headers, json=body)
    assert r.status_code == 422 and "energy or volume" in r.json()["detail"]

    body = {**NEW_FACTOR, "published": [
        {"gas": "CO2", "value": "1", "mass_unit": "kg"}, {"gas": "CH4", "value": "1", "mass_unit": "g"}]}
    r = client.post("/api/factors", headers=admin_headers, json=body)
    assert r.status_code == 422 and "GWP set is required" in r.json()["detail"]


def test_member_cannot_create_factors(client, admin_headers):
    client.post("/api/users", headers=admin_headers,
                json={"email": "m@acme.example.com", "password": "member-password-1"})
    token = client.post("/api/auth/login", json={"email": "m@acme.example.com", "password": "member-password-1"}).json()
    member = {"Authorization": f"Bearer {token['access_token']}"}
    assert client.post("/api/factors", headers=member, json=NEW_FACTOR).status_code == 403


def test_org_factors_are_private(client, admin_headers):
    fid = client.post("/api/factors", headers=admin_headers, json=NEW_FACTOR).json()["id"]
    other = register(client, email="admin@globex.example.com", org="Globex")
    assert client.get(f"/api/factors/{fid}", headers=other).status_code == 404
    assert len(client.get("/api/factors", headers=other).json()) == 40
