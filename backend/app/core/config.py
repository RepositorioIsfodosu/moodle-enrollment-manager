from functools import lru_cache

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: SecretStr
    redis_url: SecretStr
    moodle_token_keys: SecretStr | None = None
    csv_max_bytes: int = Field(default=10485760, ge=1024, le=52428800)
    csv_max_rows: int = Field(default=50000, ge=1, le=100000)
    csv_max_operations: int = Field(default=100000, ge=1, le=200000)
    validation_max_pages: int = Field(default=50, ge=1, le=500)
    enrollment_writes_enabled: bool = False
    report_export_max_rows: int = Field(default=10000, ge=1, le=50000)
    timezone: str = "America/Santo_Domingo"
    session_cookie_secure: bool = False
    session_ttl_seconds: int = Field(default=28800, ge=300, le=86400)
    login_ip_limit: int = Field(default=30, ge=1, le=1000)
    login_account_limit: int = Field(default=10, ge=1, le=100)
    login_window_seconds: int = Field(default=300, ge=10, le=3600)
    password_reset_ttl_seconds: int = Field(default=1800, ge=300, le=86400)
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str | None = None
    smtp_starttls: bool = True
    password_reset_url: AnyHttpUrl | None = None

    @field_validator("password_reset_url", mode="before")
    @classmethod
    def blank_reset_url_is_disabled(cls, value):
        return None if isinstance(value, str) and not value.strip() else value


@lru_cache
def get_settings() -> Settings:
    return Settings()
