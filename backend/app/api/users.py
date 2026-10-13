from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app import audit
from app.deps import AdminUser, DbSession
from app.models import User
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
