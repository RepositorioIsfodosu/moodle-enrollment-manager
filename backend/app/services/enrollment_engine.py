"""Durable, conservative executor. Ambiguous writes are reconciled, never blindly resent."""

import random
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_, select, text, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.token_vault import VaultError
from app.db import session as database
from app.integrations.moodle.client import MoodleError
from app.integrations.moodle.urls import UnsafeURL
from app.models import (
    CsvOperation,
    EnrollmentAttempt,
    EnrollmentJob,
    EnrollmentRecord,
    JobEvent,
    MoodleConnection,
    RoleApproval,
    SystemSetting,
    ValidationRecord,
    ValidationRun,
)
from app.schemas.jobs import BatchConfiguration
from app.schemas.moodle import Limits
from app.services.audit import audit
from app.services.csv_parser import digest
from app.services.import_access import connection_access
from app.services.validation_engine import Engine, Stopped, ValidationFailure

LEASE_SECONDS = 600
TRANSIENT = {
    "timeout",
    "transport_error",
    "remote_rate_limited",
    "http_error",
    "rate_limiter_unavailable",
}


def now():
    return datetime.now(UTC)


def event(db, job, action, **context):
    db.add(JobEvent(job_id=job.id, action=action, safe_context=context))
    audit(db, "job." + action, actor_id=job.owner_id, entity_id=str(job.id), **context)


def installation_result(db, reader, *, failed):
    key = "moodle:errors:" + digest(reader.connection.base_url)
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": int(digest(key)[:15], 16)})
    marker = db.get(SystemSetting, key, populate_existing=True)
    count = (marker.value.get("count", 0) if marker else 0) + 1 if failed else 0
    value = {"count": count, "at": now().isoformat()}
    if marker:
        marker.value = value
    else:
        db.add(SystemSetting(key=key, value=value))
    policies = [
        Limits.model_validate(c.limits)
        for c in db.scalars(
            select(MoodleConnection).where(
                MoodleConnection.base_url == reader.connection.base_url,
                MoodleConnection.active.is_(True),
            )
        )
    ]
    policies = policies or [reader.limits]
    if failed and count >= min(p.error_threshold for p in policies):
        return now() + timedelta(seconds=max(p.circuit_cooldown_seconds for p in policies))
    return None


