from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from config.constants import FILES_ROOT_DEFAULT


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url:      str
    redis_url:         str = "redis://localhost:6379"
    msal_tenant_id:    str
    msal_be_client_id: str
    files_root:        Path = FILES_ROOT_DEFAULT
    allowed_origins:   list[str] = ["http://localhost:5173"]
    gemini_api_key:    str


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
