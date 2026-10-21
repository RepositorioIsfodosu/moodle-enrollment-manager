import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.moodle.client import MoodleError
from app.models import EnrollmentAttempt, EnrollmentJob, EnrollmentRecord
from app.services.enrollment_engine import run_batch
from tests.integration.test_imports import FakeMoodle, approve, imported, validation
from tests.integration.test_imports import environment as environment  # noqa: PLC0414
from tests.integration.test_imports import run_batch as validate

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION") != "1", reason="Dedicated PostgreSQL/Redis"
)


class WritableMoodle(FakeMoodle):
    def __init__(self):
        super().__init__()
        self.writes = []
        self.fail_after_commit = False
        self.no_commit = False
        self.on_write = None

    def write_call(self, base, token, timeout, function, params):
        self.writes.append((function, params))
        if not self.no_commit:
            if function == "enrol_manual_enrol_users":
                self.members = [
                    {
                        "id": int(params["enrolments[0][userid]"]),
                        "roles": [{"roleid": int(params["enrolments[0][roleid]"])}],
                        "groups": [],
                    }
                ]
            else:
                self.members[0]["groups"] = [{"id": int(params["members[0][groupid]"])}]
        if self.on_write:
            self.on_write()
        if self.fail_after_commit:
            raise MoodleError("timeout")
        return None, 1


def setup(environment, monkeypatch, body=None):
    client, headers, connection, engine, _ = environment
    monkeypatch.setattr(get_settings(), "enrollment_writes_enabled", True)
    monkeypatch.setattr("app.api.v1.endpoints.jobs.dispatch", lambda job_id: None)
    _, entry = imported(client, headers, body=body)
    approve(client, headers, connection, groups_authorized=True)
    run = validation(client, headers, connection, [entry])
    validate(UUID(run), client=FakeMoodle(), pace=False, engine=engine)
    response = client.post(
        "/api/v1/enrollment-jobs",
        headers=headers,
        json={"name": "Engine", "validation_id": run, "configuration": {"pause_seconds": 1}},
    )
    assert response.status_code == 201, response.text
    job_id = response.json()["id"]
    response = client.post(f"/api/v1/enrollment-jobs/{job_id}/start", headers=headers)
    assert response.status_code == 202, response.text
    return job_id


def state(environment, job_id):
    client, headers, _, _, _ = environment
    return client.get(f"/api/v1/enrollment-jobs/{job_id}", headers=headers).json()


def due(engine, job_id):
    with Session(engine) as db:
        job = db.get(EnrollmentJob, UUID(job_id))
        job.next_run_at = None
        for record in db.scalars(select(EnrollmentRecord).where(EnrollmentRecord.job_id == job.id)):
            record.next_attempt_at = None
        db.commit()


def test_confirmed_only_after_read_and_existing_is_not_resent(environment, monkeypatch):
    job = setup(environment, monkeypatch)
    engine = environment[3]
    fake = WritableMoodle()
    assert run_batch(job, client=fake, pace=False, engine=engine) is False
    assert state(environment, job)["state"] == "completed"
    assert state(environment, job)["counts"] == {"confirmed": 1}
    assert len(fake.writes) == 1
    assert run_batch(job, client=fake, pace=False, engine=engine) is False
    assert len(fake.writes) == 1
    second = setup(environment, monkeypatch)
    run_batch(second, client=fake, pace=False, engine=engine)
    assert state(environment, second)["counts"] == {"existing": 1}
    assert len(fake.writes) == 1


def test_timeout_after_commit_reconciles_without_second_write(environment, monkeypatch):
    job = setup(environment, monkeypatch)
    engine = environment[3]
    fake = WritableMoodle()
    fake.fail_after_commit = True
    assert run_batch(job, client=fake, pace=False, engine=engine)
    assert state(environment, job)["counts"] == {"uncertain": 1}
    due(engine, job)
    run_batch(job, client=fake, pace=False, engine=engine)
    assert state(environment, job)["counts"] == {"confirmed": 1}
    assert len(fake.writes) == 1
    with Session(engine) as db:
        attempt = db.scalar(
            select(EnrollmentAttempt)
            .join(EnrollmentRecord)
            .where(EnrollmentRecord.job_id == UUID(job))
        )
        assert attempt.error_code == "timeout"


