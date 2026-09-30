# Third-party notices

This project includes original code and architecture informed by publicly available open-source projects and may connect to optional public services.

## PanPenek/JarvisAi

Repository: `https://github.com/PanPenek/JarvisAi`

License: MIT

Referenced ideas include local wake-word detection with openWakeWord, faster-whisper speech recognition, local Kokoro text-to-speech, microphone handoff between wake/STT stages, and local assistant architecture. The implementation in this repository has been adapted to JARVIS's own FastAPI, cloud/local brain, tool-policy, memory, and WebGL frontend architecture.

## Fish Audio S2 Pro

Repository: `https://github.com/fishaudio/fish-speech`

Public preview used by the browser voice adapter: `artificialguybr/fish-s2-pro-zero` on Hugging Face Spaces.

License: Fish Audio Research License. See the upstream repository/model for the current terms.

JARVIS does not vendor Fish Audio model weights. The optional cloud TTS adapter sends the text to the public ZeroGPU Gradio Space and plays the returned audio. Availability and queue limits are controlled by the external Space provider.

## Gradio Client

Repository: `https://github.com/gradio-app/gradio`

Used to call the public Fish Audio Gradio Space from the JARVIS backend.
