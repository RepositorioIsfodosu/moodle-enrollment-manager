import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Identity


class User(Identity, Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("email = lower(trim(email))", name="normalized_email"),)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Role(Identity, Base):
    __tablename__ = "roles"
    name: Mapped[str] = mapped_column(String(40), unique=True)


class UserRole(Base):
    __tablename__ = "user_roles"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id"), primary_key=True)


class MoodleConnection(Identity, Base):
    __tablename__ = "moodle_connections"
    __table_args__ = (
        CheckConstraint(
            "status IN ('unverified','verified','limited','error','disabled')", name="status"
        ),
    )
    name: Mapped[str] = mapped_column(String(200))
    base_url: Mapped[str] = mapped_column(Text)
    token_ciphertext: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    limits: Mapped[dict] = mapped_column(JSON, default=dict)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[str] = mapped_column(
        String(20), default="unverified", server_default="unverified"
    )
    configuration_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_probe_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(50))
    site_metadata: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    available_functions: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    latency_ms: Mapped[int | None] = mapped_column(Integer)


class ImportProfile(Identity, Base):
    __tablename__ = "csv_import_profiles"
    name: Mapped[str] = mapped_column(String(200))
    mapping: Mapped[dict] = mapped_column(JSON)


class CsvFile(Identity, Base):
    __tablename__ = "csv_files"
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    original_name: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str] = mapped_column(Text, unique=True)
    sha256: Mapped[str] = mapped_column(String(64))
    row_count: Mapped[int] = mapped_column(Integer, default=0)


JOB_STATES = (
    "draft",
    "validating",
    "ready",
    "queued",
    "running",
    "pausing",
    "paused",
    "completed",
    "completed_with_errors",
    "failed",
    "cancelling",
    "cancelled",
)
RECORD_STATES = (
    "pending",
    "valid",
    "invalid",
    "duplicate",
    "reserved",
    "confirmed",
    "existing",
    "failed",
    "uncertain",
    "skipped",
)


def state_check(states):
    return "state IN (" + ",".join("'" + s + "'" for s in states) + ")"


class EnrollmentJob(Identity, Base):
    __tablename__ = "enrollment_jobs"
    __table_args__ = (CheckConstraint(state_check(JOB_STATES), name="state"),)
    name: Mapped[str] = mapped_column(String(200))
    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("moodle_connections.id"))
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    state: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobFile(Base):
    __tablename__ = "job_files"
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("enrollment_jobs.id"), primary_key=True)
    file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("csv_files.id"), primary_key=True)


class EnrollmentRecord(Identity, Base):
    __tablename__ = "enrollment_records"
    __table_args__ = (
        UniqueConstraint("job_id", "operation_key"),
        CheckConstraint(state_check(RECORD_STATES), name="state"),
        Index("ix_records_claim", "job_id", "state", "lease_until"),
    )
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("enrollment_jobs.id"))
    file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("csv_files.id"))
    source_row: Mapped[int] = mapped_column(Integer)
    operation_key: Mapped[str] = mapped_column(String(64))
    user_identifier: Mapped[str] = mapped_column(Text)
    course_identifier: Mapped[str] = mapped_column(Text)
    role_id: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(32), default="pending")
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    resolved_user_id: Mapped[int | None] = mapped_column(Integer)
    resolved_course_id: Mapped[int | None] = mapped_column(Integer)


class EnrollmentAttempt(Identity, Base):
    __tablename__ = "enrollment_attempts"
    __table_args__ = (UniqueConstraint("record_id", "number"),)
    record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("enrollment_records.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(40))
    error_code: Mapped[str | None] = mapped_column(String(100))
    safe_context: Mapped[dict] = mapped_column(JSON, default=dict)


class JobEvent(Identity, Base):
    __tablename__ = "job_events"
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("enrollment_jobs.id"), index=True)
    action: Mapped[str] = mapped_column(String(100))
    safe_context: Mapped[dict] = mapped_column(JSON, default=dict)


class AuditLog(Identity, Base):
    __tablename__ = "audit_logs"
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(100), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(100))
    safe_context: Mapped[dict] = mapped_column(JSON, default=dict)


class SystemSetting(Base):
    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)


class AuthSession(Identity, Base):
    __tablename__ = "auth_sessions"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class MoodleConnectionCheck(Identity, Base):
    __tablename__ = "moodle_connection_checks"
    __table_args__ = (CheckConstraint("status IN ('verified','limited','error')", name="status"),)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("moodle_connections.id"), index=True
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20))
    error_code: Mapped[str | None] = mapped_column(String(50))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    available_functions: Mapped[list] = mapped_column(JSON)