def test_successful_http_without_observation_remains_uncertain_and_bounded(
    environment, monkeypatch
):
    job = setup(environment, monkeypatch)
    engine = environment[3]
    fake = WritableMoodle()
    fake.no_commit = True
    for _ in range(5):
        due(engine, job)
        run_batch(job, client=fake, pace=False, engine=engine)
    assert state(environment, job)["state"] == "completed_with_errors"
    assert state(environment, job)["counts"] == {"uncertain": 1}
    assert len(fake.writes) == 1


def test_group_membership_verified_separately(environment, monkeypatch):
    job = setup(environment, monkeypatch, b"username,course1,role1,group1\nalice,BIO,5,G1\n")
    fake = WritableMoodle()
    run_batch(job, client=fake, pace=False, engine=environment[3])
    assert state(environment, job)["counts"] == {"confirmed": 1}
    assert [name for name, _ in fake.writes] == [
        "enrol_manual_enrol_users",
        "core_group_add_group_members",
    ]


def test_pause_during_write_is_cooperative_and_resume_does_not_resend(environment, monkeypatch):
    job = setup(environment, monkeypatch)
    client, headers, _, engine, _ = environment
    fake = WritableMoodle()
    fake.on_write = lambda: client.post(f"/api/v1/enrollment-jobs/{job}/pause", headers=headers)
    run_batch(job, client=fake, pace=False, engine=engine)
    assert state(environment, job)["state"] == "paused"
    due(engine, job)
    assert client.post(f"/api/v1/enrollment-jobs/{job}/resume", headers=headers).status_code == 202
    fake.on_write = None
    run_batch(job, client=fake, pace=False, engine=engine)
    assert state(environment, job)["state"] == "completed"
    assert len(fake.writes) == 1


def test_concurrent_jobs_are_serialized_and_duplicate_delivery_is_harmless(
    environment, monkeypatch
):
    job = setup(environment, monkeypatch)
    second = setup(environment, monkeypatch)
    engine = environment[3]
    entered, release = Event(), Event()
    fake = WritableMoodle()

    def block():
        entered.set()
        assert release.wait(10)

    fake.on_write = block
    with ThreadPoolExecutor(max_workers=2) as pool:
        running = pool.submit(run_batch, job, client=fake, pace=False, engine=engine)
        assert entered.wait(10)
        assert run_batch(second, client=fake, pace=False, engine=engine)
        assert len(fake.writes) == 1
        release.set()
        running.result()
    fake.on_write = None
    with Session(engine) as db:
        assert db.get(EnrollmentJob, UUID(second)).next_run_at > datetime.now(UTC)
    due(engine, second)
    run_batch(second, client=fake, pace=False, engine=engine)
    assert state(environment, second)["counts"] == {"existing": 1}
    assert len(fake.writes) == 1


def test_abandoned_intent_is_reconciled_not_reissued(environment, monkeypatch):
    job = setup(environment, monkeypatch)
    engine = environment[3]
    with Session(engine) as db:
        row = db.get(EnrollmentJob, UUID(job))
        row.state, row.lease_owner = "running", "dead-worker"
        row.lease_until = datetime.now(UTC) - timedelta(seconds=1)
        record = db.scalar(select(EnrollmentRecord).where(EnrollmentRecord.job_id == row.id))
        record.state = "uncertain"
        db.add(
            EnrollmentAttempt(
                record_id=record.id, number=1, outcome="write_intent", safe_context={}
            )
        )
        db.commit()
    fake = WritableMoodle()
    fake.members = [{"id": 10, "roles": [{"roleid": 5}], "groups": []}]
    run_batch(job, client=fake, pace=False, engine=engine)
    assert state(environment, job)["counts"] == {"confirmed": 1}
    assert fake.writes == []


