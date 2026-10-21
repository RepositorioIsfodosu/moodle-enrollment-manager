import os
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import EnrollmentJob, EnrollmentRecord
from app.services.validation_engine import run_batch
from tests.helpers import PASSWORD, create, login
from tests.integration.test_imports import FakeMoodle, approve, imported, validation
from tests.integration.test_imports import environment as environment  # noqa: PLC0414

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION") != "1", reason="Dedicated PostgreSQL/Redis"
)
ORIGIN = {"Origin": "http://testserver", "X-CSRF-Protection": "1"}


def test_cookie_login_reload_and_csrf_rejection(client, admin):
    result = client.post(
        "/api/v1/auth/login",
        headers=ORIGIN | {"X-Session-Mode": "cookie"},
        json={"email": "admin@example.com", "password": PASSWORD},
    )
    assert result.status_code == 200, result.text
    assert result.json()["authenticated"] is True
    assert "access_token" not in result.json()
    assert "HttpOnly" in result.headers["set-cookie"]
    assert "SameSite=strict" in result.headers["set-cookie"]
    assert "Path=/api/v1" in result.headers["set-cookie"]
    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.post("/api/v1/auth/logout").status_code == 403
    assert (
        client.post(
            "/api/v1/auth/logout", headers=ORIGIN | {"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.post("/api/v1/auth/logout", headers=ORIGIN).status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_cookie_login_itself_requires_same_origin(client, admin):
    for origin in ["https://evil.example", "null", "http://testserver/path", ""]:
        response = client.post(
            "/api/v1/auth/login",
            headers={"Origin": origin, "X-Session-Mode": "cookie", "X-CSRF-Protection": "1"},
            json={"email": "admin@example.com", "password": PASSWORD},
        )
        assert response.status_code == 403
        assert "mem_session" not in client.cookies


def test_secure_cookie_setting(client, admin, monkeypatch):
    monkeypatch.setattr(get_settings(), "session_cookie_secure", True)
    response = client.post(
        "/api/v1/auth/login",
        headers=ORIGIN | {"X-Session-Mode": "cookie"},
        json={"email": "admin@example.com", "password": PASSWORD},
    )
    assert response.status_code == 200
    assert "Secure;" in response.headers["set-cookie"] or response.headers["set-cookie"].endswith(
        "Secure"
    )


def test_settings_exposes_no_secrets_and_requires_authentication(client, admin):
    assert client.get("/api/v1/settings").status_code == 401
    result = client.get("/api/v1/settings", headers=admin[1])
    assert result.status_code == 200
    assert set(result.json()) == {
        "timezone",
        "csv_max_bytes",
        "csv_max_rows",
        "csv_max_operations",
        "enrollment_writes_enabled",
    }


def test_dashboard_scopes_counts_without_counting_same_csv_twice(environment):
    client, headers, connection, engine, _ = environment
    file, entry = imported(client, headers)
    approve(client, headers, connection)
    run = validation(client, headers, connection, [entry])
    run_batch(UUID(run), client=FakeMoodle(), pace=False, engine=engine)
    for name in ["First", "Second"]:
        response = client.post(
            "/api/v1/enrollment-jobs", headers=headers, json={"name": name, "validation_id": run}
        )
        assert response.status_code == 201
    stats = client.get("/api/v1/dashboard?connection_id=" + connection, headers=headers).json()
    assert stats["imported_rows"] == 1
    assert stats["total_operations"] == 2
    assert stats["record_counts"] == {"pending": 2}
    create(client, headers, email="ui-private@example.com")
    operator = login(client, "ui-private@example.com")
    assert client.get("/api/v1/dashboard", headers=operator).json()["total_operations"] == 0
    assert client.get("/api/v1/csv-imports", headers=operator).json()["total"] == 0
    assert (
        client.get("/api/v1/csv-imports?file_id=" + file["id"], headers=headers).json()["total"]
        == 1
    )
    assert client.get("/api/v1/enrollment-jobs?state=unknown", headers=headers).status_code == 422
    assert client.get("/api/v1/enrollment-jobs?terminal=true", headers=headers).json()["total"] == 0


def test_error_overview_and_grants_follow_destination_scope(environment):
    client, headers, connection, engine, owner = environment
    with Session(engine) as db:
        # Original file/source references are produced through the real API.
        file, _ = imported(client, headers)
        job = EnrollmentJob(
            name="Private error",
            owner_id=owner,
            connection_id=UUID(connection),
            state="completed_with_errors",
            configuration={},
        )
        db.add(job)
        db.flush()
        db.add(
            EnrollmentRecord(
                job_id=job.id,
                file_id=UUID(file["id"]),
                source_row=2,
                operation_key="a" * 64,
                user_identifier="alice",
                course_identifier="BIO",
                role_id=5,
                state="failed",
                error_code="user_not_found_or_not_visible",
            )
        )
        db.commit()
    user = create(client, headers, role="supervisor", email="ui-supervisor@example.com").json()
    reader = login(client, "ui-supervisor@example.com")
    assert client.get("/api/v1/enrollment-records", headers=reader).json()["total"] == 0
    assert (
        client.post(
            f"/api/v1/moodle-connections/{connection}/grants",
            headers=headers,
            json={"user_id": user["id"]},
        ).status_code
        == 201
    )
    result = client.get("/api/v1/enrollment-records", headers=reader).json()
    assert result["total"] == 1 and result["items"][0]["job_name"] == "Private error"
    assert client.get("/api/v1/dashboard", headers=reader).json()["imported_rows"] is None
    assert (
        client.get(f"/api/v1/moodle-connections/{connection}/grants", headers=reader).status_code
        == 403
    )
    assert (
        client.get(f"/api/v1/moodle-connections/{connection}/grants", headers=headers).json()[
            "total"
        ]
        == 1
    )
