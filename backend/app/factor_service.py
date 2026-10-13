"""Creating and versioning emission factors. Shared by the seed loader and the admin API so
both derive kgco2e_per_unit the same way and both write an audit record."""

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.calc.factor_derivation import PublishedComponent, derive
from app.calc.units import UNITS, dimension
from app.config import BACKEND_DIR
from app.enums import SCOPE_BY_UTILITY, UtilityType
from app.models import EmissionFactor

SEED_PATH = BACKEND_DIR / "seed" / "emission_factors.yaml"


class FactorSpecError(ValueError):
    pass


@dataclass
class FactorSpec:
    key: str
    version: int
    utility_type: str
    region: str
    per_unit: str
    published: list[PublishedComponent]
    source_name: str
    source_url: str
    publication_year: int
    valid_from: date
    valid_to: date | None
    gwp_set: str | None = None
    notes: str = ""
    org_id: uuid.UUID | None = None
    extra: dict = field(default_factory=dict)


@lru_cache
def gwp_sets(path: Path = SEED_PATH) -> dict[str, dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        name: {**s, "values": {g: Decimal(str(v)) for g, v in s["values"].items()}}
        for name, s in data["gwp_sets"].items()
    }


def build_factor(spec: FactorSpec, created_by: str) -> EmissionFactor:
    if spec.utility_type not in UtilityType.__members__:
        raise FactorSpecError(f"Unknown utility_type {spec.utility_type!r}")
    if spec.per_unit not in UNITS or dimension(spec.per_unit) == "mass":
        raise FactorSpecError(f"per_unit must be an energy or volume unit, got {spec.per_unit!r}")
    if spec.valid_to is not None and spec.valid_to < spec.valid_from:
        raise FactorSpecError("valid_to is before valid_from")
    if not spec.source_url.startswith(("http://", "https://")):
        raise FactorSpecError("source_url must be an http(s) URL")

    gwp = None
    if spec.gwp_set is not None:
        sets = gwp_sets()
        if spec.gwp_set not in sets:
            raise FactorSpecError(f"Unknown GWP set {spec.gwp_set!r}; known: {sorted(sets)}")
        gwp = sets[spec.gwp_set]["values"]
    derived = derive(spec.published, spec.per_unit, gwp, spec.gwp_set)

    return EmissionFactor(
        id=uuid.uuid4(),
        factor_key=spec.key,
        version=spec.version,
        org_id=spec.org_id,
        utility_type=spec.utility_type,
        region=spec.region,
        unit=spec.per_unit,
        kgco2e_per_unit=derived.kgco2e_per_unit,
        ghg_basis=derived.ghg_basis.value,
        scope=SCOPE_BY_UTILITY[UtilityType(spec.utility_type)],
        source_name=spec.source_name,
        source_url=spec.source_url,
        publication_year=spec.publication_year,
        published_json={
            "per_unit": spec.per_unit,
            "gwp_set": spec.gwp_set,
            "values": [
                {"gas": c.gas, "value": str(c.value), "mass_unit": c.mass_unit} for c in spec.published
            ],
        },
        derivation=derived.derivation,
        notes=spec.notes or "",
        valid_from=spec.valid_from,
        valid_to=spec.valid_to,
        created_by=created_by,
    )


def latest_version(db: Session, key: str) -> EmissionFactor | None:
    return db.scalars(
        select(EmissionFactor)
        .where(EmissionFactor.factor_key == key)
        .order_by(EmissionFactor.version.desc())
        .limit(1)
    ).first()


def add_factor(db: Session, spec: FactorSpec, actor: str) -> EmissionFactor:
    """Insert a factor. Version 1 starts a new key; version N+1 supersedes version N.
    Does not commit."""
    prev = latest_version(db, spec.key)
    if prev is None and spec.version != 1:
        raise FactorSpecError(f"{spec.key}: first version must be 1")
    if prev is not None:
        if spec.version != prev.version + 1:
            raise FactorSpecError(f"{spec.key}: next version must be {prev.version + 1}")
        if prev.org_id != spec.org_id:
            raise FactorSpecError(f"{spec.key}: belongs to a different owner")

    factor = build_factor(spec, created_by=actor)
    db.add(factor)
    db.flush()
    if prev is not None:
        before = audit.snapshot(prev)
        prev.superseded_by = factor.id
        audit.record(
            db, actor=actor, action="supersede", entity="emission_factor", entity_id=prev.id,
            org_id=prev.org_id, before=before, after=audit.snapshot(prev),
        )
    audit.record(
        db, actor=actor, action="create", entity="emission_factor", entity_id=factor.id,
        org_id=factor.org_id, after=audit.snapshot(factor),
    )
    return factor


def spec_from_seed_row(row: dict) -> FactorSpec:
    try:
        return FactorSpec(
            key=row["key"],
            version=int(row["version"]),
            utility_type=row["utility_type"],
            region=row["region"],
            per_unit=row["per_unit"],
            published=[
                PublishedComponent(p["gas"], Decimal(str(p["value"])), p["mass_unit"])
                for p in row["published"]
            ],
            source_name=row["source_name"],
            source_url=row["source_url"],
            publication_year=int(row["publication_year"]),
            valid_from=row["valid_from"],
            valid_to=row.get("valid_to"),
            gwp_set=row.get("gwp_set"),
            notes=row.get("notes") or "",
        )
    except KeyError as e:
        raise FactorSpecError(f"Seed row {row.get('key', '?')} is missing field {e}") from None
