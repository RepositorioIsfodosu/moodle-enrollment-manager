import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.cli import bootstrap_admin
from app.core.config import get_settings
from app.core.security import token_digest
from app.db.session import get_engine
from app.main import app
from app.models import AuditLog, AuthSession, User, UserRole
from app.schemas.auth import UserCreate
from app.services.auth import purge_expired_sessions

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_INTEGRATION"), reason="Requires test PostgreSQL and Redis"
)
PASSWORD = "test-password-very-long"


from tests.helpers import create, login


def test_bootstrap_only_once(db, admin):
    with pytest.raises(ValueError, match="Ya existe"):
        bootstrap_admin(
            db, UserCreate(email="another@example.com", password=PASSWORD, roles=["administrador"])
        )


def test_login_session_storage_me_logout(client, db, admin):
    user_id, headers = admin
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["roles"] == ["administrador"]
    assert "users:manage" in me.json()["permissions"]
    assert "password" not in me.text
    user = db.get(User, user_id)
    assert user.password_hash.startswith("$argon2id$")
    raw = headers["Authorization"].split()[1]
    stored = db.scalar(select(AuthSession).where(AuthSession.user_id == user_id))
    assert stored.token_hash == token_digest(raw)
    assert raw != stored.token_hash
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    assert (
        db.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "auth.logout")
        )
        == 1
    )


def test_anonymous_malformed_and_expired_session(client, db, admin):
    assert client.get("/api/v1/users").status_code == 401
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": "Bearer invalid"}).status_code
        == 401
    )
    db.query(AuthSession).update({"expires_at": datetime.now(UTC) - timedelta(seconds=1)})
    db.commit()
    assert client.get("/api/v1/auth/me", headers=admin[1]).status_code == 401
    assert purge_expired_sessions(db) == 1


@pytest.mark.parametrize(
    "role,audit_status", [("operador", 403), ("supervisor", 200), ("consulta", 403)]
)
def test_non_admin_permissions(client, admin, role, audit_status):
    response = create(client, admin[1], role)
    assert response.status_code == 201
    headers = login(client, "operator@example.com")
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
    assert client.get("/api/v1/users", headers=headers).status_code == 403
    assert create(client, headers, email="blocked@example.com").status_code == 403
    assert client.get("/api/v1/roles", headers=headers).status_code == 403
    assert client.get("/api/v1/audit-logs", headers=headers).status_code == audit_status


def test_user_creation_validation_conflict_and_pagination(client, admin):
    headers = admin[1]
    response = create(client, headers, email="Operator@Example.com")
    assert response.status_code == 201
    user = response.json()
    assert user["email"] == "operator@example.com"
    assert "password_hash" not in user
    assert create(client, headers).status_code == 409
    response = client.post(
        "/api/v1/users",
        headers=headers,
        json={"email": "bad", "password": "secret", "roles": ["root"]},
    )
    assert response.status_code == 422
    assert "secret" not in response.text
    assert "input" not in response.text
    assert client.get("/api/v1/users?limit=1", headers=headers).json()["total"] == 2
    assert len(client.get("/api/v1/users?limit=1", headers=headers).json()["items"]) == 1
    assert client.get("/api/v1/users?search=OPERATOR", headers=headers).json()["total"] == 1
    assert client.get("/api/v1/users?limit=101", headers=headers).status_code == 422
    assert client.get("/api/v1/users/" + str(uuid4()), headers=headers).status_code == 404


def test_last_admin_guard_and_role_revocation(client, admin):
    user_id, headers = admin
    path = f"/api/v1/users/{user_id}"
    assert client.patch(path, headers=headers, json={"active": False}).status_code == 409
    assert client.patch(path, headers=headers, json={"roles": ["consulta"]}).status_code == 409
    assert client.patch(path, headers=headers, json={"roles": []}).status_code == 422
    assert client.patch(path, headers=headers, json={"active": None}).status_code == 422
    second = create(client, headers, "administrador").json()
    second_headers = login(client, "operator@example.com")
    assert (
        client.patch(path, headers=second_headers, json={"roles": ["consulta"]}).status_code == 200
    )
    assert client.get("/api/v1/users", headers=headers).status_code == 401
    new_headers = login(client, "admin@example.com")
    assert client.get("/api/v1/users", headers=new_headers).status_code == 403
    assert second["active"]


def test_deactivation_and_password_reset_revoke_sessions(client, admin):
    response = create(client, admin[1])
    target = response.json()["id"]
    headers = login(client, "operator@example.com")
    assert (
        client.patch(
            f"/api/v1/users/{target}", headers=admin[1], json={"active": False}
        ).status_code
        == 200
    )
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": "operator@example.com", "password": PASSWORD}
        ).status_code
        == 401
    )
    assert (
        client.patch(f"/api/v1/users/{target}", headers=admin[1], json={"active": True}).status_code
        == 200
    )
    headers = login(client, "operator@example.com")
    assert (
        client.post(
            f"/api/v1/users/{target}/reset-password",
            headers=admin[1],
            json={"new_password": "replacement-password"},
        ).status_code
        == 204
    )
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": "operator@example.com", "password": PASSWORD}
        ).status_code
        == 401
    )
    login(client, "operator@example.com", "replacement-password")