def test_cancel_inflight_does_not_claim_to_undo_written_enrollment(environment, monkeypatch):
    job = setup(environment, monkeypatch)
    client, headers, _, engine, _ = environment
    fake = WritableMoodle()
    fake.on_write = lambda: client.post(f"/api/v1/enrollment-jobs/{job}/cancel", headers=headers)
    run_batch(job, client=fake, pace=False, engine=engine)
    assert state(environment, job)["state"] == "cancelled"
    assert state(environment, job)["counts"] == {"confirmed": 1}
    assert len(fake.writes) == 1


def test_preflight_transient_retry_has_backoff_and_is_bounded(environment, monkeypatch):
    job = setup(environment, monkeypatch)
    engine = environment[3]
    fake = WritableMoodle()
    original = fake.read_call

    def timeout(*args):
        if args[3] == "core_user_get_users_by_field":
            raise MoodleError("timeout")
        return original(*args)

    fake.read_call = timeout
    with Session(engine) as db:
        row = db.get(EnrollmentJob, UUID(job))
        row.configuration = {**row.configuration, "max_retries": 1, "error_threshold": 10}
        db.commit()
    assert run_batch(job, client=fake, pace=False, engine=engine)
    with Session(engine) as db:
        record = db.scalar(select(EnrollmentRecord).where(EnrollmentRecord.job_id == UUID(job)))
        assert record.retry_count == 1
        assert record.next_attempt_at > datetime.now(UTC)
    due(engine, job)
    run_batch(job, client=fake, pace=False, engine=engine)
    assert state(environment, job)["counts"] == {"failed": 1}
    assert state(environment, job)["state"] == "completed_with_errors"
    assert fake.writes == []


def test_circuit_breaker_pauses_and_cannot_resume_during_cooldown(environment, monkeypatch):
    job = setup(environment, monkeypatch)
    client, headers, _, engine, _ = environment
    fake = WritableMoodle()
    fake.no_commit, fake.fail_after_commit = True, True
    with Session(engine) as db:
        row = db.get(EnrollmentJob, UUID(job))
        row.configuration = {**row.configuration, "error_threshold": 1}
        db.commit()
    run_batch(job, client=fake, pace=False, engine=engine)
    assert state(environment, job)["state"] == "paused"
    assert client.post(f"/api/v1/enrollment-jobs/{job}/resume", headers=headers).status_code == 409
    other = setup(environment, monkeypatch)
    run_batch(other, client=fake, pace=False, engine=engine)
    assert state(environment, other)["state"] == "paused"
    assert len(fake.writes) == 1


def test_window_defers_without_moodle_calls(environment, monkeypatch):
    job = setup(environment, monkeypatch)
    engine = environment[3]
    with Session(engine) as db:
        row = db.get(EnrollmentJob, UUID(job))
        row.configuration = {
            **row.configuration,
            "allowed_hours_utc": [(datetime.now(UTC).hour + 2) % 24],
        }
        db.commit()
    fake = WritableMoodle()
    assert run_batch(job, client=fake, pace=False, engine=engine)
    assert state(environment, job)["state"] == "queued"
    assert fake.calls == [] and fake.writes == []


def test_cross_job_uncertainty_blocks_a_second_write(environment, monkeypatch):
    job = setup(environment, monkeypatch)
    engine = environment[3]
    fake = WritableMoodle()
    fake.no_commit = True
    run_batch(job, client=fake, pace=False, engine=engine)
    other = setup(environment, monkeypatch)
    run_batch(other, client=fake, pace=False, engine=engine)
    assert len(fake.writes) == 1
    assert state(environment, other)["counts"] == {"failed": 1}
    client, headers, _, _, _ = environment
    records = client.get(f"/api/v1/enrollment-jobs/{other}/records", headers=headers).json()
    assert records["items"][0]["error_code"] == "another_job_has_uncertain_result"


