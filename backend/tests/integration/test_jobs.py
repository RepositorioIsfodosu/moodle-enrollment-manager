import os
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditLog, EnrollmentJob, JobEvent, JobFile
from app.services.validation_engine import run_batch
from tests.integration.test_imports import FakeMoodle, approve, imported, validation
from tests.integration.test_imports import environment as environment  # noqa: PLC0414 - fixture export

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION") != "1", reason="Requires dedicated PostgreSQL and Redis"
)


def prepare(environment):
    client, headers, connection, engine, _ = environment
    _, entry = imported(client, headers)
    approve(client, headers, connection)
    run = validation(client, headers, connection, [entry])
    run_batch(UUID(run), client=FakeMoodle(), pace=False, engine=engine)
    return run


def test_persistent_draft_cancel_audit_and_execution_block(environment):
    run = prepare(environment)
    client, headers, _, engine, _ = environment
    response = client.post(
        "/api/v1/enrollment-jobs",
        headers=headers,
        json={"name": "Primer proceso", "validation_id": run},
    )
    assert response.status_code == 201, response.text
    job = response.json()
    assert job["state"] == "draft"
    assert job["counts"] == {"pending": 1}
    assert job["configuration"]["execution_available"] is False
    job_id = job["id"]
    assert client.get(f"/api/v1/enrollment-jobs/{job_id}", headers=headers).json() == job
    records = client.get(f"/api/v1/enrollment-jobs/{job_id}/records", headers=headers).json()
    assert records["total"] == 1
    assert records["items"][0]["user_identifier"] == "alice"
    assert (
        client.post(f"/api/v1/enrollment-jobs/{job_id}/start", headers=headers).status_code == 503
    )
    assert (
        client.post(f"/api/v1/enrollment-jobs/{job_id}/cancel", headers=headers).json()["state"]
        == "cancelled"
    )
    assert (
        client.post(f"/api/v1/enrollment-jobs/{job_id}/cancel", headers=headers).status_code == 409
    )
    with Session(engine) as db:
        assert db.get(EnrollmentJob, UUID(job_id)).finished_at is not None
        assert db.scalar(select(func.count()).select_from(JobFile)) == 1
        assert db.scalar(select(func.count()).select_from(JobEvent)) == 2
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action.in_(["job.created", "job.cancelled"]))
            )
            == 2
        )


def test_draft_rejects_unchecked_and_changed_connection(environment):
    client, headers, connection, engine, _ = environment
    _, entry = imported(client, headers)
    run = validation(client, headers, connection, [entry])
    data = {"name": "Pendiente", "validation_id": run}
    assert client.post("/api/v1/enrollment-jobs", headers=headers, json=data).status_code == 409
    approve(client, headers, connection)
    run_batch(UUID(run), client=FakeMoodle(), pace=False, engine=engine)
    assert (
        client.patch(
            f"/api/v1/moodle-connections/{connection}",
            headers=headers,
            json={"description": "Changed"},
        ).status_code
        == 200
    )
    assert client.post("/api/v1/enrollment-jobs", headers=headers, json=data).status_code == 409


def test_draft_requires_authentication(environment):
    client, _, _, _, _ = environment
    assert client.get(f"/api/v1/enrollment-jobs/{UUID(int=0)}").status_code == 401


def test_draft_scope_and_readonly_role(environment):
    from tests.helpers import create, login

    run = prepare(environment)
    client, headers, _connection, _, _ = environment
    job = client.post(
        "/api/v1/enrollment-jobs", headers=headers, json={"name": "Privado", "validation_id": run}
    ).json()
    create(client, headers, email="jobs-operator@example.com")
    operator = login(client, "jobs-operator@example.com")
    assert client.get("/api/v1/enrollment-jobs", headers=operator).json()["total"] == 0
    assert client.get(f"/api/v1/enrollment-jobs/{job['id']}", headers=operator).status_code == 404
    create(client, headers, role="consulta", email="jobs-reader@example.com")
    reader = login(client, "jobs-reader@example.com")
    assert (
        client.post(f"/api/v1/enrollment-jobs/{job['id']}/cancel", headers=reader).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/enrollment-jobs",
            headers=reader,
            json={"name": "Sin permiso", "validation_id": run},
        ).status_code
        == 403
    )
    listing = client.get("/api/v1/enrollment-jobs", headers=headers).json()
    assert listing["total"] == 1
    assert listing["items"][0]["id"] == job["id"]
    assert client.get("/api/v1/enrollment-jobs?limit=201", headers=headers).status_code == 422


def test_repeated_csv_operations_make_one_draft_record(environment):
    client, headers, connection, engine, _ = environment
    _, entry = imported(client, headers, body=b"username,course1,role1\nalice,BIO,5\nalice,BIO,5\n")
    approve(client, headers, connection)
    run = validation(client, headers, connection, [entry])
    run_batch(UUID(run), client=FakeMoodle(), pace=False, engine=engine)
    response = client.post(
        "/api/v1/enrollment-jobs",
        headers=headers,
        json={"name": "Duplicados", "validation_id": run},
    )
    assert response.status_code == 201, response.text
    assert response.json()["total"] == 1


def test_invalid_rows_cannot_silently_disappear_from_job(environment):
    client, headers, connection, engine, _ = environment
    _, entry = imported(client, headers, body=b"username,course1,role1\nalice,BIO,5\n,BIO,5\n")
    approve(client, headers, connection)
    run = validation(client, headers, connection, [entry])
    run_batch(UUID(run), client=FakeMoodle(), pace=False, engine=engine)
    response = client.post(
        "/api/v1/enrollment-jobs", headers=headers, json={"name": "Invalido", "validation_id": run}
    )
    assert response.status_code == 409, response.text
    assert client.get("/api/v1/enrollment-jobs", headers=headers).json()["total"] == 0