class ExecutionReader(Engine):
    """Reuse verified resolution rules, with a fresh batch-local cache and job fencing."""

    def __init__(self, db, job, owner, client, pace):
        self.job_id, self.job_owner = job.id, owner
        self.inflight = False
        self.memory = {}
        self.options = BatchConfiguration.model_validate(
            {k: v for k, v in job.configuration.items() if k in BatchConfiguration.model_fields}
        )
        run = db.get(ValidationRun, UUID(job.configuration["validation_id"]))
        if not run:
            raise ValidationFailure("validation_unavailable")
        super().__init__(db, run, owner, client, pace)
        self.limits.timeout_seconds = min(self.limits.timeout_seconds, self.options.timeout_seconds)

    def guard(self, commit=True):
        self.db.expire_all()
        job = self.db.scalar(
            select(EnrollmentJob)
            .where(EnrollmentJob.id == self.job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        allowed = {"running", "pausing", "cancelling"} if self.inflight else {"running"}
        if (
            job.state not in allowed
            or job.lease_owner != self.job_owner
            or not self.inflight
            and now().hour not in self.options.allowed_hours_utc
        ):
            self.db.rollback()
            raise Stopped
        try:
            connection = connection_access(self.db, job.owner_id, job.connection_id)
        except HTTPException:
            raise ValidationFailure("access_revoked") from None
        if connection.configuration_version != job.configuration.get("connection_version"):
            raise ValidationFailure("configuration_changed")
        if not get_settings().enrollment_writes_enabled:
            raise ValidationFailure("writes_disabled")
        job.lease_until = now() + timedelta(seconds=LEASE_SECONDS)
        job.runtime = {**job.runtime, "worker_seen_at": now().isoformat()}
        if commit:
            self.db.commit()
        return job

    def cached(self, key):
        return self.memory.get(digest(key))

    def save(self, key, value):
        self.guard()
        if self.token in str(value):
            raise ValidationFailure("sensitive_response")
        self.memory[digest(key)] = value
        return value

    def approval(self, course_id, role_id, group_id):
        self.guard()
        row = self.db.scalar(
            select(RoleApproval)
            .where(
                RoleApproval.connection_id == self.connection.id,
                RoleApproval.configuration_version == self.connection.configuration_version,
                RoleApproval.course_id == course_id,
                RoleApproval.role_id == role_id,
                RoleApproval.active.is_(True),
                RoleApproval.expires_at > now(),
                RoleApproval.full_enrollment_visibility.is_(True),
            )
            .order_by(RoleApproval.created_at.desc())
            .limit(1)
        )
        if not row or (group_id and not row.groups_authorized):
            raise ValidationFailure("role_or_visibility_approval_expired")

    def write(self, record, function, params, group_id):
        self.inflight = False
        self.require(function)
        other = self.db.scalar(
            select(EnrollmentRecord.id)
            .join(EnrollmentJob, EnrollmentJob.id == EnrollmentRecord.job_id)
            .join(MoodleConnection, MoodleConnection.id == EnrollmentJob.connection_id)
            .where(
                MoodleConnection.base_url == self.connection.base_url,
                EnrollmentRecord.resolved_user_id == record.resolved_user_id,
                EnrollmentRecord.resolved_course_id == record.resolved_course_id,
                EnrollmentRecord.id != record.id,
                EnrollmentRecord.state == "uncertain",
            )
            .limit(1)
        )
        if other:
            raise ValidationFailure("another_job_has_uncertain_result")
        self.approval(record.resolved_course_id, record.role_id, group_id)
        # Persist uncertainty BEFORE dispatch. A crash at any following point is read-only recovery.
        self.guard(commit=False)
        record.state = "uncertain"
        number = 1 + (
            self.db.scalar(
                select(func.max(EnrollmentAttempt.number)).where(
                    EnrollmentAttempt.record_id == record.id
                )
            )
            or 0
        )
        attempt = EnrollmentAttempt(
            record_id=record.id,
            number=number,
            outcome="write_intent",
            safe_context={"function": function},
        )
        self.db.add(attempt)
        self.db.commit()
        dispatched = False
        try:
            with self.network_slot():
                self.approval(record.resolved_course_id, record.role_id, group_id)
                self.inflight = True
                dispatched = True
                _, elapsed = self.client.write_call(
                    self.connection.base_url,
                    self.token,
                    self.limits.timeout_seconds,
                    function,
                    params,
                )
            self.guard(commit=False)
            attempt.outcome = "accepted_unconfirmed"
            attempt.safe_context = {"function": function, "latency_ms": elapsed}
            record.error_code = None
            job = self.db.get(EnrollmentJob, self.job_id)
            runtime = dict(job.runtime)
            runtime["last_latency_ms"] = elapsed
            runtime["effective_pause_seconds"] = min(
                3600,
                max(self.options.pause_seconds, runtime.get("effective_pause_seconds", 0)) * 2
                if elapsed > self.options.latency_threshold_ms
                else max(self.options.pause_seconds, runtime.get("effective_pause_seconds", 0) - 1),
            )
            job.runtime = runtime
            self.db.commit()
        except (Stopped, ValidationFailure):
            if not dispatched:
                self.db.rollback()
                job = self.db.scalar(
                    select(EnrollmentJob).where(EnrollmentJob.id == self.job_id).with_for_update()
                )
                if job.lease_owner == self.job_owner:
                    record.state, attempt.outcome = "pending", "not_dispatched"
                    self.db.commit()
            raise
        except MoodleError as error:
            self.guard(commit=False)
            attempt.outcome, attempt.error_code = "uncertain", error.code
            record.error_code = error.code
            self.db.commit()
            raise

    def observe(self, record, group_id):
        self.memory.pop(digest(["members", record.resolved_course_id]), None)
        member = self.members(record.resolved_course_id, [record.resolved_user_id])["items"].get(
            str(record.resolved_user_id)
        )
        role = bool(
            member
            and member.get("roles") is not None
            and any(x["roleid"] == record.role_id for x in member["roles"])
        )
        group = not group_id or bool(
            member
            and member.get("groups") is not None
            and any(x["id"] == group_id for x in member["groups"])
        )
        return role, group


def source(db, job, record):
    validated = (
        db.get(ValidationRecord, record.validation_record_id)
        if record.validation_record_id
        else None
    )
    if validated is None:
        # Upgrade older drafts without overwriting the original validation evidence.
        validated = db.scalar(
            select(ValidationRecord).where(
                ValidationRecord.run_id == UUID(job.configuration["validation_id"]),
                ValidationRecord.resolved_key == record.operation_key,
            )
        )
        if validated:
            record.validation_record_id = validated.id
    if not validated:
        raise ValidationFailure("source_validation_missing")
    return validated, db.get(CsvOperation, validated.operation_id)


def confirm_attempts(db, record):
    for attempt in db.scalars(
        select(EnrollmentAttempt).where(
            EnrollmentAttempt.record_id == record.id,
            EnrollmentAttempt.outcome.in_(["write_intent", "accepted_unconfirmed", "uncertain"]),
        )
    ):
        attempt.outcome = "confirmed_by_observation"
        attempt.safe_context = {**attempt.safe_context, "observed_at": now().isoformat()}


def process(db, job, record, reader):
    reader.memory.pop(digest(["members", record.resolved_course_id]), None)
    validated, operation = source(db, job, record)
    recovering = record.state == "uncertain"
    reader.users([operation])
    reader.courses([operation])
    status, code, resolution = reader.resolve(validated, operation)
    if (
        resolution.get("resolved_user_id") != record.resolved_user_id
        or resolution.get("resolved_course_id") != record.resolved_course_id
        or resolution.get("resolved_key") != record.operation_key
    ):
        raise ValidationFailure("resolved_identity_changed")
    group_id = resolution.get("resolved_group_id")
    if recovering:
        role, group = reader.observe(record, group_id)
        reader.guard(commit=False)
        record.reconciliation_count += 1
        if role and group:
            record.state, record.error_code = "confirmed", None
            confirm_attempts(db, record)
            previous_id = record.reconciles_record_id
            visited = {record.id}
            while previous_id and previous_id not in visited:
                visited.add(previous_id)
                previous = db.get(EnrollmentRecord, previous_id)
                if not previous or previous.operation_key != record.operation_key:
                    break
                if previous.state == "uncertain":
                    previous.state, previous.error_code = "confirmed", None
                    confirm_attempts(db, previous)
                    event(
                        db,
                        db.get(EnrollmentJob, previous.job_id),
                        "late_reconciled",
                        record_id=str(previous.id),
                        reconciliation_job_id=str(job.id),
                    )
                previous_id = previous.reconciles_record_id
        else:
            record.state, record.error_code = "uncertain", "result_not_observed"
            record.next_attempt_at = now() + timedelta(seconds=reader.options.retry_base_seconds)
        event(db, job, "reconciled", record_id=str(record.id), outcome=record.state)
        db.commit()
        return
    if status == "existing":
        reader.guard(commit=False)
        record.state, record.error_code = "existing", None
        db.commit()
        return
    if status != "valid":
        raise ValidationFailure(code or "validation_not_ready")
    reader.approval(record.resolved_course_id, record.role_id, group_id)
    role, group = reader.observe(record, group_id)
    if not role:
        reader.write(
            record,
            "enrol_manual_enrol_users",
            {
                "enrolments[0][userid]": str(record.resolved_user_id),
                "enrolments[0][courseid]": str(record.resolved_course_id),
                "enrolments[0][roleid]": str(record.role_id),
            },
            group_id,
        )
        role, group = reader.observe(record, group_id)
    if role and not group and group_id:
        # Never add a group before observing the requested active role.
        reader.write(
            record,
            "core_group_add_group_members",
            {
                "members[0][userid]": str(record.resolved_user_id),
                "members[0][groupid]": str(group_id),
            },
            group_id,
        )
        role, group = reader.observe(record, group_id)
    reader.guard(commit=False)
    record.state = "confirmed" if role and group else "uncertain"
    record.error_code = None if record.state == "confirmed" else "result_not_observed"
    if record.state == "confirmed":
        confirm_attempts(db, record)
    record.next_attempt_at = now() + timedelta(seconds=reader.options.retry_base_seconds)
    event(db, job, "record_result", record_id=str(record.id), outcome=record.state)
    db.commit()


def run_batch(job_id, *, client=None, pace=True, engine=None):
    engine = engine or database.get_engine()
    with Session(engine) as db:
        base_url = db.scalar(
            select(MoodleConnection.base_url)
            .join(EnrollmentJob, EnrollmentJob.connection_id == MoodleConnection.id)
            .where(EnrollmentJob.id == job_id)
        )
    if not base_url:
        return False
    with Session(engine) as db:
        caps = [
            Limits.model_validate(c.limits).max_concurrency
            for c in db.scalars(
                select(MoodleConnection).where(
                    MoodleConnection.base_url == base_url, MoodleConnection.active.is_(True)
                )
            )
        ]
    # Session locks span commits; aliases share the most conservative installation limit.
    keys = [int(digest([base_url, slot])[:15], 16) for slot in range(min(caps or [1]))]
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as lock:
        acquired = None
        for key in keys:
            if lock.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}):
                acquired = key
                break
        if acquired is None:
            with Session(engine) as db:
                job = db.scalar(
                    select(EnrollmentJob).where(EnrollmentJob.id == job_id).with_for_update()
                )
                if not job or job.state not in {"queued", "running", "pausing", "cancelling"}:
                    return False
                if job.lease_until and job.lease_until > now():
                    return False
                delay = job.configuration.get("pause_seconds", 10)
                job.next_run_at = max(job.next_run_at or now(), now() + timedelta(seconds=delay))
                db.commit()
            return True
        try:
            return _run_batch(job_id, client=client, pace=pace, engine=engine)
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": acquired})


