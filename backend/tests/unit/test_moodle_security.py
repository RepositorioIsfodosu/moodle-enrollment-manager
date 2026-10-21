import base64
import json
from urllib.parse import parse_qs

import dns.exception
import httpx
import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from app.core.config import Settings
from app.core.token_vault import VaultError, decrypt_token, encrypt_token, rotate_token, vault
from app.integrations.moodle.client import EVALUATED_FUNCTIONS, MoodleClient, MoodleError
from app.integrations.moodle.urls import (
    UnsafeURL,
    normalize_base_url,
    public_address,
    resolve_public,
)


@pytest.mark.parametrize(
    "url",
    [
        "http://moodle.example.com",
        "https://localhost",
        "https://127.0.0.1",
        "https://[::1]",
        "https://user:password@moodle.example.com",
        "https://moodle.example.com:8443",
        "https://moodle.example.com?token=secret",
        "https://moodle.example.com#fragment",
        "https://moodle.example.com/../",
        "https://moodle.example.com/%2e%2e",
        "https://moodle.example.com\\@localhost",
        "https://moodle..example.com",
        "https://moodle.example.com./",
    ],
)
def test_unsafe_base_url(url):
    with pytest.raises(UnsafeURL):
        normalize_base_url(url)


def test_normalize_safe_base_path():
    assert (
        normalize_base_url("https://Moodle.Example.com:443/campus/")
        == "https://moodle.example.com/campus"
    )


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "168.63.129.16",
        "100.100.100.200",
        "0.0.0.0",
        "224.0.0.1",
        "::1",
        "fc00::1",
        "fe80::1",
        "::ffff:127.0.0.1",
        "2002:7f00:1::",
        "2001:db8::1",
    ],
)
def test_non_public_or_platform_address(address):
    assert not public_address(address)


def test_public_addresses():
    assert public_address("8.8.8.8")
    assert public_address("2606:4700:4700::1111")


def test_dns_rejects_mixed_answers_and_bounds_resolution(monkeypatch):
    calls = []

    class Resolver:
        def resolve(self, host, kind, **kwargs):
            calls.append((kind, kwargs))
            return ["8.8.8.8"] if kind == "A" else ["::1"]

    monkeypatch.setattr("app.integrations.moodle.urls.dns.resolver.Resolver", Resolver)
    with pytest.raises(UnsafeURL):
        resolve_public("moodle.example.com")
    assert [kind for kind, _ in calls] == ["A", "AAAA"]
    assert all(kwargs["lifetime"] == 3 and kwargs["search"] is False for _, kwargs in calls)


def test_dns_failure_is_sanitized(monkeypatch):
    class Resolver:
        def resolve(self, *args, **kwargs):
            raise dns.exception.Timeout("internal-dns-detail")

    monkeypatch.setattr("app.integrations.moodle.urls.dns.resolver.Resolver", Resolver)
    with pytest.raises(UnsafeURL) as error:
        resolve_public("moodle.example.com")
    assert "internal-dns-detail" not in str(error.value)


@pytest.fixture
def key_settings(monkeypatch):
    settings = Settings(
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        redis_url="redis://localhost/0",
        moodle_token_keys=Fernet.generate_key().decode(),
    )
    monkeypatch.setattr("app.core.token_vault.get_settings", lambda: settings)
    return settings


def test_encryption_and_rotation(key_settings):
    token = "test-token-secret-123456"
    ciphertext = encrypt_token(token)
    assert token not in ciphertext
    assert decrypt_token(ciphertext) == token
    original = key_settings.moodle_token_keys.get_secret_value()
    newest = Fernet.generate_key().decode()
    key_settings.moodle_token_keys = SecretStr(newest + "," + original)
    assert decrypt_token(ciphertext) == token
    rotated = rotate_token(ciphertext)
    key_settings.moodle_token_keys = SecretStr(newest)
    assert decrypt_token(rotated) == token
    with pytest.raises(VaultError):
        decrypt_token(ciphertext)
    corrupted = bytearray(base64.urlsafe_b64decode(rotated))
    corrupted[-10] ^= 1
    with pytest.raises(VaultError):
        decrypt_token(base64.urlsafe_b64encode(corrupted).decode())


@pytest.mark.parametrize("key", [None, "", "invalid", "ü", ","])
def test_missing_or_invalid_key_fails_closed(key_settings, key):
    key_settings.moodle_token_keys = SecretStr(key) if key is not None else None
    with pytest.raises(VaultError):
        vault()


def site_payload():
    return {
        "sitename": "Test Moodle",
        "siteurl": "https://moodle.example.com/campus",
        "release": "4.5",
        "version": "2024100700",
        "functions": [{"name": name, "version": "2024100700"} for name in EVALUATED_FUNCTIONS],
        "username": "private-remote-username",
        "userpictureurl": "not-retained",
    }


@pytest.fixture
def simulator(monkeypatch):
    requests, resolutions, options = [], [], []
    state = {"body": site_payload(), "status": 200, "headers": {}}

    def resolve(host):
        resolutions.append(host)
        return ["8.8.8.8"]

    def handler(request):
        requests.append(request)
        if "raise" in state:
            raise state["raise"]
        body = state.get("raw", json.dumps(state["body"]).encode())
        return httpx.Response(
            state["status"], headers=state["headers"], stream=httpx.ByteStream(body)
        )

    def transport(**kwargs):
        options.append(kwargs)
        return httpx.MockTransport(handler)

    monkeypatch.setattr("app.integrations.moodle.client.resolve_public", resolve)
    monkeypatch.setattr("app.integrations.moodle.client.httpx.HTTPTransport", transport)
    return state, requests, resolutions, options


