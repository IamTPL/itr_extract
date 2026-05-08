from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from config.constants import FILES_ROOT_DEFAULT


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url:      str
    redis_url:         str = "redis://localhost:6379"
    msal_tenant_id:    str = ""
    msal_be_client_id: str
    files_root:        Path = FILES_ROOT_DEFAULT
    allowed_origins:   list[str] = ["http://localhost:5173"]
    gemini_api_key:    str
    # Production guard: set "production" để bật strict checks (xem validate_production_config)
    environment:       str = "development"


def validate_production_config(s: Settings) -> None:
    """Fail-fast nếu chạy production mà thiếu config bắt buộc.

    Gọi trong app startup. KHÔNG gọi ở dev (environment != production)
    vì dev cố ý cho phép MSAL_TENANT_ID trống.
    """
    if s.environment != "production":
        return
    errors: list[str] = []
    if not s.msal_tenant_id:
        errors.append("MSAL_TENANT_ID is required in production (empty = permissive auth mode, dev-only)")
    if not s.msal_be_client_id or s.msal_be_client_id.startswith("00000000"):
        errors.append("MSAL_BE_CLIENT_ID is missing or placeholder")
    if not s.gemini_api_key:
        errors.append("GEMINI_API_KEY is required")
    if "http://localhost" in " ".join(s.allowed_origins):
        errors.append("ALLOWED_ORIGINS contains localhost in production")
    if errors:
        msg = "Production config validation failed:\n  - " + "\n  - ".join(errors)
        raise RuntimeError(msg)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
