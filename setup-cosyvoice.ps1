$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

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

    throw "Conda non trovato. Installa Miniconda/Anaconda oppure verifica il percorso di installazione."
}

$condaExe = Find-CondaExe
Write-Host "Conda rilevato: $condaExe" -ForegroundColor Green

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
    if ($LASTEXITCODE -ne 0) { throw "Creazione ambiente jarvis-cosyvoice non riuscita." }
}

Write-Host "[2/5] Preparo repository ufficiale QwenAudio/CosyVoice..."
if (-not (Test-Path (Join-Path $cosyRepo ".git"))) {
    git clone --recursive https://github.com/QwenAudio/CosyVoice.git $cosyRepo
    if ($LASTEXITCODE -ne 0) { throw "Clone CosyVoice non riuscito." }
} else {
    Push-Location $cosyRepo
    try {
        git submodule update --init --recursive
        if ($LASTEXITCODE -ne 0) { throw "Aggiornamento submodule CosyVoice non riuscito." }
    } finally {
        Pop-Location
    }
}

Write-Host "[3/5] Installo dipendenze CosyVoice nell'ambiente separato..."
& $condaExe run --no-capture-output -n jarvis-cosyvoice python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Aggiornamento pip CosyVoice non riuscito." }
& $condaExe run --no-capture-output -n jarvis-cosyvoice python -m pip install -r (Join-Path $cosyRepo "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Installazione requisiti CosyVoice non riuscita." }
& $condaExe run --no-capture-output -n jarvis-cosyvoice python -m pip install "huggingface_hub>=0.27,<2"
if ($LASTEXITCODE -ne 0) { throw "Installazione huggingface_hub non riuscita." }

Write-Host "[4/5] Scarico Fun-CosyVoice3-0.5B-2512..."
& $condaExe run --no-capture-output -n jarvis-cosyvoice python (Join-Path $PSScriptRoot "local_voice\download_model.py") --output $modelDir
if ($LASTEXITCODE -ne 0) { throw "Download modello CosyVoice non riuscito." }

Write-Host "[5/5] Preparo cartella privata della voce..."
Write-Host ""
Write-Host "CosyVoice e' installato. Il modello rimane sul PC e non viene caricato su GitHub."
Write-Host "Campione vocale atteso:" -ForegroundColor Cyan
Write-Host "  private\voices\jarvis.wav"
Write-Host "  private\voices\jarvis.txt   (trascrizione esatta del WAV)"
Write-Host ""
Write-Host "Avvio voce:"
Write-Host "  powershell -ExecutionPolicy Bypass -File .\start-cosyvoice.ps1"
