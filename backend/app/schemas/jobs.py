from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class BatchConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_size: int = Field(default=5, ge=1, le=50)
    pause_seconds: int = Field(default=10, ge=1, le=3600)
    timeout_seconds: int = Field(default=30, ge=5, le=120)
    max_retries: int = Field(default=3, ge=0, le=5)


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
