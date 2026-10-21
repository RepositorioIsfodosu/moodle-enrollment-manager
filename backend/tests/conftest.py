import base64
import os
import secrets

# Ephemeral test encryption key; never use the application's key or dump its value.
os.environ.setdefault(
    "MOODLE_TOKEN_KEYS", base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
)
