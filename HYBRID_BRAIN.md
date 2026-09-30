# JARVIS Hybrid Brain

The local desktop runtime combines two complementary ideas without replacing the custom WebGL UI.

## 1. OpenJarvis cognitive layer

For requests that score as complex or multi-step, `HybridReasoner` can invoke the separately installed Apache-2.0 `OpenJarvis` package using its first-class `lmstudio` engine and the configured agent (default: `orchestrator`).

OpenJarvis does **not** receive direct control of this project's Windows tools. It returns an advisory analysis/plan, which is injected into the primary JARVIS orchestrator. The primary orchestrator then performs real tool calls through this project's registry and security/confirmation policies.

This separation is intentional:

```text
user request
    |
    +-- simple --> primary LM Studio agent --> guarded tools
    |
    +-- complex --> OpenJarvis planner
                    |
                    v
              advisory plan
                    |
                    v
              primary LM Studio agent
                    |
                    v
                guarded tools
```

## 2. Room-presence context

The wake-word listener always needs microphone chunks to detect `Hey Jarvis`. JARVIS now keeps a small circular PCM buffer of those already-received chunks in RAM. No ambient audio is written to disk.

When the wake phrase is detected:

1. the recent audio buffer is snapshotted;
2. the wake microphone is paused;
3. the direct command is recorded and transcribed;
4. only then is the recent room buffer transcribed;
5. that text is treated as **context, not instructions**;
6. the context is passed to the primary and secondary reasoning layers;
7. the raw ambient audio buffer is cleared.

This means a conversation can look like:

```text
Person A: Domani potremmo fare un picnic.
Person B: Ma forse piove. Meglio organizzare qualcosa al chiuso?
You: Jarvis, che ne pensi?
```

Jarvis can use the preceding discussion when interpreting `che ne pensi?` instead of treating it as an isolated sentence.

## Privacy

- Ambient audio is RAM-only and short-lived.
- Presence text is also ephemeral and is not automatically added to long-term SQLite memory.
- Obvious secret patterns (password/PIN/API key/card-like numbers) are rejected by the presence text buffer.
- Desktop actions still pass through `SAFE`, `CONFIRMATION_REQUIRED`, and `BLOCKED` policies.

## Local setup

`run-local.ps1` installs:

- `requirements-local.txt` for Whisper, Kokoro, openWakeWord and desktop control;
- `requirements-cognitive.txt` for the optional OpenJarvis cognitive layer;
- the React/WebGL frontend.

Open LM Studio first and expose its OpenAI-compatible server at:

```text
http://127.0.0.1:1234/v1
```

Then run:

```powershell
powershell -ExecutionPolicy Bypass -File .\run-local.ps1
```

Python 3.10-3.13 is required by the current OpenJarvis package. Python 3.11 or 3.12 is recommended for this project.
