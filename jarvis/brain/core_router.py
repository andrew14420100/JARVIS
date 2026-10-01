from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


@dataclass(frozen=True, slots=True)
class CoreDecision:
    task: str
    complexity: int
    primary_model: str
    advisor_model: str = ""
    reason: str = ""


_TASK_MARKERS: dict[str, tuple[str, ...]] = {
    "vision": (
        "schermo", "screenshot", "immagine", "foto", "guarda qui", "vedi qui",
        "finestra", "interfaccia", "ui", "grafico", "documento scansionato",
    ),
    "coding": (
        "codice", "github", "repository", "repo", "commit", "pull request", "bug",
        "debug", "python", "javascript", "typescript", "react", "fastapi", "api",
        "frontend", "backend", "database", "mongodb", "sql", "deploy", "server",
        "flixit", "funzione", "classe", "script", "compila", "build",
    ),
    "math": (
        "matematica", "integrale", "derivata", "equazione", "limite", "matrice",
        "algebra", "analisi matematica", "probabilità", "probabilita", "statistica",
        "teorema", "dimostrazione", "funzione matematica", "calcolo", "geometria",
        "trigonometr", "serie", "successione",
    ),
    "planning": (
        "pianifica", "strategia", "architettura", "progetta", "ottimizza", "analizza",
        "confronta", "investiga", "diagnostica", "roadmap", "passo per passo",
        "verifica e correggi", "fai tutto", "autonomamente",
    ),
    "research": (
        "ricerca", "cerca su internet", "fonti", "verifica", "documentati", "studia",
        "confronta fonti", "aggiornato", "ultime notizie", "recente",
    ),
}

_COMPLEX_MARKERS = (
    "dimostrazione", "architettura", "refactor", "debug completo", "check completo",
    "ottimizza", "multi-step", "più file", "piu file", "intero progetto",
    "produzione", "race condition", "deadlock", "prestazioni", "sicurezza",
    "verifica e correggi", "fai tutto", "autonomamente",
)

# Ordered from efficient/easy to host toward very heavy. Task-specific routing can
# move a specialist earlier, but heavy models are reserved for genuinely complex
# work whenever a lighter expert is available.
_EFFICIENCY_ORDER = (
    "zai-org/GLM-4.7-Flash",
    "Qwen/Qwen3.6-35B-A3B",
    "Qwen/Qwen3.8-27B",
    "LGAI-EXAONE/EXAONE-4.5-33B",
    "llm-jp/llm-jp-3-13b-instruct3",
    "llm-jp/llm-jp-3-172b-instruct3",
    "deepseek-ai/DeepSeek-V3.2-Exp",
    "LGAI-EXAONE/K-EXAONE-2.0",
)

_TASK_ORDER: dict[str, tuple[str, ...]] = {
    "conversation": (
        "zai-org/GLM-4.7-Flash",
        "Qwen/Qwen3.6-35B-A3B",
        "Qwen/Qwen3.8-27B",
        "llm-jp/llm-jp-3-13b-instruct3",
        "LGAI-EXAONE/EXAONE-4.5-33B",
    ),
    "math": (
        "Qwen/Qwen3.6-35B-A3B",
        "Qwen/Qwen3.8-27B",
        "zai-org/GLM-4.7-Flash",
        "deepseek-ai/DeepSeek-V3.2-Exp",
        "llm-jp/llm-jp-3-172b-instruct3",
    ),
    "coding": (
        "Qwen/Qwen3.6-35B-A3B",
        "Qwen/Qwen3.8-27B",
        "zai-org/GLM-4.7-Flash",
        "deepseek-ai/DeepSeek-V3.2-Exp",
        "LGAI-EXAONE/K-EXAONE-2.0",
    ),
    "vision": (
        "LGAI-EXAONE/EXAONE-4.5-33B",
        "LGAI-EXAONE/K-EXAONE-2.0",
        "Qwen/Qwen3.8-27B",
    ),
    "planning": (
        "zai-org/GLM-4.7-Flash",
        "Qwen/Qwen3.6-35B-A3B",
        "Qwen/Qwen3.8-27B",
        "deepseek-ai/DeepSeek-V3.2-Exp",
        "LGAI-EXAONE/K-EXAONE-2.0",
    ),
    "research": (
        "zai-org/GLM-4.7-Flash",
        "Qwen/Qwen3.6-35B-A3B",
        "Qwen/Qwen3.8-27B",
        "deepseek-ai/DeepSeek-V3.2-Exp",
    ),
}


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _matches(loaded: str, canonical: str) -> bool:
    a = _normalise(loaded)
    b = _normalise(canonical)
    return bool(a and b and (a == b or a in b or b in a))


