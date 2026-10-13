import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field, field_validator, model_validator

from app.enums import ReportingFramework, Role, UtilityType


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- auth / users

class RegisterIn(BaseModel):
    org_name: str = Field(min_length=1, max_length=200)
    reporting_framework: ReportingFramework = ReportingFramework.BRSR
    default_region: str = Field("IN", min_length=1, max_length=40)
    fiscal_year_start_month: int = Field(4, ge=1, le=12)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    full_name: str = Field("", max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"


class OrganizationOut(ORM):
    id: uuid.UUID
    name: str
    reporting_framework: str
    default_region: str
    fiscal_year_start_month: int


class UserOut(ORM):
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    org_id: uuid.UUID


class MeOut(BaseModel):
    user: UserOut
    organization: OrganizationOut


class UserCreateIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    full_name: str = Field("", max_length=200)
    role: Role = Role.member


# ---------------------------------------------------------------- facilities

class FacilityIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    address: str = Field("", max_length=500)
    region: str = Field(min_length=1, max_length=40)


class FacilityPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    address: str | None = Field(None, max_length=500)
    region: str | None = Field(None, min_length=1, max_length=40)


class FacilityOut(ORM):
    id: uuid.UUID
    name: str
    address: str
    region: str
    created_at: datetime


# ---------------------------------------------------------------- emission factors

def _reject_float_values(v):
    # Factor values must arrive as strings: the JSON number 0.1 is not exactly 0.1.
    for item in v or []:
        if isinstance(item, dict) and isinstance(item.get("value"), float):
            raise ValueError('Send published values as strings (e.g. "0.727"), not JSON numbers')
    return v


class PublishedValueIn(BaseModel):
    gas: Literal["CO2", "CH4", "N2O", "CO2e"]
    value: Decimal = Field(ge=0)
    mass_unit: Literal["kg", "g", "t", "lb"]


class FactorCreateIn(BaseModel):
    """A new org-specific factor. kg CO2e per unit is derived from `published`, never typed in."""

    factor_key: str = Field(min_length=3, max_length=100, pattern=r"^[A-Za-z0-9_.\-]+$")
    utility_type: UtilityType
    region: str = Field(min_length=1, max_length=40)
    per_unit: str
    published: list[PublishedValueIn] = Field(min_length=1)
    gwp_set: str | None = None
    source_name: str = Field(min_length=3)
    source_url: str = Field(min_length=8)
    publication_year: int = Field(ge=1990, le=2100)
    valid_from: date
    valid_to: date | None = None
    notes: str = ""

    @field_validator("published", mode="before")
    @classmethod
    def _values_as_strings(cls, v):
        return _reject_float_values(v)


class FactorVersionIn(BaseModel):
    """A corrected version of an existing factor. Omitted fields carry over from the latest version."""

    published: list[PublishedValueIn] | None = None
    gwp_set: str | None = None
    per_unit: str | None = None
    source_name: str | None = None
    source_url: str | None = None
    publication_year: int | None = Field(None, ge=1990, le=2100)
    valid_from: date | None = None
    valid_to: date | None = None
    notes: str | None = None
    reason: str = Field(min_length=3, description="Why this version replaces the previous one")

    @field_validator("published", mode="before")
    @classmethod
    def _values_as_strings(cls, v):
        return _reject_float_values(v)

    @model_validator(mode="after")
    def _something_changes(self):
        fields = self.model_dump(exclude={"reason"}, exclude_unset=True)
        if not fields:
            raise ValueError("A new version must change at least one field")
        return self


class FactorOut(ORM):
    id: uuid.UUID
    factor_key: str
    version: int
    org_id: uuid.UUID | None
    utility_type: str
    region: str
    unit: str
    kgco2e_per_unit: Decimal
    ghg_basis: str
    scope: int
    source_name: str
    source_url: str
    publication_year: int
    published_json: dict
    derivation: str
    notes: str
    valid_from: date
    valid_to: date | None
    superseded_by: uuid.UUID | None
    created_by: str
    created_at: datetime


class AuditOut(ORM):
    id: uuid.UUID
    actor: str
    action: str
    entity: str
    entity_id: str
    before_json: dict | None
    after_json: dict | None
    timestamp: datetime


# ---------------------------------------------------------------- bills

class ExtractionOut(ORM):
    id: uuid.UUID
    provider_name: str | None
    account_number: str | None
    billing_period_start: date | None
    billing_period_end: date | None
    quantity: Decimal | None
    unit: str | None
    meter_previous: Decimal | None
    meter_current: Decimal | None
    meter_multiplier: Decimal | None
    read_type: str | None
    multiple_meters: bool
    notes: str | None
    raw_text_snippet: str | None
    page_number: int | None
    confidence: float | None
    text_method: str | None
    model_used: str | None
    validation_issues_json: list | None
    extracted_at: datetime
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None
    corrections_json: dict | None

    @computed_field
    @property
    def blocking_codes(self) -> list[str]:
        """Issue codes that must be fixed before this extraction can be approved."""
        from app.pipeline.validate import BLOCKING_CODES

        return [i["code"] for i in (self.validation_issues_json or []) if i["code"] in BLOCKING_CODES]


class BillOut(ORM):
    id: uuid.UUID
    facility_id: uuid.UUID
    original_filename: str
    file_hash: str
    file_size: int
    utility_type: str | None
    status: str
    failure_reason: str | None
    calculation_error: str | None
    uploaded_by: uuid.UUID
    uploaded_at: datetime
    updated_at: datetime


class BillListItem(BillOut):
    facility_name: str
    billing_period_start: date | None = None
    billing_period_end: date | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    issue_count: int = 0
    kgco2e: Decimal | None = None  # sum of current emission records; None if not calculated
    tco2e: Decimal | None = None  # kgco2e / 1000, rounded to 3 dp for display


class BillDetailOut(BaseModel):
    bill: BillOut
    facility_name: str
    extraction: ExtractionOut | None


class BillStatusOut(ORM):
    id: uuid.UUID
    status: str
    failure_reason: str | None
    updated_at: datetime


class UploadResult(BaseModel):
    filename: str
    outcome: Literal["queued", "duplicate", "rejected"]
    bill_id: uuid.UUID | None = None
    reason: str | None = None


class UploadOut(BaseModel):
    results: list[UploadResult]


class EmissionRecordOut(ORM):
    id: uuid.UUID
    extraction_id: uuid.UUID
    emission_factor_id: uuid.UUID
    is_current: bool
    allocation_start: date
    allocation_end: date
    allocation_fraction: Decimal
    normalized_quantity: Decimal
    normalized_unit: str
    kgco2e: Decimal
    scope: int
    calculation_trace_json: dict
    calculated_at: datetime


class BillTraceOut(BaseModel):
    bill: BillOut
    facility_name: str
    extraction: ExtractionOut | None
    records: list[EmissionRecordOut]
    total_kgco2e: Decimal | None
    total_tco2e: Decimal | None
    superseded_records: list[EmissionRecordOut]


class RecalculateOut(BaseModel):
    calculated: int
    unchanged: int
    error: int


# ---------------------------------------------------------------- review

class ReviewChangesIn(BaseModel):
    """Field values as strings (numbers too, to stay exact). Omitted fields are unchanged;
    an empty string clears a field."""

    changes: dict[str, str | None] = Field(default_factory=dict)
    reason: str | None = Field(None, max_length=1000)
    expected_updated_at: datetime | None = Field(
        None, description="bill.updated_at as last seen by the reviewer; a mismatch means someone else changed it")


class ApproveIn(ReviewChangesIn):
    note: str | None = Field(None, max_length=1000)
    remap_account: bool = False


class RejectIn(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)
    expected_updated_at: datetime | None = None


class ReopenIn(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class ReviewQueueItem(BaseModel):
    bill_id: uuid.UUID
    extraction_id: uuid.UUID | None
    original_filename: str
    facility_name: str
    utility_type: str | None
    billing_period_start: date | None
    billing_period_end: date | None
    quantity: Decimal | None
    unit: str | None
    confidence: float | None
    issue_codes: list[str]
    blocking_codes: list[str]
    uploaded_at: datetime


class ReviewCounts(BaseModel):
    needs_review: int
    failed: int
    calculation_errors: int


# ---------------------------------------------------------------- reports

class ReportCreateIn(BaseModel):
    period_start: date
    period_end: date
    label: str | None = Field(None, max_length=50, description="defaults to the reporting-year label or the date range")


class ReportOut(ORM):
    id: uuid.UUID
    period_start: date
    period_end: date
    reporting_period_label: str
    status: str
    is_draft: bool
    generated_by: uuid.UUID
    generated_at: datetime | None
    pdf_sha256: str | None
    snapshot_sha256: str | None


class ReportDetailOut(ReportOut):
    summary: dict
