import uuid

import boto3
import pytest
from moto import mock_aws

from app.storage import LocalStorage, S3Storage


@pytest.fixture
def s3():
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="greentrace-test")
        yield S3Storage("greentrace-test", region="us-east-1", access_key_id="x", secret_access_key="y", prefix="dev")


@pytest.fixture
def local(tmp_path):
    return LocalStorage(tmp_path)


@pytest.mark.parametrize("backend", ["local", "s3"])
def test_round_trip(backend, request):
    store = request.getfixturevalue(backend)
    org = uuid.uuid4()
    key = store.save(org, "ab" * 32, b"%PDF-1.4 bill")
    assert key == f"bills/{org}/{'ab' * 32}.pdf"
    assert store.read(key) == b"%PDF-1.4 bill"
    assert store.save_file(f"reports/{org}/r.pdf", b"%PDF report") == f"reports/{org}/r.pdf"
    assert store.read(f"reports/{org}/r.pdf") == b"%PDF report"


@pytest.mark.parametrize("backend", ["local", "s3"])
@pytest.mark.parametrize("key", ["../etc/passwd", "/abs/path.pdf", "bills//x.pdf", r"a\b.pdf", "bill\x00.pdf", "bills/../../x"])
def test_rejects_path_tricks(backend, key, request):
    store = request.getfixturevalue(backend)
    with pytest.raises(ValueError):
        store.save_file(key, b"x")
    with pytest.raises(ValueError):
        store.read(key)


def test_s3_uses_prefix_and_content_type(s3):
    s3.save_file("reports/r.pdf", b"%PDF")
    obj = s3.client.get_object(Bucket="greentrace-test", Key="dev/reports/r.pdf")
    assert obj["ContentType"] == "application/pdf"
