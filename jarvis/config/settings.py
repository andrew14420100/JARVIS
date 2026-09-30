from __future__ import annotations

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for JARVIS.

    Values can be overridden with environment variables prefixed by JARVIS_.
    The default AI brain is cloud-hosted and restricted to free routes only.
    Heavy local voice/cognitive components remain optional.
    """

    brain_mode: str = "cloud"
    model: str = ""
    max_agent_iterations: int = 8
    request_timeout_seconds: float = 120.0
    user_name: str = "Signore"

    # Public cloud AI. Secrets stay server-side and are never sent to React.
    # NVIDIA Nemotron 3 Ultra is preferred when configured; every provider in
    # this router is constrained to a free endpoint/model id.
    nvidia_api_key: str = ""
    nvidia_model: str = "nvidia/nemotron-3-ultra-550b-a55b"
    zai_api_key: str = ""
    zai_model: str = "glm-4.7-flash"
    groq_api_key: str = ""
    groq_model: str = "qwen/qwen3.8-27b"
    openrouter_api_key: str = ""
    openrouter_model: str = "openrouter/free"
    cloud_app_name: str = "JARVIS"
    cloud_app_url: str = ""

    # Optional legacy/local fallback for development only. It is not used when
    # brain_mode=cloud and is never selected automatically by the cloud router.
    lm_studio_base_url: str = "http://127.0.0.1:1234/v1"

    # Hybrid reasoning. OpenJarvis remains optional; the main brain can be cloud.
    openjarvis_enabled: bool = False
    openjarvis_agent: str = "orchestrator"
    openjarvis_model: str = ""
    deep_reasoning_enabled: bool = True
    deep_reasoning_min_score: int = 4

    memory_enabled: bool = True
    memory_db_path: str = "data/jarvis_memory.sqlite3"
    memory_top_k: int = 4

    # Presence context: a short-lived local context window inspired by
    # always-present assistants. Ambient audio itself is never persisted.
    presence_enabled: bool = False
    presence_context_seconds: float = 30.0
    presence_max_items: int = 12
    presence_max_chars: int = 5000

    voice_enabled: bool = False
    wake_model: str = "hey_jarvis"
    wake_threshold: float = 0.50
    wake_chunk_size: int = 1280

    stt_model: str = "small"
    stt_device: str = "auto"
    stt_compute_type: str = "int8"
    stt_language: str = "it"

    # Voice mode. CosyVoice 3 runs locally in a separate Python 3.10 process,
    # keeps the cloned speaker representation warm, and streams PCM back to
    # JARVIS. No TTS API key, credits or per-minute quota are involved.
    tts_mode: str = "cosyvoice-local"
    cosyvoice_enabled: bool = True
    cosyvoice_service_url: str = "http://127.0.0.1:8765"
    cosyvoice_repo_dir: str = ".local/cosyvoice/CosyVoice"
    cosyvoice_model_dir: str = ".local/cosyvoice/models/Fun-CosyVoice3-0.5B"
    cosyvoice_reference_audio: str = "private/voices/jarvis.wav"
    cosyvoice_reference_text: str = "private/voices/jarvis.txt"
    cosyvoice_speed: float = 1.0

    # Legacy browser/cloud TTS remains available only when TTS_MODE=cloud is
    # explicitly selected. It is not part of the default JARVIS voice path.
    cloud_tts_enabled: bool = False
    cloud_tts_provider: str = "fish-s2-pro"
    fish_s2_space: str = "artificialguybr/fish-s2-pro-zero"
    fish_s2_hf_token: str = ""
    fish_s2_style_prompt: str = "[low voice] [calm professional tone]"
    cloud_tts_fallback_enabled: bool = False
    edge_tts_voice: str = "it-IT-GiuseppeMultilingualNeural"
    edge_tts_rate: str = "-8%"
    edge_tts_pitch: str = "-6Hz"
    edge_tts_volume: str = "+0%"

    # Legacy Kokoro configuration kept only as an optional local fallback.
    tts_enabled: bool = True
    tts_voice: str = "im_nicola"
    tts_speed: float = 1.05
    tts_lang_code: str = "i"

    model_config = SettingsConfigDict(
        env_prefix="JARVIS_",
        env_file=".env",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
