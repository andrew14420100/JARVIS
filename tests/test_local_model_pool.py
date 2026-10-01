from __future__ import annotations

from jarvis.brain.lmstudio import LMStudioClient


def test_resolve_best_model_honors_priority() -> None:
    client = LMStudioClient("http://127.0.0.1:1234/v1")
    client.list_models = lambda: [
        "qwen/qwen3.8-27b",
        "zai-org/glm-4.7-flash-q4_k_m",
        "deepseek-ai/deepseek-v3.2-exp",
    ]
    try:
        selected = client.resolve_best_model(
            "zai-org/GLM-4.7-Flash|Qwen/Qwen3.8-27B|deepseek-ai/DeepSeek-V3.2-Exp"
        )
        assert selected == "zai-org/glm-4.7-flash-q4_k_m"
    finally:
        client.close()


def test_resolve_best_model_skips_missing_models() -> None:
    client = LMStudioClient("http://127.0.0.1:1234/v1")
    client.list_models = lambda: [
        "LGAI-EXAONE/EXAONE-4.5-33B",
        "Qwen/Qwen3.8-27B",
    ]
    try:
        selected = client.resolve_best_model(
            "zai-org/GLM-4.7-Flash|Qwen/Qwen3.6-35B-A3B|Qwen/Qwen3.8-27B"
        )
        assert selected == "Qwen/Qwen3.8-27B"
    finally:
        client.close()


def test_resolve_best_model_accepts_quantized_suffixes() -> None:
    client = LMStudioClient("http://127.0.0.1:1234/v1")
    client.list_models = lambda: ["Qwen3.6-35B-A3B-GGUF-Q4_K_M"]
    try:
        selected = client.resolve_best_model("Qwen/Qwen3.6-35B-A3B")
        assert selected == "Qwen3.6-35B-A3B-GGUF-Q4_K_M"
    finally:
        client.close()


def test_resolve_best_model_falls_back_to_first_loaded() -> None:
    client = LMStudioClient("http://127.0.0.1:1234/v1")
    client.list_models = lambda: ["custom/local-model"]
    try:
        selected = client.resolve_best_model("zai-org/GLM-4.7-Flash")
        assert selected == "custom/local-model"
    finally:
        client.close()
