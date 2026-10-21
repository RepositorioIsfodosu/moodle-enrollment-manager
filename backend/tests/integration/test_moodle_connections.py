import os

import pytest
from sqlalchemy import select

from app.api.v1.endpoints.moodle import moodle_client
from app.core.token_vault import decrypt_token
from app.integrations.moodle.client import EVALUATED_FUNCTIONS, MoodleClient, MoodleError
from app.main import app
from app.models import AuditLog, MoodleConnection, MoodleConnectionCheck
from tests.helpers import create as create_user

# Reuse transaction-isolated PostgreSQL fixtures and real Redis login from phase 2.
from tests.helpers import login

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION") != "1", reason="Requires test PostgreSQL and Redis"
)
TOKEN = "simulator-secret-token-123456"


def create_connection(client, headers):
    return client.post(
        "/api/v1/moodle-connections",
        headers=headers,
        json={
            "name": "Moodle de pruebas",
            "base_url": "https://moodle.example.com/campus",
            "token": TOKEN,
            "description": "No real Moodle operations",
        },
    )


def test_create_update_token_and_no_secret_exposure(client, db, admin):
    headers = admin[1]
    response = create_connection(client, headers)
    assert response.status_code == 201, response.text
    data = response.json()
    assert TOKEN not in response.text and "ciphertext" not in response.text
    assert data["status"] == "unverified"
    assert data["service_url"] == "https://moodle.example.com/campus/webservice/rest/server.php"
    row = db.get(MoodleConnection, data["id"])
    assert TOKEN not in row.token_ciphertext
    assert decrypt_token(row.token_ciphertext) == TOKEN
    path = "/api/v1/moodle-connections/" + data["id"]
    assert (
        client.patch(
            path, headers=headers, json={"base_url": "https://other.example.com"}
        ).status_code
        == 422
    )
    response = client.patch(
        path, headers=headers, json={"token": "replacement-secret-token", "name": "Updated"}
    )
    assert response.status_code == 200 and "replacement-secret-token" not in response.text
    assert response.json()["configuration_version"] == 2
    db.expire_all()
    assert (
        decrypt_token(db.get(MoodleConnection, data["id"]).token_ciphertext)
        == "replacement-secret-token"
    )
    assert (
        client.patch(path, headers=headers, json={"base_url": "http://localhost"}).status_code
        == 422
    )
    assert client.patch(path, headers=headers, json={"active": None}).status_code == 422
    assert client.get("/api/v1/moodle-connections?limit=1", headers=headers).json()["total"] == 1
    assert client.get(path, headers=headers).status_code == 200


@pytest.mark.parametrize("role", ["operador", "supervisor", "consulta"])
def test_connection_permissions(client, admin, role):
    assert create_user(client, admin[1], role).status_code == 201
    headers = login(client, "operator@example.com")
    assert create_connection(client, headers).status_code == 403
    assert client.get("/api/v1/moodle-connections", headers=headers).status_code == 403


class FakeMoodle(MoodleClient):
    calls = 0
    missing = False
    error = None
    callback = None

    def site_info(self, base_url, token, timeout):
        from app.integrations.moodle.client import SiteInfo

        self.calls += 1
        assert token == TOKEN
        if self.callback:
            self.callback()
        if self.error:
            raise MoodleError(self.error)
        names = ["core_webservice_get_site_info"] if self.missing else EVALUATED_FUNCTIONS
        return SiteInfo(
            sitename="Test Moodle",
            siteurl=base_url,
            release="4.5",
            functions=[{"name": name} for name in names],
        ), 25


