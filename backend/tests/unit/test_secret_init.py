import base64
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def initialization_script(tmp_path):
    original = Path(__file__).resolve().parents[3] / "scripts/init-secrets.py"
    target = tmp_path / "scripts/init-secrets.py"
    target.parent.mkdir()
    target.write_text(original.read_text())
    (tmp_path / "infrastructure").mkdir()
    return target, tmp_path / "infrastructure/.env"


def test_generation_is_secret_and_repeatable(initialization_script):
    script, env_file = initialization_script
    env_file.write_text("POSTGRES_USER=local-test\n")
    result = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, check=True
    )
    contents = env_file.read_text()
    key = contents.split("MOODLE_TOKEN_KEYS=")[1].strip()
    assert len(base64.urlsafe_b64decode(key)) == 32
    assert key not in result.stdout and key not in result.stderr
    subprocess.run([sys.executable, str(script)], capture_output=True, check=True)
    assert env_file.read_text() == contents
    assert contents.startswith("POSTGRES_USER=local-test\n")


@pytest.mark.parametrize(
    "binding",
    [
        "MOODLE_TOKEN_KEYS=test-only-keep",
        "export MOODLE_TOKEN_KEYS=test-only-keep",
        " MOODLE_TOKEN_KEYS = test-only-keep",
    ],
)
def test_preserves_existing_key_configuration(initialization_script, binding):
    script, env_file = initialization_script
    env_file.write_text(binding + "\n")
    subprocess.run([sys.executable, str(script)], capture_output=True, check=True)
    assert env_file.read_text() == binding + "\n"


def test_does_not_invent_database_configuration(initialization_script):
    script, env_file = initialization_script
    result = subprocess.run([sys.executable, str(script)], capture_output=True, check=False)
    assert result.returncode != 0
    assert not env_file.exists()
