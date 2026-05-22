from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .ui import normalize_public_base_path


class Settings(BaseSettings):
    database_url: str = Field(..., alias="DATABASE_URL")
    host: str = Field("0.0.0.0", alias="HOST")
    port: int = Field(8080, alias="PORT")
    default_sleep_threshold_percent: float = Field(90.0, alias="DEFAULT_SLEEP_THRESHOLD_PERCENT")
    scan_interval_seconds: int = Field(60, alias="SCAN_INTERVAL_SECONDS")
    include_openai: bool = Field(True, alias="INCLUDE_OPENAI")
    include_anthropic: bool = Field(True, alias="INCLUDE_ANTHROPIC")
    public_base_path: str = Field("/custom/oauth-sleeper", alias="PUBLIC_BASE_PATH")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    @property
    def public_base_path_prefix(self) -> str:
        return normalize_public_base_path(self.public_base_path)


@lru_cache
def get_settings() -> Settings:
    return Settings()
