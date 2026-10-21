"""Persist immutable, eligible validation results as inspectable job drafts.

Execution endpoints deliberately remain unavailable until the engine is verified.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_permission
from app.db.session import get_session
from app.models import (
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
from app.schemas.jobs import JobCreate, JobView
from app.services.audit import audit
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
        configuration=job.configuration,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        counts=counts,
        total=sum(counts.values()),
    )


def accessible_job(db, actor, job_id, *, lock=False):
    query = select(EnrollmentJob).where(EnrollmentJob.id == job_id)
    if lock:
        query = query.with_for_update()
    job = db.scalar(query)
    if not job:
        raise HTTPException(404, "Trabajo no encontrado")
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
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    actor: User = Depends(reader),
    db: Session = Depends(get_session),
):
    query = select(EnrollmentJob)
    if not is_admin(db, actor.id):
        query = query.join(
            ConnectionGrant, ConnectionGrant.connection_id == EnrollmentJob.connection_id
        ).where(EnrollmentJob.owner_id == actor.id, ConnectionGrant.user_id == actor.id)
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
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    actor: User = Depends(reader),
    db: Session = Depends(get_session),
):
    accessible_job(db, actor, job_id)
    query = select(EnrollmentRecord).where(EnrollmentRecord.job_id == job_id)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.order_by(EnrollmentRecord.created_at, EnrollmentRecord.id).offset(offset).limit(limit)
    )
    return Page(
        items=[
            {
                "id": row.id,
                "file_id": row.file_id,
                "source_row": row.source_row,
                "user_identifier": row.user_identifier,
                "course_identifier": row.course_identifier,
                "role_id": row.role_id,
                "state": row.state,
            }
            for row in rows
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("/enrollment-jobs/{job_id}/cancel", response_model=JobView)
def cancel(job_id: UUID, actor: User = Depends(writer), db: Session = Depends(get_session)):
    job = accessible_job(db, actor, job_id, lock=True)
    try:
        job.state = transition(job.state, "cancelled")
    except ValueError as error:
        raise HTTPException(409, str(error)) from None
    job.finished_at = datetime.now(UTC)
    db.add(JobEvent(job_id=job.id, action="cancelled", safe_context={}))
    audit(db, "job.cancelled", actor_id=actor.id, entity_id=str(job.id))
    db.commit()
    return view(db, job)


@router.post("/enrollment-jobs/{job_id}/start", status_code=503)
def start(job_id: UUID, actor: User = Depends(writer), db: Session = Depends(get_session)):
    accessible_job(db, actor, job_id)
    raise HTTPException(503, "Motor en desarrollo; la ejecución de matrículas está deshabilitada")