def test_official_rest_contract_and_dns_pinning(simulator):
    _, requests, resolutions, options = simulator
    site, elapsed = MoodleClient().site_info(
        "https://moodle.example.com/campus", "test-token-secret-123456", 5
    )
    assert elapsed >= 0 and site.release == "4.5"
    assert resolutions == ["moodle.example.com"]  # No second hostname resolution before connecting.
    request = requests[0]
    assert request.url.host == "8.8.8.8"
    assert request.url.path == "/campus/webservice/rest/server.php"
    assert request.headers["Host"] == "moodle.example.com"
    assert request.extensions["sni_hostname"] == "moodle.example.com"
    assert options == [{"verify": True, "trust_env": False, "retries": 0}]
    assert not request.url.query
    assert parse_qs(request.content.decode()) == {
        "wstoken": ["test-token-secret-123456"],
        "wsfunction": ["core_webservice_get_site_info"],
        "moodlewsrestformat": ["json"],
    }
    assert request.method == "POST"


@pytest.mark.parametrize(
    "state,expected",
    [
        (
            {
                "body": {
                    "exception": "moodle_exception",
                    "errorcode": "invalidtoken",
                    "message": "secret-echo",
                }
            },
            "invalid_token",
        ),
        ({"body": {"errorcode": "accessexception"}}, "insufficient_permissions"),
        ({"body": {"errorcode": "servicenotavailable"}}, "function_unavailable"),
        ({"body": {"errorcode": []}}, "moodle_error"),
        ({"status": 302, "headers": {"Location": "http://127.0.0.1"}}, "redirect_not_allowed"),
        ({"status": 429}, "remote_rate_limited"),
        ({"status": 503}, "http_error"),
        ({"raw": b"<html>secret-echo</html>"}, "invalid_response"),
        ({"raw": b"X" * 1048577}, "response_too_large"),
        ({"headers": {"Content-Encoding": "gzip"}}, "invalid_response"),
        ({"raise": httpx.ReadTimeout("secret-echo")}, "timeout"),
        ({"raise": httpx.ConnectError("secret-echo")}, "transport_error"),
    ],
)
def test_remote_errors_are_classified_without_secret_echo(simulator, state, expected):
    simulation, requests, _, _ = simulator
    simulation.update(state)
    with pytest.raises(MoodleError) as error:
        MoodleClient().site_info("https://moodle.example.com/campus", "test-token-secret-123456", 5)
    assert error.value.code == expected
    assert "secret-echo" not in str(error.value)
    assert len(requests) == 1  # No retries or redirect follow.


def test_untrusted_site_url_and_sensitive_echo(simulator):
    state, _, _, _ = simulator
    state["body"]["siteurl"] = "https://another.example.com"
    with pytest.raises(MoodleError, match="site_url_mismatch"):
        MoodleClient().site_info("https://moodle.example.com/campus", "test-token-secret-123456", 5)
    state["body"] = site_payload() | {"sitename": "echo test-token-secret-123456"}
    with pytest.raises(MoodleError, match="sensitive_response"):
        MoodleClient().site_info("https://moodle.example.com/campus", "test-token-secret-123456", 5)


def test_private_dns_never_opens_transport_or_sends_token(simulator, monkeypatch):
    _, requests, _, options = simulator

    def rejected(host):
        raise UnsafeURL("private_address")

    monkeypatch.setattr("app.integrations.moodle.client.resolve_public", rejected)
    with pytest.raises(UnsafeURL):
        MoodleClient().site_info("https://moodle.example.com", "test-token-secret-123456", 5)
    assert requests == [] and options == []


def test_read_client_cannot_call_mutating_functions(simulator):
    _, requests, _, _ = simulator
    with pytest.raises(MoodleError, match="function_not_allowed"):
        MoodleClient().read_call(
            "https://moodle.example.com",
            "test-token",
            3,
            "enrol_manual_enrol_users",
            {"enrolments[0][userid]": "1"},
        )
    with pytest.raises(MoodleError, match="function_not_allowed"):
        MoodleClient().read_call(
            "https://moodle.example.com",
            "test-token",
            3,
            "core_user_get_users_by_field",
            {"wstoken": "override"},
        )
    assert requests == []


def test_read_client_uses_verified_user_search_parameters(simulator):
    state, requests, _, _ = simulator
    state["body"] = [{"id": 10, "username": "alice", "suspended": False}]
    payload, _ = MoodleClient().read_call(
        "https://moodle.example.com",
        "test-token",
        3,
        "core_user_get_users_by_field",
        {"field": "username", "values[0]": "alice", "values[1]": "bob"},
    )
    assert payload[0]["id"] == 10
    params = parse_qs(requests[0].content.decode())
    assert params["values[0]"] == ["alice"] and params["values[1]"] == ["bob"]
    assert params["wsfunction"] == ["core_user_get_users_by_field"]


@pytest.mark.parametrize("function", ["enrol_manual_enrol_users", "core_group_add_group_members"])
def test_explicit_write_contract_requires_null_response(monkeypatch, function):
    client = MoodleClient()
    monkeypatch.setattr(client, "_call", lambda *args: (None, 1))
    assert client.write_call("https://moodle.example.com", "test-only", 5, function, {}) == (
        None,
        1,
    )
    monkeypatch.setattr(client, "_call", lambda *args: ({"success": True}, 1))
    with pytest.raises(MoodleError, match="invalid_write_response"):
        client.write_call("https://moodle.example.com", "test-only", 5, function, {})


def test_write_client_cannot_override_authentication_or_call_arbitrary_functions():
    client = MoodleClient()
    for function, params in [
        ("core_user_create_users", {}),
        ("enrol_manual_enrol_users", {"wstoken": "override"}),
    ]:
        with pytest.raises(MoodleError, match="function_not_allowed"):
            client.write_call("https://moodle.example.com", "test-only", 5, function, params)
