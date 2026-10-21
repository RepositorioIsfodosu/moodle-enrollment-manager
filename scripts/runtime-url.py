"""Write a private Compose env file with a URL-encoded runtime password; never print it."""

import argparse
import ipaddress
import os
import re
from getpass import getpass
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]


def write_runtime_env(
    destination, password, *, role="mem_runtime", host="db", database="enrollment", port=5432
):
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", role):
        raise ValueError("Nombre de rol no válido")
    if not password or not 20 <= len(password) <= 128 or any(ord(c) < 32 for c in password):
        raise ValueError("Contraseña de 20–128 caracteres sin controles")
    if not database or any(ord(c) < 32 for c in database) or not 1 <= port <= 65535:
        raise ValueError("Base o puerto no válidos")
    if ":" in host:
        host = "[" + str(ipaddress.IPv6Address(host)) + "]"
    elif not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", host):
        raise ValueError("Host no válido")
    path = Path(destination).resolve()
    if path.is_relative_to(ROOT):
        raise ValueError("Guardar credenciales fuera del repositorio")
    url = f"postgresql+psycopg://{role}:{quote(password, safe='')}@{host}:{port}/{quote(database, safe='')}"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(f"RUNTIME_DB_USER={role}\nRUNTIME_DATABASE_URL='{url}'\n")
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


def main():
    parser = argparse.ArgumentParser(
        description="Crear archivo privado de conexión de runtime sin mostrar contraseña"
    )
    parser.add_argument("destination")
    parser.add_argument("--role", default="mem_runtime")
    parser.add_argument("--host", default="db")
    parser.add_argument("--database", default="enrollment")
    parser.add_argument("--port", type=int, default=5432)
    args = parser.parse_args()
    password = getpass("Contraseña del rol PostgreSQL ya creado: ")
    if password != getpass("Repetir contraseña: "):
        raise SystemExit("Las contraseñas no coinciden")
    try:
        write_runtime_env(
            args.destination,
            password,
            role=args.role,
            host=args.host,
            database=args.database,
            port=args.port,
        )
    except (ValueError, OSError):
        raise SystemExit(
            "No se creó archivo; verificar destino nuevo fuera del repositorio, permisos y valores"
        ) from None
    print("Archivo privado creado. Protegerlo y pasarlo como segundo --env-file; no subirlo a Git.")


if __name__ == "__main__":
    main()
