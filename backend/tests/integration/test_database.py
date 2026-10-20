import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_engine
from app.main import app
from app.models import Base, User

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_INTEGRATION"), reason="Requires migrated PostgreSQL and Redis"
)


def test_migration_and_readiness():
    assert set(Base.metadata.tables) <= set(inspect(get_engine()).get_table_names())
    assert TestClient(app).get("/api/v1/health/ready").status_code == 200


def test_unique_email_and_rollback():
    with Session(get_engine()) as session:
        email = f"{uuid.uuid4()}@example.test"
        session.add_all(
            [
                User(email=email, password_hash="test-only"),
                User(email=email, password_hash="test-only"),
            ]
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


def test_foreign_key_rejects_unknown_user():
    from app.models import UserRole

    with Session(get_engine()) as session:
        session.add(UserRole(user_id=uuid.uuid4(), role_id=uuid.uuid4()))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


def test_job_state_constraint_exists():
    checks = inspect(get_engine()).get_check_constraints("enrollment_jobs")
    assert any("cancelled" in check["sqltext"] and "draft" in check["sqltext"] for check in checks)
