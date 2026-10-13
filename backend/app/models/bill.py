import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, JSONType, Quantity, utcnow


class Bill(IdMixin, Base):
    __tablename__ = "bill"
    # Same file uploaded twice in one org is a duplicate.
    __table_args__ = (UniqueConstraint("org_id", "file_hash", name="uq_bill_org_hash"),)

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organization.id"), index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facility.id"), index=True)
    original_filename: Mapped[str] = mapped_column(String(300))
    file_path: Mapped[str] = mapped_column(String(500))
    file_hash: Mapped[str] = mapped_column(String(64))  # SHA-256 hex
    file_size: Mapped[int] = mapped_column(Integer)
    # Unknown until extracted.
    utility_type: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), index=True)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    # Set when an approved bill can't be calculated (e.g. no emission factor for its period).
    # Such a bill contributes nothing to totals until fixed; the dashboard counts it.
    calculation_error: Mapped[str | None] = mapped_column(Text)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    extractions: Mapped[list["Extraction"]] = relationship(back_populates="bill")


class Extraction(IdMixin, Base):
    __tablename__ = "extraction"

    bill_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bill.id"), index=True)
    # Re-extraction keeps the old row for audit; only one row per bill is current.
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)

    provider_name: Mapped[str | None] = mapped_column(String(200))
    account_number: Mapped[str | None] = mapped_column(String(100))
    billing_period_start: Mapped[date | None] = mapped_column(Date)
    billing_period_end: Mapped[date | None] = mapped_column(Date)
    quantity: Mapped[Decimal | None] = mapped_column(Quantity)
    unit: Mapped[str | None] = mapped_column(String(20))
    meter_previous: Mapped[Decimal | None] = mapped_column(Quantity)
    meter_current: Mapped[Decimal | None] = mapped_column(Quantity)
    meter_multiplier: Mapped[Decimal | None] = mapped_column(Quantity)
    read_type: Mapped[str | None] = mapped_column(String(20))
    multiple_meters: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)

    raw_text_snippet: Mapped[str | None] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float | None] = mapped_column(Float)
    text_method: Mapped[str | None] = mapped_column(String(20))  # "pdfplumber" | "ocr"
    model_used: Mapped[str | None] = mapped_column(String(100))
    validation_issues_json: Mapped[list | None] = mapped_column(JSONType)
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # {field: {"before": ..., "after": ...}} for every value a reviewer changed.
    corrections_json: Mapped[dict | None] = mapped_column(JSONType)

    bill: Mapped[Bill] = relationship(back_populates="extractions")
