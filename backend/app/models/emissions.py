import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, FactorValue, IdMixin, JSONType, Quantity, utcnow


class EmissionFactor(IdMixin, CreatedAtMixin, Base):
    """A versioned emission factor. Rows are never edited in place: a correction is a new
    version with the same factor_key, and the old row gets superseded_by set."""

    __tablename__ = "emission_factor"
    __table_args__ = (UniqueConstraint("factor_key", "version", name="uq_factor_key_version"),)

    # Stable identifier for one published factor across its versions, e.g. "IN-CEA-GRID-FY2023-24".
    factor_key: Mapped[str] = mapped_column(String(100), index=True)
    version: Mapped[int] = mapped_column(Integer)
    # NULL = global factor (seeded from official sources); set = org-specific factor.
    org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organization.id"), index=True)

    utility_type: Mapped[str] = mapped_column(String(20))
    region: Mapped[str] = mapped_column(String(40), index=True)
    unit: Mapped[str] = mapped_column(String(20))  # denominator: kg CO2e per <unit>
    kgco2e_per_unit: Mapped[Decimal] = mapped_column(FactorValue)
    ghg_basis: Mapped[str] = mapped_column(String(10))
    scope: Mapped[int] = mapped_column(Integer)

    source_name: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    publication_year: Mapped[int] = mapped_column(Integer)
    # The value(s) exactly as printed by the source, before unit/GWP conversion.
    published_json: Mapped[dict] = mapped_column(JSONType)
    derivation: Mapped[str] = mapped_column(Text)  # human-readable conversion from published_json
    notes: Mapped[str] = mapped_column(Text, default="")

    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)  # NULL = open-ended
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("emission_factor.id"))
    created_by: Mapped[str] = mapped_column(String(100))  # user id or "seed"


class EmissionRecord(IdMixin, Base):
    """One calculated emission figure. A bill split by pro-rating yields several records.
    Recalculation marks old records is_current=False rather than deleting them."""

    __tablename__ = "emission_record"

    extraction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("extraction.id"), index=True)
    emission_factor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("emission_factor.id"))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    allocation_start: Mapped[date] = mapped_column(Date)
    allocation_end: Mapped[date] = mapped_column(Date)
    allocation_fraction: Mapped[Decimal] = mapped_column(FactorValue)

    normalized_quantity: Mapped[Decimal] = mapped_column(Quantity)
    normalized_unit: Mapped[str] = mapped_column(String(20))
    kgco2e: Mapped[Decimal] = mapped_column(Quantity)
    scope: Mapped[int] = mapped_column(Integer)
    calculation_trace_json: Mapped[dict] = mapped_column(JSONType)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Report(IdMixin, Base):
    __tablename__ = "report"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organization.id"), index=True)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    reporting_period_label: Mapped[str] = mapped_column(String(50))  # e.g. "FY2024-25"
    status: Mapped[str] = mapped_column(String(20), default="pending")
    generated_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    file_path: Mapped[str | None] = mapped_column(String(500))
    snapshot_json: Mapped[dict | None] = mapped_column(JSONType)
    # SHA-256 of the canonical snapshot JSON and of the PDF, so either can be verified later.
    snapshot_sha256: Mapped[str | None] = mapped_column(String(64))
    pdf_sha256: Mapped[str | None] = mapped_column(String(64))
    # True when bills that may belong to the period were not included (pending, failed, ...).
    is_draft: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())


class AuditLog(IdMixin, Base):
    __tablename__ = "audit_log"

    org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organization.id"), index=True)
    actor: Mapped[str] = mapped_column(String(100))  # user id, "system", or "seed"
    action: Mapped[str] = mapped_column(String(50))
    entity: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str] = mapped_column(String(100), index=True)
    before_json: Mapped[dict | None] = mapped_column(JSONType)
    after_json: Mapped[dict | None] = mapped_column(JSONType)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
