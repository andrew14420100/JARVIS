from __future__ import annotations

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for JARVIS.

    Values can be overridden with environment variables prefixed by JARVIS_.
    Heavy components are optional and are kept off the latency-critical path.
    """

    brain_mode: str = "cloud"
    model: str = ""
    max_agent_iterations: int = 8
    request_timeout_seconds: float = 120.0
    user_name: str = "Signore"

    # Public/free cloud routes. No paid provider is required by default.
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

    # Open-weight local model pool. Only an already-served model is selected;
    # JARVIS never attempts to keep this whole list resident in RAM/VRAM.
    lm_studio_base_url: str = "http://127.0.0.1:1234/v1"
    lm_studio_fallback_enabled: bool = True
    conversation_local_first: bool = True
    local_model_priority: str = (
        "zai-org/GLM-4.7-Flash|"
        "Qwen/Qwen3.6-35B-A3B|"
        "Qwen/Qwen3.8-27B|"
        "LGAI-EXAONE/EXAONE-4.5-33B|"
        "llm-jp/llm-jp-3-13b-instruct3|"
        "llm-jp/llm-jp-3-172b-instruct3|"
        "deepseek-ai/DeepSeek-V3.2-Exp|"
        "LGAI-EXAONE/K-EXAONE-2.0"
    )
    vision_model_priority: str = "LGAI-EXAONE/EXAONE-4.5-33B"

    # JARVIS-Core: one identity, many specialist brains. The router selects only
    # models already exposed by the local server. Difficult turns may use a
    # second already-available model as a silent advisor before the final answer.
    core_router_enabled: bool = True
    core_consensus_enabled: bool = True
    core_consensus_min_complexity: int = 3
    core_advisor_max_chars: int = 1400

    openjarvis_enabled: bool = False
    openjarvis_agent: str = "orchestrator"
    openjarvis_model: str = ""
    deep_reasoning_enabled: bool = True
    deep_reasoning_min_score: int = 4

    # Permanent local memory: complete transcript + semantic snippets.
    memory_enabled: bool = True
    memory_db_path: str = "data/jarvis_memory.sqlite3"
    memory_top_k: int = 8
    memory_full_transcript: bool = True
    memory_auto_semantic: bool = True
    memory_redact_secrets: bool = True
    memory_recent_search_limit: int = 1200

    # The live LLM prompt stays bounded even though the full transcript is kept.
    conversation_max_messages: int = 40
    persistent_session_enabled: bool = True
    persistent_session_poll_seconds: float = 12.0

    presence_enabled: bool = True
    presence_context_seconds: float = 120.0
    presence_max_items: int = 24
    presence_max_chars: int = 9000

    voice_enabled: bool = False
    audio_input_device: str = ""
    wake_model: str = "hey_jarvis"
    wake_threshold: float = 0.28
    wake_min_rms: float = 0.004
    wake_chunk_size: int = 1280

    stt_model: str = "small"
    stt_device: str = "auto"
    stt_compute_type: str = "float16"
    stt_language: str = "it"
    stt_silence_seconds: float = 0.55
    stt_incomplete_phrase_silence_seconds: float = 2.5

    browser_voice_input_enabled: bool = False
    listener_remote_base_url: str = ""
    listener_followup_silence_seconds: float = 12.0
    listener_max_utterance_seconds: float = 60.0
    listener_wake_ack_enabled: bool = True
    listener_activation_phrase: str = "Sì, signore?"
    listener_barge_in_enabled: bool = True
    listener_stop_phrases: str = "jarvis stop|stop jarvis|basta jarvis|torna in standby|vai in standby|chiudi la sessione"
    listener_error_phrase: str = "Mi dispiace signore, non ho capito l'ultima parte."
    listener_unauthorized_phrase: str = "Mi dispiace, non posso eseguire questa richiesta."

    # Lightweight voice identity. The owner may be auto-enrolled from the first
    # clear command after a verified wake; additional profiles can be added later.
    speaker_auth_enabled: bool = True
    speaker_profiles_dir: str = "data/speaker_profiles"
    speaker_match_threshold: float = 0.78
    speaker_auto_enroll_owner: bool = True
    speaker_owner_name: str = "Signore"
    speaker_owner_role: str = "owner"
    prosody_enabled: bool = True

    # Anti-echo barge-in. The output reference is compared with mic audio so the
    # cloned JARVIS voice does not interrupt itself through loudspeakers.
    echo_guard_enabled: bool = True
    echo_guard_max_correlation: float = 0.82
    barge_in_min_rms: float = 0.010
    barge_in_min_seconds: float = 0.45

    # Continuous screen presence: only the latest frame is kept in RAM. An image
    # is attached to the LLM only when the request actually refers to the screen.
    screen_monitor_enabled: bool = True
    screen_capture_interval_seconds: float = 2.0
    screen_max_width: int = 1280
    screen_jpeg_quality: int = 58
    screen_attach_on_visual_request: bool = True

    # Important proactive alerts only; ordinary observations stay silent.
    proactive_enabled: bool = True
    proactive_poll_seconds: float = 15.0
    proactive_cooldown_seconds: float = 300.0
    proactive_cpu_percent: float = 97.0
    proactive_memory_percent: float = 96.0
    proactive_disk_percent: float = 96.0
    proactive_gpu_temp_c: float = 88.0

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
