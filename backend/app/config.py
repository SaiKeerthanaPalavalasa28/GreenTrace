from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """All configuration comes from environment variables (or backend/.env). No secrets in code."""

    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    app_env: str = "development"
    # Supabase: use the Postgres connection string, e.g.
    # postgresql+psycopg://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'greentrace.db').as_posix()}"

    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 8 * 60

    cors_origins: list[str] = ["http://localhost:5173"]

    storage_backend: Literal["local", "s3"] = "local"
    storage_dir: Path = BACKEND_DIR / "storage"  # local backend
    # s3 backend (Supabase Storage S3 endpoint, AWS S3, MinIO). Keep the bucket private.
    s3_bucket: str | None = None
    s3_endpoint_url: str | None = None
    s3_region: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_prefix: str = ""
    max_upload_mb: int = 20
    max_files_per_upload: int = 50
    max_pdf_pages: int = 30

    # Structured extraction (Gemini). Bills fail with a clear reason if the key is missing.
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.8-flash"
    gemini_timeout_seconds: int = 120
    # Free-tier keys allow only a few requests per minute (5 for flash models at the time of writing).
    gemini_requests_per_minute: int | None = None
    max_prompt_chars: int = 60_000
    extraction_workers: int = 3
    requeue_on_startup: bool = True  # resume bills interrupted by a restart

    # Text extraction: a page with fewer non-whitespace characters than this is OCR'd.
    min_text_chars_per_page: int = 40
    ocr_dpi: int = 300
    tesseract_cmd: str | None = None  # e.g. C:\Program Files\Tesseract-OCR\tesseract.exe

    # Validation rules (code, not LLM). Any failed rule sends the bill to review.
    review_confidence_threshold: float = 0.85
    max_billing_period_days: int = 95
    outlier_ratio: float = 3.0  # flag if daily usage is >3x or <1/3 of the facility's median
    outlier_min_history: int = 3

    @field_validator("database_url")
    @classmethod
    def _normalize_postgres_driver(cls, v: str) -> str:
        # Supabase hands out postgresql:// URLs; SQLAlchemy needs the psycopg v3 driver named.
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://"):]
        if v.startswith("postgresql://"):
            v = "postgresql+psycopg://" + v[len("postgresql://"):]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
