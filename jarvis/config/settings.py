from __future__ import annotations

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for JARVIS.

    Values can be overridden with environment variables prefixed by JARVIS_.
    """

    lm_studio_base_url: str = "http://127.0.0.1:1234/v1"
    model: str = ""
    max_agent_iterations: int = 8
    request_timeout_seconds: float = 120.0
    user_name: str = "Signore"

    model_config = SettingsConfigDict(
        env_prefix="JARVIS_",
        env_file=".env",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
