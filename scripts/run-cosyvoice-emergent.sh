#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COSY_ROOT="${ROOT_DIR}/.local/cosyvoice"
COSY_REPO="${COSY_ROOT}/CosyVoice"
MODEL_DIR="${COSY_ROOT}/models/Fun-CosyVoice3-0.5B"
VENV_PY="${COSY_ROOT}/venv/bin/python"
VOICE_AUDIO="${ROOT_DIR}/private/voices/jarvis.wav"
VOICE_TEXT="${ROOT_DIR}/private/voices/jarvis.txt"
PORT="${JARVIS_COSYVOICE_PORT:-8765}"

mkdir -p "${ROOT_DIR}/private/voices" "${COSY_ROOT}/models"

while true; do
  if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
    echo "[JARVIS] GPU NVIDIA disponibile per CosyVoice."
    break
  fi

  if [[ "${JARVIS_ALLOW_CPU_COSYVOICE:-0}" == "1" ]]; then
    echo "[JARVIS] CosyVoice in modalità CPU forzata. La latenza può essere elevata."
    break
  fi

  echo "[JARVIS] WAITING_FOR_GPU · Emergent non espone ancora una GPU NVIDIA."
  sleep 30
done

while [[ ! -x "${VENV_PY}" || ! -d "${COSY_REPO}" || ! -d "${MODEL_DIR}" ]]; do
  echo "[JARVIS] WAITING_FOR_MODEL · esegui scripts/setup-cosyvoice-emergent.sh"
  sleep 20
done

while [[ ! -s "${VOICE_AUDIO}" || ! -s "${VOICE_TEXT}" ]]; do
  echo "[JARVIS] WAITING_FOR_VOICE · servono private/voices/jarvis.wav + jarvis.txt"
  sleep 20
done

export PYTHONUNBUFFERED=1
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
fi

echo "[JARVIS] Avvio CosyVoice su 127.0.0.1:${PORT}..."
exec "${VENV_PY}" "${ROOT_DIR}/local_voice/cosyvoice_server.py" \
  --cosyvoice-repo "${COSY_REPO}" \
  --model-dir "${MODEL_DIR}" \
  --reference-audio "${VOICE_AUDIO}" \
  --reference-text "${VOICE_TEXT}" \
  --port "${PORT}"
