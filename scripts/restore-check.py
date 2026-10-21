"""Restore only to a new network-isolated disposable PostgreSQL container; never production."""

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path
from uuid import uuid4


def restore_check(source):
    path = Path(source).resolve()
    expected = path.with_suffix(path.suffix + ".sha256").read_text().strip()
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
            raise ValueError("Checksum del respaldo no coincide")
    name = "mem-restore-check-" + uuid4().hex
    created = False
    try:
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                name,
                "--network",
                "none",
                "--memory",
                "512m",
                "--cpus",
                "1",
                "--pids-limit",
                "256",
                "-e",
                "POSTGRES_USER=enrollment",
                "-e",
                "POSTGRES_DB=enrollment_restore_test",
                "-e",
                "POSTGRES_HOST_AUTH_METHOD=trust",
                "postgres:16-alpine",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=True,
        )
        created = True
        deadline = time.monotonic() + 45
        while True:
            ready = subprocess.run(
                [
                    "docker",
                    "exec",
                    name,
                    "pg_isready",
                    "-U",
                    "enrollment",
                    "-d",
                    "enrollment_restore_test",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if ready.returncode == 0:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("PostgreSQL temporal no está listo")
            time.sleep(0.5)
        with path.open("rb") as stream:
            subprocess.run(
                [
                    "docker",
                    "exec",
                    "-i",
                    name,
                    "pg_restore",
                    "-U",
                    "enrollment",
                    "-d",
                    "enrollment_restore_test",
                    "--exit-on-error",
                    "--no-owner",
                    "--no-acl",
                ],
                stdin=stream,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                check=True,
            )
        query = """SELECT json_build_object(
            'revision',(SELECT version_num FROM alembic_version),
            'users',(SELECT count(*) FROM users),
            'connections',(SELECT count(*) FROM moodle_connections),
            'csv_files',(SELECT count(*) FROM csv_files),
            'csv_contents',(SELECT count(*) FROM csv_contents),
            'csv_content_bytes',(SELECT coalesce(sum(octet_length(content)),0) FROM csv_contents),
            'jobs',(SELECT count(*) FROM enrollment_jobs),
            'records',(SELECT count(*) FROM enrollment_records),
            'audit_logs',(SELECT count(*) FROM audit_logs))"""
        result = subprocess.run(
            [
                "docker",
                "exec",
                name,
                "psql",
                "-U",
                "enrollment",
                "-d",
                "enrollment_restore_test",
                "-Atqc",
                query,
            ],
            capture_output=True,
            check=True,
            text=True,
        )
        value = json.loads(result.stdout)
        if value["revision"] != "0006":
            raise ValueError("Revisión inesperada; revisar compatibilidad antes de restaurar")
        return value
    finally:
        if created:
            subprocess.run(
                ["docker", "rm", "-f", "-v", name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )


def main():
    parser = argparse.ArgumentParser(
        description="Comprobar restauración aislada de un respaldo confiable"
    )
    parser.add_argument("source")
    args = parser.parse_args()
    try:
        result = restore_check(args.source)
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError):
        raise SystemExit(
            "La restauración aislada no se completó. Verificar checksum, formato, Docker y revisión; no se modificó la aplicación."
        ) from None
    print(json.dumps(result))
    print(
        "Contenedor temporal eliminado. No valida recuperación de claves, RPO/RTO ni aceptación Moodle."
    )


if __name__ == "__main__":
    main()
