#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VOICE_AUDIO="${ROOT_DIR}/private/voices/jarvis.wav"
VOICE_TEXT="${ROOT_DIR}/private/voices/jarvis.txt"
SERVICE_URL="${JARVIS_COSYVOICE_SERVICE_URL:-http://127.0.0.1:8765}"

echo "=== JARVIS / CosyVoice Emergent check ==="
echo "root: ${ROOT_DIR}"
echo

if command -v nvidia-smi >/dev/null 2>&1; then
  echo "[GPU]"
  nvidia-smi --query-gpu=name,memory.total,memory.used,utilization.gpu,driver_version --format=csv,noheader 2>&1 | head -n 4
else
  echo "[GPU] nvidia-smi non disponibile"
fi

echo
echo "[DISK]"
df -h "${ROOT_DIR}" | tail -n 1

echo
echo "[VOICE FILES]"
[[ -s "${VOICE_AUDIO}" ]] && echo "jarvis.wav: OK ($(du -h "${VOICE_AUDIO}" | cut -f1))" || echo "jarvis.wav: MANCANTE"
[[ -s "${VOICE_TEXT}" ]] && echo "jarvis.txt: OK" || echo "jarvis.txt: MANCANTE"

echo
echo "[SUPERVISOR]"
if command -v supervisorctl >/dev/null 2>&1; then
  supervisorctl status jarvis-cosyvoice 2>&1 || true
else
  echo "supervisorctl non disponibile"
fi

echo
echo "[SERVICE]"
curl -sS --max-time 3 "${SERVICE_URL}/health" 2>&1 || echo "CosyVoice non è ancora raggiungibile"
echo

echo
echo "[RECENT LOGS]"
[[ -f /var/log/jarvis-cosyvoice.log ]] && tail -n 15 /var/log/jarvis-cosyvoice.log || true
[[ -f /var/log/jarvis-cosyvoice-error.log ]] && tail -n 15 /var/log/jarvis-cosyvoice-error.log || true
