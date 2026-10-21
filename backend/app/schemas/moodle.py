from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.integrations.moodle.urls import normalize_base_url


class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timeout_seconds: int = Field(default=15, ge=3, le=60)
    min_probe_interval_seconds: int = Field(default=30, ge=5, le=3600)
    requests_per_minute: int = Field(default=10, ge=1, le=120)
    max_concurrency: Literal[1] = 1  # Enrollment engine calibration belongs to phase 5.


class ConnectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    base_url: str = Field(max_length=2048)
    token: SecretStr = Field(min_length=1, max_length=4096)
    description: str = Field(default="", max_length=2000)
    limits: Limits = Field(default_factory=Limits)

    @field_validator("base_url")
    @classmethod
    def url(cls, value):
        return normalize_base_url(value)

    @field_validator("token")
    @classmethod
    def token_format(cls, value):
        if any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value.get_secret_value()):
            raise ValueError("Token no válido")
        return value

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value):
        if not value.strip():
            raise ValueError("Nombre vacío")
        return value.strip()


class ConnectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    base_url: str | None = Field(default=None, max_length=2048)
    token: SecretStr | None = Field(default=None, min_length=1, max_length=4096)
    description: str | None = Field(default=None, max_length=2000)
    active: bool | None = None
    limits: Limits | None = None

    @field_validator("name", "base_url", "token", "description", "active", "limits")
    @classmethod
    def non_null(cls, value):
        if value is None:
            raise ValueError("No se permite null")
        return value


class ConnectionView(BaseModel):
    id: UUID
    name: str
    base_url: str
    service_url: str
    token_configured: bool
    active: bool
    description: str
    limits: Limits
    status: str
    configuration_version: int
    created_at: datetime
    last_verified_at: datetime | None
    last_error_code: str | None
    site_metadata: dict
    available_functions: list[str]
    missing_evaluated_functions: list[str]
    latency_ms: int | None


class ConnectionPage(BaseModel):
    items: list[ConnectionView]
    total: int
    offset: int
    limit: int


class CheckView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    connection_id: UUID
    actor_id: UUID
    created_at: datetime
    status: str
    error_code: str | None
    latency_ms: int | None
    available_functions: list[str]


class CheckPage(BaseModel):
    items: list[CheckView]
    total: int
    offset: int
    limit: int
