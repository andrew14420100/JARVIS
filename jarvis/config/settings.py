from __future__ import annotations

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for JARVIS.

    Values can be overridden with environment variables prefixed by JARVIS_.
    The heavy local voice stack is optional and disabled in cloud previews.
    """

    lm_studio_base_url: str = "http://127.0.0.1:1234/v1"
    model: str = ""
    max_agent_iterations: int = 8
    request_timeout_seconds: float = 120.0
    user_name: str = "Signore"

    memory_enabled: bool = True
    memory_db_path: str = "data/jarvis_memory.sqlite3"
    memory_top_k: int = 4

    voice_enabled: bool = False
    wake_model: str = "hey_jarvis"
    wake_threshold: float = 0.50
    wake_chunk_size: int = 1280

    stt_model: str = "small"
    stt_device: str = "auto"
    stt_compute_type: str = "int8"
    stt_language: str = "it"

    tts_enabled: bool = True
    tts_voice: str = "af_heart"
    tts_speed: float = 1.05
    tts_lang_code: str = "a"

    model_config = SettingsConfigDict(
        env_prefix="JARVIS_",
        env_file=".env",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
