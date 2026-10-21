import json
import logging
import time
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.integrations.moodle.urls import endpoint_url, resolve_public

# Do not allow HTTPX/httpcore debug logs to disclose request bodies or server metadata.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

EVALUATED_FUNCTIONS = (
    "core_webservice_get_site_info",
    "core_user_get_users",
    "core_user_get_users_by_field",
    "core_course_get_courses",
    "core_enrol_get_enrolled_users",
    "enrol_manual_enrol_users",
)


class MoodleError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class FunctionInfo(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,150}$")
    version: str | None = Field(default=None, max_length=128)


class SiteInfo(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    sitename: str = Field(max_length=512)
    siteurl: str = Field(max_length=2048)
    release: str | None = Field(default=None, max_length=128)
    version: str | None = Field(default=None, max_length=128)
    functions: list[FunctionInfo] = Field(max_length=5000)


class PinnedTransport(httpx.BaseTransport):
    """Validated public IP socket, original TLS SNI/hostname verification and Host."""

    def __init__(self, hostname: str, address: str):
        self.hostname = hostname
        self.address = address
        self.transport = httpx.HTTPTransport(verify=True, trust_env=False, retries=0)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.host != self.hostname or request.url.scheme != "https":
            raise MoodleError("unsafe_destination")
        request.headers["Host"] = self.hostname
        request.extensions["sni_hostname"] = self.hostname
        request.url = request.url.copy_with(host=self.address)
        return self.transport.handle_request(request)

    def close(self):
        self.transport.close()


class MoodleClient:
    def read_call(self, base_url: str, token: str, timeout: float, function: str, parameters: dict):
        allowed = {
            "core_webservice_get_site_info",
            "core_user_get_users_by_field",
            "core_course_get_courses",
            "core_course_get_courses_by_field",
            "core_enrol_get_enrolled_users",
            "core_group_get_course_groups",
        }
        if function not in allowed or any(
            k in parameters for k in ("wstoken", "wsfunction", "moodlewsrestformat")
        ):
            raise MoodleError("function_not_allowed")
        return self._call(base_url, token, timeout, function, parameters)

    def write_call(
        self, base_url: str, token: str, timeout: float, function: str, parameters: dict
    ):
        if function not in {"enrol_manual_enrol_users", "core_group_add_group_members"} or any(
            k in parameters for k in ("wstoken", "wsfunction", "moodlewsrestformat")
        ):
            raise MoodleError("function_not_allowed")
        payload, elapsed = self._call(base_url, token, timeout, function, parameters)
        if payload is not None:
            raise MoodleError("invalid_write_response")
        return payload, elapsed

    def _call(self, base_url, token, timeout, function, parameters):
        endpoint = endpoint_url(base_url)
        host = urlsplit(endpoint).hostname
        addresses = resolve_public(host)
        transport = PinnedTransport(host, addresses[0])
        started = time.monotonic()
        try:
            with (
                httpx.Client(
                    transport=transport,
                    trust_env=False,
                    follow_redirects=False,
                    timeout=timeout,
                    headers={"Accept-Encoding": "identity"},
                ) as client,
                client.stream(
                    "POST",
                    endpoint,
                    data={
                        "wstoken": token,
                        "wsfunction": function,
                        **parameters,
                        "moodlewsrestformat": "json",
                    },
                ) as response,
            ):
                if 300 <= response.status_code < 400:
                    raise MoodleError("redirect_not_allowed")
                if response.status_code == 429:
                    raise MoodleError("remote_rate_limited")
                if response.status_code >= 400:
                    raise MoodleError("http_error")
                if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                    raise MoodleError("invalid_response")
                body = bytearray()
                for chunk in response.iter_raw():
                    if time.monotonic() - started > timeout:
                        raise MoodleError("timeout")
                    if len(body) + len(chunk) > 1048576:
                        raise MoodleError("response_too_large")
                    body.extend(chunk)
                payload = json.loads(body)
                if isinstance(payload, dict) and ("exception" in payload or "errorcode" in payload):
                    codes = {
                        "invalidtoken": "invalid_token",
                        "accessexception": "insufficient_permissions",
                        "wsaccessuserex": "insufficient_permissions",
                        "servicenotavailable": "function_unavailable",
                    }
                    raise MoodleError(
                        codes.get(payload.get("errorcode"), "moodle_error")
                        if isinstance(payload.get("errorcode"), str)
                        else "moodle_error"
                    )
                return payload, round((time.monotonic() - started) * 1000)
        except httpx.TimeoutException:
            raise MoodleError("timeout") from None
        except httpx.TransportError:
            raise MoodleError("transport_error") from None
        except (ValueError, ValidationError):
            raise MoodleError("invalid_response") from None

    def site_info(self, base_url: str, token: str, timeout: float) -> tuple[SiteInfo, int]:
        payload, elapsed = self.read_call(
            base_url, token, timeout, "core_webservice_get_site_info", {}
        )
        try:
            site = SiteInfo.model_validate(payload)
        except ValidationError:
            raise MoodleError("invalid_response") from None
        exposed = [site.sitename, site.release or "", site.version or ""]
        exposed.extend(item.name for item in site.functions)
        if any(token in value for value in exposed):
            raise MoodleError("sensitive_response")
        if site.siteurl.rstrip("/") != base_url.rstrip("/"):
            raise MoodleError("site_url_mismatch")
        return site, elapsed
