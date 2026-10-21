import os
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditLog, AuthSession, CsvFile, ValidationCache, ValidationRun
from app.services.maintenance import purge_transient
from tests.integration.test_imports import environment as environment  # noqa: PLC0414
from tests.integration.test_imports import imported

pytestmark = pytest.mark.skipif(os.getenv("RUN_INTEGRATION") != "1", reason="Dedicated services")


def test_retention_dry_run_and_execution_preserve_history(environment):
    c, h, connection, engine, owner = environment
    imported(c, h)
    with Session(engine) as db:
        old = datetime.now(UTC) - timedelta(days=60)
        states = ["completed", "failed", "cancelled", "running", "queued"]
        for state in states:
            run = ValidationRun(
                owner_id=owner,
                connection_id=UUID(connection),
                configuration_version=1,
                import_ids=[],
                state=state,
                finished_at=old,
            )
            db.add(run)
            db.flush()
            db.add(ValidationCache(run_id=run.id, key=state, value={"items": []}))
        fresh = ValidationRun(
            owner_id=owner,
            connection_id=UUID(connection),
            configuration_version=1,
            import_ids=[],
            state="completed",
            finished_at=datetime.now(UTC),
        )
        db.add(fresh)
        db.flush()
        db.add(ValidationCache(run_id=fresh.id, key="fresh", value={}))
        db.add(AuthSession(user_id=owner, token_hash="a" * 64, expires_at=old))
        db.commit()
        assert purge_transient(db) == {"auth_sessions": 1, "validation_cache": 3}
        assert db.scalar(select(func.count()).select_from(ValidationCache)) == 6
        assert purge_transient(db, execute=True) == {"auth_sessions": 1, "validation_cache": 3}
        assert db.scalar(select(func.count()).select_from(ValidationCache)) == 3
        assert db.scalar(select(func.count()).select_from(ValidationRun)) == 6
        assert db.scalar(select(func.count()).select_from(CsvFile)) == 1
        assert db.scalar(select(AuditLog).where(AuditLog.action == "maintenance.transient_purged"))
        assert purge_transient(db, execute=True) == {"auth_sessions": 0, "validation_cache": 0}
    assert c.get("/api/v1/auth/me", headers=h).status_code == 200


def test_retention_rejects_unsafe_period(environment):
    with Session(environment[3]) as db:
        for days in [0, 6, 3651]:
            with pytest.raises(ValueError):
                purge_transient(db, days=days, execute=True)
