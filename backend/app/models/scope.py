import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JSONType, utcnow


class ScopeDocument(IdMixin, Base):
    """A PDF uploaded under one GHG scope (1, 2 or 3), with what was read from it and what looked
    suspicious. `items` and `flags` are JSON lists; see app/scope_analysis.py for their shape."""

    __tablename__ = "scope_document"
    __table_args__ = (UniqueConstraint("org_id", "file_hash", name="uq_scope_document_org_hash"),)

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organization.id"), index=True)
    scope: Mapped[int] = mapped_column(Integer, index=True)
    original_filename: Mapped[str] = mapped_column(String(300))
    file_path: Mapped[str] = mapped_column(String(500))
    file_hash: Mapped[str] = mapped_column(String(64))
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    items: Mapped[list] = mapped_column(JSONType, default=list)
    flags: Mapped[list] = mapped_column(JSONType, default=list)
    total_kg_co2e: Mapped[float] = mapped_column(Float, default=0.0)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
