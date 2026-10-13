from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app import audit
from app.deps import CurrentUser, DbSession
from app.enums import Role
from app.models import Organization, User
from app.schemas import LoginIn, MeOut, OrganizationOut, RegisterIn, TokenOut, UserOut
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

# Compared against when the email is unknown, so response time doesn't reveal which emails exist.
_DUMMY_HASH = hash_password("timing-equalizer-not-a-real-password")


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(body: RegisterIn, db: DbSession):
    """Create an organization and its first (admin) user."""
    email = body.email.lower()
    if db.scalar(select(func.count()).select_from(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    org = Organization(
        name=body.org_name,
        reporting_framework=body.reporting_framework.value,
        default_region=body.default_region,
        fiscal_year_start_month=body.fiscal_year_start_month,
    )
    db.add(org)
    db.flush()
    user = User(
        org_id=org.id,
        email=email,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        role=Role.admin.value,
    )
    db.add(user)
    db.flush()
    audit.record(db, actor=str(user.id), action="register", entity="organization",
                 entity_id=org.id, org_id=org.id, after=audit.snapshot(org))
    db.commit()
    return TokenOut(access_token=create_access_token(user.id, org.id))


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: DbSession):
    user = db.scalars(select(User).where(User.email == body.email.lower())).first()
    ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    return TokenOut(access_token=create_access_token(user.id, user.org_id))


@router.get("/me", response_model=MeOut)
def me(user: CurrentUser, db: DbSession):
    org = db.get(Organization, user.org_id)
    return MeOut(user=UserOut.model_validate(user), organization=OrganizationOut.model_validate(org))
