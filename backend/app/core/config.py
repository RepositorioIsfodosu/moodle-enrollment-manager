from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: SecretStr
    redis_url: SecretStr
    timezone: str = "America/Santo_Domingo"
    session_ttl_seconds: int = Field(default=28800, ge=300, le=86400)
    login_ip_limit: int = Field(default=30, ge=1, le=1000)
    login_account_limit: int = Field(default=10, ge=1, le=100)
    login_window_seconds: int = Field(default=300, ge=10, le=3600)


@lru_cache
def get_settings() -> Settings:
    return Settings()