def test_selective_retry_creates_separate_readonly_reconciliation_job(environment, monkeypatch):
    job = setup(environment, monkeypatch)
    client, headers, _, engine, _ = environment
    fake = WritableMoodle()
    fake.no_commit = True
    for _ in range(5):
        due(engine, job)
        run_batch(job, client=fake, pace=False, engine=engine)
    records = client.get(f"/api/v1/enrollment-jobs/{job}/records", headers=headers).json()["items"]
    response = client.post(
        f"/api/v1/enrollment-jobs/{job}/retry",
        headers=headers,
        json={"record_ids": [records[0]["id"]]},
    )
    assert response.status_code == 201, response.text
    retry = response.json()["id"]
    assert retry != job
    assert client.post(f"/api/v1/enrollment-jobs/{retry}/start", headers=headers).status_code == 202
    fake.members = [{"id": 10, "roles": [{"roleid": 5}], "groups": []}]
    run_batch(retry, client=fake, pace=False, engine=engine)
    assert state(environment, retry)["counts"] == {"confirmed": 1}
    assert state(environment, job)["counts"] == {"confirmed": 1}
    assert len(fake.writes) == 1


def test_connection_change_prevents_any_write(environment, monkeypatch):
    job = setup(environment, monkeypatch)
    client, headers, connection, engine, _ = environment
    client.patch(
        f"/api/v1/moodle-connections/{connection}", headers=headers, json={"description": "Changed"}
    )
    fake = WritableMoodle()
    run_batch(job, client=fake, pace=False, engine=engine)
    assert state(environment, job)["state"] == "failed"
    assert fake.writes == []


def test_crash_after_remote_commit_recovers_after_lease_without_resending(environment, monkeypatch):
    class SimulatedPowerLoss(BaseException):
        pass

    job = setup(environment, monkeypatch)
    engine = environment[3]
    fake = WritableMoodle()

    def crash():
        raise SimulatedPowerLoss

    fake.on_write = crash
    with pytest.raises(SimulatedPowerLoss):
        run_batch(job, client=fake, pace=False, engine=engine)
    assert state(environment, job)["state"] == "running"
    assert state(environment, job)["counts"] == {"uncertain": 1}
    assert run_batch(job, client=fake, pace=False, engine=engine) is False
    with Session(engine) as db:
        row = db.get(EnrollmentJob, UUID(job))
        row.lease_until = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    fake.on_write = None
    run_batch(job, client=fake, pace=False, engine=engine)
    assert state(environment, job)["state"] == "completed"
    assert len(fake.writes) == 1


def test_two_installation_slots_still_prevent_same_user_concurrent_writes(environment, monkeypatch):
    from app.models import MoodleConnection

    job = setup(environment, monkeypatch)
    second = setup(environment, monkeypatch)
    engine = environment[3]
    with Session(engine) as db:
        connection = db.get(MoodleConnection, UUID(environment[2]))
        connection.limits = {**connection.limits, "max_concurrency": 2}
        db.commit()
    entered, release = Event(), Event()
    fake = WritableMoodle()

    def block():
        entered.set()
        assert release.wait(10)

    fake.on_write = block
    with ThreadPoolExecutor(max_workers=2) as pool:
        task = pool.submit(run_batch, job, client=fake, pace=False, engine=engine)
        assert entered.wait(10)
        assert run_batch(second, client=fake, pace=False, engine=engine)
        assert state(environment, second)["counts"] == {"pending": 1}
        release.set()
        task.result()
    fake.on_write = None
    due(engine, second)
    run_batch(second, client=fake, pace=False, engine=engine)
    assert len(fake.writes) == 1
    assert state(environment, second)["counts"] == {"existing": 1}


