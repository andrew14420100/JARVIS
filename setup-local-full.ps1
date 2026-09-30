param(
    [switch]$SkipCosyVoiceSetup
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Require-Command([string]$Name, [string]$Help) {
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $cmd) {
        throw "$Name non trovato. $Help"
    }
    return $cmd
}

function Assert-LastExit([string]$Step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Step non riuscito (exit code $LASTEXITCODE)."
    }
}

function Find-CondaExe {
    $command = Get-Command conda -ErrorAction SilentlyContinue
    if ($command -and $command.Source) {
        return $command.Source
    }

    $candidates = @(
        (Join-Path $env:USERPROFILE "miniconda3\Scripts\conda.exe"),
        (Join-Path $env:LOCALAPPDATA "miniconda3\Scripts\conda.exe"),
        (Join-Path $env:USERPROFILE "anaconda3\Scripts\conda.exe"),
        (Join-Path $env:LOCALAPPDATA "anaconda3\Scripts\conda.exe"),
        (Join-Path $env:ProgramData "miniconda3\Scripts\conda.exe"),
        (Join-Path $env:ProgramData "anaconda3\Scripts\conda.exe")
    ) | Where-Object { $_ -and (Test-Path $_) }

    if ($candidates.Count -gt 0) {
        return $candidates[0]
    }
    return $null
}

function Set-EnvValue([string]$Key, [string]$Value) {
    $envPath = Join-Path $PSScriptRoot ".env"
    if (-not (Test-Path $envPath)) {
        if (Test-Path (Join-Path $PSScriptRoot ".env.example")) {
            Copy-Item (Join-Path $PSScriptRoot ".env.example") $envPath
        } else {
            New-Item -ItemType File -Path $envPath -Force | Out-Null
        }
    }

    $lines = @(Get-Content $envPath)
    $prefix = "$Key="
    $found = $false
    $updated = foreach ($line in $lines) {
        if ($line.StartsWith($prefix)) {
            $found = $true
            "$Key=$Value"
        } else {
            $line
        }
    }
    if (-not $found) {
        $updated += "$Key=$Value"
    }
    Set-Content -Path $envPath -Value $updated -Encoding UTF8
}

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host " JARVIS - SETUP COMPLETO LOCALE" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

Write-Host "[1/8] Controllo strumenti di base..."
Require-Command git "Installa Git per Windows." | Out-Null
Require-Command py "Installa Python 3.11, 3.12 o 3.13." | Out-Null
Require-Command npm "Installa Node.js LTS." | Out-Null

