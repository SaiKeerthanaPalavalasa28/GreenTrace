from fastapi import APIRouter
from sqlalchemy import select

from app.deps import AdminUser, DbSession
from app.models import AuditLog
from app.schemas import AuditOut

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=list[AuditOut])
def list_audit(
    admin: AdminUser,
    db: DbSession,
    entity: str | None = None,
    entity_id: str | None = None,
    limit: int = 200,
):
    q = select(AuditLog).where(AuditLog.org_id == admin.org_id)
    if entity:
        q = q.where(AuditLog.entity == entity)
    if entity_id:
        q = q.where(AuditLog.entity_id == entity_id)
    return db.scalars(q.order_by(AuditLog.timestamp.desc()).limit(min(limit, 1000))).all()
