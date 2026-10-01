$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    py -m venv .venv
}

$python = ".\.venv\Scripts\python.exe"

$versionOk = & $python -c "import sys; print(int(sys.version_info < (3,14)))"
if ($versionOk.Trim() -ne "1") {
    throw "JARVIS richiede Python >=3.10 e <3.14. Crea .venv con Python 3.11, 3.12 o 3.13."
}

Write-Host "[1/7] Aggiorno Python e dipendenze locali..."
& $python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Aggiornamento pip fallito (exit code $LASTEXITCODE)." }
& $python -m pip install -r requirements-local.txt
if ($LASTEXITCODE -ne 0) { throw "Installazione dipendenze Python fallita (exit code $LASTEXITCODE)." }

# faster-whisper/CTranslate2 on Windows expects CUDA 12 cuBLAS and cuDNN DLLs
# on PATH. The CosyVoice environment already contains a Blackwell-compatible
# PyTorch CUDA 12.8 runtime, so reuse those local DLLs instead of installing a
# second CUDA stack just for STT.
$cudaRuntimeDirs = @(
    (Join-Path $env:USERPROFILE "miniconda3\envs\jarvis-cosyvoice\Lib\site-packages\torch\lib"),
    (Join-Path $env:USERPROFILE "miniconda3\envs\jarvis-cosyvoice\Library\bin"),
    (Join-Path $env:LOCALAPPDATA "miniconda3\envs\jarvis-cosyvoice\Lib\site-packages\torch\lib"),
    (Join-Path $env:LOCALAPPDATA "miniconda3\envs\jarvis-cosyvoice\Library\bin"),
    (Join-Path $env:USERPROFILE "anaconda3\envs\jarvis-cosyvoice\Lib\site-packages\torch\lib"),
    (Join-Path $env:USERPROFILE "anaconda3\envs\jarvis-cosyvoice\Library\bin"),
    (Join-Path $env:LOCALAPPDATA "anaconda3\envs\jarvis-cosyvoice\Lib\site-packages\torch\lib"),
    (Join-Path $env:LOCALAPPDATA "anaconda3\envs\jarvis-cosyvoice\Library\bin")
)

$addedCudaDirs = @()
foreach ($dir in $cudaRuntimeDirs) {
    if ($dir -and (Test-Path -LiteralPath $dir)) {
        $env:PATH = "$dir;$env:PATH"
        $addedCudaDirs += $dir
    }
}

if ($addedCudaDirs.Count -gt 0) {
    $cublas = $null
    $cudnn = $null
    foreach ($dir in $addedCudaDirs) {
        if (-not $cublas) {
            $cublas = Get-ChildItem -LiteralPath $dir -Filter "cublas64_12.dll" -File -ErrorAction SilentlyContinue | Select-Object -First 1
        }
        if (-not $cudnn) {
            $cudnn = Get-ChildItem -LiteralPath $dir -Filter "cudnn64_9.dll" -File -ErrorAction SilentlyContinue | Select-Object -First 1
        }
    }
    if ($cublas) {
        Write-Host "CUDA STT: cuBLAS 12 disponibile ($($cublas.DirectoryName))." -ForegroundColor Green
    } else {
        Write-Warning "CUDA STT: cublas64_12.dll non trovato; faster-whisper usera' il fallback CPU se necessario."
    }
    if ($cudnn) {
        Write-Host "CUDA STT: cuDNN 9 disponibile ($($cudnn.DirectoryName))." -ForegroundColor Green
    } else {
        Write-Warning "CUDA STT: cudnn64_9.dll non trovato; faster-whisper potrebbe usare il fallback CPU."
    }
}

Write-Host "[2/7] Controllo Hybrid Brain opzionale..."
$openJarvisEnabled = $false
if (Test-Path ".env") {
    $openJarvisLine = Get-Content ".env" | Where-Object { $_ -match '^JARVIS_OPENJARVIS_ENABLED=' } | Select-Object -Last 1
    if ($openJarvisLine) {
        $openJarvisEnabled = (($openJarvisLine -split '=', 2)[1].Trim().ToLower()) -eq "true"
    }
}
if ($openJarvisEnabled) {
    Write-Host "OpenJarvis abilitato: installo/aggiorno il modulo cognitivo..."
    & $python -m pip install -r requirements-cognitive.txt
    if ($LASTEXITCODE -ne 0) { throw "Installazione Hybrid Brain fallita (exit code $LASTEXITCODE)." }
} else {
    Write-Host "OpenJarvis disabilitato: salto installazione cognitiva pesante."
}

Write-Host "[3/7] Controllo modelli wake-word..."
& $python -c "from openwakeword import utils; utils.download_models()"
if ($LASTEXITCODE -ne 0) { throw "Preparazione modelli wake-word fallita (exit code $LASTEXITCODE)." }

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
    $reactScriptsCmd = Join-Path (Get-Location) "node_modules\.bin\react-scripts.cmd"
    $reactScriptsJs = Join-Path (Get-Location) "node_modules\react-scripts\bin\react-scripts.js"
    if (-not (Test-Path $reactScriptsCmd) -or -not (Test-Path $reactScriptsJs)) {
        Write-Host "Dipendenze frontend incomplete o react-scripts mancante: riparo node_modules..." -ForegroundColor Yellow
        npm install --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) {
            throw "npm install frontend fallito (exit code $LASTEXITCODE)."
        }
    }

    if (-not (Test-Path $reactScriptsCmd) -or -not (Test-Path $reactScriptsJs)) {
        throw "react-scripts non e' disponibile dopo npm install. Elimina frontend\node_modules e riprova."
    }

    npm run build
    if ($LASTEXITCODE -ne 0) {
        throw "Build frontend fallita (exit code $LASTEXITCODE)."
    }
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
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Avvio script CosyVoice fallito; provo comunque il controllo health."
        }

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
            Write-Warning "CosyVoice non e' diventato pronto entro 120 secondi. JARVIS continuera' senza TTS locale."
        }
    } else {
        Write-Host "CosyVoice e' gia' attivo."
    }
} else {
    Write-Host "Campione vocale o runtime CosyVoice non ancora configurato: JARVIS partira' senza TTS locale."
    Write-Host "Servono private\voices\jarvis.wav e private\voices\jarvis.txt, oltre al modello CosyVoice."
}

Write-Host "[7/7] Avvio JARVIS realtime..."
$brainMode = "cloud"
if (Test-Path ".env") {
    $brainLine = Get-Content ".env" | Where-Object { $_ -match '^JARVIS_BRAIN_MODE=' } | Select-Object -Last 1
    if ($brainLine) {
        $brainMode = (($brainLine -split '=', 2)[1].Trim().ToLower())
    }
}
if ($brainMode -eq "local") {
    Write-Host "Cervello AI: LM Studio locale su http://127.0.0.1:1234/v1 · streaming ON"
    Write-Host "Voce/STT/wake word/memoria/tool: locali."
} else {
    Write-Host "Cervello AI: router cloud gratuito con fallback LM Studio streaming."
    Write-Host "JARVIS non seleziona automaticamente modelli AI a pagamento."
}
& $python -m jarvis.desktop_stable