@pytest.fixture
def fake_moodle():
    fake = FakeMoodle()
    app.dependency_overrides[moodle_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(moodle_client, None)


def test_verification_history_and_cooldown(client, db, admin, fake_moodle):
    response = create_connection(client, admin[1])
    path = "/api/v1/moodle-connections/" + response.json()["id"]
    response = client.post(path + "/test", headers=admin[1])
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "verified"
    assert response.json()["missing_evaluated_functions"] == []
    assert response.json()["latency_ms"] == 25
    assert client.post(path + "/test", headers=admin[1]).status_code == 429
    assert fake_moodle.calls == 1
    history = client.get(path + "/checks", headers=admin[1])
    assert history.json()["total"] == 1
    assert history.json()["items"][0]["status"] == "verified"
    assert TOKEN not in history.text
    assert db.scalar(select(AuditLog).where(AuditLog.action == "moodle.probe_finished"))


@pytest.mark.parametrize(
    "error,missing,status",
    [(None, True, "limited"), ("invalid_token", False, "error"), ("timeout", False, "error")],
)
def test_limited_capabilities_and_safe_failures(
    client, db, admin, fake_moodle, error, missing, status
):
    fake_moodle.error, fake_moodle.missing = error, missing
    data = create_connection(client, admin[1]).json()
    response = client.post(f"/api/v1/moodle-connections/{data['id']}/test", headers=admin[1])
    assert response.status_code == 200
    assert response.json()["status"] == status
    assert response.json()["last_error_code"] == error
    assert db.scalar(select(MoodleConnectionCheck.status)) == status


def test_disable_and_stale_probe_result(client, db, admin, fake_moodle):
    data = create_connection(client, admin[1]).json()
    path = "/api/v1/moodle-connections/" + data["id"]
    assert (
        client.patch(path, headers=admin[1], json={"active": False}).json()["status"] == "disabled"
    )
    assert client.post(path + "/test", headers=admin[1]).status_code == 409
    assert fake_moodle.calls == 0
    assert (
        client.patch(path, headers=admin[1], json={"active": True}).json()["status"] == "unverified"
    )

    def changed():
        row = db.get(MoodleConnection, data["id"])
        row.configuration_version += 1
        db.commit()

    fake_moodle.callback = changed
    assert client.post(path + "/test", headers=admin[1]).status_code == 409
    assert db.scalar(select(MoodleConnectionCheck)) is None


def test_vault_failure_is_generic(client, admin, monkeypatch):
    from app.core.token_vault import VaultError

    def unavailable(*args):
        raise VaultError("secret-key-value")

    monkeypatch.setattr("app.api.v1.endpoints.moodle.encrypt_token", unavailable)
    response = create_connection(client, admin[1])
    assert response.status_code == 503 and "secret-key-value" not in response.text


def test_rotation_cli_is_atomic_and_supports_removing_old_key(redis_client, monkeypatch):
    import sys
    from uuid import UUID

    from cryptography.fernet import Fernet
    from pydantic import SecretStr
    from sqlalchemy import delete
    from sqlalchemy.orm import Session

    from app.cli import main
    from app.core.config import get_settings
    from app.core.token_vault import encrypt_token
    from app.db.session import get_engine

    old_key = get_settings().moodle_token_keys.get_secret_value()
    newest = Fernet.generate_key().decode()
    first, second = UUID(int=1), UUID(int=2)
    original = encrypt_token(TOKEN)
    with Session(get_engine()) as db:
        db.add_all(
            [
                MoodleConnection(
                    id=first,
                    name="rotation-test",
                    base_url="https://moodle.example.com",
                    token_ciphertext=original,
                ),
                MoodleConnection(
                    id=second,
                    name="invalid-test",
                    base_url="https://moodle.example.com",
                    token_ciphertext="invalid-ciphertext",
                ),
            ]
        )
        db.commit()
    monkeypatch.setattr(get_settings(), "moodle_token_keys", SecretStr(newest + "," + old_key))
    monkeypatch.setattr(sys, "argv", ["app.cli", "rotate-moodle-tokens"])
    try:
        with pytest.raises(SystemExit, match="No se cambiaron tokens"):
            main()
        with Session(get_engine()) as db:
            assert db.get(MoodleConnection, first).token_ciphertext == original
            db.execute(delete(MoodleConnection).where(MoodleConnection.id == second))
            db.commit()
        main()
        monkeypatch.setattr(get_settings(), "moodle_token_keys", SecretStr(newest))
        with Session(get_engine()) as db:
            assert decrypt_token(db.get(MoodleConnection, first).token_ciphertext) == TOKEN
    finally:
        with Session(get_engine()) as db:
            db.execute(delete(MoodleConnection).where(MoodleConnection.id.in_([first, second])))
            db.execute(delete(AuditLog).where(AuditLog.action == "moodle.tokens_rotated"))
            db.commit()


def test_full_probe_path_uses_real_client_and_sanitizes_metadata(client, db, admin, monkeypatch):
    import json
    from urllib.parse import parse_qs

    import httpx

    requests = []

    def handle(request):
        requests.append(request)
        assert parse_qs(request.content.decode())["wstoken"] == [TOKEN]
        assert request.url.host == "8.8.8.8"
        body = {
            "sitename": "REST simulator",
            "siteurl": "https://moodle.example.com/campus",
            "functions": [{"name": name} for name in EVALUATED_FUNCTIONS],
            "username": "private-username",
            "userpictureurl": "secret-extra-metadata",
        }
        return httpx.Response(200, stream=httpx.ByteStream(json.dumps(body).encode()))

    monkeypatch.setattr("app.integrations.moodle.client.resolve_public", lambda host: ["8.8.8.8"])
    monkeypatch.setattr(
        "app.integrations.moodle.client.httpx.HTTPTransport",
        lambda **kwargs: httpx.MockTransport(handle),
    )
    data = create_connection(client, admin[1]).json()
    response = client.post(f"/api/v1/moodle-connections/{data['id']}/test", headers=admin[1])
    assert response.status_code == 200 and response.json()["status"] == "verified"
    assert len(requests) == 1
    assert TOKEN not in response.text and "private-username" not in response.text
    assert "secret-extra-metadata" not in response.text
    assert db.get(MoodleConnection, data["id"]).site_metadata == {
        "sitename": "REST simulator",
        "release": None,
        "version": None,
    }


def test_unreadable_stored_token_is_audited_without_network_call(client, db, admin, fake_moodle):
    data = create_connection(client, admin[1]).json()
    connection = db.get(MoodleConnection, data["id"])
    connection.token_ciphertext = "unreadable-ciphertext"
    db.commit()
    response = client.post(f"/api/v1/moodle-connections/{data['id']}/test", headers=admin[1])
    assert response.status_code == 503
    assert "unreadable-ciphertext" not in response.text
    assert fake_moodle.calls == 0
    event = db.scalar(select(AuditLog).where(AuditLog.action == "moodle.probe_blocked"))
    assert event.safe_context == {"error_code": "encryption_unavailable"}