def test_real_celery_delivery_and_lost_publication_recovery_without_http_polling(
    environment, monkeypatch
):
    import time

    from celery.contrib.testing.worker import start_worker
    from kombu.exceptions import OperationalError

    from app.models import MoodleConnection
    from app.tasks.enrollments import enqueue, execute, recover
    from app.workers.celery_app import celery_app

    job = setup(environment, monkeypatch)
    engine = environment[3]
    fake = WritableMoodle()
    monkeypatch.setattr("app.services.validation_engine.MoodleClient", lambda: fake)
    with Session(engine) as db:
        connection = db.get(MoodleConnection, UUID(environment[2]))
        connection.limits = {**connection.limits, "requests_per_minute": 120}
        db.commit()

    def broker_unavailable(*args, **kwargs):
        raise OperationalError("simulated broker outage")

    with monkeypatch.context() as outage:
        outage.setattr(execute, "apply_async", broker_unavailable)
        enqueue(job)
    assert state(environment, job)["state"] == "queued"
    with Session(engine) as db:
        row = db.get(EnrollmentJob, UUID(job))
        row.dispatched_at = datetime.now(UTC) - timedelta(seconds=61)
        db.commit()
    with start_worker(
        celery_app,
        pool="solo",
        concurrency=1,
        queues=["enrollment"],
        perform_ping_check=False,
        shutdown_timeout=15,
    ):
        recover.run()
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            with Session(engine) as db:
                current = db.get(EnrollmentJob, UUID(job)).state
            if current == "completed":
                break
            time.sleep(0.1)
        assert current == "completed"
    assert len(fake.writes) == 1
    assert state(environment, job)["counts"] == {"confirmed": 1}


def test_larger_import_is_bounded_and_user_lookups_are_batched(environment, monkeypatch):
    body = b"username,course1,role1\n" + b"".join(f"u{i},BIO,5\n".encode() for i in range(25))
    job = setup(environment, monkeypatch, body)
    engine = environment[3]
    fake = WritableMoodle()
    with Session(engine) as db:
        row = db.get(EnrollmentJob, UUID(job))
        row.configuration = {**row.configuration, "batch_size": 10}
        db.commit()
    for expected in [10, 20, 25]:
        due(engine, job)
        run_batch(job, client=fake, pace=False, engine=engine)
        assert len(fake.writes) == expected
    assert state(environment, job)["state"] == "completed"
    assert state(environment, job)["counts"] == {"confirmed": 25}
    lookups = [params for fn, params in fake.calls if fn == "core_user_get_users_by_field"]
    assert len(lookups) == 3
    assert [sum(k.startswith("values[") for k in p) for p in lookups] == [10, 10, 5]


def test_disabling_writes_still_allows_cancellation_recovery(environment, monkeypatch):
    job = setup(environment, monkeypatch)
    engine = environment[3]
    with Session(engine) as db:
        row = db.get(EnrollmentJob, UUID(job))
        row.state = "cancelling"
        db.commit()
    monkeypatch.setattr(get_settings(), "enrollment_writes_enabled", False)
    fake = WritableMoodle()
    run_batch(job, client=fake, pace=False, engine=engine)
    assert state(environment, job)["state"] == "cancelled"
    assert fake.writes == [] and fake.calls == []


def test_supervisor_reads_only_granted_destinations_and_cannot_mutate(environment, monkeypatch):
    from tests.helpers import create, login

    job = setup(environment, monkeypatch)
    client, headers, connection, _, _ = environment
    supervisor = create(
        client, headers, role="supervisor", email="engine-supervisor@example.com"
    ).json()
    scoped = login(client, "engine-supervisor@example.com")
    assert client.get(f"/api/v1/enrollment-jobs/{job}", headers=scoped).status_code == 404
    assert (
        client.post(
            f"/api/v1/moodle-connections/{connection}/grants",
            headers=headers,
            json={"user_id": supervisor["id"]},
        ).status_code
        == 201
    )
    assert client.get(f"/api/v1/enrollment-jobs/{job}", headers=scoped).status_code == 200
    assert client.get("/api/v1/enrollment-jobs", headers=scoped).json()["total"] == 1
    assert client.post(f"/api/v1/enrollment-jobs/{job}/pause", headers=scoped).status_code == 403


