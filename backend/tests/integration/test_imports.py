import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.cli import bootstrap_admin
from app.core.permissions import ROLE_PERMISSIONS
from app.db.session import get_engine
from app.integrations.moodle.client import SiteInfo
from app.main import app
from app.models import Base, Role, ValidationRun
from app.schemas.auth import UserCreate
from app.services.validation_engine import run_batch
from tests.helpers import PASSWORD, login
from tests.helpers import create as create_user

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION") != "1", reason="Requires dedicated PostgreSQL and Redis"
)


@pytest.fixture
def environment(monkeypatch, redis_client):
    original = get_engine()
    schema = "csvtest_" + uuid4().hex
    with original.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = original.execution_options(schema_translate_map={None: schema})
    Base.metadata.create_all(engine)
    monkeypatch.setattr("app.db.session.get_engine", lambda: engine)
    monkeypatch.setattr("app.api.v1.endpoints.validations.enqueue_validation", lambda run_id: None)
    with Session(engine) as db:
        db.add_all(Role(name=name) for name in ROLE_PERMISSIONS)
        db.commit()
        admin_id = bootstrap_admin(
            db,
            UserCreate(email="csv-admin@example.com", password=PASSWORD, roles=["administrador"]),
        )
    try:
        with TestClient(app) as client:
            headers = login(client, "csv-admin@example.com")
            response = client.post(
                "/api/v1/moodle-connections",
                headers=headers,
                json={
                    "name": "CSV test",
                    "base_url": "https://moodle.example.com",
                    "token": "csv-simulator-token",
                },
            )
            assert response.status_code == 201, response.text
            yield client, headers, response.json()["id"], engine, admin_id
    finally:
        with original.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


def upload(client, headers, body=b"username,course1,role1\nalice,BIO,5\n", **params):
    return client.post(
        "/api/v1/csv-files",
        params={"filename": "input.csv", "delimiter": ",", **params},
        headers=headers | {"Content-Type": "text/csv"},
        content=body,
    )


def imported(client, headers, body=None, mapping=None):
    file = upload(client, headers, body) if body is not None else upload(client, headers)
    assert file.status_code == 201, file.text
    entry = client.post(
        f"/api/v1/csv-files/{file.json()['id']}/normalize",
        headers=headers,
        json={"mapping": mapping or {}},
    )
    assert entry.status_code == 201, entry.text
    return file.json(), entry.json()


def validation(client, headers, connection, entries):
    response = client.post(
        "/api/v1/validations",
        headers=headers,
        json={"connection_id": connection, "import_ids": [entry["id"] for entry in entries]},
    )
    assert response.status_code == 202, response.text
    return response.json()["id"]


