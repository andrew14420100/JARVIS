from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass

import httpx

from jarvis.config.settings import get_settings
from jarvis.voice import LocalSTT, WakeWordListener


@dataclass(slots=True)
class RemoteReply:
    text: str
    model: str = ""


class EmergentJarvisClient:
    """Tiny client used by the Windows listener to talk to JARVIS on Emergent."""

    def __init__(self, base_url: str, timeout_seconds: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.client = httpx.Client(timeout=timeout_seconds)

    def close(self) -> None:
        self.client.close()

    def health(self) -> dict[str, object]:
        response = self.client.get(f"{self.base_url}/api/health", timeout=10.0)
        response.raise_for_status()
        return response.json()

    def chat(self, text: str) -> RemoteReply:
        response = self.client.post(
            f"{self.base_url}/api/chat",
            json={"message": text},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        return RemoteReply(
            text=str(data.get("reply") or "").strip(),
            model=str(data.get("model") or "").strip(),
        )

    def speak(self, text: str) -> bool:
        """Play the Emergent TTS stream locally when the remote voice is ready.

        Voice generation remains server-side. If the selected TTS engine is not
        ready yet, the conversational listener keeps working and returns False.
        """
        if not text.strip():
            return False

        try:
            import sounddevice as sd

            with self.client.stream(
                "POST",
                f"{self.base_url}/api/tts/stream",
                json={"text": text},
                timeout=self.timeout_seconds,
            ) as response:
                if response.status_code != 200:
                    return False

                sample_rate = int(response.headers.get("X-Sample-Rate") or 24000)
                with sd.RawOutputStream(
                    samplerate=sample_rate,
                    channels=1,
                    dtype="int16",
                    blocksize=0,
                    latency="low",
                ) as stream:
                    carry = b""
                    for chunk in response.iter_bytes():
                        if not chunk:
                            continue
                        data = carry + chunk
                        usable = len(data) - (len(data) % 2)
                        carry = data[usable:]
                        if usable:
                            stream.write(data[:usable])
                return True
        except Exception as exc:
            print(f"[JARVIS LISTENER] Voce remota non disponibile: {exc}")
            return False


def _normalize(text: str) -> str:
    return " ".join(str(text or "").lower().strip().split()).strip(" .,!?:;")


def main() -> None:
    settings = get_settings()
    base_url = settings.listener_remote_base_url.strip()
    if not base_url:
        raise SystemExit(
            "Configura JARVIS_LISTENER_REMOTE_BASE_URL nel file .env con l'URL "
            "pubblico del progetto Emergent, per esempio https://<progetto>.preview.emergentagent.com"
        )

    stt = LocalSTT(
        model_name=settings.stt_model,
        device=settings.stt_device,
        compute_type=settings.stt_compute_type,
        language=settings.stt_language,
    )
    wake = WakeWordListener(
        model_name=settings.wake_model,
        threshold=settings.wake_threshold,
        chunk_size=settings.wake_chunk_size,
        context_seconds=5.0,
    )

    missing: list[str] = []
    if not stt.available():
        missing.append(f"STT: {stt.dependency_status()}")
    if not wake.available():
        missing.append(f"Wake word: {wake.dependency_status()}")
    if missing:
        raise SystemExit("Componenti listener mancanti:\n- " + "\n- ".join(missing))

    remote = EmergentJarvisClient(base_url, settings.request_timeout_seconds)
    try:
        health = remote.health()
    except Exception as exc:
        remote.close()
        raise SystemExit(f"Backend Emergent non raggiungibile: {exc}") from exc

    print(f"[JARVIS LISTENER] Collegato a {base_url}")
    print(f"[JARVIS LISTENER] Backend: {'ONLINE' if health.get('ok') else 'DEGRADED'}")
    print(f"[JARVIS LISTENER] Wake word: {settings.wake_model}")
    print("[JARVIS LISTENER] Dica 'Jarvis' per iniziare. Dopo l'attivazione non serve ripeterlo.")

    stop_phrases = {
        _normalize(item)
        for item in settings.listener_stop_phrases.split("|")
        if _normalize(item)
    }
    busy = threading.Event()
    shutting_down = threading.Event()

    def end_session() -> None:
        busy.clear()
        print("[JARVIS LISTENER] STANDBY · in attesa di 'Jarvis'.")

    def conversation() -> None:
        if busy.is_set():
            return
        busy.set()
        wake.pause()
        print("[JARVIS LISTENER] WAKE · sessione vocale attiva.")

        try:
            # Let the AI acknowledge the wake word naturally rather than using a
            # hard-coded canned phrase. This is optional because it costs one AI
            # turn and can be disabled from .env.
            if settings.listener_wake_ack_enabled:
                try:
                    acknowledgement = remote.chat("Jarvis")
                    if acknowledgement.text:
                        print(f"JARVIS: {acknowledgement.text}")
                        remote.speak(acknowledgement.text)
                except Exception as exc:
                    print(f"[JARVIS LISTENER] Wake acknowledgement non disponibile: {exc}")

            first_turn = True
            while not shutting_down.is_set():
                print("[JARVIS LISTENER] LISTENING")
                audio = stt.record_until_silence(
                    silence_seconds=0.9,
                    max_seconds=settings.listener_max_utterance_seconds,
                    initial_silence_seconds=(
                        15.0 if first_turn else settings.listener_followup_silence_seconds
                    ),
                )
                first_turn = False

                if not stt.last_recording_heard_speech:
                    end_session()
                    return

                try:
                    result = stt.transcribe(audio)
                except Exception as exc:
                    print(f"[JARVIS LISTENER] Trascrizione fallita: {exc}")
                    continue

                text = result.text.strip()
                if not text:
                    continue

                print(f"TU: {text}")
                if _normalize(text) in stop_phrases:
                    end_session()
                    return

                try:
                    reply = remote.chat(text)
                except httpx.HTTPStatusError as exc:
                    body = exc.response.text[:500] if exc.response is not None else ""
                    print(f"[JARVIS LISTENER] Emergent ha rifiutato il turno: {exc} {body}")
                    continue
                except Exception as exc:
                    print(f"[JARVIS LISTENER] Errore rete: {exc}")
                    time.sleep(0.5)
                    continue

                if not reply.text:
                    continue

                print(f"JARVIS: {reply.text}")
                # If the remote cloned voice is still pending, the loop remains
                # fully usable and immediately returns to microphone listening.
                remote.speak(reply.text)
        finally:
            wake.resume()
            busy.clear()

    try:
        wake.run(conversation, busy=busy.is_set)
    except KeyboardInterrupt:
        pass
    finally:
        shutting_down.set()
        stt.abort()
        wake.stop()
        remote.close()
        print("[JARVIS LISTENER] Arrestato.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[JARVIS LISTENER] Errore fatale: {exc}", file=sys.stderr)
        raise