def test_pause_in_dispatch_gap_is_proven_not_sent_and_can_resume(environment, monkeypatch):
    from contextlib import contextmanager

    from sqlalchemy import func

    from app.services.enrollment_engine import ExecutionReader

    job = setup(environment, monkeypatch)
    client, headers, _, engine, _ = environment
    fired = False

    @contextmanager
    def controlled_gate(reader):
        nonlocal fired
        intents = reader.db.scalar(select(func.count()).select_from(EnrollmentAttempt))
        if intents and not fired:
            fired = True
            assert (
                client.post(f"/api/v1/enrollment-jobs/{job}/pause", headers=headers).status_code
                == 200
            )
            reader.guard()
        yield

    monkeypatch.setattr(ExecutionReader, "network_slot", controlled_gate)
    fake = WritableMoodle()
    run_batch(job, client=fake, pace=False, engine=engine)
    assert state(environment, job)["state"] == "paused"
    assert state(environment, job)["counts"] == {"pending": 1}
    assert fake.writes == []
    with Session(engine) as db:
        assert db.scalar(select(EnrollmentAttempt)).outcome == "not_dispatched"
    assert client.post(f"/api/v1/enrollment-jobs/{job}/resume", headers=headers).status_code == 202
    run_batch(job, client=fake, pace=False, engine=engine)
    assert state(environment, job)["counts"] == {"confirmed": 1}
    assert len(fake.writes) == 1


def test_installation_circuit_aggregates_errors_across_different_jobs(environment, monkeypatch):
    engine = environment[3]
    fake = WritableMoodle()
    fake.no_commit, fake.fail_after_commit = True, True
    jobs = []
    for number in range(3):
        job = setup(environment, monkeypatch, f"username,course1,role1\nu{number},BIO,5\n".encode())
        with Session(engine) as db:
            row = db.get(EnrollmentJob, UUID(job))
            row.configuration = {**row.configuration, "error_threshold": 20}
            db.commit()
        run_batch(job, client=fake, pace=False, engine=engine)
        jobs.append(job)
    assert state(environment, jobs[0])["state"] == "running"
    assert state(environment, jobs[1])["state"] == "running"
    assert state(environment, jobs[2])["state"] == "paused"
    assert len(fake.writes) == 3


def test_high_latency_increases_persisted_pause(environment, monkeypatch):
    job = setup(environment, monkeypatch)
    fake = WritableMoodle()
    write = fake.write_call

    def slow(*args):
        payload, _ = write(*args)
        return payload, 12000

    fake.write_call = slow
    run_batch(job, client=fake, pace=False, engine=environment[3])
    runtime = state(environment, job)["runtime"]
    assert runtime["last_latency_ms"] == 12000
    assert runtime["effective_pause_seconds"] == 2


def test_expired_role_attestation_prevents_write(environment, monkeypatch):
    from app.models import RoleApproval

    job = setup(environment, monkeypatch)
    engine = environment[3]
    with Session(engine) as db:
        for approval in db.scalars(select(RoleApproval)):
            approval.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    fake = WritableMoodle()
    run_batch(job, client=fake, pace=False, engine=engine)
    assert state(environment, job)["counts"] == {"failed": 1}
    assert fake.writes == []


def test_role_expiry_while_waiting_for_dispatch_is_checked_again(environment, monkeypatch):
    from contextlib import contextmanager

    from sqlalchemy import func

    from app.models import RoleApproval
    from app.services.enrollment_engine import ExecutionReader

    job = setup(environment, monkeypatch)

    @contextmanager
    def expiring_gate(reader):
        if reader.db.scalar(select(func.count()).select_from(EnrollmentAttempt)):
            with Session(environment[3]) as db:
                for row in db.scalars(select(RoleApproval)):
                    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
                db.commit()
        yield

    monkeypatch.setattr(ExecutionReader, "network_slot", expiring_gate)
    fake = WritableMoodle()
    run_batch(job, client=fake, pace=False, engine=environment[3])
    assert state(environment, job)["counts"] == {"failed": 1}
    assert fake.writes == []
    with Session(environment[3]) as db:
        assert db.scalar(select(EnrollmentAttempt)).outcome == "not_dispatched"
