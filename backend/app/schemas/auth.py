from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator

RoleName = Literal["administrador", "operador", "supervisor", "consulta"]
Password = Annotated[SecretStr, Field(min_length=12, max_length=128)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Input):
    email: EmailStr
    password: SecretStr = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        return str(value).strip().lower()


class UserCreate(Login):
    password: Password
    roles: list[RoleName] = Field(min_length=1, max_length=4)


class UserUpdate(Input):
    active: bool | None = None
    roles: list[RoleName] | None = Field(default=None, min_length=1, max_length=4)

    @field_validator("active", "roles")
    @classmethod
    def reject_explicit_null(cls, value):
        if value is None:
            raise ValueError("No se permite null")
        return value


class PasswordChange(Input):
    current_password: SecretStr = Field(min_length=1, max_length=128)
    new_password: Password


class PasswordReset(Input):
    new_password: Password


class UserView(BaseModel):
    id: UUID
    email: str
    active: bool
    roles: list[str]
    created_at: datetime


class Me(UserView):
    permissions: list[str]


class TokenView(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime


class UserPage(BaseModel):
    items: list[UserView]
    total: int
    offset: int
    limit: int


class RoleView(BaseModel):
    name: str
    permissions: list[str]


class AuditView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime
    actor_id: UUID | None
    action: str
    entity_id: str | None
    safe_context: dict


class AuditPage(BaseModel):
    items: list[AuditView]
    total: int
    offset: int
    limit: int


class CookieLoginView(BaseModel):
    authenticated: bool = True
    expires_at: datetime
