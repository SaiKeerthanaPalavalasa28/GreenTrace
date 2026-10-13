import uuid
from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.calc.service import recalculate
from app.calc.factor_derivation import FactorDerivationError, PublishedComponent
from app.deps import AdminUser, CurrentUser, DbSession
from app.factor_service import FactorSpec, FactorSpecError, add_factor, gwp_sets, latest_version
from app.models import EmissionFactor
from app.schemas import FactorCreateIn, FactorOut, FactorVersionIn

router = APIRouter(prefix="/factors", tags=["emission factors"])


def _visible(org_id: uuid.UUID):
    """Global (seeded) factors plus this org's own."""
    return or_(EmissionFactor.org_id.is_(None), EmissionFactor.org_id == org_id)


def _get_visible(db: Session, org_id: uuid.UUID, factor_id: uuid.UUID) -> EmissionFactor:
    f = db.get(EmissionFactor, factor_id)
    if f is None or (f.org_id is not None and f.org_id != org_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Emission factor not found")
    return f


def _components(published) -> list[PublishedComponent]:
    return [PublishedComponent(p.gas, p.value, p.mass_unit) for p in published]


@router.get("", response_model=list[FactorOut])
def list_factors(
    user: CurrentUser,
    db: DbSession,
    utility_type: str | None = None,
    region: str | None = None,
    include_superseded: bool = False,
):
    q = select(EmissionFactor).where(_visible(user.org_id))
    if utility_type:
        q = q.where(EmissionFactor.utility_type == utility_type)
    if region:
        q = q.where(EmissionFactor.region == region)
    if not include_superseded:
        q = q.where(EmissionFactor.superseded_by.is_(None))
    q = q.order_by(EmissionFactor.region, EmissionFactor.utility_type,
                   EmissionFactor.valid_from, EmissionFactor.factor_key)
    return db.scalars(q).all()


@router.get("/regions", response_model=list[str])
def list_regions(user: CurrentUser, db: DbSession):
    return sorted(db.scalars(select(EmissionFactor.region).where(_visible(user.org_id)).distinct()))


@router.get("/gwp-sets")
def list_gwp_sets(user: CurrentUser):
    return {
        name: {"source_name": s["source_name"], "source_url": s["source_url"],
               "values": {g: str(v) for g, v in s["values"].items()}}
        for name, s in gwp_sets().items()
    }


@router.get("/{factor_id}", response_model=FactorOut)
def get_factor(factor_id: uuid.UUID, user: CurrentUser, db: DbSession):
    return _get_visible(db, user.org_id, factor_id)


@router.get("/{factor_id}/history", response_model=list[FactorOut])
def factor_history(factor_id: uuid.UUID, user: CurrentUser, db: DbSession):
    f = _get_visible(db, user.org_id, factor_id)
    return db.scalars(
        select(EmissionFactor).where(EmissionFactor.factor_key == f.factor_key)
        .order_by(EmissionFactor.version.desc())
    ).all()


@router.post("", response_model=FactorOut, status_code=status.HTTP_201_CREATED)
def create_factor(body: FactorCreateIn, admin: AdminUser, db: DbSession):
    if latest_version(db, body.factor_key) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "factor_key already exists; add a new version to it instead")
    spec = FactorSpec(
        key=body.factor_key, version=1, utility_type=body.utility_type.value, region=body.region,
        per_unit=body.per_unit, published=_components(body.published), gwp_set=body.gwp_set,
        source_name=body.source_name, source_url=body.source_url,
        publication_year=body.publication_year, valid_from=body.valid_from,
        valid_to=body.valid_to, notes=body.notes, org_id=admin.org_id,
    )
    try:
        factor = add_factor(db, spec, actor=str(admin.id))
    except (FactorSpecError, FactorDerivationError) as e:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    # An org factor can take precedence over a global one, or cover a period that had none.
    recalculate(db, actor=str(admin.id), reason=f"factor {factor.factor_key} v1 added",
                org_id=admin.org_id, utility_type=factor.utility_type)
    db.commit()
    return factor


@router.post("/{factor_id}/versions", response_model=FactorOut, status_code=status.HTTP_201_CREATED)
def create_version(factor_id: uuid.UUID, body: FactorVersionIn, admin: AdminUser, db: DbSession):
    """Supersede a factor with a corrected version. The old row is kept for audit."""
    f = _get_visible(db, admin.org_id, factor_id)
    if f.org_id is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Global factors are maintained in seed/emission_factors.yaml. "
            "To override one for your organization, create an org-specific factor.",
        )
    latest = latest_version(db, f.factor_key)
    if latest.id != f.id:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Version {f.version} is superseded; create new versions from the latest (v{latest.version})")

    published = (
        _components(body.published) if body.published is not None
        else [PublishedComponent(v["gas"], v["value"], v["mass_unit"]) for v in _published_decimals(f)]
    )
    set_fields = body.model_fields_set
    spec = FactorSpec(
        key=f.factor_key, version=f.version + 1, utility_type=f.utility_type, region=f.region,
        per_unit=body.per_unit or f.unit,
        published=published,
        gwp_set=body.gwp_set if "gwp_set" in set_fields else f.published_json.get("gwp_set"),
        source_name=body.source_name or f.source_name,
        source_url=body.source_url or f.source_url,
        publication_year=body.publication_year or f.publication_year,
        valid_from=body.valid_from or f.valid_from,
        valid_to=body.valid_to if "valid_to" in set_fields else f.valid_to,
        notes=(body.notes if body.notes is not None else f.notes) + f"\nv{f.version + 1}: {body.reason}",
        org_id=f.org_id,
    )
    try:
        factor = add_factor(db, spec, actor=str(admin.id))
    except (FactorSpecError, FactorDerivationError) as e:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    recalculate(db, actor=str(admin.id), reason=f"factor {factor.factor_key} v{factor.version} supersedes v{f.version}",
                org_id=admin.org_id, utility_type=factor.utility_type)
    db.commit()
    return factor


def _published_decimals(f: EmissionFactor) -> list[dict]:
    return [{**v, "value": Decimal(v["value"])} for v in f.published_json["values"]]
