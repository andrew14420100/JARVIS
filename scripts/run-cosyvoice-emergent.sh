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

if [[ ! -x "${VENV_PY}" || ! -d "${COSY_REPO}" || ! -d "${MODEL_DIR}" ]]; then
  echo "[JARVIS] CosyVoice non è ancora installato. Esegui scripts/setup-cosyvoice-emergent.sh"
  exit 30
fi

if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  echo "[JARVIS] CosyVoice userà la GPU NVIDIA di Emergent."
elif [[ "${JARVIS_ALLOW_CPU_COSYVOICE:-0}" != "1" ]]; then
  echo "[JARVIS] Nessuna GPU NVIDIA disponibile. Arresto per evitare una voce troppo lenta."
  echo "[JARVIS] Per test CPU: export JARVIS_ALLOW_CPU_COSYVOICE=1"
  exit 31
else
  echo "[JARVIS] Modalità CPU forzata: la latenza potrebbe essere elevata."
fi

mkdir -p "$(dirname "${VOICE_AUDIO}")"

while [[ ! -s "${VOICE_AUDIO}" || ! -s "${VOICE_TEXT}" ]]; do
  echo "[JARVIS] In attesa del campione vocale: private/voices/jarvis.wav + jarvis.txt"
  sleep 20
done

export PYTHONUNBUFFERED=1
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"

exec "${VENV_PY}" "${ROOT_DIR}/local_voice/cosyvoice_server.py" \
  --cosyvoice-repo "${COSY_REPO}" \
  --model-dir "${MODEL_DIR}" \
  --reference-audio "${VOICE_AUDIO}" \
  --reference-text "${VOICE_TEXT}" \
  --port "${PORT}"
