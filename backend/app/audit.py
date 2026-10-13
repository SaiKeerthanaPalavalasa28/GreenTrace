import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.models import AuditLog


def _jsonable(value: Any) -> Any:
    if isinstance(value, (uuid.UUID, Decimal)):
        return str(value)  # str keeps Decimal exact
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def snapshot(obj: Any) -> dict:
    """Column values of an ORM object as JSON-safe data, for before/after audit records."""
    return {c.key: _jsonable(getattr(obj, c.key)) for c in inspect(obj).mapper.column_attrs}


def record(
    db: Session,
    *,
    actor: str,
    action: str,
    entity: str,
    entity_id: Any,
    org_id: uuid.UUID | None,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    """Add an audit row to the current transaction; it commits (or rolls back) with the change."""
    db.add(
        AuditLog(
            org_id=org_id,
            actor=actor,
            action=action,
            entity=entity,
            entity_id=str(entity_id),
            before_json=_jsonable(before),
            after_json=_jsonable(after),
        )
    )
