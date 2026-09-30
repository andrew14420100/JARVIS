$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Find-CondaExe {
    $command = Get-Command conda -ErrorAction SilentlyContinue
    if ($command -and $command.Source) {
        return [string]$command.Source
    }

    $candidatePaths = @(
        (Join-Path $env:USERPROFILE "miniconda3\Scripts\conda.exe"),
        (Join-Path $env:LOCALAPPDATA "miniconda3\Scripts\conda.exe"),
        (Join-Path $env:USERPROFILE "anaconda3\Scripts\conda.exe"),
        (Join-Path $env:LOCALAPPDATA "anaconda3\Scripts\conda.exe"),
        (Join-Path $env:ProgramData "miniconda3\Scripts\conda.exe"),
        (Join-Path $env:ProgramData "anaconda3\Scripts\conda.exe")
    )

    foreach ($candidate in $candidatePaths) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return [string]$candidate
        }
    }

    throw "Conda non trovato. Installa Miniconda/Anaconda oppure verifica il percorso di installazione."
}

function Assert-LastExit([string]$Step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Step non riuscito (exit code $LASTEXITCODE)."
    }
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
    Assert-LastExit "Creazione ambiente jarvis-cosyvoice"
}

Write-Host "[2/5] Preparo repository ufficiale FunAudioLLM/CosyVoice..."
if (-not (Test-Path (Join-Path $cosyRepo ".git"))) {
    git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git $cosyRepo
    Assert-LastExit "Clone CosyVoice"
} else {
    Push-Location $cosyRepo
    try {
        git submodule update --init --recursive
        Assert-LastExit "Aggiornamento submodule CosyVoice"
    } finally {
        Pop-Location
    }
}

Write-Host "[3/5] Installo dipendenze CosyVoice nell'ambiente separato..."
& $condaExe run --no-capture-output -n jarvis-cosyvoice python -m pip install --upgrade pip
Assert-LastExit "Aggiornamento pip CosyVoice"

# openai-whisper==20231117 (ancora richiesto dal repository ufficiale CosyVoice)
# usa pkg_resources durante il build. Con i tool di build moderni e build
# isolation su Windows può fallire con ModuleNotFoundError: pkg_resources.
# Manteniamo quindi un setuptools che fornisce pkg_resources e installiamo
# Whisper separatamente senza build isolation.
Write-Host "  - Preparo tool di build compatibili con Whisper 20231117..."
& $condaExe run --no-capture-output -n jarvis-cosyvoice python -m pip install "setuptools<81" wheel setuptools-rust
Assert-LastExit "Installazione tool build Whisper"

& $condaExe run --no-capture-output -n jarvis-cosyvoice python -c "import pkg_resources; print('pkg_resources OK')"
Assert-LastExit "Verifica pkg_resources"

$requirementsPath = Join-Path $cosyRepo "requirements.txt"
$tempRequirements = Join-Path $env:TEMP "jarvis-cosyvoice-requirements-no-whisper.txt"
Get-Content $requirementsPath |
    Where-Object { $_ -notmatch '^\s*openai-whisper\s*==' } |
    Set-Content -Path $tempRequirements -Encoding UTF8

try {
    Write-Host "  - Installo requisiti CosyVoice (Whisper escluso temporaneamente)..."
    & $condaExe run --no-capture-output -n jarvis-cosyvoice python -m pip install -r $tempRequirements
    Assert-LastExit "Installazione requisiti CosyVoice"

    Write-Host "  - Installo openai-whisper 20231117 senza build isolation..."
    & $condaExe run --no-capture-output -n jarvis-cosyvoice python -m pip install --no-build-isolation "openai-whisper==20231117"
    Assert-LastExit "Installazione openai-whisper"
} finally {
    Remove-Item -LiteralPath $tempRequirements -Force -ErrorAction SilentlyContinue
}

& $condaExe run --no-capture-output -n jarvis-cosyvoice python -m pip install "huggingface_hub>=0.27,<2"
Assert-LastExit "Installazione huggingface_hub"

Write-Host "[4/5] Scarico Fun-CosyVoice3-0.5B-2512..."
& $condaExe run --no-capture-output -n jarvis-cosyvoice python (Join-Path $PSScriptRoot "local_voice\download_model.py") --output $modelDir
Assert-LastExit "Download modello CosyVoice"

Write-Host "[5/5] Preparo cartella privata della voce..."
Write-Host ""
Write-Host "CosyVoice e' installato. Il modello rimane sul PC e non viene caricato su GitHub."
Write-Host "Campione vocale atteso:" -ForegroundColor Cyan
Write-Host "  private\voices\jarvis.wav"
Write-Host "  private\voices\jarvis.txt   (trascrizione esatta del WAV)"
Write-Host ""
Write-Host "Avvio voce:"
Write-Host "  powershell -ExecutionPolicy Bypass -File .\start-cosyvoice.ps1"
