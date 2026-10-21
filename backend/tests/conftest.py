import base64
import os
import secrets

# Always use an ephemeral test-only encryption key, including when the caller has a real key.
os.environ["MOODLE_TOKEN_KEYS"] = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
