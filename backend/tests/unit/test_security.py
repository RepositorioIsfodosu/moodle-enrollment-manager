import pytest
from pydantic import ValidationError

from app.core.permissions import permissions_for
from app.core.security import hash_password, token_digest, verify_password
from app.schemas.auth import UserCreate


def test_argon2id_and_verification():
    encoded = hash_password("correct-test-password")
    assert encoded.startswith("$argon2id$")
    assert encoded != "correct-test-password"
    assert verify_password("correct-test-password", encoded)
    assert not verify_password("wrong-password", encoded)
    assert not verify_password("any", "invalid-hash")
    assert hash_password("correct-test-password") != encoded


def test_token_digest_is_deterministic():
    assert token_digest("token") == token_digest("token")
    assert len(token_digest("token")) == 64
    assert token_digest("token") != token_digest("other")


@pytest.mark.parametrize(
    "role,permission,expected",
    [
        ("administrador", "users:manage", True),
        ("operador", "users:manage", False),
        ("operador", "jobs:write", True),
        ("supervisor", "jobs:write", False),
        ("supervisor", "audit:read", True),
        ("consulta", "reports:read", False),
        ("unknown", "users:manage", False),
    ],
)
def test_role_permissions(role, permission, expected):
    assert (permission in permissions_for([role])) is expected


@pytest.mark.parametrize(
    "changes",
    [
        {"password": "short"},
        {"password": "x" * 129},
        {"email": "not-an-email"},
        {"roles": ["root"]},
        {"roles": []},
    ],
)
def test_rejects_invalid_user_input(changes):
    data = {"email": "person@example.com", "password": "test-long-password", "roles": ["operador"]}
    with pytest.raises(ValidationError):
        UserCreate(**(data | changes))
