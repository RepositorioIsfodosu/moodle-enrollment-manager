from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CourseColumn(Input):
    course: str = Field(min_length=1, max_length=100)
    role: str | None = Field(default=None, max_length=100)
    group: str | None = Field(default=None, max_length=100)


class Mapping(Input):
    user_column: str | None = Field(default=None, max_length=100)
    user_field: Literal["username", "email", "idnumber"] = "username"
    course_field: Literal["id", "shortname", "idnumber"] = "shortname"
    group_field: Literal["id", "name", "idnumber"] = "name"
    courses: list[CourseColumn] = Field(default_factory=list, max_length=50)
    default_role_id: int | None = Field(default=None, gt=0, le=2147483647)
    role_map: dict[str, int] = Field(default_factory=dict, max_length=100)
    metadata_columns: dict[Literal["period", "campus"], str] = Field(default_factory=dict)

    @field_validator("role_map")
    @classmethod
    def roles(cls, value):
        if any(not k.strip() or len(k) > 100 or v < 1 or v > 2147483647 for k, v in value.items()):
            raise ValueError("Mapa de roles no válido")
        return value


class ProfileCreate(Input):
    name: str = Field(min_length=1, max_length=200)
    mapping: Mapping


class ProfileView(ProfileCreate):
    id: UUID
    owner_id: UUID | None


class Normalize(Input):
    profile_id: UUID | None = None
    mapping: Mapping = Field(default_factory=Mapping)


class FileView(BaseModel):
    id: UUID
    original_name: str
    sha256: str
    row_count: int
    byte_count: int
    encoding: str
    delimiter: str
    headers: list[str]
    preview: list[dict]
    created_at: datetime


class ImportView(BaseModel):
    id: UUID
    file_id: UUID
    mapping_snapshot: dict
    operation_count: int
    counts: dict[str, int]


class ValidationCreate(Input):
    connection_id: UUID
    import_ids: list[UUID] = Field(min_length=1, max_length=20)

    @field_validator("import_ids")
    @classmethod
    def unique(cls, values):
        if len(set(values)) != len(values):
            raise ValueError("Importaciones repetidas")
        return values


class ValidationView(BaseModel):
    id: UUID
    connection_id: UUID
    configuration_version: int
    state: str
    error_code: str | None
    created_at: datetime
    finished_at: datetime | None
    total: int
    checked: int
    counts: dict[str, int]
    progress_percent: float


class ApprovalCreate(Input):
    course_id: int = Field(gt=0, le=2147483647)
    role_id: int = Field(gt=0, le=2147483647)
    expires_at: datetime
    reference: str = Field(min_length=20, max_length=1000)
    groups_authorized: bool = False
    full_enrollment_visibility: bool = False


class GrantCreate(Input):
    user_id: UUID


class ApprovalView(ApprovalCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    configuration_version: int
    active: bool
    approved_by: UUID


class Page(BaseModel):
    items: list[dict]
    total: int
    offset: int
    limit: int
