"""Scoped read models for administrative UI; all aggregates come from PostgreSQL."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import current_user, require_permission
from app.core.config import get_settings
from app.db.session import get_session
from app.models import ConnectionGrant, CsvFile, EnrollmentJob, EnrollmentRecord, JobFile, User
from app.schemas.csv import Page
from app.services.auth import roles_for
from app.services.import_access import is_admin

router = APIRouter(tags=["overview"])
reader = require_permission("jobs:read")


def scoped_jobs(db, actor):
    query = select(EnrollmentJob.id)
    if not is_admin(db, actor.id):
        query = query.join(
            ConnectionGrant, ConnectionGrant.connection_id == EnrollmentJob.connection_id
        ).where(ConnectionGrant.user_id == actor.id)
        if not ({"supervisor", "consulta"} & set(roles_for(db, actor.id))):
            query = query.where(EnrollmentJob.owner_id == actor.id)
    return query


class SettingsView(BaseModel):
    timezone: str
    csv_max_bytes: int
    csv_max_rows: int
    csv_max_operations: int
    enrollment_writes_enabled: bool


@router.get("/settings", response_model=SettingsView)
def settings(actor: User = Depends(current_user)):
    value = get_settings()
    return SettingsView(**{field: getattr(value, field) for field in SettingsView.model_fields})


class DashboardView(BaseModel):
    imported_rows: int | None
    job_counts: dict[str, int]
    record_counts: dict[str, int]
    total_operations: int


@router.get("/dashboard", response_model=DashboardView)
def dashboard(
    connection_id: UUID | None = None,
    actor: User = Depends(reader),
    db: Session = Depends(get_session),
):
    ids = scoped_jobs(db, actor)
    if connection_id:
        ids = ids.where(EnrollmentJob.connection_id == connection_id)
    jobs = dict(
        db.execute(
            select(EnrollmentJob.state, func.count())
            .where(EnrollmentJob.id.in_(ids))
            .group_by(EnrollmentJob.state)
        ).all()
    )
    records = dict(
        db.execute(
            select(EnrollmentRecord.state, func.count())
            .where(EnrollmentRecord.job_id.in_(ids))
            .group_by(EnrollmentRecord.state)
        ).all()
    )
    rows = None
    if is_admin(db, actor.id) or "operador" in roles_for(db, actor.id):
        files = select(CsvFile.row_count)
        if not is_admin(db, actor.id):
            files = files.where(CsvFile.uploaded_by == actor.id)
        if connection_id:
            files = files.where(
                CsvFile.id.in_(select(JobFile.file_id).where(JobFile.job_id.in_(ids)))
            )
        rows = db.scalar(select(func.coalesce(func.sum(files.subquery().c.row_count), 0)))
    return DashboardView(
        imported_rows=rows,
        job_counts=jobs,
        record_counts=records,
        total_operations=sum(records.values()),
    )


@router.get("/enrollment-records", response_model=Page)
def errors(
    connection_id: UUID | None = None,
    state: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    actor: User = Depends(reader),
    db: Session = Depends(get_session),
):
    if state and state not in {"failed", "uncertain"}:
        raise HTTPException(422, "Estado de error no válido")
    ids = scoped_jobs(db, actor)
    if connection_id:
        ids = ids.where(EnrollmentJob.connection_id == connection_id)
    query = (
        select(EnrollmentRecord, EnrollmentJob.name)
        .join(EnrollmentJob)
        .where(
            EnrollmentRecord.job_id.in_(ids),
            EnrollmentRecord.state.in_([state] if state else ["failed", "uncertain"]),
        )
    )
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(
        query.order_by(EnrollmentRecord.created_at.desc(), EnrollmentRecord.id)
        .offset(offset)
        .limit(limit)
    )
    return Page(
        items=[
            {
                "id": r.id,
                "job_id": r.job_id,
                "job_name": name,
                "source_row": r.source_row,
                "user_identifier": r.user_identifier,
                "course_identifier": r.course_identifier,
                "state": r.state,
                "error_code": r.error_code,
            }
            for r, name in rows
        ],
        total=total,
        offset=offset,
        limit=limit,
    )
