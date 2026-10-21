"""Authorized report projections; never include credentials or technical JSON contexts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import DateTime, cast, func, select

from app.api.v1.endpoints.overview import scoped_jobs
from app.core.permissions import permissions_for
from app.models import (
    RECORD_STATES,
    AuditLog,
    CsvFile,
    CsvOperation,
    EnrollmentAttempt,
    EnrollmentJob,
    EnrollmentRecord,
    MoodleConnection,
    ValidationRecord,
)
from app.services.auth import roles_for

KINDS = Literal["general", "successful", "errors", "pending", "audit", "course", "campus"]
TITLES = {
    "general": "Reporte general",
    "successful": "Matrículas confirmadas",
    "errors": "Errores e incertidumbre",
    "pending": "Operaciones pendientes",
    "audit": "Auditoría administrativa",
    "course": "Resultados por curso",
    "campus": "Resultados por recinto",
}


class Filters(BaseModel):
    kind: KINDS = "general"
    since: datetime | None = None
    until: datetime | None = None
    connection_id: UUID | None = None
    job_id: UUID | None = None
    file_id: UUID | None = None
    user: str | None = Field(None, max_length=300)
    course: str | None = Field(None, max_length=300)
    state: str | None = Field(None, max_length=32)
    error_code: str | None = Field(None, max_length=100)
    campus: str | None = Field(None, max_length=200)
    academic_period: str | None = Field(None, max_length=200)
    actor_id: UUID | None = None
    action: str | None = Field(None, max_length=100)

    @model_validator(mode="after")
    def validate_filters(self):
        if any(d and d.tzinfo is None for d in (self.since, self.until)):
            raise ValueError("Las fechas deben incluir zona horaria")
        if self.since and self.until and self.since > self.until:
            raise ValueError("Período de fechas inválido")
        if self.state and self.state not in RECORD_STATES:
            raise ValueError("Estado no válido")
        audit_only = self.actor_id is not None or self.action is not None
        record_only = any(
            getattr(self, k) is not None
            for k in (
                "connection_id",
                "job_id",
                "file_id",
                "user",
                "course",
                "state",
                "error_code",
                "campus",
                "academic_period",
            )
        )
        if (self.kind == "audit" and record_only) or (self.kind != "audit" and audit_only):
            raise ValueError("Filtros incompatibles con el tipo de reporte")
        return self


def report_query(db, actor, filters):
    f = filters
    if f.kind == "audit":
        if "audit:read" not in permissions_for(roles_for(db, actor.id)):
            raise HTTPException(403, "Permisos insuficientes para auditoría")
        q = select(
            AuditLog.id.label("id"),
            AuditLog.created_at.label("fecha_utc"),
            AuditLog.actor_id.label("responsable"),
            AuditLog.action.label("accion"),
            AuditLog.entity_id.label("entidad"),
        )
        for attr in ("actor_id", "action"):
            if getattr(f, attr) is not None:
                q = q.where(getattr(AuditLog, attr) == getattr(f, attr))
        date = AuditLog.created_at
    else:
        metadata = CsvOperation.payload["metadata"]
        campus = metadata["campus"].as_string()
        period = metadata["academic_period"].as_string()
        observed = (
            select(
                func.max(
                    cast(
                        EnrollmentAttempt.safe_context["observed_at"].as_string(),
                        DateTime(timezone=True),
                    )
                )
            )
            .where(
                EnrollmentAttempt.record_id == EnrollmentRecord.id,
                EnrollmentAttempt.outcome == "confirmed_by_observation",
            )
            .correlate(EnrollmentRecord)
            .scalar_subquery()
        )
        q = (
            select(
                EnrollmentRecord.id.label("id"),
                EnrollmentJob.name.label("proceso"),
                EnrollmentJob.id.label("proceso_id"),
                MoodleConnection.name.label("moodle"),
                MoodleConnection.id.label("moodle_id"),
                CsvFile.original_name.label("archivo"),
                EnrollmentRecord.source_row.label("fila"),
                EnrollmentRecord.user_identifier.label("usuario"),
                EnrollmentRecord.course_identifier.label("curso"),
                EnrollmentRecord.role_id.label("rol"),
                EnrollmentRecord.state.label("estado"),
                EnrollmentRecord.error_code.label("error"),
                campus.label("recinto"),
                period.label("periodo_academico"),
                EnrollmentRecord.created_at.label("fecha_utc"),
                observed.label("confirmacion_utc"),
            )
            .join(EnrollmentJob, EnrollmentRecord.job_id == EnrollmentJob.id)
            .join(MoodleConnection, EnrollmentJob.connection_id == MoodleConnection.id)
            .join(CsvFile, EnrollmentRecord.file_id == CsvFile.id)
            .outerjoin(
                ValidationRecord, EnrollmentRecord.validation_record_id == ValidationRecord.id
            )
            .outerjoin(CsvOperation, ValidationRecord.operation_id == CsvOperation.id)
            .where(EnrollmentRecord.job_id.in_(scoped_jobs(db, actor)))
        )
        for value, col in [
            (f.connection_id, EnrollmentJob.connection_id),
            (f.job_id, EnrollmentRecord.job_id),
            (f.file_id, EnrollmentRecord.file_id),
            (f.user, EnrollmentRecord.user_identifier),
            (f.course, EnrollmentRecord.course_identifier),
            (f.state, EnrollmentRecord.state),
            (f.error_code, EnrollmentRecord.error_code),
            (f.campus, campus),
            (f.academic_period, period),
        ]:
            if value is not None:
                q = q.where(col == value)
        states = {
            "successful": ["confirmed"],
            "errors": ["failed", "uncertain"],
            "pending": ["pending", "reserved"],
        }.get(f.kind)
        if states:
            q = q.where(EnrollmentRecord.state.in_(states))
        date = EnrollmentRecord.created_at
    if f.since:
        q = q.where(date >= f.since)
    if f.until:
        q = q.where(date <= f.until)
    return q


def projection(query, kind):
    base = query.subquery()
    if kind not in {"course", "campus"}:
        return select(base)
    key = base.c.curso if kind == "course" else base.c.recinto
    if kind == "course":
        return select(
            base.c.moodle_id,
            base.c.moodle,
            key.label("curso"),
            base.c.estado,
            func.count().label("operaciones"),
        ).group_by(base.c.moodle_id, base.c.moodle, key, base.c.estado)
    return select(
        key.label("curso" if kind == "course" else "recinto"),
        base.c.estado.label("estado"),
        func.count().label("operaciones"),
    ).group_by(key, base.c.estado)


def summary(db, query, kind):
    base = query.subquery()
    total = db.scalar(select(func.count()).select_from(base))
    counts = (
        {}
        if kind == "audit"
        else dict(db.execute(select(base.c.estado, func.count()).group_by(base.c.estado)).all())
    )
    return {
        "total_operations": total,
        "counts": counts,
        "percentages": {s: round(n * 100 / total, 2) for s, n in counts.items()} if total else {},
    }
