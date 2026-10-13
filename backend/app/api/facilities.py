import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit
from app.deps import AdminUser, CurrentUser, DbSession
from app.models import EmissionFactor, Facility
from app.schemas import FacilityIn, FacilityOut, FacilityPatch

router = APIRouter(prefix="/facilities", tags=["facilities"])


def known_regions(db: Session, org_id: uuid.UUID) -> set[str]:
    return set(
        db.scalars(
            select(EmissionFactor.region)
            .where(or_(EmissionFactor.org_id.is_(None), EmissionFactor.org_id == org_id))
            .distinct()
        )
    )


def _check_region(db: Session, org_id: uuid.UUID, region: str) -> None:
    # A typo here would make every bill for the facility fail factor lookup, so reject it early.
    regions = known_regions(db, org_id)
    if region not in regions:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"No emission factors exist for region {region!r}. Known regions: {', '.join(sorted(regions))}",
        )


def get_org_facility(db: Session, org_id: uuid.UUID, facility_id: uuid.UUID) -> Facility:
    facility = db.get(Facility, facility_id)
    if facility is None or facility.org_id != org_id:  # 404 either way: don't leak other orgs' ids
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Facility not found")
    return facility


@router.get("", response_model=list[FacilityOut])
def list_facilities(user: CurrentUser, db: DbSession):
    return db.scalars(select(Facility).where(Facility.org_id == user.org_id).order_by(Facility.name)).all()


@router.post("", response_model=FacilityOut, status_code=status.HTTP_201_CREATED)
def create_facility(body: FacilityIn, admin: AdminUser, db: DbSession):
    _check_region(db, admin.org_id, body.region)
    facility = Facility(org_id=admin.org_id, **body.model_dump())
    db.add(facility)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A facility with this name already exists")
    audit.record(db, actor=str(admin.id), action="create", entity="facility",
                 entity_id=facility.id, org_id=admin.org_id, after=audit.snapshot(facility))
    db.commit()
    return facility


@router.patch("/{facility_id}", response_model=FacilityOut)
def update_facility(facility_id: uuid.UUID, body: FacilityPatch, admin: AdminUser, db: DbSession):
    facility = get_org_facility(db, admin.org_id, facility_id)
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if "region" in changes:
        _check_region(db, admin.org_id, changes["region"])
    before = audit.snapshot(facility)
    for k, v in changes.items():
        setattr(facility, k, v)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A facility with this name already exists")
    audit.record(db, actor=str(admin.id), action="update", entity="facility",
                 entity_id=facility.id, org_id=admin.org_id, before=before, after=audit.snapshot(facility))
    db.commit()
    return facility
