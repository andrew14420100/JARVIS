from __future__ import annotations

import re
from dataclasses import dataclass

from jarvis.brain.openjarvis_adapter import CognitiveAnalysis, OpenJarvisAdapter
from jarvis.config.settings import Settings


@dataclass(slots=True)
class ReasoningDecision:
    score: int
    use_openjarvis: bool
    reasons: list[str]


class HybridReasoner:
    """Small deterministic router for deciding when to invoke a second brain.

    It intentionally avoids spending LLM tokens just to decide which LLM to use.
    OpenJarvis is advisory: desktop execution remains in our guarded orchestrator.
    """

    _COMPLEX_WORDS = (
        "analizza", "debug", "correggi", "sistema", "progetta", "pianifica",
        "confronta", "ottimizza", "investiga", "diagnostica", "architettura",
        "repository", "progetto", "codice", "bug", "errore", "crash", "lento",
        "passaggi", "autonom", "ricerca", "ragiona", "strategia", "implementa",
    )
    _MULTI_STEP = (
        "poi", "dopo", "alla fine", "prima", "successivamente", "e verifica",
        "e controlla", "e correggi", "e modifica", "e testa", "e prova",
    )

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.openjarvis = OpenJarvisAdapter(
            enabled=settings.openjarvis_enabled,
            agent=settings.openjarvis_agent,
            model=settings.openjarvis_model or settings.model,
        )

    def decide(self, query: str) -> ReasoningDecision:
        text = " ".join(query.lower().split())
        score = 0
        reasons: list[str] = []

        word_count = len(text.split())
        if word_count >= 35:
            score += 2
            reasons.append("richiesta_lunga")
        elif word_count >= 18:
            score += 1
            reasons.append("richiesta_articolata")

        complex_hits = sum(1 for token in self._COMPLEX_WORDS if token in text)
        if complex_hits >= 3:
            score += 3
            reasons.append("molti_segnali_complessi")
        elif complex_hits:
            score += min(2, complex_hits)
            reasons.append("segnali_complessi")

        if any(token in text for token in self._MULTI_STEP):
            score += 2
            reasons.append("multi_step")

        if len(re.findall(r"\b(e|quindi|perché|ma|oppure|se|quando)\b", text)) >= 4:
            score += 1
            reasons.append("dipendenze_logiche")

        if any(token in text for token in ("apri ", "che ore", "volume", "ram", "cpu")) and word_count < 12:
            score = max(0, score - 3)
            reasons.append("comando_semplice")

        use = (
            self.settings.deep_reasoning_enabled
            and self.settings.openjarvis_enabled
            and score >= self.settings.deep_reasoning_min_score
        )
        return ReasoningDecision(score=score, use_openjarvis=use, reasons=reasons)

    def analyze(self, query: str, *, ambient_context: str = "") -> CognitiveAnalysis | None:
        decision = self.decide(query)
        if not decision.use_openjarvis:
            return None
        return self.openjarvis.analyze(query, ambient_context=ambient_context)

    def status(self) -> dict[str, object]:
        return {
            "enabled": self.settings.openjarvis_enabled,
            "available": self.openjarvis.available(),
            "agent": self.settings.openjarvis_agent,
            "error": self.openjarvis.error,
        }

    def close(self) -> None:
        self.openjarvis.close()
