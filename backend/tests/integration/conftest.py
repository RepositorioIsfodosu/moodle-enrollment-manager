import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy.orm import Session

from app.cli import bootstrap_admin
from app.core.config import get_settings
from app.db.session import get_engine, get_session
from app.main import app
from app.schemas.auth import UserCreate
from tests.helpers import PASSWORD, login


@pytest.fixture
def redis_client():
    client = Redis.from_url(get_settings().redis_url.get_secret_value())
    # Dedicated test Redis only. Never flush an application broker.
    if not get_engine().url.database.endswith("_test"):
        pytest.fail("Authentication tests require a dedicated database ending in _test")
    keys = list(client.scan_iter("auth:login:*"))
    if keys:
        client.delete(*keys)
    yield client
    client.close()


@pytest.fixture
def db(redis_client):
    connection = get_engine().connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    app.dependency_overrides[get_session] = lambda: session
    yield session
    app.dependency_overrides.clear()
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(db):
    with TestClient(app) as client:
        yield client


@pytest.fixture
def admin(db, client):
    user_id = bootstrap_admin(
        db, UserCreate(email="admin@example.com", password=PASSWORD, roles=["administrador"])
    )
    return user_id, login(client, "admin@example.com")
