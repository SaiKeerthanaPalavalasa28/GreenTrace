from datetime import UTC, datetime, timedelta

import jwt

from app.config import get_settings
from tests.conftest import register


def test_register_login_me(client):
    headers = register(client)
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["user"]["email"] == "admin@acme.example.com"
    assert me["user"]["role"] == "admin"
    assert me["organization"]["name"] == "Acme Ltd"
    assert me["organization"]["fiscal_year_start_month"] == 4

    r = client.post("/api/auth/login", json={"email": "ADMIN@acme.example.com", "password": "correct-horse-battery"})
    assert r.status_code == 200
    assert r.json()["token_type"] == "bearer"


def test_duplicate_email_rejected(client):
    register(client)
    r = client.post("/api/auth/register", json={
        "org_name": "Other", "email": "admin@acme.example.com", "password": "another-long-password",
    })
    assert r.status_code == 409


def test_short_password_rejected(client):
    r = client.post("/api/auth/register", json={"org_name": "X", "email": "a@b.example.com", "password": "short"})
    assert r.status_code == 422


def test_wrong_password_and_unknown_email_look_the_same(client):
    register(client)
    a = client.post("/api/auth/login", json={"email": "admin@acme.example.com", "password": "wrong-password!"})
    b = client.post("/api/auth/login", json={"email": "nobody@acme.example.com", "password": "wrong-password!"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_routes_require_auth(client):
    for path in ["/api/auth/me", "/api/facilities", "/api/factors", "/api/audit", "/api/users"]:
        assert client.get(path).status_code == 401, path


def test_bad_and_expired_tokens_rejected(client):
    register(client)
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer nonsense"}).status_code == 401

    s = get_settings()
    expired = jwt.encode(
        {"sub": "00000000-0000-0000-0000-000000000000", "exp": datetime.now(UTC) - timedelta(minutes=1)},
        s.jwt_secret, algorithm=s.jwt_algorithm,
    )
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401

    forged = jwt.encode(
        {"sub": "00000000-0000-0000-0000-000000000000", "exp": datetime.now(UTC) + timedelta(hours=1)},
        "a-different-secret-that-is-long-enough-xx", algorithm="HS256",
    )
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_admin_creates_member_who_cannot_do_admin_things(client, admin_headers):
    r = client.post("/api/users", headers=admin_headers, json={
        "email": "member@acme.example.com", "password": "member-password-1", "role": "member",
    })
    assert r.status_code == 201
    login = client.post("/api/auth/login", json={"email": "member@acme.example.com", "password": "member-password-1"})
    member = {"Authorization": f"Bearer {login.json()['access_token']}"}

    assert client.get("/api/facilities", headers=member).status_code == 200
    assert client.post("/api/facilities", headers=member,
                       json={"name": "Plant", "region": "IN"}).status_code == 403
    assert client.get("/api/users", headers=member).status_code == 403
