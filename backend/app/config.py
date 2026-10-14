import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Configuration with working defaults: no .env file and no API keys are needed. Real process
    environment variables (e.g. DATABASE_URL, set by the deployment) still override a default."""

    model_config = SettingsConfigDict(
        extra="ignore", populate_by_name=True, env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8"
    )

    app_env: str = "development"
    # Supabase: use the Postgres connection string, e.g.
    # postgresql+psycopg://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'greentrace.db').as_posix()}"

    # Generated on first start and kept in the storage directory (so it survives restarts and is
    # shared by every instance mounting that directory). Set JWT_SECRET to pin your own.
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 8 * 60

    # Outgoing mail (credentials for new organizations). Any SMTP server works, e.g. Gmail with an
    # app password: SMTP_HOST=smtp.gmail.com SMTP_PORT=587 SMTP_USER=you@gmail.com SMTP_PASSWORD=...
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None  # defaults to smtp_user
    smtp_use_ssl: bool = False  # True = implicit TLS (port 465); False = STARTTLS
    # Development only: print emails to the server log instead of sending them.
    mail_console_only: bool = False
    # The old one-person signup (no email delivery check). Off: organizations sign up via
    # /auth/register-org, which emails each role its own credentials.
    allow_direct_signup: bool = False
    app_url: str = "http://localhost:5173"  # link placed in the credentials email

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

    # Structured extraction: a LangChain chat model (Google Gemini). Set GOOGLE_API_KEY (or
    # GEMINI_API_KEY) - get one free at https://aistudio.google.com/apikey
    google_api_key: str | None = Field(default=None, validation_alias=AliasChoices("GOOGLE_API_KEY", "GEMINI_API_KEY", "google_api_key"))
    llm_model: str = "gemini-2.5-flash"
    llm_timeout_seconds: int = 120
    llm_requests_per_minute: int = 10  # stay under the free-tier quota; 0 = no limit
    max_prompt_chars: int = 60_000
    extraction_workers: int = 3
    requeue_on_startup: bool = True  # resume bills interrupted by a restart

    # Text extraction: a page with fewer non-whitespace characters than this is OCR'd.
    min_text_chars_per_page: int = 40
    ocr_dpi: int = 300
    tesseract_cmd: str | None = None  # optional; without Tesseract, scanned pages are read by Gemini vision

    # Validation rules (code, not LLM). Any failed rule sends the bill to review.
    review_confidence_threshold: float = 0.85
    max_billing_period_days: int = 95
    outlier_ratio: float = 3.0  # flag if daily usage is >3x or <1/3 of the facility's median
    outlier_min_history: int = 3

    @model_validator(mode="after")
    def _ensure_jwt_secret(self):
        if len(self.jwt_secret) < 32:
            self.jwt_secret = _load_or_create_secret(self.storage_dir / ".jwt_secret")
        return self

    @field_validator("database_url")
    @classmethod
    def _normalize_postgres_driver(cls, v: str) -> str:
        # Supabase hands out postgresql:// URLs; SQLAlchemy needs the psycopg v3 driver named.
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://"):]
        if v.startswith("postgresql://"):
            v = "postgresql+psycopg://" + v[len("postgresql://"):]
        return v


def _load_or_create_secret(path: Path) -> str:
    try:
        if path.exists() and len(path.read_text().strip()) >= 32:
            return path.read_text().strip()
        secret = secrets.token_urlsafe(48)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secret)
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return secret
    except OSError:
        # Read-only filesystem: fall back to a per-process secret (logins reset on restart).
        return secrets.token_urlsafe(48)


@lru_cache
def get_settings() -> Settings:
    return Settings()
