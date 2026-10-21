"""Persisted jobs, explicit execution authorization and cooperative control."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.dependencies import require_permission
from app.core.config import get_settings
from app.db.session import get_session
from app.models import (
    JOB_STATES,
    RECORD_STATES,
    ConnectionGrant,
    CsvImport,
    CsvOperation,
    EnrollmentJob,
    EnrollmentRecord,
    JobEvent,
    JobFile,
    User,
    ValidationRecord,
)
from app.schemas.csv import Page
from app.schemas.jobs import JobCreate, JobView, RetrySelection
from app.services.audit import audit
from app.services.auth import roles_for
from app.services.import_access import connection_access, is_admin, own_resource
from app.services.job_states import transition

from .validations import accessible_run

router = APIRouter(tags=["enrollment-jobs"])
writer = require_permission("jobs:write")
reader = require_permission("jobs:read")


def view(db, job):
    counts = dict(
        db.execute(
            select(EnrollmentRecord.state, func.count())
            .where(EnrollmentRecord.job_id == job.id)
            .group_by(EnrollmentRecord.state)
        ).all()
    )
    return JobView(
        id=job.id,
        name=job.name,
        connection_id=job.connection_id,
        state=job.state,
        configuration={
            **job.configuration,
            "execution_available": get_settings().enrollment_writes_enabled,
        },
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        counts=counts,
        total=sum(counts.values()),
        progress_percent=round(
            100
            * sum(v for k, v in counts.items() if k not in {"pending", "reserved"})
            / sum(counts.values()),
            2,
        )
        if counts
        else 0,
        runtime=job.runtime,
    )


def accessible_job(db, actor, job_id, *, lock=False):
    query = select(EnrollmentJob).where(EnrollmentJob.id == job_id)
    if lock:
        query = query.with_for_update()
    job = db.scalar(query)
    if not job:
        raise HTTPException(404, "Trabajo no encontrado")
    if lock or not ({"supervisor", "consulta"} & set(roles_for(db, actor.id))):
        own_resource(db, actor, job.owner_id)
    connection_access(db, actor.id, job.connection_id, writing=False)
    return job


@router.post("/enrollment-jobs", response_model=JobView, status_code=201)
def create(data: JobCreate, actor: User = Depends(writer), db: Session = Depends(get_session)):
    run = accessible_run(db, actor, data.validation_id, writing=True)
    connection = connection_access(db, actor.id, run.connection_id)
    if run.state != "completed" or run.configuration_version != connection.configuration_version:
        raise HTTPException(
            409, "Se requiere una validación completada de la configuración vigente"
        )
    # Incomplete validation must never silently discard invalid/pending operations.
    rejected = db.scalar(
        select(func.count())
        .select_from(ValidationRecord)
        .where(
            ValidationRecord.run_id == run.id,
            ValidationRecord.status.in_(["pending", "invalid"]),
        )
    )
    if rejected:
        raise HTTPException(409, "La validación contiene operaciones pendientes o inválidas")
    job = EnrollmentJob(
        name=data.name.strip(),
        connection_id=run.connection_id,
        owner_id=actor.id,
        state="draft",
        configuration={
            **data.configuration.model_dump(),
            "validation_id": str(run.id),
            "connection_version": run.configuration_version,
            "execution_available": False,
        },
    )
    db.add(job)
    db.flush()
    rows = db.execute(
        select(ValidationRecord, CsvOperation, CsvImport)
        .join(CsvOperation, ValidationRecord.operation_id == CsvOperation.id)
        .join(CsvImport, CsvOperation.import_id == CsvImport.id)
        .where(
            ValidationRecord.run_id == run.id, ValidationRecord.status.in_(["valid", "existing"])
        )
        .order_by(ValidationRecord.sequence)
    )
    files = set()
    total = 0
    for validated, operation, imported in rows:
        if (
            not validated.resolved_key
            or not validated.resolved_user_id
            or not validated.resolved_course_id
            or not operation.payload.get("role_id")
        ):
            raise HTTPException(
                409, "La validación no conserva identificadores resueltos completos"
            )
        db.add(
            EnrollmentRecord(
                validation_record_id=validated.id,
                job_id=job.id,
                file_id=imported.file_id,
                source_row=operation.source_row,
                operation_key=validated.resolved_key,
                user_identifier=operation.payload["user_identifier"],
                course_identifier=operation.payload["course_identifier"],
                role_id=operation.payload["role_id"],
                resolved_user_id=validated.resolved_user_id,
                resolved_course_id=validated.resolved_course_id,
                state="pending",  # Validation observations are not execution confirmations.
            )
        )
        files.add(imported.file_id)
        total += 1
    if not total:
        raise HTTPException(409, "No hay operaciones elegibles")
    for file_id in files:
        db.add(JobFile(job_id=job.id, file_id=file_id))
    db.add(
        JobEvent(
            job_id=job.id,
            action="draft_created",
            safe_context={
                "validation_id": str(run.id),
                "operations": total,
            },
        )
    )
    audit(db, "job.created", actor_id=actor.id, entity_id=str(job.id), operations=total)
    db.commit()
    return view(db, job)


@router.get("/enrollment-jobs", response_model=Page)
def listing(
    connection_id: UUID | None = None,
    state: str | None = None,
    terminal: bool | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    actor: User = Depends(reader),
    db: Session = Depends(get_session),
):
    if state and state not in JOB_STATES:
        raise HTTPException(422, "Estado no válido")
    query = select(EnrollmentJob)
    if terminal is not None:
        terminal_states = ["completed", "completed_with_errors", "cancelled", "failed"]
        query = query.where(
            EnrollmentJob.state.in_(terminal_states)
            if terminal
            else EnrollmentJob.state.not_in(terminal_states)
        )
    if connection_id:
        query = query.where(EnrollmentJob.connection_id == connection_id)
    if state:
        query = query.where(EnrollmentJob.state == state)
    if not is_admin(db, actor.id):
        query = query.join(
            ConnectionGrant, ConnectionGrant.connection_id == EnrollmentJob.connection_id
        ).where(ConnectionGrant.user_id == actor.id)
        if not ({"supervisor", "consulta"} & set(roles_for(db, actor.id))):
            query = query.where(EnrollmentJob.owner_id == actor.id)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.order_by(EnrollmentJob.created_at.desc(), EnrollmentJob.id)
        .offset(offset)
        .limit(limit)
    )
    return Page(
        items=[view(db, job).model_dump() for job in rows], total=total, offset=offset, limit=limit
    )


@router.get("/enrollment-jobs/{job_id}", response_model=JobView)
def detail(job_id: UUID, actor: User = Depends(reader), db: Session = Depends(get_session)):
    return view(db, accessible_job(db, actor, job_id))


@router.get("/enrollment-jobs/{job_id}/records", response_model=Page)
def records(
    job_id: UUID,
    state: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    actor: User = Depends(reader),
    db: Session = Depends(get_session),
):
    accessible_job(db, actor, job_id)
    if state and state not in RECORD_STATES:
        raise HTTPException(422, "Estado no válido")
    query = select(EnrollmentRecord).where(EnrollmentRecord.job_id == job_id)
    if state:
        query = query.where(EnrollmentRecord.state == state)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.order_by(EnrollmentRecord.created_at, EnrollmentRecord.id).offset(offset).limit(limit)
    )
    from app.services.enrollment_engine import TRANSIENT

    return Page(
        items=[
            {
                "retryable": row.state == "uncertain"
                or (row.state == "failed" and row.error_code in TRANSIENT),
                "id": row.id,
                "file_id": row.file_id,
                "source_row": row.source_row,
                "user_identifier": row.user_identifier,
                "course_identifier": row.course_identifier,
                "role_id": row.role_id,
                "state": row.state,
                "error_code": row.error_code,
                "retry_count": row.retry_count,
                "reconciliation_count": row.reconciliation_count,
            }
            for row in rows
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


def dispatch(job_id):
    from app.tasks.enrollments import enqueue

    enqueue(job_id)


def changed(db, job, actor, target):
    job.state = transition(job.state, target)
    db.add(JobEvent(job_id=job.id, action=target, safe_context={}))
    audit(db, "job." + target, actor_id=actor.id, entity_id=str(job.id))


@router.post("/enrollment-jobs/{job_id}/cancel", response_model=JobView)
def cancel(job_id: UUID, actor: User = Depends(writer), db: Session = Depends(get_session)):
    job = accessible_job(db, actor, job_id, lock=True)
    try:
        changed(
            db,
            job,
            actor,
            "cancelling" if job.state in {"running", "pausing", "validating"} else "cancelled",
        )
    except ValueError as error:
        raise HTTPException(409, str(error)) from None
    if job.state == "cancelling" and not job.lease_owner:
        changed(db, job, actor, "cancelled")
    if job.state == "cancelled":
        job.finished_at = datetime.now(UTC)
        db.execute(
            update(EnrollmentRecord)
            .where(
                EnrollmentRecord.job_id == job.id,
                EnrollmentRecord.state.in_(["pending", "reserved"]),
            )
            .values(state="skipped", lease_owner=None, lease_until=None)
        )
    db.commit()
    if job.state == "cancelling":
        dispatch(job.id)
    return view(db, job)


@router.post("/enrollment-jobs/{job_id}/start", response_model=JobView, status_code=202)
def start(job_id: UUID, actor: User = Depends(writer), db: Session = Depends(get_session)):
    return activate(db, actor, job_id, resume=False)


@router.post("/enrollment-jobs/{job_id}/resume", response_model=JobView, status_code=202)
def resume(job_id: UUID, actor: User = Depends(writer), db: Session = Depends(get_session)):
    return activate(db, actor, job_id, resume=True)


def activate(db, actor, job_id, *, resume):
    job = accessible_job(db, actor, job_id, lock=True)
    if not get_settings().enrollment_writes_enabled:
        raise HTTPException(503, "Las escrituras Moodle están deshabilitadas por configuración")
    connection = connection_access(db, actor.id, job.connection_id)
    if connection.configuration_version != job.configuration.get("connection_version"):
        raise HTTPException(409, "La configuración Moodle cambió; validar y crear otro trabajo")
    if resume and job.state != "paused" or not resume and job.state not in {"draft", "ready"}:
        raise HTTPException(409, "Acción no válida para el estado actual")
    if job.next_run_at and job.next_run_at > datetime.now(UTC):
        raise HTTPException(409, "El período de enfriamiento todavía no ha terminado")
    if job.state == "draft":
        changed(db, job, actor, "ready")
    changed(db, job, actor, "queued")
    db.commit()
    dispatch(job.id)
    return view(db, job)


@router.post("/enrollment-jobs/{job_id}/pause", response_model=JobView)
def pause(job_id: UUID, actor: User = Depends(writer), db: Session = Depends(get_session)):
    job = accessible_job(db, actor, job_id, lock=True)
    try:
        changed(db, job, actor, "pausing" if job.state == "running" else "paused")
    except ValueError as error:
        raise HTTPException(409, str(error)) from None
    if job.state == "pausing" and not job.lease_owner:
        changed(db, job, actor, "paused")
    job.next_run_at = None
    db.commit()
    if job.state == "pausing":
        dispatch(job.id)
    return view(db, job)


@router.get("/enrollment-jobs/{job_id}/attempts", response_model=Page)
def attempts(
    job_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    actor: User = Depends(reader),
    db: Session = Depends(get_session),
):
    from app.models import EnrollmentAttempt

    accessible_job(db, actor, job_id)
    query = (
        select(EnrollmentAttempt).join(EnrollmentRecord).where(EnrollmentRecord.job_id == job_id)
    )
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.order_by(EnrollmentAttempt.created_at, EnrollmentAttempt.id)
        .offset(offset)
        .limit(limit)
    )
    return Page(
        items=[
            {
                "id": r.id,
                "record_id": r.record_id,
                "number": r.number,
                "outcome": r.outcome,
                "error_code": r.error_code,
                "created_at": r.created_at,
                "context": r.safe_context,
            }
            for r in rows
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/enrollment-jobs/{job_id}/events", response_model=Page)
def events(
    job_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    actor: User = Depends(reader),
    db: Session = Depends(get_session),
):
    accessible_job(db, actor, job_id)
    query = select(JobEvent).where(JobEvent.job_id == job_id)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(JobEvent.created_at, JobEvent.id).offset(offset).limit(limit))
    return Page(
        items=[
            {"id": r.id, "action": r.action, "created_at": r.created_at, "context": r.safe_context}
            for r in rows
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("/enrollment-jobs/{job_id}/retry", response_model=JobView, status_code=201)
def retry(
    job_id: UUID,
    data: RetrySelection,
    actor: User = Depends(writer),
    db: Session = Depends(get_session),
):
    from app.services.enrollment_engine import TRANSIENT

    original = accessible_job(db, actor, job_id, lock=True)
    connection_access(db, actor.id, original.connection_id)
    if original.state not in {"completed_with_errors", "failed", "cancelled"}:
        raise HTTPException(409, "El trabajo debe estar terminado")
    rows = list(
        db.scalars(
            select(EnrollmentRecord).where(
                EnrollmentRecord.job_id == job_id, EnrollmentRecord.id.in_(data.record_ids)
            )
        )
    )
    if len(rows) != len(set(data.record_ids)) or any(
        r.state != "uncertain" and not (r.state == "failed" and r.error_code in TRANSIENT)
        for r in rows
    ):
        raise HTTPException(409, "Selección con errores permanentes o registros no elegibles")
    job = EnrollmentJob(
        name=original.name[:180] + " — reintento",
        connection_id=original.connection_id,
        owner_id=actor.id,
        state="draft",
        configuration=dict(original.configuration),
    )
    db.add(job)
    db.flush()
    files = set()
    for row in rows:
        db.add(
            EnrollmentRecord(
                job_id=job.id,
                file_id=row.file_id,
                source_row=row.source_row,
                operation_key=row.operation_key,
                user_identifier=row.user_identifier,
                course_identifier=row.course_identifier,
                role_id=row.role_id,
                resolved_user_id=row.resolved_user_id,
                resolved_course_id=row.resolved_course_id,
                validation_record_id=row.validation_record_id,
                reconciles_record_id=row.id if row.state == "uncertain" else None,
                state="uncertain" if row.state == "uncertain" else "pending",
            )
        )
        files.add(row.file_id)
    for file_id in files:
        db.add(JobFile(job_id=job.id, file_id=file_id))
    db.add(
        JobEvent(
            job_id=job.id,
            action="retry_created",
            safe_context={"original_job_id": str(original.id)},
        )
    )
    audit(
        db,
        "job.retry_created",
        actor_id=actor.id,
        entity_id=str(job.id),
        original_job_id=str(original.id),
    )
    db.commit()
    return view(db, job)
