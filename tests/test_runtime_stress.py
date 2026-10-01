from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from jarvis.brain.core_router import JarvisCoreRouter
from jarvis.memory.store import LocalMemory


MODELS = [
    "zai-org/GLM-4.7-Flash-Q4_K_M",
    "Qwen/Qwen3.6-35B-A3B-GGUF-Q4_K_M",
    "Qwen/Qwen3.8-27B-Q4_K_M",
    "LGAI-EXAONE/EXAONE-4.5-33B-Q4_K_M",
    "deepseek-ai/DeepSeek-V3.2-Exp",
]


def test_memory_survives_concurrent_turn_writes(tmp_path):
    memory = LocalMemory(str(tmp_path / "stress.sqlite3"), top_k=8)

    def write_batch(worker: int):
        for index in range(20):
            memory.record_turn(
                f"Worker {worker} messaggio persistente numero {index} per il progetto JARVIS",
                f"Risposta JARVIS {worker}-{index}",
                speaker=f"utente-{worker}",
                metadata={"worker": worker, "index": index},
                auto_semantic=True,
            )

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(write_batch, worker) for worker in range(8)]
        for future in futures:
            future.result()

    transcript = memory.recent_transcript(1000)
    assert len(transcript) == 8 * 20 * 2
    assert any("utente-0:" in item.content for item in transcript)
    assert any("Jarvis:" in item.content for item in transcript)

    found = memory.search("progetto JARVIS worker 3", top_k=8)
    assert found
    memory.close()


def test_core_router_is_deterministic_under_parallel_load():
    router = JarvisCoreRouter(consensus_enabled=True, consensus_min_complexity=3)
    prompts = [
        "Spiegami un integrale improprio e fammi capire i passaggi",
        "Debug completo del backend FlixIT, trova race condition e correggi tutto",
        "Guarda lo screenshot e dimmi che errore vedi",
        "Come stai oggi?",
    ] * 100

    def decide(prompt: str):
        decision = router.decide(MODELS, text=prompt, has_image="screenshot" in prompt)
        return decision.task, decision.primary_model, decision.complexity

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(decide, prompts))

    assert len(results) == len(prompts)
    assert all(primary for _task, primary, _complexity in results)
    assert {task for task, _primary, _complexity in results} >= {"math", "coding", "vision", "conversation"}
