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

Write-Host "[1/6] Controllo runtime Python..."
$requirementsPath = Join-Path $PSScriptRoot "requirements-local.txt"
$requirementsStamp = Join-Path $PSScriptRoot ".venv\.jarvis-requirements.sha256"
$requirementsHash = (Get-FileHash -LiteralPath $requirementsPath -Algorithm SHA256).Hash
$installedHash = if (Test-Path $requirementsStamp) { (Get-Content $requirementsStamp -Raw).Trim() } else { "" }
if ($installedHash -ne $requirementsHash) {
    Write-Host "Dipendenze cambiate: aggiorno l'ambiente locale..." -ForegroundColor Yellow
    & $python -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "Aggiornamento pip fallito (exit code $LASTEXITCODE)." }
    & $python -m pip install -r requirements-local.txt
    if ($LASTEXITCODE -ne 0) { throw "Installazione dipendenze Python fallita (exit code $LASTEXITCODE)." }
    Set-Content -LiteralPath $requirementsStamp -Value $requirementsHash -Encoding ASCII
} else {
    Write-Host "Dipendenze Python gia' pronte: nessuna reinstallazione." -ForegroundColor Green
}

$openJarvisEnabled = $false
if (Test-Path ".env") {
    $openJarvisLine = Get-Content ".env" | Where-Object { $_ -match '^JARVIS_OPENJARVIS_ENABLED=' } | Select-Object -Last 1
    if ($openJarvisLine) {
        $openJarvisEnabled = (($openJarvisLine -split '=', 2)[1].Trim().ToLower()) -eq "true"
    }
}
if ($openJarvisEnabled) {
    $cognitivePath = Join-Path $PSScriptRoot "requirements-cognitive.txt"
    $cognitiveStamp = Join-Path $PSScriptRoot ".venv\.jarvis-cognitive.sha256"
    $cognitiveHash = (Get-FileHash -LiteralPath $cognitivePath -Algorithm SHA256).Hash
    $oldCognitiveHash = if (Test-Path $cognitiveStamp) { (Get-Content $cognitiveStamp -Raw).Trim() } else { "" }
    if ($oldCognitiveHash -ne $cognitiveHash) {
        & $python -m pip install -r requirements-cognitive.txt
        if ($LASTEXITCODE -ne 0) { throw "Installazione Hybrid Brain fallita (exit code $LASTEXITCODE)." }
        Set-Content -LiteralPath $cognitiveStamp -Value $cognitiveHash -Encoding ASCII
    }
}

Write-Host "[2/6] Preparo configurazione..."
if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Creato .env da .env.example."
}

Write-Host "[3/6] Controllo UI voice-only..."
$npm = Get-Command npm -ErrorAction SilentlyContinue
if (-not $npm) {
    throw "Node.js/npm non trovato. Installa Node.js LTS."
}
Push-Location "frontend"
try {
    $reactScriptsCmd = Join-Path (Get-Location) "node_modules\.bin\react-scripts.cmd"
    $reactScriptsJs = Join-Path (Get-Location) "node_modules\react-scripts\bin\react-scripts.js"
    if (-not (Test-Path $reactScriptsCmd) -or -not (Test-Path $reactScriptsJs)) {
        Write-Host "Dipendenze frontend incomplete: eseguo npm install..." -ForegroundColor Yellow
        npm install --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw "npm install frontend fallito (exit code $LASTEXITCODE)." }
    }

    $buildIndex = Join-Path (Get-Location) "build\index.html"
    $needsBuild = -not (Test-Path $buildIndex)
    if (-not $needsBuild) {
        $buildTime = (Get-Item $buildIndex).LastWriteTimeUtc
        $watch = @()
        if (Test-Path "src") { $watch += Get-ChildItem "src" -Recurse -File }
        if (Test-Path "public") { $watch += Get-ChildItem "public" -Recurse -File }
        foreach ($name in @("package.json", "package-lock.json")) {
            if (Test-Path $name) { $watch += Get-Item $name }
        }
        $needsBuild = @($watch | Where-Object { $_.LastWriteTimeUtc -gt $buildTime }).Count -gt 0
    }

    if ($needsBuild) {
        Write-Host "Sorgenti UI cambiate: creo la build di produzione..."
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "Build frontend fallita (exit code $LASTEXITCODE)." }
    } else {
        Write-Host "UI gia' compilata e aggiornata: salto la build." -ForegroundColor Green
    }
} finally {
    Pop-Location
}

Write-Host "[4/6] Controllo voce locale CosyVoice..."
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
            if (Test-CosyVoiceReady) { $ready = $true; break }
        }
        if ($ready) {
            Write-Host "CosyVoice pronto. Voce clonata calda in memoria." -ForegroundColor Green
        } else {
            Write-Warning "CosyVoice non e' diventato pronto entro 120 secondi."
        }
    } else {
        Write-Host "CosyVoice gia' caldo: nessun riavvio." -ForegroundColor Green
    }
} else {
    Write-Warning "Campione vocale o runtime CosyVoice non configurato completamente."
}

