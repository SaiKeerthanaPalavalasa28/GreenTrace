import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, IdMixin


class Organization(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "organization"

    name: Mapped[str] = mapped_column(String(200))
    reporting_framework: Mapped[str] = mapped_column(String(20))
    default_region: Mapped[str] = mapped_column(String(40))
    # 4 = April (Indian fiscal year, BRSR); 1 = calendar year.
    fiscal_year_start_month: Mapped[int] = mapped_column(Integer, default=4)

    facilities: Mapped[list["Facility"]] = relationship(back_populates="organization")


class User(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "app_user"  # "user" is reserved in Postgres

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organization.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    full_name: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Facility(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "facility"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_facility_org_name"),)

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organization.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str] = mapped_column(String(500), default="")
    # Grid zone / region code used for emission factor selection, e.g. "IN", "UK", "US-CAMX".
    region: Mapped[str] = mapped_column(String(40))

    organization: Mapped[Organization] = relationship(back_populates="facilities")


class FacilityAccount(IdMixin, CreatedAtMixin, Base):
    """Maps a utility account number to a facility, learned when a reviewer approves a bill."""

    __tablename__ = "facility_account"
    __table_args__ = (
        UniqueConstraint("org_id", "utility_type", "account_number", name="uq_facility_account"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organization.id"), index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facility.id"))
    utility_type: Mapped[str] = mapped_column(String(20))
    account_number: Mapped[str] = mapped_column(String(100))
