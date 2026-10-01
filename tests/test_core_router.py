from jarvis.brain.core_router import JarvisCoreRouter, classify_task, rank_loaded_models


LOADED = [
    "zai-org/GLM-4.7-Flash-GGUF-Q4_K_M",
    "Qwen-Qwen3.6-35B-A3B-Q4_K_M",
    "Qwen-Qwen3.8-27B-Q4_K_M",
    "LGAI-EXAONE-EXAONE-4.5-33B-Q4",
    "deepseek-ai-DeepSeek-V3.2-Exp",
]


def test_conversation_prefers_efficient_glm():
    ranked, task, complexity = rank_loaded_models(LOADED, text="Come stai oggi?")
    assert task == "conversation"
    assert complexity == 1
    assert "GLM-4.7-Flash" in ranked[0]


def test_math_prefers_qwen_specialist_without_jumping_to_huge_model():
    ranked, task, complexity = rank_loaded_models(
        LOADED,
        text="Spiegami questo integrale improprio e fammi capire i passaggi",
    )
    assert task == "math"
    assert complexity < 3
    assert "Qwen3.6-35B-A3B" in ranked[0]


def test_vision_prefers_exaone():
    ranked, task, _ = rank_loaded_models(
        LOADED,
        text="Guarda lo schermo e dimmi che errore c'è",
        has_image=True,
    )
    assert task == "vision"
    assert "EXAONE-4.5-33B" in ranked[0]


def test_complex_coding_can_promote_heavy_specialist():
    text = (
        "Fai un debug completo dell'intero progetto, controlla race condition, prestazioni, "
        "sicurezza, architettura e verifica e correggi tutti i problemi di produzione."
    )
    ranked, task, complexity = rank_loaded_models(LOADED, text=text)
    assert task in {"coding", "planning"}
    assert complexity == 3
    assert "DeepSeek-V3.2-Exp" in ranked[0]


def test_consensus_uses_second_available_model_only_for_complex_turns():
    router = JarvisCoreRouter(consensus_enabled=True, consensus_min_complexity=3)
    simple = router.decide(LOADED, text="Ciao Jarvis")
    assert simple.advisor_model == ""

    complex_decision = router.decide(
        LOADED,
        text=(
            "Fai un debug completo dell'intero progetto, analizza architettura, race condition, "
            "prestazioni, sicurezza e verifica e correggi ogni problema di produzione."
        ),
    )
    assert complex_decision.complexity == 3
    assert complex_decision.primary_model
    assert complex_decision.advisor_model
    assert complex_decision.advisor_model != complex_decision.primary_model


def test_task_classifier_detects_math_and_visual_intent():
    assert classify_task("Calcola una derivata e spiegami il teorema")[0] == "math"
    assert classify_task("cosa vedi?", has_image=True)[0] == "vision"
