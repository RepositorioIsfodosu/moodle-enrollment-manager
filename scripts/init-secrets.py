"""Add a locally generated encryption key without printing it or overwriting existing config."""

import base64
import os
import re
import secrets
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "infrastructure/.env"
if not path.exists():
    raise SystemExit(
        "Crear infrastructure/.env a partir de env.example antes de inicializar secretos"
    )
contents = path.read_text()
if not any(
    re.match(r"^\s*(?:export\s+)?MOODLE_TOKEN_KEYS\s*=", line) for line in contents.splitlines()
):
    key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
    with path.open("a") as target:
        target.write("\nMOODLE_TOKEN_KEYS=" + key + "\n")
    os.chmod(path, 0o600)
    print("Clave de cifrado añadida a .env; guardar una copia segura")
else:
    print("Configuración de clave existente conservada")