def _run_batch(job_id, *, client=None, pace=True, engine=None):
    with Session(engine or database.get_engine()) as db:
        job = db.scalar(select(EnrollmentJob).where(EnrollmentJob.id == job_id).with_for_update())
        if not job or job.state not in {"queued", "running", "pausing", "cancelling"}:
            return False
        if job.lease_until and job.lease_until > now():
            return False
        if (
            job.state not in {"pausing", "cancelling"}
            and job.next_run_at
            and job.next_run_at > now()
        ):
            return False
        options = BatchConfiguration.model_validate(
            {k: v for k, v in job.configuration.items() if k in BatchConfiguration.model_fields}
        )
        owner = secrets.token_hex(16)
        job.lease_owner, job.lease_until = owner, now() + timedelta(seconds=LEASE_SECONDS)
        for row in db.scalars(
            select(EnrollmentRecord)
            .where(EnrollmentRecord.job_id == job.id, EnrollmentRecord.state == "reserved")
            .with_for_update()
        ):
            # No write intent was committed for these records.
            row.state, row.lease_owner, row.lease_until = "pending", None, None
        if job.state in {"pausing", "cancelling"}:
            job.state = "paused" if job.state == "pausing" else "cancelled"
            if job.state == "cancelled":
                job.finished_at = now()
                db.execute(
                    update(EnrollmentRecord)
                    .where(EnrollmentRecord.job_id == job.id, EnrollmentRecord.state == "pending")
                    .values(state="skipped")
                )
            job.lease_owner = job.lease_until = None
            event(db, job, job.state)
            db.commit()
            return False
        if not get_settings().enrollment_writes_enabled:
            job.state = "paused"
            job.lease_owner = job.lease_until = None
            event(db, job, "writes_disabled")
            db.commit()
            return False
        connection = db.get(MoodleConnection, job.connection_id)
        circuit = db.get(SystemSetting, "moodle:circuit:" + digest(connection.base_url))
        if circuit and datetime.fromisoformat(circuit.value["until"]) > now():
            job.state = "paused"
            job.next_run_at = datetime.fromisoformat(circuit.value["until"])
            job.lease_owner = job.lease_until = None
            event(db, job, "installation_circuit_open")
            db.commit()
            return False
        if now().hour not in options.allowed_hours_utc:
            job.next_run_at = now() + timedelta(minutes=1)
            job.lease_owner = job.lease_until = None
            db.commit()
            return True
        job.state, job.started_at = "running", job.started_at or now()
        db.commit()
        reader = None
        try:
            reader = ExecutionReader(db, job, owner, client, pace)
            operations = list(
                db.scalars(
                    select(CsvOperation)
                    .join(ValidationRecord, ValidationRecord.operation_id == CsvOperation.id)
                    .join(
                        EnrollmentRecord,
                        EnrollmentRecord.validation_record_id == ValidationRecord.id,
                    )
                    .where(
                        EnrollmentRecord.job_id == job.id,
                        or_(
                            EnrollmentRecord.state == "pending",
                            (EnrollmentRecord.state == "uncertain")
                            & (EnrollmentRecord.reconciliation_count < 3),
                        ),
                        or_(
                            EnrollmentRecord.next_attempt_at.is_(None),
                            EnrollmentRecord.next_attempt_at <= now(),
                        ),
                    )
                    .order_by(EnrollmentRecord.created_at, EnrollmentRecord.id)
                    .limit(options.batch_size)
                )
            )
            prefetch_error = None
            try:
                reader.users(operations)
                reader.courses(operations)
            except MoodleError as error:
                prefetch_error = error
            for _ in range(options.batch_size):
                reader.inflight = False
                reader.guard(commit=False)
                record = db.scalar(
                    select(EnrollmentRecord)
                    .where(
                        EnrollmentRecord.job_id == job.id,
                        or_(
                            EnrollmentRecord.state == "pending",
                            (EnrollmentRecord.state == "uncertain")
                            & (EnrollmentRecord.reconciliation_count < 3),
                        ),
                        or_(
                            EnrollmentRecord.next_attempt_at.is_(None),
                            EnrollmentRecord.next_attempt_at <= now(),
                        ),
                    )
                    .order_by(EnrollmentRecord.created_at, EnrollmentRecord.id)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                if not record:
                    db.commit()
                    break
                if record.state == "pending":
                    record.state, record.lease_owner = "reserved", owner
                    record.lease_until = now() + timedelta(seconds=LEASE_SECONDS)
                db.commit()
                try:
                    if prefetch_error:
                        raise prefetch_error
                    # Serialize the actual user/course operation even across different groups/jobs.
                    operation_key = int(
                        digest(
                            [
                                reader.connection.base_url,
                                record.resolved_user_id,
                                record.resolved_course_id,
                            ]
                        )[:15],
                        16,
                    )
                    with (
                        (engine or database.get_engine())
                        .connect()
                        .execution_options(isolation_level="AUTOCOMMIT") as operation_lock
                    ):
                        if not operation_lock.scalar(
                            text("SELECT pg_try_advisory_lock(:key)"), {"key": operation_key}
                        ):
                            record.state = "uncertain" if record.state == "uncertain" else "pending"
                            record.next_attempt_at = now() + timedelta(
                                seconds=options.pause_seconds
                            )
                            db.commit()
                            continue
                        try:
                            process(db, job, record, reader)
                        finally:
                            operation_lock.execute(
                                text("SELECT pg_advisory_unlock(:key)"), {"key": operation_key}
                            )
                    installation_result(db, reader, failed=False)
                    runtime = dict(job.runtime)
                    runtime["consecutive_errors"] = 0
                    job.runtime = runtime
                    db.commit()
                except (MoodleError, ValidationFailure) as error:
                    db.rollback()
                    reader.guard(commit=False)
                    code = error.code if isinstance(error, MoodleError) else str(error)
                    record.error_code = code
                    if record.state == "uncertain":
                        record.reconciliation_count += 1
                        record.next_attempt_at = now() + timedelta(
                            seconds=options.retry_base_seconds
                        )
                    elif code in TRANSIENT and record.retry_count < options.max_retries:
                        record.retry_count += 1
                        record.state = "pending"
                        record.next_attempt_at = now() + timedelta(
                            seconds=min(
                                3600, options.retry_base_seconds * 2 ** (record.retry_count - 1)
                            )
                            * random.uniform(0.8, 1.2)
                        )
                    else:
                        record.state = "failed"
                    if code == "installation_circuit_open":
                        job.state = "pausing"
                        marker = db.get(
                            SystemSetting, "moodle:circuit:" + digest(reader.connection.base_url)
                        )
                        job.next_run_at = datetime.fromisoformat(marker.value["until"])
                        if record.state != "uncertain":
                            record.state = "pending"
                        db.commit()
                        break
                    installation_until = installation_result(db, reader, failed=True)
                    errors = job.runtime.get("consecutive_errors", 0) + 1
                    job.runtime = {
                        **job.runtime,
                        "consecutive_errors": errors,
                        "last_error_code": code,
                    }
                    event(db, job, "record_error", record_id=str(record.id), error_code=code)
                    if errors >= options.error_threshold or installation_until:
                        job.state = "pausing"
                        job.next_run_at = max(
                            installation_until or now(),
                            now() + timedelta(seconds=options.circuit_cooldown_seconds),
                        )
                        key = "moodle:circuit:" + digest(reader.connection.base_url)
                        circuit = db.get(SystemSetting, key)
                        value = {"until": job.next_run_at.isoformat(), "error_code": code}
                        if circuit:
                            circuit.value = value
                        else:
                            db.add(SystemSetting(key=key, value=value))
                        event(db, job, "circuit_opened", error_code=code)
                    db.commit()
                    if job.state == "pausing":
                        break
            return finish(db, job.id, owner, options)
        except Stopped:
            db.rollback()
            return finish(db, job.id, owner, options)
        except (VaultError, UnsafeURL, ValidationFailure, HTTPException):
            db.rollback()
            return fail(db, job.id, owner, "configuration_or_access_unavailable")
        except Exception:  # noqa: BLE001 - redact and preserve write uncertainty on task failure.
            db.rollback()
            fail(db, job.id, owner, "internal_error")
            raise RuntimeError("enrollment_worker_failed") from None


def finish(db, job_id, owner, options):
    db.expire_all()
    job = db.scalar(select(EnrollmentJob).where(EnrollmentJob.id == job_id).with_for_update())
    if job.lease_owner != owner:
        return False
    db.execute(
        update(EnrollmentRecord)
        .where(EnrollmentRecord.job_id == job.id, EnrollmentRecord.state == "reserved")
        .values(state="pending", lease_owner=None, lease_until=None)
    )
    db.execute(
        update(EnrollmentRecord)
        .where(EnrollmentRecord.job_id == job.id, EnrollmentRecord.lease_owner == owner)
        .values(lease_owner=None, lease_until=None)
    )
    unfinished = db.scalar(
        select(func.count())
        .select_from(EnrollmentRecord)
        .where(
            EnrollmentRecord.job_id == job.id,
            or_(
                EnrollmentRecord.state.in_(["pending", "reserved"]),
                (EnrollmentRecord.state == "uncertain")
                & (EnrollmentRecord.reconciliation_count < 3),
            ),
        )
    )
    if job.state == "cancelling":
        job.state, job.finished_at = "cancelled", now()
        db.execute(
            update(EnrollmentRecord)
            .where(EnrollmentRecord.job_id == job.id, EnrollmentRecord.state == "pending")
            .values(state="skipped")
        )
    elif job.state == "pausing":
        job.state = "paused"
    elif unfinished:
        job.state = "running"
        job.next_run_at = now() + timedelta(
            seconds=job.runtime.get("effective_pause_seconds", options.pause_seconds)
        )
    else:
        errors = db.scalar(
            select(func.count())
            .select_from(EnrollmentRecord)
            .where(
                EnrollmentRecord.job_id == job.id,
                EnrollmentRecord.state.in_(["failed", "uncertain"]),
            )
        )
        job.state = "completed_with_errors" if errors else "completed"
        job.finished_at = now()
    job.lease_owner = job.lease_until = None
    event(db, job, job.state)
    db.commit()
    return job.state in {"queued", "running"}


def fail(db, job_id, owner, code):
    job = db.scalar(select(EnrollmentJob).where(EnrollmentJob.id == job_id).with_for_update())
    if job.lease_owner == owner:
        job.state, job.finished_at = "failed", now()
        db.execute(
            update(EnrollmentRecord)
            .where(EnrollmentRecord.job_id == job.id, EnrollmentRecord.state == "reserved")
            .values(state="failed", error_code=code, lease_owner=None, lease_until=None)
        )
        job.lease_owner = job.lease_until = None
        event(db, job, "failed", error_code=code)
        db.commit()
    return False