Write-Host "[5/6] Controllo cervello AI locale..."
function Test-LMStudioServer {
    try {
        $null = Invoke-RestMethod -Uri "http://127.0.0.1:1234/api/v1/models" -TimeoutSec 2
        return $true
    } catch {
        try {
            $null = Invoke-RestMethod -Uri "http://127.0.0.1:1234/v1/models" -TimeoutSec 2
            return $true
        } catch { return $false }
    }
}

function Get-LMStudioResidentModels {
    try {
        $catalog = Invoke-RestMethod -Uri "http://127.0.0.1:1234/api/v1/models" -TimeoutSec 2
        $resident = @()
        foreach ($model in @($catalog.models)) {
            if ([string]$model.type -ne "llm") { continue }
            foreach ($instance in @($model.loaded_instances)) {
                $id = [string]$instance.id
                if (-not $id) { $id = [string]$model.key }
                if ($id) { $resident += $id }
            }
        }
        return @($resident | Select-Object -Unique)
    } catch {
        # Compatibility path for older LM Studio versions without native v1.
        try {
            $legacy = Invoke-RestMethod -Uri "http://127.0.0.1:1234/v1/models" -TimeoutSec 2
            return @($legacy.data | ForEach-Object { [string]$_.id } | Where-Object { $_ })
        } catch {
            return @()
        }
    }
}

function Test-LMStudioBrain {
    return (@(Get-LMStudioResidentModels).Count -gt 0)
}

$lms = Get-Command lms -ErrorAction SilentlyContinue
if (-not $lms) {
    $bundledLms = Join-Path $env:USERPROFILE ".lmstudio\bin\lms.exe"
    if (Test-Path -LiteralPath $bundledLms) { $lms = Get-Item -LiteralPath $bundledLms }
}

if (-not (Test-LMStudioBrain) -and $lms) {
    $lmsPath = if ($lms.Source) { $lms.Source } else { $lms.FullName }
    if (-not (Test-LMStudioServer)) {
        Write-Host "Avvio server LM Studio locale..."
        try { & $lmsPath server start --port 1234 | Out-Host } catch {}
        for ($i = 0; $i -lt 20; $i++) {
            if (Test-LMStudioServer) { break }
            Start-Sleep -Milliseconds 500
        }
    }

    if (-not (Test-LMStudioBrain)) {
        try {
            $modelsRaw = (& $lmsPath ls --llm --json 2>$null | Out-String).Trim()
            $downloaded = if ($modelsRaw) { @($modelsRaw | ConvertFrom-Json) } else { @() }
        } catch { $downloaded = @() }

        $selected = $null
        # Keep the realtime resident brain small whenever such a model is already
        # installed. Heavy models may still be used outside the hot voice path.
        $priorities = @("flash", "4b", "7b", "8b", "mini", "small", "qwen3.8", "qwen", "glm", "deepseek", "exaone")
        foreach ($needle in $priorities) {
            $selected = $downloaded | Where-Object {
                $key = [string]($_.modelKey)
                $name = [string]($_.displayName)
                ($key.ToLower().Contains($needle) -or $name.ToLower().Contains($needle))
            } | Select-Object -First 1
            if ($selected) { break }
        }
        if (-not $selected) { $selected = $downloaded | Select-Object -First 1 }

        if ($selected) {
            $modelKey = [string]$selected.modelKey
            if (-not $modelKey) { $modelKey = [string]$selected.path }
            if ($modelKey) {
                Write-Host "Carico modello conversazionale locale residente: $modelKey"
                try { & $lmsPath load $modelKey --gpu auto --context-length 4096 | Out-Host } catch {
                    Write-Warning "Caricamento modello LM Studio fallito: $($_.Exception.Message)"
                }
            }
        }
        for ($i = 0; $i -lt 60; $i++) {
            if (Test-LMStudioBrain) { break }
            Start-Sleep -Seconds 1
        }
    }
}

$residentModels = @(Get-LMStudioResidentModels)
if ($residentModels.Count -gt 0) {
    Write-Host "Cervello locale LM Studio: READY (residente)" -ForegroundColor Green
    Write-Host ("Modelli residenti: " + ($residentModels -join ", "))
} else {
    Write-Warning "Nessun modello LM Studio realmente residente: usero' i fallback cloud gratuiti."
}

Write-Host "[6/6] Avvio JARVIS Realtime Core v2..."
Write-Host "Percorso critico: browser mic -> AI streaming -> CosyVoice bistream -> WebAudio."
Write-Host "Memoria, tool, visione e automazioni restano servizi laterali."
& $python -m jarvis.desktop_stable
