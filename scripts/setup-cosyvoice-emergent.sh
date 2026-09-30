#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COSY_ROOT="${ROOT_DIR}/.local/cosyvoice"
COSY_REPO="${COSY_ROOT}/CosyVoice"
MODEL_DIR="${COSY_ROOT}/models/Fun-CosyVoice3-0.5B"
VENV_DIR="${COSY_ROOT}/venv"
VOICE_DIR="${ROOT_DIR}/private/voices"
SUPERVISOR_CONF="/etc/supervisor/conf.d/jarvis-cosyvoice.conf"

mkdir -p "${COSY_ROOT}" "${COSY_ROOT}/models" "${VOICE_DIR}"

echo "[JARVIS] Emergent CosyVoice setup"
echo "[JARVIS] Root: ${ROOT_DIR}"

GPU_AVAILABLE=0
if command -v nvidia-smi >/dev/null 2>&1; then
  if nvidia-smi >/dev/null 2>&1; then
    GPU_AVAILABLE=1
    echo "[JARVIS] NVIDIA GPU rilevata:"
    nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader | head -n 1 || true
  fi
fi

if [[ "${GPU_AVAILABLE}" != "1" ]]; then
  echo "[JARVIS] ATTENZIONE: nessuna GPU NVIDIA visibile nel container Emergent."
  echo "[JARVIS] Per la risposta vocale quasi istantanea serve una GPU disponibile."
  echo "[JARVIS] Per forzare comunque l'installazione CPU: JARVIS_ALLOW_CPU_COSYVOICE=1 bash $0"
  if [[ "${JARVIS_ALLOW_CPU_COSYVOICE:-0}" != "1" ]]; then
    exit 20
  fi
fi

choose_python() {
  if [[ -n "${JARVIS_COSYVOICE_PYTHON:-}" ]] && command -v "${JARVIS_COSYVOICE_PYTHON}" >/dev/null 2>&1; then
    echo "${JARVIS_COSYVOICE_PYTHON}"
    return 0
  fi
  for candidate in python3.10 python3.11 python3; do
    if command -v "${candidate}" >/dev/null 2>&1; then
      if "${candidate}" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if (3, 10) <= sys.version_info[:2] < (3, 12) else 1)
PY
      then
        echo "${candidate}"
        return 0
      fi
    fi
  done
  return 1
}

PYTHON_BIN="$(choose_python || true)"
if [[ -z "${PYTHON_BIN}" ]]; then
  echo "[JARVIS] CosyVoice richiede un Python compatibile. Su Emergent serve Python 3.10 o 3.11."
  exit 21
fi

echo "[JARVIS] Python CosyVoice: $(${PYTHON_BIN} --version 2>&1)"

if command -v apt-get >/dev/null 2>&1 && [[ "$(id -u)" == "0" ]]; then
  if ! command -v sox >/dev/null 2>&1; then
    echo "[JARVIS] Installo sox/libsox-dev..."
    apt-get update -y
    DEBIAN_FRONTEND=noninteractive apt-get install -y sox libsox-dev
  fi
fi

if [[ ! -d "${COSY_REPO}/.git" ]]; then
  echo "[JARVIS] Clono QwenAudio/CosyVoice..."
  git clone --recursive https://github.com/QwenAudio/CosyVoice.git "${COSY_REPO}"
else
  echo "[JARVIS] Aggiorno CosyVoice..."
  git -C "${COSY_REPO}" fetch origin main
  git -C "${COSY_REPO}" checkout main
  git -C "${COSY_REPO}" reset --hard origin/main
  git -C "${COSY_REPO}" submodule update --init --recursive
fi

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  echo "[JARVIS] Creo ambiente Python separato..."
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

"${VENV_DIR}/bin/python" -m pip install --upgrade pip setuptools wheel

echo "[JARVIS] Installo runtime CosyVoice ufficiale..."
"${VENV_DIR}/bin/python" -m pip install -r "${COSY_REPO}/requirements.txt"
"${VENV_DIR}/bin/python" -m pip install "huggingface_hub>=0.27,<1"

echo "[JARVIS] Scarico/aggiorno Fun-CosyVoice3-0.5B-2512..."
"${VENV_DIR}/bin/python" - <<PY
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id="FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
    local_dir=r"${MODEL_DIR}",
)
print("[JARVIS] Modello pronto: ${MODEL_DIR}")
PY

chmod +x "${ROOT_DIR}/scripts/run-cosyvoice-emergent.sh"

if command -v supervisorctl >/dev/null 2>&1 && [[ -d /etc/supervisor/conf.d ]] && [[ -w /etc/supervisor/conf.d ]]; then
  cat > "${SUPERVISOR_CONF}" <<EOF
[program:jarvis-cosyvoice]
command=/bin/bash ${ROOT_DIR}/scripts/run-cosyvoice-emergent.sh
directory=${ROOT_DIR}
autostart=true
autorestart=true
startsecs=3
startretries=999
stopasgroup=true
killasgroup=true
stdout_logfile=/var/log/jarvis-cosyvoice.log
stderr_logfile=/var/log/jarvis-cosyvoice-error.log
environment=PYTHONUNBUFFERED="1"
EOF
  echo "[JARVIS] Registro jarvis-cosyvoice in Supervisor..."
  supervisorctl reread || true
  supervisorctl update || true
else
  echo "[JARVIS] Supervisor non disponibile: avvio manuale con scripts/run-cosyvoice-emergent.sh"
fi

echo
echo "[JARVIS] Setup completato."
echo "[JARVIS] Campione voce atteso in: ${VOICE_DIR}/jarvis.wav"
echo "[JARVIS] Trascrizione attesa in: ${VOICE_DIR}/jarvis.txt"
echo "[JARVIS] Finché questi due file non esistono, il servizio resta in attesa senza andare in crash-loop."
