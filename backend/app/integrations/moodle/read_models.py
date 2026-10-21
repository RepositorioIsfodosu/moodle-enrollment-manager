from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.integrations.moodle.client import MoodleError


class UserInfo(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    id: int = Field(gt=0)
    username: str | None = Field(default=None, max_length=4096)
    email: str | None = Field(default=None, max_length=4096)
    idnumber: str | None = Field(default=None, max_length=4096)
    suspended: bool | None = None


class CourseInfo(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    id: int = Field(gt=0)
    shortname: str | None = Field(default=None, max_length=4096)
    idnumber: str | None = Field(default=None, max_length=4096)


class RoleInfo(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    roleid: int = Field(gt=0)


class GroupInfo(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    id: int = Field(gt=0)
    name: str | None = Field(default=None, max_length=4096)
    idnumber: str | None = Field(default=None, max_length=4096)


class MemberInfo(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    id: int = Field(gt=0)
    roles: list[RoleInfo] | None = Field(default=None, max_length=100)
    groups: list[GroupInfo] | None = Field(default=None, max_length=1000)


def filtered_list(payload, model, maximum=100):
    if not isinstance(payload, list) or len(payload) > maximum:
        raise MoodleError("invalid_response")
    try:
        return [model.model_validate(item).model_dump() for item in payload]
    except ValidationError:
        raise MoodleError("invalid_response") from None
