"""Portable binary-safe pg_dump; never overwrite or save backups in the checkout."""

import argparse
import hashlib
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def backup(destination, env_file, compose_file):
    path = Path(destination).resolve()
    manifest = path.with_suffix(path.suffix + ".sha256")
    if path.is_relative_to(ROOT):
        raise ValueError("Guardar respaldos fuera del repositorio")
    if path.exists() or manifest.exists():
        raise ValueError("El respaldo o su manifiesto ya existe; no se sobrescribe")
    command = [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "-f",
        str(compose_file),
        "exec",
        "-T",
        "db",
        "sh",
        "-c",
        'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner --no-acl',
    ]
    created = False
    manifest_created = False
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
        with os.fdopen(descriptor, "wb") as stream:
            subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.PIPE, check=True)
            stream.flush()
            os.fsync(stream.fileno())
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        descriptor = os.open(manifest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        manifest_created = True
        with os.fdopen(descriptor, "w") as stream:
            stream.write(digest + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        if manifest_created:
            manifest.unlink(missing_ok=True)
        if created:
            path.unlink(missing_ok=True)
        raise
    return {"file": str(path), "bytes": path.stat().st_size, "sha256": digest}


def main():
    parser = argparse.ArgumentParser(description="Respaldo PostgreSQL binario, sin copiar claves")
    parser.add_argument("destination")
    parser.add_argument("--env-file", default=str(ROOT / "infrastructure/.env"))
    parser.add_argument("--compose-file", default=str(ROOT / "infrastructure/compose.yaml"))
    args = parser.parse_args()
    try:
        result = backup(args.destination, args.env_file, args.compose_file)
    except (ValueError, OSError, subprocess.CalledProcessError):
        raise SystemExit(
            "Respaldo no completado. Verificar destino, permisos y servicio db; no se sobrescribieron archivos."
        ) from None
    print(result)
    print(
        "Guardar cifrado y respaldar las claves por un canal seguro separado. No hay cifrado automático del archivo."
    )


if __name__ == "__main__":
    main()
