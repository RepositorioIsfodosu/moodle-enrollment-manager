from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_permission
from app.db.session import get_session
from app.models import AuditLog, User
from app.schemas.auth import AuditPage

router = APIRouter(tags=["audit"])
audit_reader = require_permission("audit:read")


@router.get("/audit-logs", response_model=AuditPage)
def logs(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    action: str | None = Query(None, max_length=100),
    actor_id: UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    actor: User = Depends(audit_reader),
    db: Session = Depends(get_session),
):
    if any(value is not None and value.tzinfo is None for value in (since, until)):
        raise HTTPException(422, "Las fechas deben incluir zona horaria")
    if since and until and since > until:
        raise HTTPException(422, "Período de fechas inválido")
    query = select(AuditLog)
    if action:
        query = query.where(AuditLog.action == action)
    if actor_id:
        query = query.where(AuditLog.actor_id == actor_id)
    if since:
        query = query.where(AuditLog.created_at >= since)
    if until:
        query = query.where(AuditLog.created_at <= until)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = list(
        db.scalars(
            query.order_by(AuditLog.created_at.desc(), AuditLog.id).offset(offset).limit(limit)
        )
    )
    return AuditPage(items=rows, total=total, offset=offset, limit=limit)
