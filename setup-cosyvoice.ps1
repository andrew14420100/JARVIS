$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$condaCommand = Get-Command conda -ErrorAction SilentlyContinue
if (-not $condaCommand) {
    throw "Conda non trovato. Installa Miniconda o Anaconda, riapri PowerShell e rilancia questo script."
}

$condaBase = (& conda info --base).Trim()
$condaExe = Join-Path $condaBase "Scripts\conda.exe"
if (-not (Test-Path $condaExe)) {
    $condaExe = $condaCommand.Source
}

$voiceRoot = Join-Path $PSScriptRoot ".local\cosyvoice"
$cosyRepo = Join-Path $voiceRoot "CosyVoice"
$modelDir = Join-Path $voiceRoot "models\Fun-CosyVoice3-0.5B"
$privateVoice = Join-Path $PSScriptRoot "private\voices"

New-Item -ItemType Directory -Force -Path $voiceRoot | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $modelDir -Parent) | Out-Null
New-Item -ItemType Directory -Force -Path $privateVoice | Out-Null

Write-Host "[1/5] Preparo ambiente Python 3.10 dedicato a CosyVoice..."
$envInfo = (& $condaExe env list --json | ConvertFrom-Json)
$hasEnv = $false
foreach ($path in $envInfo.envs) {
    if ((Split-Path $path -Leaf) -eq "jarvis-cosyvoice") {
        $hasEnv = $true
        break
    }
}
if (-not $hasEnv) {
    & $condaExe create -n jarvis-cosyvoice -y python=3.10
}

Write-Host "[2/5] Preparo repository ufficiale QwenAudio/CosyVoice..."
if (-not (Test-Path (Join-Path $cosyRepo ".git"))) {
    git clone --recursive https://github.com/QwenAudio/CosyVoice.git $cosyRepo
} else {
    Push-Location $cosyRepo
    try {
        git submodule update --init --recursive
    } finally {
        Pop-Location
    }
}

Write-Host "[3/5] Installo dipendenze CosyVoice nell'ambiente separato..."
& $condaExe run --no-capture-output -n jarvis-cosyvoice python -m pip install --upgrade pip
& $condaExe run --no-capture-output -n jarvis-cosyvoice python -m pip install -r (Join-Path $cosyRepo "requirements.txt")
& $condaExe run --no-capture-output -n jarvis-cosyvoice python -m pip install "huggingface_hub>=0.27,<2"

Write-Host "[4/5] Scarico Fun-CosyVoice3-0.5B-2512..."
& $condaExe run --no-capture-output -n jarvis-cosyvoice python (Join-Path $PSScriptRoot "local_voice\download_model.py") --output $modelDir

Write-Host "[5/5] Preparo cartella privata della voce..."
Write-Host ""
Write-Host "CosyVoice e' installato. Il modello rimane sul PC e non viene caricato su GitHub."
Write-Host "Quando avrai il campione vocale, inseriremo:" -ForegroundColor Cyan
Write-Host "  private\voices\jarvis.wav"
Write-Host "  private\voices\jarvis.txt   (trascrizione esatta del WAV)"
Write-Host ""
Write-Host "Dopo aver aggiunto quei due file potrai avviare la voce con:"
Write-Host "  powershell -ExecutionPolicy Bypass -File .\start-cosyvoice.ps1"
