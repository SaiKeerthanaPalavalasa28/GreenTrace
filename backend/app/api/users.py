import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app import audit
from app.deps import AdminUser, DbSession
from app.models import Organization, User
from app.api.auth import email_credentials, generate_password
from app.mailer import MailError
from app.schemas import UserCreateIn, UserOut
from app.security import hash_password

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(admin: AdminUser, db: DbSession):
    return db.scalars(select(User).where(User.org_id == admin.org_id).order_by(User.email)).all()


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreateIn, admin: AdminUser, db: DbSession):
    email = body.email.lower()
    if db.scalars(select(User).where(User.email == email)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    user = User(
        org_id=admin.org_id,
        email=email,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        role=body.role.value,
    )
    db.add(user)
    db.flush()
    after = audit.snapshot(user)
    after.pop("password_hash")
    audit.record(db, actor=str(admin.id), action="create", entity="user",
                 entity_id=user.id, org_id=admin.org_id, after=after)
    db.commit()
    return user


@router.post("/{user_id}/resend-credentials")
def resend_credentials(user_id: uuid.UUID, admin: AdminUser, db: DbSession):
    """Generate a new password for a teammate and email it to them (e.g. the first email bounced)."""
    user = db.get(User, user_id)
    if user is None or user.org_id != admin.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if user.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Use change password for your own account")
    pw = generate_password()
    old = user.password_hash
    user.password_hash = hash_password(pw)
    try:
        email_credentials(user, db.get(Organization, user.org_id).name, pw)
    except MailError as exc:
        user.password_hash = old
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))
    audit.record(db, actor=str(admin.id), action="resend_credentials", entity="user", entity_id=user.id, org_id=admin.org_id)
    db.commit()
    return {"sent_to": user.email}
