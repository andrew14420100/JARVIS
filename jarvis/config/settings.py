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

    # Local Qwen in LM Studio can act as an offline fallback for cloud mode.
    lm_studio_base_url: str = "http://127.0.0.1:1234/v1"
    lm_studio_fallback_enabled: bool = True

    openjarvis_enabled: bool = False
    openjarvis_agent: str = "orchestrator"
    openjarvis_model: str = ""
    deep_reasoning_enabled: bool = True
    deep_reasoning_min_score: int = 4

    memory_enabled: bool = True
    memory_db_path: str = "data/jarvis_memory.sqlite3"
    memory_top_k: int = 4

    presence_enabled: bool = False
    presence_context_seconds: float = 30.0
    presence_max_items: int = 12
    presence_max_chars: int = 5000

    voice_enabled: bool = False
    # Optional sounddevice input selector. Leave blank for the Windows default,
    # or set an exact/unique device name such as "Microfono (USB ...)".
    audio_input_device: str = ""
    wake_model: str = "hey_jarvis"
    wake_threshold: float = 0.35
    wake_chunk_size: int = 1280

    stt_model: str = "small"
    stt_device: str = "auto"
    # RTX-class CUDA GPUs are considerably faster with float16 than plain int8.
    stt_compute_type: str = "float16"
    stt_language: str = "it"

    browser_voice_input_enabled: bool = False
    listener_remote_base_url: str = ""
    listener_followup_silence_seconds: float = 8.0
    listener_max_utterance_seconds: float = 45.0
    listener_wake_ack_enabled: bool = True
    listener_stop_phrases: str = "jarvis stop|stop jarvis|basta jarvis|torna in standby|vai in standby"

    tts_mode: str = "cosyvoice-local"
    cosyvoice_enabled: bool = True
    cosyvoice_service_url: str = "http://127.0.0.1:8765"
    cosyvoice_repo_dir: str = ".local/cosyvoice/CosyVoice"
    cosyvoice_model_dir: str = ".local/cosyvoice/models/Fun-CosyVoice3-0.5B"
    cosyvoice_reference_audio: str = "private/voices/jarvis.wav"
    cosyvoice_reference_text: str = "private/voices/jarvis.txt"
    cosyvoice_speed: float = 1.0

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
