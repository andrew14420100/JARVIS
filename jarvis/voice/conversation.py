from __future__ import annotations

import re
import unicodedata


_NEGATED_STOP_RE = re.compile(
    r"\b(?:non|mai)\s+(?:jarvis\s+)?(?:stop|basta|fermati|fermarsi|andare\s+in\s+standby|vai\s+in\s+standby)\b"
)

_NATURAL_STOP_RES = (
    re.compile(r"\bjarvis\s+(?:stop|basta|fermati)\b"),
    re.compile(r"\b(?:stop|fermati)(?:\s+un\s+attimo)?\b"),
    re.compile(r"\bbasta\s+(?:cosi|così)\b"),
    re.compile(r"\b(?:puoi|potresti)\s+fermarti\b"),
    re.compile(r"\b(?:vai|torna|mettiti)\s+in\s+standby\b"),
    re.compile(r"\bgrazie(?:\s+jarvis)?\s+basta\b"),
)


def normalize_spoken_text(text: str) -> str:
    """Normalize STT text for intent matching without changing user content."""
    value = unicodedata.normalize("NFKC", str(text or "")).casefold()
    value = value.replace("’", "'")
    value = re.sub(r"[^\w\s']+", " ", value, flags=re.UNICODE)
    value = value.replace("'", " ")
    return " ".join(value.split())


def _contains_phrase(text: str, phrase: str) -> bool:
    if not phrase:
        return False
    return bool(re.search(rf"(?:^|\s){re.escape(phrase)}(?:$|\s)", text))


def is_stop_phrase(text: str, configured_phrases: str = "") -> bool:
    """Return True for explicit, natural requests to stop/stand by.

    The matcher accepts short conversational variants while rejecting common
    negated forms such as "non fermarti". Configured phrases remain supported
    and may appear inside a polite wrapper (for example "ok, jarvis stop").
    """
    normalized = normalize_spoken_text(text)
    if not normalized:
        return False
    if _NEGATED_STOP_RE.search(normalized):
        return False

    for item in str(configured_phrases or "").split("|"):
        phrase = normalize_spoken_text(item)
        if phrase and _contains_phrase(normalized, phrase):
            return True

    return any(pattern.search(normalized) for pattern in _NATURAL_STOP_RES)


def followup_wait_seconds(value: float, *, minimum: float = 6.0, maximum: float = 20.0) -> float:
    """Clamp conversational follow-up wait to a practical safe range."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = 10.0
    return max(minimum, min(maximum, parsed))
