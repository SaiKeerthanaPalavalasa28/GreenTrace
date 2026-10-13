"""File storage behind a small interface: local disk for development, any S3-compatible
service (Supabase Storage, AWS S3, MinIO) for production. Select with STORAGE_BACKEND."""

import uuid
from pathlib import Path
from typing import Protocol

from app.config import get_settings


class Storage(Protocol):
    def save(self, org_id: uuid.UUID, file_hash: str, data: bytes) -> str: ...
    def save_file(self, key: str, data: bytes) -> str: ...
    def read(self, key: str) -> bytes: ...


def bill_key(org_id: uuid.UUID, file_hash: str) -> str:
    # Keys are built from a UUID and a hex digest only, so no user input reaches the path.
    return f"bills/{org_id}/{file_hash}.pdf"


def _check_key(key: str) -> str:
    if (key.startswith("/") or "\\" in key or any(ord(c) < 32 for c in key)
            or any(part in ("", ".", "..") for part in key.split("/"))):
        raise ValueError("Invalid storage key")
    return key


class LocalStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / _check_key(key)).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Invalid storage key")
        return path

    def save(self, org_id: uuid.UUID, file_hash: str, data: bytes) -> str:
        return self.save_file(bill_key(org_id, file_hash), data)

    def save_file(self, key: str, data: bytes) -> str:
        """Save under a key built by the caller from ids (never from user input)."""
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()


class S3Storage:
    """S3-compatible object storage. For Supabase Storage use its S3 endpoint
    (https://<project-ref>.supabase.co/storage/v1/s3) and S3 access keys from the dashboard;
    keep the bucket private - files are only ever served through the API's org checks."""

    def __init__(self, bucket: str, *, endpoint_url: str | None = None, region: str | None = None,
                 access_key_id: str | None = None, secret_access_key: str | None = None, prefix: str = ""):
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self.prefix = prefix.strip("/") + "/" if prefix.strip("/") else ""
        self.client = boto3.client(
            "s3", endpoint_url=endpoint_url, region_name=region, aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 5, "mode": "standard"}),
        )

    def save(self, org_id: uuid.UUID, file_hash: str, data: bytes) -> str:
        return self.save_file(bill_key(org_id, file_hash), data)

    def save_file(self, key: str, data: bytes) -> str:
        content_type = "application/pdf" if key.endswith(".pdf") else "application/octet-stream"
        self.client.put_object(Bucket=self.bucket, Key=self.prefix + _check_key(key), Body=data, ContentType=content_type)
        return key

    def read(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=self.prefix + _check_key(key))["Body"].read()


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        s = get_settings()
        if s.storage_backend == "s3":
            if not s.s3_bucket:
                raise RuntimeError("STORAGE_BACKEND=s3 requires S3_BUCKET")
            _storage = S3Storage(s.s3_bucket, endpoint_url=s.s3_endpoint_url, region=s.s3_region,
                                 access_key_id=s.s3_access_key_id, secret_access_key=s.s3_secret_access_key,
                                 prefix=s.s3_prefix)
        else:
            _storage = LocalStorage(s.storage_dir)
    return _storage
