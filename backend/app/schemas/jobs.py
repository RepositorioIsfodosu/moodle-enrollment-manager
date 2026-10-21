from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BatchConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_size: int = Field(default=5, ge=1, le=50)
    pause_seconds: int = Field(default=10, ge=1, le=3600)
    timeout_seconds: int = Field(default=30, ge=5, le=120)
    max_concurrency: Literal[1] = 1
    retry_base_seconds: int = Field(default=30, ge=1, le=3600)
    latency_threshold_ms: int = Field(default=10000, ge=100, le=120000)
    error_threshold: int = Field(default=3, ge=1, le=20)
    circuit_cooldown_seconds: int = Field(default=300, ge=30, le=3600)
    allowed_hours_utc: list[int] = Field(
        default_factory=lambda: list(range(24)), min_length=1, max_length=24
    )
    max_retries: int = Field(default=3, ge=0, le=5)

    @field_validator("allowed_hours_utc")
    @classmethod
    def hours(cls, values):
        if len(set(values)) != len(values) or any(h < 0 or h > 23 for h in values):
            raise ValueError("Horas UTC no válidas")
        return values


class JobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200, pattern=r"\S")
    validation_id: UUID
    configuration: BatchConfiguration = Field(default_factory=BatchConfiguration)


class JobView(BaseModel):
    id: UUID
    name: str
    connection_id: UUID
    state: str
    configuration: dict
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    counts: dict[str, int]
    total: int
    progress_percent: float
    runtime: dict


class RetrySelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    record_ids: list[UUID] = Field(min_length=1, max_length=200)
