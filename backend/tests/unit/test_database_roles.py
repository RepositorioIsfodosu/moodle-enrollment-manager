import importlib.util
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from app.services.database_roles import DatabaseRoleError, valid_identifier, validate_runtime_target

OWNER = "postgresql+psycopg://owner:owner-test-only@db/enrollment"
RUNTIME = "postgresql+psycopg://mem_runtime:runtime-test-only@db/enrollment"


@pytest.mark.parametrize("name", ["ADMIN", "x;drop role x", "pg role", "a" * 49, "1user", ""])
def test_invalid_identifiers_rejected(name):
    with pytest.raises(DatabaseRoleError):
        valid_identifier(name)


@pytest.mark.parametrize(
    "url",
    [
        "not a URL",
        "postgresql+psycopg://owner:password@db/enrollment",
        "postgresql+psycopg://mem_runtime@db/enrollment",
        "postgresql+psycopg://mem_runtime:password@other/enrollment",
        "postgresql+psycopg://mem_runtime:password@db/other",
        "postgresql+psycopg://mem_runtime:password@db:5433/enrollment",
        "postgresql://mem_runtime:password@db/enrollment",
    ],
)
def test_runtime_target_mismatch_rejected_without_exposing_url(url):
    with pytest.raises(DatabaseRoleError) as error:
        validate_runtime_target(OWNER, url, "mem_runtime")
    assert url not in str(error.value)


def test_runtime_url_and_default_port():
    assert validate_runtime_target(OWNER, RUNTIME, "mem_runtime").username == "mem_runtime"
    assert validate_runtime_target(OWNER, RUNTIME.replace("@db/", "@db:5432/"), "mem_runtime")

    for suffix in [
        "?host=other",
        "?hostaddr=127.0.0.1",
        "?dbname=other",
        "?service=other",
        "?options=-csearch_path=other",
        "?sslmode=require&sslmode=disable",
    ]:
        with pytest.raises(DatabaseRoleError):
            validate_runtime_target(OWNER, RUNTIME + suffix, "mem_runtime")
    assert validate_runtime_target(OWNER, RUNTIME + "?sslmode=require", "mem_runtime")


def test_private_url_file_encodes_password_and_never_overwrites(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[3] / "scripts/runtime-url.py"
    spec = importlib.util.spec_from_file_location("runtime_url_script", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target = tmp_path / "runtime.env"
    password = "test$#@:/'+percent% space-long"
    module.write_runtime_env(target, password)
    content = target.read_text()
    assert password not in content
    url = content.split("RUNTIME_DATABASE_URL=", 1)[1].strip().strip("'")
    assert make_url(url).password == password and make_url(url).username == "mem_runtime"
    with pytest.raises(FileExistsError):
        module.write_runtime_env(target, "different-password-long")
    assert target.read_text() == content

    failed = tmp_path / "failed.env"

    def fail_sync(fd):
        raise OSError("simulated disk failure")

    with monkeypatch.context() as patch:
        patch.setattr(module.os, "fsync", fail_sync)
        with pytest.raises(OSError):
            module.write_runtime_env(failed, password)
    assert not failed.exists()
