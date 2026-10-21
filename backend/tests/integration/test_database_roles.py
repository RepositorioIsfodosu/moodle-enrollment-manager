import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.services.database_roles import DatabaseRoleError, configure_runtime_role
from app.services.enrollment_engine import run_batch
from tests.helpers import create
from tests.integration.test_enrollment_engine import WritableMoodle, setup
from tests.integration.test_imports import environment as environment  # noqa: PLC0414

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION") != "1", reason="Dedicated PostgreSQL/Redis"
)
PASSWORD = "runtime-test-password-long$#@"


@pytest.fixture
def restricted(environment, monkeypatch):
    c, h, connection, owner, admin = environment
    schema = owner.get_execution_options()["schema_translate_map"][None]
    role = "runtime_test_" + uuid4().hex[:12]
    with owner.begin() as db:
        db.execute(
            text(f'CREATE TABLE "{schema}".alembic_version (version_num varchar(32) PRIMARY KEY)')
        )
        db.execute(text(f"INSERT INTO \"{schema}\".alembic_version VALUES ('0006')"))
    with Session(owner) as db:
        configure_runtime_role(db, role, password=PASSWORD, schema=schema)
    runtime = create_engine(
        owner.url.set(username=role, password=PASSWORD).update_query_dict(
            {"options": "-csearch_path=" + schema}
        ),
        hide_parameters=True,
    ).execution_options(schema_translate_map={None: schema})
    monkeypatch.setattr("app.db.session.get_engine", lambda: runtime)
    try:
        yield (c, h, connection, runtime, admin), owner, role, schema
    finally:
        runtime.dispose()
        with owner.begin() as db:
            db.exec_driver_sql(f'DROP OWNED BY "{role}"')
            db.exec_driver_sql(f'DROP ROLE "{role}"')


def test_runtime_can_authenticate_import_validate_execute_report_and_manage_users(
    restricted, monkeypatch
):
    env, _, role, _ = restricted
    c, h, _, runtime, _ = env
    with runtime.connect() as db:
        assert db.scalar(text("SELECT current_user")) == role
    user = create(c, h, email="reduced@example.com")
    assert user.status_code == 201, user.text
    changed = c.patch(
        "/api/v1/users/" + user.json()["id"], headers=h, json={"roles": ["supervisor"]}
    )
    assert changed.status_code == 200, changed.text
    job = setup(env, monkeypatch)
    fake = WritableMoodle()
    assert run_batch(job, client=fake, pace=False, engine=runtime) is False
    result = c.get("/api/v1/enrollment-jobs/" + job, headers=h)
    assert result.json()["counts"] == {"confirmed": 1}
    for format in ["csv", "xlsx", "pdf"]:
        r = c.get("/api/v1/reports/export", headers=h, params={"job_id": job, "format": format})
        assert r.status_code == 200, r.text
    assert c.post("/api/v1/auth/logout", headers=h).status_code == 204


def test_runtime_cannot_modify_schema_roles_audit_or_originals(restricted):
    env, _, _, schema = restricted
    runtime = env[3]
    denied = [
        f'CREATE TABLE "{schema}".forbidden (id int)',
        f'ALTER TABLE "{schema}".users ADD COLUMN forbidden text',
        f'DELETE FROM "{schema}".audit_logs WHERE false',
        f"UPDATE \"{schema}\".audit_logs SET action='tampered' WHERE false",
        f'TRUNCATE "{schema}".job_events',
        f'DELETE FROM "{schema}".csv_contents WHERE false',
        f"UPDATE \"{schema}\".roles SET name='forbidden' WHERE false",
        f"UPDATE \"{schema}\".alembic_version SET version_num='bad' WHERE false",
    ]
    for statement in denied:
        with pytest.raises(DBAPIError), runtime.begin() as db:
            db.exec_driver_sql(statement)
    with runtime.connect() as db:
        flags = db.execute(
            text(
                "SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,rolinherit FROM pg_roles WHERE rolname=current_user"
            )
        ).one()
        assert not any(flags)


def test_refuses_existing_password_reset_and_role_memberships(restricted):
    _, owner, role, schema = restricted
    with Session(owner) as db, pytest.raises(DatabaseRoleError, match="ya existe"):
        configure_runtime_role(db, role, password="different-test-password-long", schema=schema)
    with owner.begin() as db:
        db.exec_driver_sql(f'CREATE TABLE "{schema}".owned_probe (id int)')
        db.exec_driver_sql(f'ALTER TABLE "{schema}".owned_probe OWNER TO "{role}"')
    with Session(owner) as db, pytest.raises(DatabaseRoleError, match="propietario"):
        configure_runtime_role(db, role, schema=schema)
    with owner.begin() as db:
        db.exec_driver_sql(f'ALTER TABLE "{schema}".owned_probe OWNER TO "{owner.url.username}"')
        db.exec_driver_sql(f'GRANT pg_monitor TO "{role}"')
    with Session(owner) as db, pytest.raises(DatabaseRoleError, match="otros roles"):
        configure_runtime_role(db, role, schema=schema)


def test_public_grants_fail_closed_and_future_tables_are_not_automatically_granted(restricted):
    env, owner, role, schema = restricted
    with owner.begin() as db:
        db.exec_driver_sql(f'CREATE TABLE "{schema}".future_data (secret text)')
    with pytest.raises(DBAPIError), env[3].begin() as db:
        db.exec_driver_sql(f'SELECT * FROM "{schema}".future_data')
    with owner.begin() as db:
        db.exec_driver_sql(f'GRANT UPDATE ON "{schema}".audit_logs TO PUBLIC')
    try:
        with Session(owner) as db, pytest.raises(DatabaseRoleError, match="externos"):
            configure_runtime_role(db, role, schema=schema)
    finally:
        with owner.begin() as db:
            db.exec_driver_sql(f'REVOKE UPDATE ON "{schema}".audit_logs FROM PUBLIC')
    with owner.begin() as db:
        db.exec_driver_sql(f'GRANT CREATE ON SCHEMA "{schema}" TO PUBLIC')
    try:
        with Session(owner) as db, pytest.raises(DatabaseRoleError, match="CREATE"):
            configure_runtime_role(db, role, schema=schema)
    finally:
        with owner.begin() as db:
            db.exec_driver_sql(f'REVOKE CREATE ON SCHEMA "{schema}" FROM PUBLIC')
