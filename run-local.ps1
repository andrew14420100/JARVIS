$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "JARVIS · PersonalJarvis v2.5.0" -ForegroundColor Cyan

Write-Host "[1/5] Controllo upstream..."
git submodule update --init --recursive
if ($LASTEXITCODE -ne 0) { throw "Inizializzazione PersonalJarvis fallita." }

$upstream = Join-Path $PSScriptRoot "personal-jarvis"
if (-not (Test-Path (Join-Path $upstream "pyproject.toml"))) {
    throw "PersonalJarvis non disponibile nel submodule."
}

Write-Host "[2/5] Controllo ambiente Python pulito..."
$venv = Join-Path $PSScriptRoot ".venv-personaljarvis"
$python = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $python)) {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        & py -3.12 -m venv $venv
        if ($LASTEXITCODE -ne 0) { & py -3.11 -m venv $venv }
    } else {
        & python -m venv $venv
    }
    if (-not (Test-Path $python)) { throw "Impossibile creare l'ambiente Python." }
}

Write-Host "[3/5] Controllo installazione PersonalJarvis..."
$stamp = Join-Path $venv ".personaljarvis-v2.5.0-full"
if (-not (Test-Path $stamp)) {
    Push-Location $upstream
    try {
        & $python -m pip install --upgrade pip
        if ($LASTEXITCODE -ne 0) { throw "Aggiornamento pip fallito." }
        & $python -m pip install -e ".[full]"
        if ($LASTEXITCODE -ne 0) { throw "Installazione PersonalJarvis full fallita." }
        Set-Content -LiteralPath $stamp -Value "v2.5.0" -Encoding ASCII
    } finally {
        Pop-Location
    }
} else {
    Write-Host "PersonalJarvis gia' installato nell'ambiente pulito." -ForegroundColor Green
}

Write-Host "[4/5] Carico la voce JARVIS personalizzata..."
$voiceDir = Join-Path $PSScriptRoot "voice"
$voiceAudio = Join-Path $voiceDir "jarvis.mp3"
$voiceTxt = Join-Path $voiceDir "jarvis.txt"
$voicePatch = Join-Path $voiceDir "apply_voice.py"

foreach ($required in @($voiceAudio, $voiceTxt, $voicePatch)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "File voce mancante: $required"
    }
}

$env:JARVIS_CUSTOM_VOICE_WAV = (Resolve-Path -LiteralPath $voiceAudio).Path
$env:JARVIS_CUSTOM_VOICE_TEXT = (Get-Content -LiteralPath $voiceTxt -Raw -Encoding UTF8).Trim()

& $python $voicePatch --repo $upstream --audio $voiceAudio --text $voiceTxt --sync-config
if ($LASTEXITCODE -ne 0) { throw "Configurazione della voce JARVIS fallita." }
Write-Host "Voce clonata JARVIS pronta." -ForegroundColor Green

Write-Host "[5/5] Avvio JARVIS con il profilo del video..." -ForegroundColor Green
$profileRunner = Join-Path $PSScriptRoot "custom\run_ironman_jarvis.py"
if (-not (Test-Path -LiteralPath $profileRunner)) {
    throw "Profilo JARVIS mancante: $profileRunner"
}

Push-Location $upstream
try {
    & $python $profileRunner
} finally {
    Pop-Location
}