def classify_task(text: str, *, has_image: bool = False) -> tuple[str, int]:
    value = " ".join(str(text or "").casefold().split())
    if has_image:
        task = "vision"
    else:
        scores = {
            task: sum(1 for marker in markers if marker in value)
            for task, markers in _TASK_MARKERS.items()
        }
        best_task, best_score = max(scores.items(), key=lambda item: item[1], default=("conversation", 0))
        task = best_task if best_score else "conversation"

    complexity = 1
    if len(value) >= 180 or any(marker in value for marker in _COMPLEX_MARKERS):
        complexity = 2
    if len(value) >= 500 or sum(1 for marker in _COMPLEX_MARKERS if marker in value) >= 2:
        complexity = 3
    return task, complexity


def _canonical_priority(configured_priority: str | Iterable[str] | None) -> list[str]:
    if isinstance(configured_priority, str):
        raw = configured_priority.replace("\n", "|").replace(",", "|")
        items = [item.strip() for item in raw.split("|") if item.strip()]
    elif configured_priority is None:
        items = []
    else:
        items = [str(item).strip() for item in configured_priority if str(item).strip()]
    return items or list(_EFFICIENCY_ORDER)


def rank_loaded_models(
    loaded_models: Iterable[str],
    *,
    text: str,
    has_image: bool = False,
    configured_priority: str | Iterable[str] | None = None,
) -> tuple[list[str], str, int]:
    loaded = [str(model).strip() for model in loaded_models if str(model).strip()]
    task, complexity = classify_task(text, has_image=has_image)
    if not loaded:
        return [], task, complexity

    task_order = list(_TASK_ORDER.get(task, _TASK_ORDER["conversation"]))
    efficiency = _canonical_priority(configured_priority)

    # For the hardest coding/math/planning work, a served heavyweight specialist
    # may move ahead of generalists. It is never loaded automatically.
    if complexity >= 3 and task in {"coding", "math", "planning", "research"}:
        heavy = ["deepseek-ai/DeepSeek-V3.2-Exp", "LGAI-EXAONE/K-EXAONE-2.0"]
        task_order = heavy + [item for item in task_order if item not in heavy]

    canonical_order: list[str] = []
    for item in [*task_order, *efficiency, *_EFFICIENCY_ORDER]:
        if item not in canonical_order:
            canonical_order.append(item)

    ranked: list[str] = []
    for canonical in canonical_order:
        for model in loaded:
            if model not in ranked and _matches(model, canonical):
                ranked.append(model)
    ranked.extend(model for model in loaded if model not in ranked)
    return ranked, task, complexity


class JarvisCoreRouter:
    """Select a specialist brain while keeping one JARVIS identity."""

    def __init__(self, *, consensus_enabled: bool = True, consensus_min_complexity: int = 3) -> None:
        self.consensus_enabled = bool(consensus_enabled)
        self.consensus_min_complexity = max(1, int(consensus_min_complexity))

    def decide(
        self,
        loaded_models: Iterable[str],
        *,
        text: str,
        has_image: bool = False,
        configured_priority: str | Iterable[str] | None = None,
    ) -> CoreDecision:
        ranked, task, complexity = rank_loaded_models(
            loaded_models,
            text=text,
            has_image=has_image,
            configured_priority=configured_priority,
        )
        if not ranked:
            return CoreDecision(task=task, complexity=complexity, primary_model="", reason="nessun modello locale disponibile")

        advisor = ""
        if (
            self.consensus_enabled
            and complexity >= self.consensus_min_complexity
            and len(ranked) >= 2
            and task != "vision"
        ):
            advisor = ranked[1]

        reason = f"specialista {task}; complessità {complexity}; priorità efficienza/specializzazione"
        return CoreDecision(
            task=task,
            complexity=complexity,
            primary_model=ranked[0],
            advisor_model=advisor,
            reason=reason,
        )
