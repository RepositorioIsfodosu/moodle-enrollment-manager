from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_permission
from app.core.config import get_settings
from app.db.session import get_session
from app.models import (
    ConnectionGrant,
    CsvImport,
    CsvOperation,
    MoodleConnection,
    RoleApproval,
    User,
    ValidationRecord,
    ValidationRun,
)
from app.schemas.csv import (
    ApprovalCreate,
    ApprovalView,
    GrantCreate,
    Page,
    ValidationCreate,
    ValidationView,
)
from app.services.audit import audit
from app.services.auth import roles_for
from app.services.import_access import connection_access, is_admin, own_resource
from app.services.imports import record_view

router = APIRouter(tags=["validations"])
writer = require_permission("imports:write")
reader = require_permission("jobs:read")
manager = require_permission("connections:manage")


def enqueue_validation(run_id):
    # PostgreSQL remains authoritative if the broker is temporarily unavailable.
    from app.tasks.validations import enqueue

    enqueue(run_id)


def run_view(db, run):
    counts = dict(
        db.execute(
            select(ValidationRecord.status, func.count())
            .where(ValidationRecord.run_id == run.id)
            .group_by(ValidationRecord.status)
        ).all()
    )
    total = sum(counts.values())
    checked = db.scalar(
        select(func.count())
        .select_from(ValidationRecord)
        .where(ValidationRecord.run_id == run.id, ValidationRecord.checked_at.is_not(None))
    )
    return ValidationView(
        id=run.id,
        connection_id=run.connection_id,
        configuration_version=run.configuration_version,
        state=run.state,
        error_code=run.error_code,
        created_at=run.created_at,
        finished_at=run.finished_at,
        total=total,
        checked=checked,
        counts=counts,
        progress_percent=round(100 * checked / total, 2) if total else 0,
    )


def accessible_run(db, actor, run_id, writing=False):
    run = db.get(ValidationRun, run_id)
    if not run:
        raise HTTPException(404, "Validación no encontrada")
    connection_access(db, actor.id, run.connection_id, writing=writing)
    if writing or not ({"supervisor", "consulta"} & set(roles_for(db, actor.id))):
        own_resource(db, actor, run.owner_id)
    return run


@router.get("/validations/connections", response_model=Page)
def available_connections(actor: User = Depends(reader), db: Session = Depends(get_session)):
    query = (
        select(MoodleConnection)
        .where(MoodleConnection.active.is_(True))
        .order_by(MoodleConnection.name, MoodleConnection.id)
    )
    if not is_admin(db, actor.id):
        query = query.join(ConnectionGrant).where(ConnectionGrant.user_id == actor.id)
    rows = list(db.scalars(query))
    return Page(
        items=[
            {
                "id": row.id,
                "name": row.name,
                "base_url": row.base_url,
                "status": row.status,
                "last_verified_at": row.last_verified_at,
            }
            for row in rows
        ],
        total=len(rows),
        offset=0,
        limit=len(rows),
    )


@router.post("/validations", response_model=ValidationView, status_code=202)
def create(
    data: ValidationCreate, actor: User = Depends(writer), db: Session = Depends(get_session)
):
    connection = connection_access(db, actor.id, data.connection_id)
    imports = []
    total = 0
    for import_id in data.import_ids:
        row = db.get(CsvImport, import_id)
        if not row:
            raise HTTPException(404, "Importación no encontrada")
        own_resource(db, actor, row.owner_id)
        total += row.operation_count
        imports.append(row)
    if total > get_settings().csv_max_operations:
        raise HTTPException(422, "Límite total de operaciones por validación excedido")
    run = ValidationRun(
        owner_id=actor.id,
        connection_id=connection.id,
        configuration_version=connection.configuration_version,
        import_ids=[str(x.id) for x in imports],
    )
    db.add(run)
    db.flush()
    seen, sequence = set(), 0
    for entry in imports:
        for op in db.scalars(
            select(CsvOperation)
            .where(CsvOperation.import_id == entry.id)
            .order_by(CsvOperation.source_row, CsvOperation.slot)
        ):
            status, code = op.local_status, op.error_code
            if status == "pending" and op.operation_key in seen:
                status, code = "duplicate", "cross_file_duplicate"
            if status == "pending":
                seen.add(op.operation_key)
            db.add(
                ValidationRecord(
                    run_id=run.id,
                    operation_id=op.id,
                    sequence=sequence,
                    status=status,
                    error_code=code,
                    checked_at=datetime.now(UTC) if status != "pending" else None,
                )
            )
            sequence += 1
    audit(db, "validation.created", actor.id, run.id, operations=total, files=len(imports))
    db.flush()
    result = run_view(db, run)
    db.commit()
    enqueue_validation(run.id)
    return result


