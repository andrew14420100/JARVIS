# Third-party notices

This project includes original code and architecture informed by publicly available open-source projects and may connect to optional public services.

## QwenAudio / CosyVoice

Repository: `https://github.com/QwenAudio/CosyVoice`

Model used by the voice setup: `FunAudioLLM/Fun-CosyVoice3-0.5B-2512`

License: Apache License 2.0 for the upstream repository and the referenced Hugging Face model metadata.

JARVIS does not vendor the CosyVoice source tree or model weights. On Emergent, `scripts/setup-cosyvoice-emergent.sh` creates a separate runtime under the ignored `/app/.local/cosyvoice/` path, clones the upstream repository, downloads the model, and registers the voice worker with Supervisor when available. A Windows/local setup helper may also be kept for development, but the deployed JARVIS voice path targets the Emergent worker.

The private reference voice remains under the ignored `/app/private/voices/` directory and is never intended to be committed to GitHub. JARVIS uses CosyVoice zero-shot voice cloning and streaming inference. The reference speaker representation is prepared once when the voice worker starts, then reused for subsequent utterances. The worker also performs one warm-up synthesis before reporting ready so the first real reply does not pay the full lazy initialization cost.

## PanPenek/JarvisAi

Repository: `https://github.com/PanPenek/JarvisAi`

License: MIT

Referenced ideas include local wake-word detection with openWakeWord, faster-whisper speech recognition, local Kokoro text-to-speech, microphone handoff between wake/STT stages, and local assistant architecture. The implementation in this repository has been adapted to JARVIS's own FastAPI, cloud/local brain, tool-policy, memory, and WebGL frontend architecture.

## Legacy optional Fish Audio S2 Pro adapter

Repository: `https://github.com/fishaudio/fish-speech`

License: Fish Audio Research License. See the upstream repository/model for the current terms.

A legacy adapter remains in the codebase for explicit `JARVIS_TTS_MODE=cloud` configurations, but the default JARVIS voice path is CosyVoice and does not call Fish Audio.
