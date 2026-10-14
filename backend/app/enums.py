from enum import StrEnum


class UtilityType(StrEnum):
    electricity = "electricity"
    natural_gas = "natural_gas"


# GHG Protocol: purchased electricity is Scope 2 (location-based here);
# natural gas burned on site is Scope 1 (stationary combustion).
SCOPE_BY_UTILITY = {UtilityType.electricity: 2, UtilityType.natural_gas: 1}


class BillStatus(StrEnum):
    uploaded = "uploaded"
    processing = "processing"
    needs_review = "needs_review"
    approved = "approved"
    rejected = "rejected"
    failed = "failed"


class Role(StrEnum):
    admin = "admin"  # can edit everything
    manager = "manager"  # view only
    auditor = "auditor"  # view only
    member = "member"  # legacy role from before managers/auditors existed; can still write


READ_ONLY_ROLES = frozenset({Role.manager.value, Role.auditor.value})


class ReportingFramework(StrEnum):
    BRSR = "BRSR"  # India, SEBI Business Responsibility and Sustainability Report
    SECR = "SECR"  # UK, Streamlined Energy and Carbon Reporting
    CSRD = "CSRD"  # EU, Corporate Sustainability Reporting Directive
    EPA = "EPA"  # US EPA GHG reporting
    OTHER = "OTHER"


class GhgBasis(StrEnum):
    CO2 = "CO2"  # factor covers CO2 only (e.g. CEA grid factor)
    CO2e = "CO2e"  # factor covers CO2 + CH4 + N2O as CO2-equivalent
