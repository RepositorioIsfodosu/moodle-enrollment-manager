from functools import lru_cache

from pydantic import Field, SecretStr
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
    timezone: str = "America/Santo_Domingo"
    session_ttl_seconds: int = Field(default=28800, ge=300, le=86400)
    login_ip_limit: int = Field(default=30, ge=1, le=1000)
    login_account_limit: int = Field(default=10, ge=1, le=100)
    login_window_seconds: int = Field(default=300, ge=10, le=3600)


@lru_cache
def get_settings() -> Settings:
    return Settings()
