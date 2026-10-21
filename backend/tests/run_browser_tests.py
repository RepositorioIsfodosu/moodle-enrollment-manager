"""Run the real API, Redis worker and Vite against disposable services, then stop them."""

import os
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen
from uuid import uuid4

from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.permissions import ROLE_PERMISSIONS
from app.db.session import get_engine
from app.models import Base, Role
from app.services.database_roles import configure_runtime_role


@contextmanager
def test_database(original):
    schema = "browsertest_" + uuid4().hex
    role = "browser_runtime_" + uuid4().hex[:12]
    password = secrets.token_urlsafe(32)
    schema_created = role_created = False
    owner_url = original.url.update_query_dict({"options": "-csearch_path=" + schema})
    owner = create_engine(owner_url)
    try:
        with original.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        schema_created = True
        Base.metadata.create_all(owner)
        with owner.begin() as connection:
            connection.execute(
                text("CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)")
            )
            connection.execute(text("INSERT INTO alembic_version VALUES ('0006')"))
        with Session(owner) as db:
            db.add_all(Role(name=name) for name in ROLE_PERMISSIONS)
            db.commit()
            configure_runtime_role(db, role, password=password, schema=schema)
        role_created = True
        yield (
            owner_url.render_as_string(hide_password=False),
            owner_url.set(username=role, password=password).render_as_string(hide_password=False),
        )
    finally:
        owner.dispose()
        with original.begin() as connection:
            if role_created:
                connection.exec_driver_sql(f'DROP OWNED BY "{role}"')
                connection.exec_driver_sql(f'DROP ROLE "{role}"')
            if schema_created:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


def main():
    if os.getenv("RUN_BROWSER_TESTS") != "1" or not get_engine().url.database.endswith("_test"):
        raise RuntimeError(
            "Requires explicit RUN_BROWSER_TESTS=1 and dedicated *_test database/Redis"
        )
    backend = Path(__file__).resolve().parents[1]
    frontend = backend.parent / "frontend"
    environment = os.environ | {
        "MOODLE_TOKEN_KEYS": Fernet.generate_key().decode(),
        "ENROLLMENT_WRITES_ENABLED": "false",
        "SESSION_COOKIE_SECURE": "false",
        "API_PROXY_TARGET": "http://127.0.0.1:18000",
        "E2E_BASE_URL": "http://127.0.0.1:15173",
    }
    if "PLAYWRIGHT_CHROMIUM_EXECUTABLE" not in environment and shutil.which("chromium"):
        environment["PLAYWRIGHT_CHROMIUM_EXECUTABLE"] = shutil.which("chromium")
    original = get_engine()
    with test_database(original) as (owner_url, runtime_url):
        environment["DATABASE_URL"] = owner_url
        processes = []
        with tempfile.TemporaryDirectory(prefix="mem-browser-") as temporary, ExitStack() as logs:
            environment["E2E_SEED_PATH"] = str(Path(temporary) / "seed.json")
            subprocess.run(
                [sys.executable, "-m", "tests.browser_seed"],
                cwd=backend,
                env=environment,
                check=True,
            )
            environment["DATABASE_URL"] = runtime_url
            commands = [
                (
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "app.main:app",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        "18000",
                        "--no-proxy-headers",
                    ],
                    backend,
                ),
                (
                    [
                        sys.executable,
                        "-m",
                        "celery",
                        "-A",
                        "app.workers.celery_app:celery_app",
                        "worker",
                        "--pool=solo",
                        "--concurrency=1",
                        "--queues=validation",
                        "--hostname=ui-validation@%h",
                        "--loglevel=WARNING",
                    ],
                    backend,
                ),
                (["npm", "run", "dev", "--", "--port", "15173", "--strictPort"], frontend),
            ]
            try:
                for index, (command, directory) in enumerate(commands):
                    log = logs.enter_context(open(Path(temporary) / f"process-{index}.log", "w+"))
                    processes.append(
                        subprocess.Popen(
                            command,
                            cwd=directory,
                            env=environment,
                            stdout=log,
                            stderr=subprocess.STDOUT,
                            start_new_session=os.name == "posix",
                        )
                    )
                for endpoint in [
                    "http://127.0.0.1:18000/api/v1/health/live",
                    environment["E2E_BASE_URL"],
                ]:
                    deadline = time.monotonic() + 30
                    while True:
                        if any(process.poll() is not None for process in processes):
                            raise RuntimeError("A browser test service exited during startup")
                        try:
                            with urlopen(endpoint, timeout=1) as response:
                                if response.status == 200:
                                    break
                        except (URLError, TimeoutError):
                            pass
                        if time.monotonic() > deadline:
                            raise RuntimeError("Browser test service did not start")
                        time.sleep(0.2)
                subprocess.run(
                    ["npm", "run", "test:e2e"], cwd=frontend, env=environment, check=True
                )
            except BaseException:
                destination = frontend / "test-results" / "services"
                destination.mkdir(parents=True, exist_ok=True)
                for log in Path(temporary).glob("process-*.log"):
                    shutil.copyfile(log, destination / log.name)
                raise
            finally:
                for process in reversed(processes):
                    if os.name == "posix":
                        try:
                            os.killpg(process.pid, signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                    else:
                        process.terminate()
                for process in reversed(processes):
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        if os.name == "posix":
                            os.killpg(process.pid, signal.SIGKILL)
                        else:
                            process.kill()
                        process.wait()


if __name__ == "__main__":
    main()
