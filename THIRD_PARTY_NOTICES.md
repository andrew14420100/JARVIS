# Third-party notices

This project includes original code and architecture informed by publicly available open-source projects and may connect to optional public services.

## QwenAudio / CosyVoice

Repository: `https://github.com/QwenAudio/CosyVoice`

Model used by the local voice setup: `FunAudioLLM/Fun-CosyVoice3-0.5B-2512`

License: Apache License 2.0 for the upstream repository and the referenced Hugging Face model metadata.

JARVIS does not vendor the CosyVoice source tree or model weights. `setup-cosyvoice.ps1` creates a separate local Conda environment, clones the upstream repository into the ignored `.local/` directory, and downloads the model into an ignored local model directory. The private reference voice remains under the ignored `private/` directory and is never intended to be committed to GitHub.

JARVIS uses CosyVoice zero-shot voice cloning and streaming inference. The reference speaker representation is prepared once when the local voice service starts, then reused for subsequent utterances to reduce latency.

## PanPenek/JarvisAi

Repository: `https://github.com/PanPenek/JarvisAi`

License: MIT

Referenced ideas include local wake-word detection with openWakeWord, faster-whisper speech recognition, local Kokoro text-to-speech, microphone handoff between wake/STT stages, and local assistant architecture. The implementation in this repository has been adapted to JARVIS's own FastAPI, cloud/local brain, tool-policy, memory, and WebGL frontend architecture.

## Legacy optional Fish Audio S2 Pro adapter

Repository: `https://github.com/fishaudio/fish-speech`

License: Fish Audio Research License. See the upstream repository/model for the current terms.

A legacy adapter remains in the codebase for explicit `JARVIS_TTS_MODE=cloud` configurations, but the default JARVIS voice path is local CosyVoice and does not call Fish Audio.