$pythonVersion = (& py -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
$pythonOk = (& py -c "import sys; print(int((3,10) <= sys.version_info[:2] < (3,14)))").Trim()
if ($pythonOk -ne "1") {
    throw "Python $pythonVersion non compatibile. Usa Python 3.10-3.13; consigliato 3.11 o 3.12 per la massima compatibilita'."
}
Write-Host "Python $pythonVersion OK."

Write-Host "[2/8] Configuro JARVIS per cervello 100% locale via LM Studio..."
Set-EnvValue "JARVIS_BRAIN_MODE" "local"
Set-EnvValue "JARVIS_MODEL" ""
Set-EnvValue "JARVIS_LM_STUDIO_BASE_URL" "http://127.0.0.1:1234/v1"
Set-EnvValue "JARVIS_VOICE_ENABLED" "true"
Set-EnvValue "JARVIS_PRESENCE_ENABLED" "true"
Set-EnvValue "JARVIS_TTS_MODE" "cosyvoice-local"
Set-EnvValue "JARVIS_COSYVOICE_ENABLED" "true"
Set-EnvValue "JARVIS_COSYVOICE_SERVICE_URL" "http://127.0.0.1:8765"
Set-EnvValue "JARVIS_COSYVOICE_REPO_DIR" ".local/cosyvoice/CosyVoice"
Set-EnvValue "JARVIS_COSYVOICE_MODEL_DIR" ".local/cosyvoice/models/Fun-CosyVoice3-0.5B"
Set-EnvValue "JARVIS_COSYVOICE_REFERENCE_AUDIO" "private/voices/jarvis.wav"
Set-EnvValue "JARVIS_COSYVOICE_REFERENCE_TEXT" "private/voices/jarvis.txt"
Set-EnvValue "JARVIS_OPENJARVIS_ENABLED" "false"

Write-Host "[3/8] Verifico LM Studio..."
try {
    $models = Invoke-RestMethod -Uri "http://127.0.0.1:1234/v1/models" -TimeoutSec 3
} catch {
    Write-Host "" -ForegroundColor Yellow
    Write-Warning "LM Studio non risponde su http://127.0.0.1:1234/v1"
    Write-Host "Apri LM Studio, carica Qwen3.8-27B e abilita il Local Server sulla porta 1234." -ForegroundColor Yellow
    Write-Host "Poi rilancia questo script." -ForegroundColor Yellow
    exit 20
}

$loadedModels = @($models.data | ForEach-Object { $_.id } | Where-Object { $_ })
if ($loadedModels.Count -eq 0) {
    Write-Warning "LM Studio risponde, ma non espone alcun modello. Carica Qwen3.8-27B e rilancia."
    exit 21
}
Write-Host "Modelli LM Studio disponibili:" -ForegroundColor Green
$loadedModels | ForEach-Object { Write-Host "  - $_" }

Write-Host "[4/8] Preparo cartella privata voce..."
$voiceDir = Join-Path $PSScriptRoot "private\voices"
New-Item -ItemType Directory -Force -Path $voiceDir | Out-Null
$voiceAudio = Join-Path $voiceDir "jarvis.wav"
$voiceText = Join-Path $voiceDir "jarvis.txt"
if (-not (Test-Path $voiceAudio)) {
    Write-Warning "Manca private\voices\jarvis.wav. Copia qui il WAV della voce che abbiamo preparato."
}
if (-not (Test-Path $voiceText)) {
    Write-Warning "Manca private\voices\jarvis.txt. Deve contenere la trascrizione esatta del WAV."
}

Write-Host "[5/8] Preparo ambiente Python JARVIS..."
if (-not (Test-Path ".venv")) {
    & py -m venv .venv
    Assert-LastExit "Creazione .venv"
}
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $python -m pip install --upgrade pip
Assert-LastExit "Aggiornamento pip"
& $python -m pip install -r requirements-local.txt
Assert-LastExit "Installazione requirements-local.txt"

Write-Host "[6/8] Preparo wake word..."
& $python -c "from openwakeword import utils; utils.download_models()"
Assert-LastExit "Download modelli openWakeWord"

Write-Host "[7/8] Compilo frontend..."
Push-Location (Join-Path $PSScriptRoot "frontend")
try {
    if (-not (Test-Path "node_modules")) {
        npm install
        Assert-LastExit "npm install"
    }
    npm run build
    Assert-LastExit "npm run build"
} finally {
    Pop-Location
}

Write-Host "[8/8] Controllo CosyVoice..."
$cosyRepo = Join-Path $PSScriptRoot ".local\cosyvoice\CosyVoice"
$cosyModel = Join-Path $PSScriptRoot ".local\cosyvoice\models\Fun-CosyVoice3-0.5B"
$cosyInstalled = (Test-Path $cosyRepo) -and (Test-Path $cosyModel)

if (-not $cosyInstalled -and -not $SkipCosyVoiceSetup) {
    $condaExe = Find-CondaExe
    if (-not $condaExe) {
        Write-Warning "Conda non trovato automaticamente. Installa Miniconda oppure esegui .\setup-cosyvoice.ps1 dopo aver verificato il percorso di conda.exe."
    } else {
        Write-Host "Conda rilevato: $condaExe" -ForegroundColor Green
        Write-Host "CosyVoice non ancora installato: avvio setup dedicato..."
        powershell -ExecutionPolicy Bypass -File ".\setup-cosyvoice.ps1"
        Assert-LastExit "Setup CosyVoice"
    }
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host " CONFIGURAZIONE LOCALE COMPLETATA" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host "Cervello: LM Studio locale"
Write-Host "STT: faster-whisper locale"
Write-Host "Wake word: openWakeWord locale"
Write-Host "Memoria/tool: locali"
Write-Host "TTS: CosyVoice locale quando modello + campione voce sono pronti"
Write-Host ""
Write-Host "Avvio finale:" -ForegroundColor Cyan
Write-Host "  powershell -ExecutionPolicy Bypass -File .\run-local.ps1"
