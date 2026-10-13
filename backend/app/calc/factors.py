"""Emission factor selection. Pure: candidates are passed in, nothing is read from the DB.

Rules, in order:
 1. Same utility type, not superseded, and valid on the date (valid_from <= date <= valid_to).
 2. Region: the facility's exact region. Only if NO factor of this utility type exists for
    the exact region at all (any date) may the parent region be used ("US-CAMX" -> "US"),
    e.g. natural gas, which is published nationally. An exact-region factor that merely
    doesn't cover the date is an error, never a fallback to the parent's number.
 3. Owner: a factor belonging to the organization beats a global (seeded) one.
 4. Unit: the factor's unit must be convertible from the bill unit (same dimension).
    If several remain, an exact unit match wins.
 5. Anything still ambiguous, or nothing left, raises. There is no default factor.
"""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.calc.units import UNITS, convertible


@dataclass(frozen=True)
class FactorData:
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
    valid_from: date
    valid_to: date | None
    derivation: str = ""
    superseded: bool = False

    def covers(self, d: date) -> bool:
        return self.valid_from <= d and (self.valid_to is None or d <= self.valid_to)


@dataclass(frozen=True)
class Selection:
    factor: FactorData
    region_match: str  # "exact" | "parent"
    owner: str  # "organization" | "global"


class FactorSelectionError(LookupError):
    pass


def parent_region(region: str) -> str | None:
    return region.rsplit("-", 1)[0] if "-" in region else None


def _describe(factors: list[FactorData]) -> str:
    if not factors:
        return "none"
    return "; ".join(
        f"{f.factor_key} v{f.version} ({f.unit}, {f.valid_from} to {f.valid_to or 'open'})"
        for f in sorted(factors, key=lambda f: f.valid_from)
    )


def select_factor(
    candidates: list[FactorData],
    *,
    utility_type: str,
    region: str,
    on_date: date,
    bill_unit: str,
    org_id: uuid.UUID | None,
) -> Selection:
    usable = [
        f for f in candidates
        if f.utility_type == utility_type and not f.superseded and (f.org_id is None or f.org_id == org_id)
    ]

    region_match, lookup_region = "exact", region
    if not any(f.region == region for f in usable):
        parent = parent_region(region)
        if parent and any(f.region == parent for f in usable):
            region_match, lookup_region = "parent", parent
        else:
            raise FactorSelectionError(
                f"No {utility_type.replace('_', ' ')} emission factor exists for region {region!r}"
                + (f" or its parent {parent!r}" if parent else "")
                + ". Add one on the Emission factors page."
            )
    in_region = [f for f in usable if f.region == lookup_region]

    on_day = [f for f in in_region if f.covers(on_date)]
    if not on_day:
        raise FactorSelectionError(
            f"No {utility_type.replace('_', ' ')} emission factor for region {lookup_region!r} covers {on_date}. "
            f"Available: {_describe(in_region)}. Add the factor published for this period; "
            f"factors from other periods are never used as a substitute."
        )

    org_owned = [f for f in on_day if f.org_id is not None]
    pool, owner = (org_owned, "organization") if org_owned else (on_day, "global")

    if bill_unit not in UNITS:
        raise FactorSelectionError(f"Unknown bill unit {bill_unit!r}")
    compatible = [f for f in pool if convertible(bill_unit, f.unit)]
    if not compatible:
        raise FactorSelectionError(
            f"Bill is in {bill_unit} ({UNITS[bill_unit].dimension}) but the {lookup_region!r} factors for {on_date} "
            f"are per {', '.join(sorted({f.unit for f in pool}))}. Converting between volume and energy needs "
            f"the supplier's calorific value; add a factor in a compatible unit or correct the bill unit."
        )
    exact = [f for f in compatible if f.unit == bill_unit]
    finalists = exact or compatible
    if len(finalists) > 1:
        raise FactorSelectionError(
            f"Ambiguous: {len(finalists)} factors match {utility_type} / {lookup_region} / {on_date} / {bill_unit}: "
            f"{_describe(finalists)}. Narrow their validity periods so only one applies."
        )
    return Selection(finalists[0], region_match, owner)


def factor_boundaries(candidates: list[FactorData], utility_type: str, start: date, end: date) -> list[date]:
    """Dates inside [start, end] on which some relevant factor's validity starts or ends,
    so a bill can be split where the applicable factor might change."""
    out = set()
    for f in candidates:
        if f.utility_type != utility_type or f.superseded:
            continue
        out.add(f.valid_from)
        if f.valid_to is not None:
            out.add(f.valid_to + timedelta(days=1))
    return sorted(d for d in out if start < d <= end)
