"""Actual HTTPS simulator; local routing and a test CA exist only inside this test."""

import json
import os
import ssl
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from urllib.parse import parse_qs

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app.integrations.moodle.client import MoodleClient, MoodleError

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION") != "1", reason="Integration test opt-in"
)


def test_real_tls_sni_certificate_verification_and_rest(monkeypatch, tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "moodle.example.com")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
        .not_valid_after(datetime.now(UTC) + timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("moodle.example.com")]), critical=False
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
    requests, server_names = [], []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Never log request credentials.

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            requests.append((self.path, self.headers["Host"], parse_qs(body.decode())))
            payload = json.dumps(
                {
                    "sitename": "TLS simulator",
                    "siteurl": "https://moodle.example.com",
                    "functions": [{"name": "core_webservice_get_site_info"}],
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    context.set_servername_callback(lambda sock, name, ctx: server_names.append(name))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original_transport = httpx.HTTPTransport

    class LocalTestTransport(original_transport):
        def __init__(self, **options):
            assert options["verify"] is True and options["trust_env"] is False
            options["verify"] = ssl.create_default_context(cafile=str(cert_path))
            super().__init__(**options)

        def handle_request(self, request):
            # Only the simulator's routing is overridden. TLS must still verify the original DNS name.
            request.url = request.url.copy_with(port=server.server_port)
            return super().handle_request(request)

    monkeypatch.setattr("app.integrations.moodle.client.resolve_public", lambda host: ["127.0.0.1"])
    monkeypatch.setattr("app.integrations.moodle.client.httpx.HTTPTransport", LocalTestTransport)
    try:
        site, _ = MoodleClient().site_info("https://moodle.example.com", "tls-simulator-token", 3)
        assert site.sitename == "TLS simulator"
        assert server_names[0] == "moodle.example.com"
        assert requests == [
            (
                "/webservice/rest/server.php",
                "moodle.example.com",
                {
                    "wstoken": ["tls-simulator-token"],
                    "wsfunction": ["core_webservice_get_site_info"],
                    "moodlewsrestformat": ["json"],
                },
            )
        ]
        with pytest.raises(MoodleError, match="transport_error"):
            MoodleClient().site_info("https://wrong.example.com", "tls-simulator-token", 3)
        assert len(requests) == 1  # A hostname mismatch fails TLS before credentials are sent.
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