def approve(client, headers, connection, **overrides):
    response = client.post(
        f"/api/v1/moodle-connections/{connection}/role-approvals",
        headers=headers,
        json={
            "course_id": 101,
            "role_id": 5,
            "expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            "reference": "Verified manually in test Moodle course settings",
            "full_enrollment_visibility": True,
            **overrides,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


class FakeMoodle:
    def __init__(self):
        self.calls = []
        self.members = []
        self.user_override = None
        self.warnings = []
        self.on_site = None
        self.names = [
            "enrol_manual_enrol_users",
            "core_group_add_group_members",
            "core_webservice_get_site_info",
            "core_user_get_users_by_field",
            "core_course_get_courses_by_field",
            "core_enrol_get_enrolled_users",
            "core_group_get_course_groups",
        ]

    def site_info(self, base, token, timeout):
        assert token == "csv-simulator-token"
        if self.on_site:
            self.on_site()
        self.calls.append(("site", {}))
        return SiteInfo(
            sitename="CSV simulator",
            siteurl=base,
            functions=[{"name": name} for name in self.names],
        ), 1

    def read_call(self, base, token, timeout, function, params):
        assert token == "csv-simulator-token"
        self.calls.append((function, params))
        if function == "core_user_get_users_by_field":
            if self.user_override is not None:
                return self.user_override, 1
            values = [value for key, value in params.items() if key.startswith("values[")]
            return [
                {
                    "id": 10
                    if value in ("alice", "A", "alice@example.com")
                    else (
                        1000 + int(value[1:])
                        if value.startswith("u") and value[1:].isdigit()
                        else 11
                    ),
                    "username": "alice" if value in ("alice", "A", "alice@example.com") else value,
                    "email": "alice@example.com"
                    if value in ("alice", "A", "alice@example.com")
                    else value + "@example.com",
                    "idnumber": "A" if value in ("alice", "A", "alice@example.com") else value,
                    "suspended": False,
                }
                for value in values
                if value != "missing"
            ], 1
        if function == "core_course_get_courses_by_field":
            values = params["value"].split(",")
            return {
                "courses": [{"id": 101, "shortname": "BIO", "idnumber": "C101"}]
                if any(v in ("BIO", "101", "C101") for v in values)
                else [],
                "warnings": self.warnings,
            }, 1
        if function == "core_enrol_get_enrolled_users":
            assert any(value == "onlyactive" for value in params.values())
            return self.members, 1
        if function == "core_group_get_course_groups":
            return [{"id": 701, "name": "G1", "idnumber": "GID"}], 1
        raise AssertionError("Unexpected or mutating Moodle function: " + function)


def results(client, headers, run):
    response = client.get(f"/api/v1/validations/{run}/records", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def test_original_preview_profile_snapshot_and_safe_upload(environment, monkeypatch):
    client, headers, _, _engine, _ = environment
    body = b"username,course1,role1\nalice,BIO,5\n"
    file, _entry = imported(client, headers, body)
    assert file["row_count"] == 1 and len(file["preview"]) == 1
    assert client.get(f"/api/v1/csv-files/{file['id']}/original", headers=headers).content == body
    profile = client.post(
        "/api/v1/import-profiles",
        headers=headers,
        json={"name": "One", "mapping": {"default_role_id": 5}},
    ).json()
    snapshot = client.post(
        f"/api/v1/csv-files/{file['id']}/normalize",
        headers=headers,
        json={"profile_id": profile["id"]},
    ).json()
    client.put(
        f"/api/v1/import-profiles/{profile['id']}",
        headers=headers,
        json={"name": "Changed", "mapping": {"default_role_id": 9}},
    )
    assert (
        client.get(f"/api/v1/csv-imports/{snapshot['id']}", headers=headers).json()[
            "mapping_snapshot"
        ]["default_role_id"]
        == 5
    )
    assert upload(client, headers, filename="../escape.csv").status_code == 422
    assert upload(client, headers, filename="file.exe").status_code == 422
    assert upload(client, headers, b"a,a\n1,2\n").status_code == 422
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "csv_max_bytes", 4)
    assert upload(client, headers, body).status_code == 413


def test_multiple_files_duplicate_counts_and_remote_batching(environment):
    client, headers, connection, engine, _ = environment
    approve(client, headers, connection)
    _, first = imported(
        client, headers, b"username,course1,role1\nalice,BIO,5\nalice,BIO,5\nbob,BIO,5\n"
    )
    _, second = imported(client, headers)
    run = validation(client, headers, connection, [first, second])
    fake = FakeMoodle()
    assert run_batch(run, fake, pace=False, engine=engine) is False
    rows = results(client, headers, run)
    assert [x["status"] for x in rows] == ["valid", "duplicate", "valid", "duplicate"]
    assert all(x["resolved_user_id"] for x in rows if x["status"] == "valid")
    assert all(
        x["approval_id"] and x["role_evidence_source"] == "administrator_attestation"
        for x in rows
        if x["status"] == "valid"
    )
    assert sum(name == "core_user_get_users_by_field" for name, _ in fake.calls) == 1
    assert sum(name == "core_course_get_courses_by_field" for name, _ in fake.calls) == 1
    assert sum(name == "core_enrol_get_enrolled_users" for name, _ in fake.calls) == 1
    assert (
        client.get(f"/api/v1/validations/{run}", headers=headers).json()["progress_percent"] == 100
    )


def test_missing_users_courses_and_unverified_roles(environment):
    client, headers, connection, engine, _ = environment
    _, entry = imported(
        client, headers, b"username,course1,role1\nmissing,BIO,5\nalice,missing,5\nalice,BIO,5\n"
    )
    run = validation(client, headers, connection, [entry])
    run_batch(run, FakeMoodle(), pace=False, engine=engine)
    rows = results(client, headers, run)
    assert [r["error_code"] for r in rows] == [
        "user_not_found_or_not_visible",
        "course_not_found_or_not_visible",
        "role_assignability_unverified",
    ]
    assert rows[-1]["status"] == "pending"  # No API role catalog is invented.


def test_active_enrollment_detection_and_group_resolution(environment):
    client, headers, connection, engine, _ = environment
    _, entry = imported(client, headers, b"username,course1,role1,group1\nalice,BIO,5,G1\n")
    run = validation(client, headers, connection, [entry])
    fake = FakeMoodle()
    fake.members = [{"id": 10, "roles": [{"roleid": 5}], "groups": [{"id": 701}]}]
    run_batch(run, fake, pace=False, engine=engine)
    row = results(client, headers, run)[0]
    assert row["status"] == "existing" and row["resolved_group_id"] == 701
    assert row["approval_id"] is None


def test_role_evidence_expiry_groups_and_revocation(environment):
    client, headers, connection, engine, _ = environment
    approval = approve(client, headers, connection)
    _, entry = imported(client, headers, b"username,course1,role1,group1\nalice,BIO,5,G1\n")
    run = validation(client, headers, connection, [entry])
    run_batch(run, FakeMoodle(), pace=False, engine=engine)
    assert results(client, headers, run)[0]["error_code"] == "group_permission_unverified"
    assert (
        client.delete(f"/api/v1/role-approvals/{approval['id']}", headers=headers).status_code
        == 204
    )
    approve(client, headers, connection, groups_authorized=True)
    run = validation(client, headers, connection, [entry])
    run_batch(run, FakeMoodle(), pace=False, engine=engine)
    assert results(client, headers, run)[0]["status"] == "valid"
    bad = client.post(
        f"/api/v1/moodle-connections/{connection}/role-approvals",
        headers=headers,
        json={
            "course_id": 101,
            "role_id": 5,
            "expires_at": (datetime.now(UTC) + timedelta(days=8)).isoformat(),
            "reference": "This evidence is outside allowed time",
        },
    )
    assert bad.status_code == 422


def test_resolved_alias_duplicate_and_internal_course_ids(environment):
    client, headers, connection, engine, _ = environment
    approve(client, headers, connection)
    _, first = imported(client, headers)
    _, second = imported(
        client, headers, b"idnumber,course1,role1\nA,101,5\n", {"course_field": "id"}
    )
    run = validation(client, headers, connection, [first, second])
    run_batch(run, FakeMoodle(), pace=False, engine=engine)
    rows = results(client, headers, run)
    assert [x["status"] for x in rows] == ["valid", "duplicate"]
    assert rows[1]["error_code"] == "resolved_duplicate"


def test_cancel_and_connection_edit_discard_inflight_results(environment):
    client, headers, connection, engine, _ = environment
    _, entry = imported(client, headers)
    run = validation(client, headers, connection, [entry])
    fake = FakeMoodle()
    fake.on_site = lambda: client.post(f"/api/v1/validations/{run}/cancel", headers=headers)
    run_batch(run, fake, pace=False, engine=engine)
    assert client.get(f"/api/v1/validations/{run}", headers=headers).json()["state"] == "cancelled"
    assert not any(name == "core_user_get_users_by_field" for name, _ in fake.calls)
    run = validation(client, headers, connection, [entry])
    fake = FakeMoodle()
    fake.on_site = lambda: client.patch(
        f"/api/v1/moodle-connections/{connection}", headers=headers, json={"description": "changed"}
    )
    run_batch(run, fake, pace=False, engine=engine)
    assert (
        client.get(f"/api/v1/validations/{run}", headers=headers).json()["error_code"]
        == "configuration_changed"
    )


def test_lease_recovery_and_concurrent_claim(environment):
    client, headers, connection, engine, _ = environment
    approve(client, headers, connection)
    _, entry = imported(client, headers)
    run = validation(client, headers, connection, [entry])
    entered, release = Event(), Event()
    fake = FakeMoodle()

    def waiting():
        entered.set()
        assert release.wait(10)

    fake.on_site = waiting
    with ThreadPoolExecutor(2) as pool:
        future = pool.submit(run_batch, run, fake, False, engine)
        assert entered.wait(10)
        assert run_batch(run, FakeMoodle(), pace=False, engine=engine) is False
        release.set()
        future.result(timeout=15)
    assert results(client, headers, run)[0]["status"] == "valid"
    run = validation(client, headers, connection, [entry])
    with Session(engine) as db:
        row = db.get(ValidationRun, run)
        row.state, row.lease_owner = "running", "dead-worker"
        row.lease_until = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    run_batch(run, FakeMoodle(), pace=False, engine=engine)
    with Session(engine) as db:
        assert db.get(ValidationRun, run).recovery_count == 1
    assert results(client, headers, run)[0]["status"] == "valid"


def test_file_privacy_grants_and_revocation(environment):
    client, headers, connection, engine, _ = environment
    file, _ = imported(client, headers)
    first = create_user(client, headers, email="first@example.com").json()
    create_user(client, headers, email="second@example.com")
    operator = login(client, "first@example.com")
    other = login(client, "second@example.com")
    assert client.get(f"/api/v1/csv-files/{file['id']}", headers=operator).status_code == 404
    assert client.get("/api/v1/csv-files", headers=operator).json()["total"] == 0
    ownfile, entry = imported(client, operator)
    assert (
        client.get(f"/api/v1/csv-files/{ownfile['id']}/original", headers=other).status_code == 404
    )
    response = client.post(
        "/api/v1/validations",
        headers=operator,
        json={"connection_id": connection, "import_ids": [entry["id"]]},
    )
    assert response.status_code == 404
    assert (
        client.post(
            f"/api/v1/moodle-connections/{connection}/grants",
            headers=headers,
            json={"user_id": first["id"]},
        ).status_code
        == 201
    )
    run = validation(client, operator, connection, [entry])
    fake = FakeMoodle()
    fake.on_site = lambda: client.delete(
        f"/api/v1/moodle-connections/{connection}/grants/{first['id']}", headers=headers
    )
    run_batch(run, fake, pace=False, engine=engine)
    with Session(engine) as db:
        assert db.get(ValidationRun, run).error_code == "access_revoked"
    assert client.get(f"/api/v1/validations/{run}", headers=operator).status_code == 404
    assert client.get(f"/api/v1/validations/{run}/records", headers=other).status_code == 404


def test_checkpoint_continuation_reuses_persisted_cache(environment):
    client, headers, connection, engine, _ = environment
    approve(client, headers, connection)
    body = ("username,course1,role1\n" + "".join(f"u{i},BIO,5\n" for i in range(51))).encode()
    _, entry = imported(client, headers, body)
    run = validation(client, headers, connection, [entry])
    first = FakeMoodle()
    assert run_batch(run, first, pace=False, engine=engine) is True
    assert client.get(f"/api/v1/validations/{run}", headers=headers).json()["checked"] == 50
    second = FakeMoodle()
    assert run_batch(run, second, pace=False, engine=engine) is False
    state = client.get(f"/api/v1/validations/{run}", headers=headers).json()
    assert state["counts"] == {"valid": 51} and state["state"] == "completed"
    assert [name for name, _ in second.calls] == ["core_user_get_users_by_field"]


@pytest.mark.parametrize(
    "user,status,code",
    [
        ({"id": 10, "username": "alice", "suspended": True}, "invalid", "suspended_user"),
        ({"id": 10, "username": "alice"}, "pending", "suspension_not_disclosed"),
    ],
)
def test_suspension_is_not_assumed(environment, user, status, code):
    client, headers, connection, engine, _ = environment
    approve(client, headers, connection)
    _, entry = imported(client, headers)
    run = validation(client, headers, connection, [entry])
    fake = FakeMoodle()
    fake.user_override = [user]
    run_batch(run, fake, pace=False, engine=engine)
    record = results(client, headers, run)[0]
    assert record["status"] == status and record["error_code"] == code


def test_incomplete_membership_scan_stays_pending(environment, monkeypatch):
    from app.core.config import get_settings

    client, headers, connection, engine, _ = environment
    monkeypatch.setattr(get_settings(), "validation_max_pages", 1)
    approve(client, headers, connection)
    _, entry = imported(client, headers)
    run = validation(client, headers, connection, [entry])
    fake = FakeMoodle()
    fake.members = [{"id": 100 + i, "roles": [{"roleid": 5}], "groups": []} for i in range(100)]
    run_batch(run, fake, pace=False, engine=engine)
    assert results(client, headers, run)[0]["error_code"] == "enrollment_scan_limit"


def test_missing_function_and_unexpected_failure_are_visible(environment):
    client, headers, connection, engine, _ = environment
    _, entry = imported(client, headers)
    run = validation(client, headers, connection, [entry])
    fake = FakeMoodle()
    fake.names = []
    run_batch(run, fake, pace=False, engine=engine)
    assert (
        client.get(f"/api/v1/validations/{run}", headers=headers).json()["error_code"]
        == "function_unavailable"
    )
    run = validation(client, headers, connection, [entry])

    def crash():
        raise ValueError("must-not-leak-sensitive-context")

    fake = FakeMoodle()
    fake.on_site = crash
    with pytest.raises(RuntimeError, match="validation_worker_failed") as error:
        run_batch(run, fake, pace=False, engine=engine)
    assert "must-not-leak" not in str(error.value)
    assert (
        client.get(f"/api/v1/validations/{run}", headers=headers).json()["error_code"]
        == "internal_error"
    )


def test_recovery_sweep_broker_outage_and_retry_bound(environment, monkeypatch):
    from kombu.exceptions import OperationalError

    from app.tasks import validations as tasks

    client, headers, connection, engine, _ = environment
    _, entry = imported(client, headers)
    queued = validation(client, headers, connection, [entry])
    active = validation(client, headers, connection, [entry])
    expired = validation(client, headers, connection, [entry])
    with Session(engine) as db:
        live, dead = db.get(ValidationRun, active), db.get(ValidationRun, expired)
        live.state, live.lease_until = "running", datetime.now(UTC) + timedelta(minutes=1)
        dead.state, dead.lease_owner, dead.lease_until = (
            "running",
            "dead",
            datetime.now(UTC) - timedelta(seconds=1),
        )
        dead.recovery_count = 3
        db.commit()
    published = []
    original_enqueue = tasks.enqueue
    monkeypatch.setattr(tasks, "enqueue", lambda run_id: published.append(str(run_id)))
    tasks.recover.run()
    assert set(published) == {queued, expired}
    monkeypatch.setattr(tasks, "enqueue", original_enqueue)

    def broker_down(*args, **kwargs):
        raise OperationalError("broker-unavailable")

    monkeypatch.setattr(tasks.validate_batch, "apply_async", broker_down)
    tasks.enqueue(queued)
    with Session(engine) as db:
        assert db.get(ValidationRun, queued).state == "queued"
        assert db.get(ValidationRun, queued).dispatched_at is not None
    assert run_batch(expired, FakeMoodle(), pace=False, engine=engine) is False
    assert (
        client.get(f"/api/v1/validations/{expired}", headers=headers).json()["error_code"]
        == "recovery_limit"
    )


def test_shared_network_gate_limits_concurrency_and_request_rate(environment, redis_client):
    import time
    from threading import Lock

    from app.services.csv_parser import digest

    client, headers, connection, engine, _ = environment
    client.patch(
        f"/api/v1/moodle-connections/{connection}",
        headers=headers,
        json={"limits": {"requests_per_minute": 120}},
    )
    approve(client, headers, connection)
    _, entry = imported(client, headers)
    runs = [validation(client, headers, connection, [entry]) for _ in range(2)]
    state = {"active": 0, "maximum": 0, "times": []}
    lock = Lock()

    class MeasuredMoodle(FakeMoodle):
        def measured(self, fn, *args):
            with lock:
                state["active"] += 1
                state["maximum"] = max(state["maximum"], state["active"])
                state["times"].append(time.monotonic())
            try:
                time.sleep(0.03)
                return fn(*args)
            finally:
                with lock:
                    state["active"] -= 1

        def site_info(self, *args):
            return self.measured(super().site_info, *args)

        def read_call(self, *args):
            return self.measured(super().read_call, *args)

    prefix = "moodle:validation:" + digest("https://moodle.example.com")
    redis_client.delete(prefix + ":lock", prefix + ":slot")
    try:
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(run_batch, run, MeasuredMoodle(), True, engine) for run in runs]
            for future in futures:
                future.result(timeout=30)
        assert state["maximum"] == 1
        times = sorted(state["times"])
        assert len(times) == 8
        assert all(b - a >= 0.45 for a, b in pairwise(times))
        assert all(results(client, headers, run)[0]["status"] == "valid" for run in runs)
    finally:
        redis_client.delete(prefix + ":lock", prefix + ":slot")


def test_missing_enrollment_capability_never_claims_readiness(environment):
    client, headers, connection, engine, _ = environment
    approve(client, headers, connection)
    _, entry = imported(client, headers)
    run = validation(client, headers, connection, [entry])
    fake = FakeMoodle()
    fake.names.remove("enrol_manual_enrol_users")
    run_batch(run, fake, pace=False, engine=engine)
    assert results(client, headers, run)[0]["error_code"] == "enrollment_function_unavailable"
    assert results(client, headers, run)[0]["status"] == "pending"


def test_partial_visibility_never_proves_an_enrollment_absent(environment):
    client, headers, connection, engine, _ = environment
    approve(client, headers, connection, full_enrollment_visibility=False)
    _, entry = imported(client, headers)
    run = validation(client, headers, connection, [entry])
    run_batch(run, FakeMoodle(), pace=False, engine=engine)
    record = results(client, headers, run)[0]
    assert record["status"] == "pending"
    assert record["error_code"] == "enrollment_visibility_unverified"
