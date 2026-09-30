#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COSY_ROOT="${ROOT_DIR}/.local/cosyvoice"
COSY_REPO="${COSY_ROOT}/CosyVoice"
MODEL_DIR="${COSY_ROOT}/models/Fun-CosyVoice3-0.5B"
VENV_DIR="${COSY_ROOT}/venv"
VOICE_DIR="${ROOT_DIR}/private/voices"
SUPERVISOR_CONF="/etc/supervisor/conf.d/jarvis-cosyvoice.conf"
CPU_REQUIREMENTS="${COSY_ROOT}/requirements-cpu.txt"

mkdir -p "${COSY_ROOT}" "${COSY_ROOT}/models" "${VOICE_DIR}"
chmod +x "${ROOT_DIR}/scripts/run-cosyvoice-emergent.sh"

echo "[JARVIS] Emergent CosyVoice setup"
echo "[JARVIS] Root: ${ROOT_DIR}"

GPU_AVAILABLE=0
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  GPU_AVAILABLE=1
  echo "[JARVIS] NVIDIA GPU rilevata:"
  nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader | head -n 1 || true
else
  echo "[JARVIS] Nessuna GPU NVIDIA visibile: preparo CosyVoice in modalità CPU."
  echo "[JARVIS] La qualità resta la stessa; la latenza dipenderà dalle CPU assegnate da Emergent."
fi

CPU_FLAG=0
if [[ "${GPU_AVAILABLE}" != "1" ]]; then
  CPU_FLAG=1
fi

# Supervisor is always registered. In CPU mode the flag is persisted in the
# program environment so the worker does not remain stuck in WAITING_FOR_GPU.
if command -v supervisorctl >/dev/null 2>&1 && [[ -d /etc/supervisor/conf.d ]] && [[ -w /etc/supervisor/conf.d ]]; then
  cat > "${SUPERVISOR_CONF}" <<EOF
[program:jarvis-cosyvoice]
command=/bin/bash ${ROOT_DIR}/scripts/run-cosyvoice-emergent.sh
directory=${ROOT_DIR}
autostart=true
autorestart=true
startsecs=0
startretries=999
stopasgroup=true
killasgroup=true
stdout_logfile=/var/log/jarvis-cosyvoice.log
stderr_logfile=/var/log/jarvis-cosyvoice-error.log
environment=PYTHONUNBUFFERED="1",JARVIS_ALLOW_CPU_COSYVOICE="${CPU_FLAG}"
EOF
  echo "[JARVIS] Registro jarvis-cosyvoice in Supervisor..."
  supervisorctl reread || true
  supervisorctl update || true
else
  echo "[JARVIS] Supervisor non disponibile: il servizio dovrà essere avviato manualmente."
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
  echo "[JARVIS] CosyVoice richiede Python 3.10 o 3.11 su Emergent."
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

if [[ "${GPU_AVAILABLE}" == "1" ]]; then
  echo "[JARVIS] Installo runtime CosyVoice CUDA ufficiale..."
  "${VENV_DIR}/bin/python" -m pip install -r "${COSY_REPO}/requirements.txt"
else
  echo "[JARVIS] Installo runtime CosyVoice CPU..."
  # The upstream Linux requirements intentionally pull CUDA ONNX/TensorRT and
  # CUDA PyTorch wheels. For a CPU-only Emergent container we retain the common
  # inference dependencies and replace those packages with CPU builds.
  grep -Ev '^(--extra-index-url|deepspeed==|onnxruntime-gpu==|tensorrt-cu12|torch==|torchaudio==)' \
    "${COSY_REPO}/requirements.txt" > "${CPU_REQUIREMENTS}"
  "${VENV_DIR}/bin/python" -m pip install \
    --index-url https://download.pytorch.org/whl/cpu \
    torch==2.3.1 torchaudio==2.3.1
  "${VENV_DIR}/bin/python" -m pip install onnxruntime==1.18.0
  "${VENV_DIR}/bin/python" -m pip install -r "${CPU_REQUIREMENTS}"
fi

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

if command -v supervisorctl >/dev/null 2>&1; then
  supervisorctl reread || true
  supervisorctl update || true
  supervisorctl restart jarvis-cosyvoice || true
fi

echo
echo "[JARVIS] Setup completato."
echo "[JARVIS] Modalità: $([[ "${GPU_AVAILABLE}" == "1" ]] && echo GPU || echo CPU)"
echo "[JARVIS] Campione voce: ${VOICE_DIR}/jarvis.wav"
echo "[JARVIS] Trascrizione: ${VOICE_DIR}/jarvis.txt"
if [[ ! -s "${VOICE_DIR}/jarvis.txt" ]]; then
  echo "[JARVIS] ATTENZIONE: jarvis.txt manca ancora. Crealo prima del test vocale."
fi
