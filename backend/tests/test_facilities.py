from tests.conftest import register


def test_create_list_update_facility(client, admin_headers):
    r = client.post("/api/facilities", headers=admin_headers,
                    json={"name": "Pune Plant", "address": "MIDC Chakan", "region": "IN"})
    assert r.status_code == 201, r.text
    fid = r.json()["id"]

    r = client.patch(f"/api/facilities/{fid}", headers=admin_headers, json={"address": "Plot 7, MIDC Chakan"})
    assert r.status_code == 200
    assert r.json()["address"] == "Plot 7, MIDC Chakan"

    names = [f["name"] for f in client.get("/api/facilities", headers=admin_headers).json()]
    assert names == ["Pune Plant"]

    audit = client.get("/api/audit", headers=admin_headers, params={"entity_id": fid}).json()
    assert [a["action"] for a in audit] == ["update", "create"]
    assert audit[0]["before_json"]["address"] == "MIDC Chakan"
    assert audit[0]["after_json"]["address"] == "Plot 7, MIDC Chakan"


def test_unknown_region_rejected(client, admin_headers):
    r = client.post("/api/facilities", headers=admin_headers, json={"name": "X", "region": "IN-MH"})
    assert r.status_code == 422
    assert "No emission factors exist for region 'IN-MH'" in r.json()["detail"]


def test_duplicate_facility_name_rejected(client, admin_headers):
    body = {"name": "Pune Plant", "region": "IN"}
    assert client.post("/api/facilities", headers=admin_headers, json=body).status_code == 201
    assert client.post("/api/facilities", headers=admin_headers, json=body).status_code == 409


def test_orgs_cannot_see_each_others_facilities(client, admin_headers):
    fid = client.post("/api/facilities", headers=admin_headers,
                      json={"name": "Pune Plant", "region": "IN"}).json()["id"]

    other = register(client, email="admin@globex.example.com", org="Globex", region="UK")
    assert client.get("/api/facilities", headers=other).json() == []
    r = client.patch(f"/api/facilities/{fid}", headers=other, json={"name": "Hijacked"})
    assert r.status_code == 404
    assert client.get("/api/audit", headers=other, params={"entity_id": fid}).json() == []