@router.get("/validations", response_model=Page)
def listing(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    actor: User = Depends(reader),
    db: Session = Depends(get_session),
):
    query = select(ValidationRun)
    if not is_admin(db, actor.id):
        query = query.join(
            ConnectionGrant, ConnectionGrant.connection_id == ValidationRun.connection_id
        ).where(ConnectionGrant.user_id == actor.id)
        if not ({"supervisor", "consulta"} & set(roles_for(db, actor.id))):
            query = query.where(ValidationRun.owner_id == actor.id)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.order_by(ValidationRun.created_at.desc(), ValidationRun.id)
        .offset(offset)
        .limit(limit)
    )
    return Page(
        items=[run_view(db, row).model_dump() for row in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/validations/{run_id}", response_model=ValidationView)
def detail(run_id: UUID, actor: User = Depends(reader), db: Session = Depends(get_session)):
    return run_view(db, accessible_run(db, actor, run_id))


@router.get("/validations/{run_id}/records", response_model=Page)
def records(
    run_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    status: Literal["pending", "valid", "invalid", "duplicate", "existing"] | None = None,
    error_code: str | None = Query(None, max_length=80),
    actor: User = Depends(reader),
    db: Session = Depends(get_session),
):
    accessible_run(db, actor, run_id)
    query = (
        select(ValidationRecord, CsvOperation)
        .join(CsvOperation)
        .where(ValidationRecord.run_id == run_id)
    )
    if status:
        query = query.where(ValidationRecord.status == status)
    if error_code:
        query = query.where(ValidationRecord.error_code == error_code)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(query.order_by(ValidationRecord.sequence).offset(offset).limit(limit))
    return Page(
        items=[record_view(record, op) for record, op in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("/validations/{run_id}/cancel", response_model=ValidationView)
def cancel(run_id: UUID, actor: User = Depends(writer), db: Session = Depends(get_session)):
    accessible_run(db, actor, run_id, writing=True)
    run = db.scalar(select(ValidationRun).where(ValidationRun.id == run_id).with_for_update())
    if run.state not in ("queued", "running"):
        raise HTTPException(409, "La validación ya finalizó")
    run.state, run.finished_at = "cancelled", datetime.now(UTC)
    run.lease_owner = run.lease_until = None
    audit(db, "validation.cancelled", actor.id, run.id)
    result = run_view(db, run)
    db.commit()
    return result


@router.get("/moodle-connections/{connection_id}/grants", response_model=Page)
def grants(connection_id: UUID, actor: User = Depends(manager), db: Session = Depends(get_session)):
    if not db.get(MoodleConnection, connection_id):
        raise HTTPException(404, "Conexión no encontrada")
    rows = db.execute(
        select(User.id, User.email)
        .join(ConnectionGrant, ConnectionGrant.user_id == User.id)
        .where(ConnectionGrant.connection_id == connection_id)
        .order_by(User.email)
    )
    items = [{"user_id": user_id, "email": email} for user_id, email in rows]
    return Page(items=items, total=len(items), offset=0, limit=len(items))


@router.post("/moodle-connections/{connection_id}/grants", status_code=201)
def grant(
    connection_id: UUID,
    data: GrantCreate,
    actor: User = Depends(manager),
    db: Session = Depends(get_session),
):
    if not db.get(MoodleConnection, connection_id) or not db.get(User, data.user_id):
        raise HTTPException(404, "Conexión o usuario no encontrado")
    if not db.get(ConnectionGrant, (connection_id, data.user_id)):
        db.add(ConnectionGrant(connection_id=connection_id, user_id=data.user_id))
    audit(db, "moodle.access_granted", actor.id, connection_id, user_id=str(data.user_id))
    db.commit()
    return {"user_id": data.user_id, "connection_id": connection_id}


@router.delete("/moodle-connections/{connection_id}/grants/{user_id}", status_code=204)
def revoke(
    connection_id: UUID,
    user_id: UUID,
    actor: User = Depends(manager),
    db: Session = Depends(get_session),
):
    row = db.get(ConnectionGrant, (connection_id, user_id))
    if not row:
        raise HTTPException(404, "Autorización no encontrada")
    db.delete(row)
    audit(db, "moodle.access_revoked", actor.id, connection_id, user_id=str(user_id))
    db.commit()


@router.post(
    "/moodle-connections/{connection_id}/role-approvals",
    response_model=ApprovalView,
    status_code=201,
)
def approve(
    connection_id: UUID,
    data: ApprovalCreate,
    actor: User = Depends(manager),
    db: Session = Depends(get_session),
):
    connection = db.get(MoodleConnection, connection_id)
    if not connection:
        raise HTTPException(404, "Conexión no encontrada")
    if data.expires_at.tzinfo is None or not datetime.now(UTC) < data.expires_at <= datetime.now(
        UTC
    ) + timedelta(days=7):
        raise HTTPException(
            422, "La evidencia debe caducar en las próximas 168 horas e incluir zona horaria"
        )
    row = RoleApproval(
        connection_id=connection_id,
        approved_by=actor.id,
        configuration_version=connection.configuration_version,
        **data.model_dump(),
    )
    db.add(row)
    db.flush()
    audit(
        db,
        "moodle.role_approved",
        actor.id,
        row.id,
        connection_id=str(connection_id),
        course_id=data.course_id,
        role_id=data.role_id,
    )
    result = ApprovalView.model_validate(row)
    db.commit()
    return result


@router.get("/moodle-connections/{connection_id}/role-approvals", response_model=Page)
def approvals(
    connection_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    actor: User = Depends(manager),
    db: Session = Depends(get_session),
):
    query = select(RoleApproval).where(RoleApproval.connection_id == connection_id)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.order_by(RoleApproval.created_at.desc(), RoleApproval.id).offset(offset).limit(limit)
    )
    return Page(
        items=[ApprovalView.model_validate(row).model_dump() for row in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.delete("/role-approvals/{approval_id}", status_code=204)
def remove_approval(
    approval_id: UUID, actor: User = Depends(manager), db: Session = Depends(get_session)
):
    row = db.get(RoleApproval, approval_id)
    if not row:
        raise HTTPException(404, "Evidencia no encontrada")
    row.active = False
    audit(db, "moodle.role_approval_revoked", actor.id, row.id)
    db.commit()
