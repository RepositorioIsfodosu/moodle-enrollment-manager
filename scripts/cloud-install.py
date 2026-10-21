"""Build in cloud environments with an injected HTTPS proxy; never copy its credentials."""

import os
import secrets
import socket
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

root = Path(__file__).resolve().parents[1]
env_file = root / "infrastructure/.env"
if not env_file.exists():
    env_file.write_text(
        "POSTGRES_USER=enrollment\nPOSTGRES_DB=enrollment\nPOSTGRES_PASSWORD="
        + secrets.token_hex(24)
        + "\n"
    )
    env_file.chmod(0o600)
subprocess.run([os.sys.executable, str(root / "scripts/init-secrets.py")], check=True)
args = ["docker", "build", "--network", "host"]
for name in ("HTTPS_PROXY", "HTTP_PROXY"):
    host = urlsplit(os.environ.get(name, "")).hostname
    if host:
        args += ["--build-arg", name, "--add-host", host + ":" + socket.gethostbyname(host)]
cert = os.environ.get("CODEX_PROXY_CERT")
if cert and Path(cert).is_file():
    args += ["--secret", "id=build_ca,src=" + cert]
args += ["-t", "moodle-enrollment-manager-api", "backend"]
subprocess.run(args, cwd=root, check=True)
