$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    py -m venv .venv
}

$python = ".\.venv\Scripts\python.exe"

$versionOk = & $python -c "import sys; print(int(sys.version_info < (3,14)))"
if ($versionOk.Trim() -ne "1") {
    throw "OpenJarvis richiede Python >=3.10 e <3.14. Crea .venv con Python 3.11, 3.12 o 3.13."
}

Write-Host "[1/7] Aggiorno Python e dipendenze locali..."
& $python -m pip install --upgrade pip
& $python -m pip install -r requirements-local.txt

Write-Host "[2/7] Installo Hybrid Brain OpenJarvis..."
& $python -m pip install -r requirements-cognitive.txt

Write-Host "[3/7] Controllo modelli wake-word..."
& $python -c "from openwakeword import utils; utils.download_models()"

Write-Host "[4/7] Preparo configurazione..."
if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Creato .env da .env.example."
}

Write-Host "[5/7] Compilo la UI React/WebGL..."
$npm = Get-Command npm -ErrorAction SilentlyContinue
if (-not $npm) {
    throw "Node.js/npm non trovato. Installa Node.js LTS per usare la nuova UI WebGL locale."
}
Push-Location "frontend"
try {
    if (-not (Test-Path "node_modules")) {
        npm install
    }
    npm run build
} finally {
    Pop-Location
}

Write-Host "[6/7] Controllo voce locale CosyVoice..."
$voiceAudio = Join-Path $PSScriptRoot "private\voices\jarvis.wav"
$voiceText = Join-Path $PSScriptRoot "private\voices\jarvis.txt"
$cosyRepo = Join-Path $PSScriptRoot ".local\cosyvoice\CosyVoice"
$cosyModel = Join-Path $PSScriptRoot ".local\cosyvoice\models\Fun-CosyVoice3-0.5B"

function Test-CosyVoiceReady {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8765/health" -TimeoutSec 1
        return [bool]$health.ok
    } catch {
        return $false
    }
}

if ((Test-Path $voiceAudio) -and (Test-Path $voiceText) -and (Test-Path $cosyRepo) -and (Test-Path $cosyModel)) {
    if (-not (Test-CosyVoiceReady)) {
        Write-Host "Avvio CosyVoice 3 in background..."
        powershell -ExecutionPolicy Bypass -File ".\start-cosyvoice.ps1" -Background

        $ready = $false
        for ($i = 0; $i -lt 120; $i++) {
            Start-Sleep -Seconds 1
            if (Test-CosyVoiceReady) {
                $ready = $true
                break
            }
        }
        if ($ready) {
            Write-Host "CosyVoice pronto. Voce clonata caricata in memoria."
        } else {
            Write-Warning "CosyVoice non e' diventato pronto entro 120 secondi. JARVIS continuera' senza TTS."
        }
    } else {
        Write-Host "CosyVoice e' gia' attivo."
    }
} else {
    Write-Host "Campione vocale non ancora configurato: JARVIS partira' senza TTS locale."
    Write-Host "Quando avrai il WAV, useremo private\voices\jarvis.wav e private\voices\jarvis.txt."
}

Write-Host "[7/7] Avvio JARVIS..."
Write-Host "Il cervello AI e' pubblico/cloud; la voce CosyVoice gira invece sul tuo PC."
Write-Host "Configura almeno una chiave gratuita tra NVIDIA, Z.AI, Groq o OpenRouter nel file .env."
Write-Host "JARVIS non seleziona automaticamente modelli AI a pagamento."
& $python -m jarvis.desktop
