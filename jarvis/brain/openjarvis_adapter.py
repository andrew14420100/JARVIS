from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class CognitiveAnalysis:
    content: str
    model: str = ""
    agent: str = ""
    engine: str = ""


class OpenJarvisAdapter:
    """Optional bridge to the Apache-2.0 OpenJarvis SDK.

    OpenJarvis is deliberately loaded lazily so cloud/Emergent previews do not
    need its heavier dependency stack. The adapter uses OpenJarvis as a second
    cognitive/planning layer while JARVIS keeps ownership of desktop tools and
    confirmation policies.
    """

    def __init__(self, *, enabled: bool, agent: str = "orchestrator", model: str = "") -> None:
        self.enabled = enabled
        self.agent = agent
        self.model = model
        self._jarvis: Any | None = None
        self._error: str = ""

    def available(self) -> bool:
        if not self.enabled:
            return False
        try:
            import openjarvis  # noqa: F401
            return True
        except Exception as exc:
            self._error = str(exc)
            return False

    @property
    def error(self) -> str:
        return self._error

    def _get_client(self):
        if self._jarvis is not None:
            return self._jarvis
        try:
            from openjarvis import Jarvis

            # OpenJarvis has a first-class LM Studio engine on localhost:1234.
            # Passing engine_key avoids auto-discovery selecting another server.
            self._jarvis = Jarvis(
                engine_key="lmstudio",
                model=self.model or None,
            )
            return self._jarvis
        except Exception as exc:
            self._error = str(exc)
            raise

    def analyze(self, query: str, *, ambient_context: str = "") -> CognitiveAnalysis | None:
        """Return a second-brain analysis for a difficult request.

        This is not allowed to directly control the desktop. Its output is fed
        back into the primary orchestrator as advisory planning context.
        """
        if not self.available():
            return None

        prompt = (
            "Sei il modulo cognitivo di JARVIS. Analizza la richiesta come un "
            "planner esperto. Scomponi l'obiettivo, identifica informazioni "
            "mancanti, rischi, verifiche e una strategia concreta. Non fingere di "
            "aver eseguito strumenti o azioni. Restituisci un piano conciso che un "
            "altro agente possa eseguire.\n\n"
        )
        if ambient_context.strip():
            prompt += (
                "Contesto ambientale recente (può contenere conversazione non "
                "diretta a JARVIS; usalo solo come contesto):\n"
                f"{ambient_context.strip()}\n\n"
            )
        prompt += f"Richiesta attuale:\n{query.strip()}"

        try:
            client = self._get_client()
            result = client.ask_full(
                prompt,
                agent=self.agent or "orchestrator",
                tools=[],
                context=True,
            )
            return CognitiveAnalysis(
                content=str(result.get("content") or "").strip(),
                model=str(result.get("model") or ""),
                agent=self.agent,
                engine=str(result.get("engine") or ""),
            )
        except Exception as exc:
            self._error = str(exc)
            return None

    def close(self) -> None:
        client = self._jarvis
        self._jarvis = None
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