def test_password_change_and_logout_all(client, admin):
    headers = admin[1]
    another = login(client, "admin@example.com")
    assert (
        client.post(
            "/api/v1/auth/change-password",
            headers=headers,
            json={"current_password": "incorrect", "new_password": "new-password-long"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/auth/change-password",
            headers=headers,
            json={"current_password": PASSWORD, "new_password": "new-password-long"},
        ).status_code
        == 204
    )
    assert client.get("/api/v1/auth/me", headers=another).status_code == 401
    headers = login(client, "admin@example.com", "new-password-long")
    another = login(client, "admin@example.com", "new-password-long")
    assert client.post("/api/v1/auth/logout-all", headers=headers).status_code == 204
    assert client.get("/api/v1/auth/me", headers=another).status_code == 401


def test_login_errors_are_generic_and_audited(client, admin, db):
    responses = [
        client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-secret"})
        for email in ("admin@example.com", "missing@example.com")
    ]
    assert responses[0].status_code == responses[1].status_code == 401
    assert responses[0].json() == responses[1].json()
    logs = list(db.scalars(select(AuditLog).where(AuditLog.action == "auth.login_failed")))
    assert len(logs) == 2
    assert all("secret" not in str(log.safe_context) for log in logs)


def test_rate_limit_ignores_forwarded_ip_and_is_atomic(client, admin, monkeypatch):
    monkeypatch.setattr(get_settings(), "login_account_limit", 2)
    for _ in range(2):
        response = client.post(
            "/api/v1/auth/login",
            headers={"X-Forwarded-For": str(uuid4())},
            json={"email": "missing@example.com", "password": "wrong"},
        )
        assert response.status_code == 401
    response = client.post(
        "/api/v1/auth/login", json={"email": "missing@example.com", "password": "wrong"}
    )
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0


def test_login_fails_closed_without_redis(client, monkeypatch):
    def unavailable(*args, **kwargs):
        raise RedisConnectionError("sensitive-redis-address")

    monkeypatch.setattr("app.services.auth.Redis.from_url", unavailable)
    response = client.post(
        "/api/v1/auth/login", json={"email": "missing@example.com", "password": "wrong"}
    )
    assert response.status_code == 503
    assert "sensitive" not in response.text


def test_audit_filter_dates_and_denials(client, admin):
    create(client, admin[1])
    operator = login(client, "operator@example.com")
    client.get("/api/v1/users", headers=operator)
    logs = client.get("/api/v1/audit-logs?action=authorization.denied&limit=1", headers=admin[1])
    assert logs.status_code == 200
    assert logs.json()["total"] == 1
    assert logs.json()["items"][0]["safe_context"] == {"permission": "users:manage"}
    assert PASSWORD not in logs.text
    assert client.get("/api/v1/audit-logs?since=2026-01-01", headers=admin[1]).status_code == 422


def test_concurrent_admin_demotion_and_duplicate_creation(redis_client):
    # Separate committed connections exercise the real PostgreSQL advisory lock.
    assert not app.dependency_overrides
    user_ids = []
    with Session(get_engine()) as db:
        user_ids.append(
            bootstrap_admin(
                db,
                UserCreate(
                    email="parallel-admin@example.com", password=PASSWORD, roles=["administrador"]
                ),
            )
        )
    try:
        with TestClient(app) as client:
            first = login(client, "parallel-admin@example.com")
            barrier = Barrier(2)

            def create_same(_):
                with TestClient(app) as c:
                    barrier.wait(timeout=10)
                    return create(c, first, "administrador", "parallel-second@example.com")

            with ThreadPoolExecutor(2) as pool:
                responses = list(pool.map(create_same, range(2)))
            assert sorted(r.status_code for r in responses) == [201, 409]
            second_id = next(r.json()["id"] for r in responses if r.status_code == 201)
            user_ids.append(second_id)
            second = login(client, "parallel-second@example.com")
            barrier = Barrier(2)

            def demote(item):
                user_id, headers = item
                with TestClient(app) as c:
                    barrier.wait(timeout=10)
                    return c.patch(
                        f"/api/v1/users/{user_id}", headers=headers, json={"roles": ["consulta"]}
                    ).status_code

            with ThreadPoolExecutor(2) as pool:
                statuses = list(pool.map(demote, [(user_ids[0], first), (second_id, second)]))
            assert sorted(statuses) == [200, 409]
    finally:
        with Session(get_engine()) as db:
            db.execute(delete(AuthSession).where(AuthSession.user_id.in_(user_ids)))
            db.execute(delete(UserRole).where(UserRole.user_id.in_(user_ids)))
            db.execute(delete(AuditLog).where(AuditLog.actor_id.in_(user_ids)))
            db.execute(delete(User).where(User.id.in_(user_ids)))
            db.commit()


def test_ip_limit_cannot_be_bypassed_with_forwarded_headers(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "login_ip_limit", 2)
    for index in range(2):
        response = client.post(
            "/api/v1/auth/login",
            headers={"X-Forwarded-For": f"192.0.2.{index}"},
            json={"email": f"missing{index}@example.com", "password": "wrong"},
        )
        assert response.status_code == 401
    response = client.post(
        "/api/v1/auth/login",
        headers={"X-Forwarded-For": "192.0.2.3"},
        json={"email": "other@example.com", "password": "wrong"},
    )
    assert response.status_code == 429


def test_atomic_limiter_with_concurrent_clients(redis_client, monkeypatch):
    from fastapi import HTTPException, Request

    from app.services.auth import login_limit

    monkeypatch.setattr(get_settings(), "login_ip_limit", 2)
    barrier = Barrier(6)

    def attempt(index):
        request = Request({"type": "http", "client": ("192.0.2.50", index), "headers": []})
        barrier.wait(timeout=10)
        try:
            login_limit(request, f"parallel{index}@example.com")
        except HTTPException as error:
            return error.status_code
        return 200

    with ThreadPoolExecutor(6) as pool:
        results = list(pool.map(attempt, range(6)))
    assert results.count(200) == 2
    assert results.count(429) == 4
