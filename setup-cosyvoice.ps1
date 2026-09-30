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

Write-Host "  - Installo ANTLR 4.9.3 precompilato da conda-forge (workaround Windows)..."
& $condaExe install -n jarvis-cosyvoice -y --override-channels -c conda-forge "antlr4-python3-runtime=4.9.3"
Assert-LastExit "Installazione ANTLR 4.9.3 da conda-forge"

& $condaExe run --no-capture-output -n jarvis-cosyvoice python -c "import antlr4; print('ANTLR runtime OK')"
Assert-LastExit "Verifica ANTLR runtime"

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

# CosyVoice pins torch 2.3.1+cu121, which predates NVIDIA Blackwell.
# RTX 50-series GPUs (sm_120) require a PyTorch CUDA 12.8+ build. Upgrade only
# torch/torchaudio themselves so pip does not replace CosyVoice-compatible
# transitive dependencies such as fsspec and MarkupSafe.
$gpuName = ""
$nvidiaSmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($nvidiaSmi) {
    try {
        $gpuName = ((& $nvidiaSmi.Source --query-gpu=name --format=csv,noheader | Select-Object -First 1) -as [string]).Trim()
    } catch {
        $gpuName = ""
    }
}

if ($gpuName -match 'RTX\s*50') {
    Write-Host "  - Rilevata $gpuName: aggiorno PyTorch/Torchaudio per Blackwell (CUDA 12.8)..." -ForegroundColor Cyan
    & $condaExe run --no-capture-output -n jarvis-cosyvoice python -m pip install --upgrade --force-reinstall --no-deps "torch==2.7.1" "torchaudio==2.7.1" --index-url https://download.pytorch.org/whl/cu128
    Assert-LastExit "Installazione PyTorch 2.7.1 CUDA 12.8 per RTX 50"

    Write-Host "  - Ripristino dipendenze compatibili con Gradio/Lightning..."
    & $condaExe run --no-capture-output -n jarvis-cosyvoice python -m pip install "MarkupSafe==2.1.5" "fsspec[http]==2024.12.0"
    Assert-LastExit "Ripristino dipendenze CosyVoice dopo upgrade Torch"

    & $condaExe run --no-capture-output -n jarvis-cosyvoice python -c "import torch; print('Torch', torch.__version__, 'CUDA', torch.version.cuda, 'GPU', torch.cuda.get_device_name(0), 'capability', torch.cuda.get_device_capability(0)); assert torch.cuda.is_available(); assert torch.cuda.get_device_capability(0)[0] >= 12"
    Assert-LastExit "Verifica supporto Blackwell PyTorch"
} elseif ($gpuName) {
    Write-Host "  - GPU rilevata: $gpuName. Mantengo la build Torch richiesta da CosyVoice."
}

Write-Host "  - Verifico coerenza dipendenze Python..."
& $condaExe run --no-capture-output -n jarvis-cosyvoice python -m pip check
Assert-LastExit "Verifica dipendenze CosyVoice"

Write-Host "  - Abilito download Hugging Face ottimizzati (hf_xet)..."
& $condaExe run --no-capture-output -n jarvis-cosyvoice python -m pip install "huggingface_hub[hf_xet]>=0.27,<2"
Assert-LastExit "Installazione huggingface_hub + hf_xet"

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
