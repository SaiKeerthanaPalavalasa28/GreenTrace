import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, MetaData, Numeric
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Portable types: JSONB on Postgres (Supabase), plain JSON on SQLite (tests / offline dev).
JSONType = JSON().with_variant(JSONB(), "postgresql")
# Emission math uses Decimal end to end; never float.
Quantity = Numeric(20, 6)
FactorValue = Numeric(24, 12)


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
