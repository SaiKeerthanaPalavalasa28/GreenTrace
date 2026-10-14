import logging
import secrets

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app import audit
from app.config import get_settings
from app.deps import CurrentUser, DbSession
from app.mailer import MailError, credentials_email, mail_configured, send_mail
from app.enums import Role
from app.models import Organization, User
from app.schemas import (
    ChangePasswordIn, LoginIn, MeOut, OrganizationOut, RegisterIn, RegisterOrgIn, RegisterOrgOut, TokenOut, UserOut,
)
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger(__name__)

# No look-alike characters (0/O, 1/l/I) because people retype emailed passwords.
_PW_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"


def generate_password(length: int = 14) -> str:
    return "".join(secrets.choice(_PW_ALPHABET) for _ in range(length))


def email_credentials(user: User, org_name: str, password: str) -> None:
    subject, text, html = credentials_email(to=user.email, org_name=org_name, role=user.role, password=password)
    send_mail(user.email, subject, text, html)

# Compared against when the email is unknown, so response time doesn't reveal which emails exist.
_DUMMY_HASH = hash_password("timing-equalizer-not-a-real-password")


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(body: RegisterIn, db: DbSession):
    """Create an organization and its first (admin) user, without any email check. Disabled unless
    ALLOW_DIRECT_SIGNUP is set; real sign-ups go through /auth/register-org."""
    if not get_settings().allow_direct_signup:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
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


@router.post("/register-org", response_model=RegisterOrgOut, status_code=status.HTTP_201_CREATED)
def register_org(body: RegisterOrgIn, db: DbSession):
    """Sign an organization up. An admin, a manager and an auditor each get their own generated
    password, emailed to their own address; nobody chooses a password here, so the only way in is
    to receive the email. The admin's email is sent first and the sign-up is rolled back if it
    fails, so an organization can never exist without a working admin login."""
    if not mail_configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Email delivery is not configured on this server, so credentials cannot be sent.")
    people = [("admin", body.admin_email, body.admin_name), ("manager", body.manager_email, body.manager_name),
              ("auditor", body.auditor_email, body.auditor_name)]
    for _, em, _ in people:
        if db.scalar(select(func.count()).select_from(User).where(User.email == em.lower())):
            raise HTTPException(status.HTTP_409_CONFLICT, f"An account with {em} already exists")
    org = Organization(name=body.org_name, reporting_framework=body.reporting_framework.value,
                       default_region=body.default_region, fiscal_year_start_month=body.fiscal_year_start_month)
    db.add(org)
    db.flush()
    created: list[tuple[User, str]] = []
    for role, em, name in people:
        pw = generate_password()
        u = User(org_id=org.id, email=em.lower(), password_hash=hash_password(pw), full_name=name, role=role)
        db.add(u)
        created.append((u, pw))
    db.flush()
    audit.record(db, actor=str(created[0][0].id), action="register", entity="organization",
                 entity_id=org.id, org_id=org.id, after=audit.snapshot(org))

    admin, admin_pw = created[0]
    try:
        email_credentials(admin, org.name, admin_pw)
    except MailError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))
    db.commit()

    delivery = [{"role": "admin", "email": admin.email, "sent": True, "error": None}]
    for u, pw in created[1:]:
        try:
            email_credentials(u, org.name, pw)
            delivery.append({"role": u.role, "email": u.email, "sent": True, "error": None})
        except MailError as exc:
            delivery.append({"role": u.role, "email": u.email, "sent": False, "error": str(exc)})
    return RegisterOrgOut(organization=org.name, delivery=delivery)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(body: ChangePasswordIn, user: CurrentUser, db: DbSession):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    user.password_hash = hash_password(body.new_password)
    audit.record(db, actor=str(user.id), action="change_password", entity="user", entity_id=user.id, org_id=user.org_id)
    db.commit()


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
