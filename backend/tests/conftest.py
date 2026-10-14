import os

# Must be set before app modules read settings.
os.environ["JWT_SECRET"] = "test-secret-" + "x" * 40
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["REQUEUE_ON_STARTUP"] = "false"
os.environ["ALLOW_DIRECT_SIGNUP"] = "true"

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models import Base
from app.models import Facility, FacilityAccount
from app.pipeline import queue as queue_mod
from app.pipeline.runner import process_bill
from app.seed import load_seed
from app.storage import LocalStorage, get_storage
from tests.helpers import ELECTRICITY_BILL, FakeExtractor, llm_json, make_text_pdf


@pytest.fixture
def engine():
    from sqlalchemy import create_engine, event

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(eng, "connect")
    def _fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with Session() as session:
        yield session


@pytest.fixture
def seeded_db(db):
    load_seed(db)
    return db


@pytest.fixture
def client(engine, seeded_db):
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _get_db():
        with Session() as s:
            yield s

    app.dependency_overrides[get_db] = _get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def register(client, email="admin@acme.example.com", org="Acme Ltd", region="IN", password="correct-horse-battery"):
    r = client.post("/api/auth/register", json={
        "org_name": org, "email": email, "password": password, "default_region": region,
    })
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def admin_headers(client):
    return register(client)


# ---------------------------------------------------------------- pipeline fixtures (sync queue, fake LLM)

TODAY = date(2026, 10, 13)


class SyncQueue:
    """Processes a bill immediately, in the request, with the fake LLM."""

    def __init__(self, session_factory, storage, extractor):
        self.session_factory, self.storage, self.extractor = session_factory, storage, extractor

    def enqueue(self, bill_id):
        process_bill(bill_id, session_factory=self.session_factory, extractor=self.extractor,
                     storage=self.storage, today=TODAY)


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(tmp_path / "files")


@pytest.fixture
def fake_llm():
    return FakeExtractor(llm_json())


@pytest.fixture
def api(client, engine, storage, fake_llm):
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    app.dependency_overrides[queue_mod.get_queue] = lambda: SyncQueue(Session, storage, fake_llm)
    app.dependency_overrides[get_storage] = lambda: storage
    headers = register(client)
    facility = client.post("/api/facilities", headers=headers, json={"name": "Pune Plant", "region": "IN"}).json()
    return client, headers, facility["id"]


def upload(client, headers, facility_id, *files):
    r = client.post("/api/bills/upload", headers=headers, data={"facility_id": facility_id},
                    files=[("files", (name, data, "application/pdf")) for name, data in files])
    assert r.status_code == 200, r.text
    return r.json()["results"]


def bill_pdf(account="170012345678", tag=""):
    lines = [line.replace("170012345678", account) for line in ELECTRICITY_BILL]
    return make_text_pdf([lines + [f"ref {tag}"]])


def map_account(db_engine, facility_id, account="170012345678"):
    Session = sessionmaker(bind=db_engine)
    with Session() as db:
        f = db.get(Facility, uuid.UUID(facility_id))
        db.add(FacilityAccount(org_id=f.org_id, facility_id=f.id, utility_type="electricity", account_number=account))
        db.commit()


