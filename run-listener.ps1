param(
    [string]$RemoteBaseUrl = ""
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$venv = ".listener-venv"
if (-not (Test-Path $venv)) {
    py -3.11 -m venv $venv 2>$null
    if (-not (Test-Path "$venv\Scripts\python.exe")) {
        py -m venv $venv
    }
}

$python = ".\$venv\Scripts\python.exe"

Write-Host "[JARVIS] Preparo il listener vocale Windows..."
& $python -m pip install --upgrade pip
& $python -m pip install -r requirements-listener.txt

Write-Host "[JARVIS] Controllo il modello wake-word..."
& $python -c "from openwakeword import utils; utils.download_models()"

if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
    Write-Host "[JARVIS] Creato .env da .env.example"
}

if ($RemoteBaseUrl.Trim()) {
    $env:JARVIS_LISTENER_REMOTE_BASE_URL = $RemoteBaseUrl.Trim().TrimEnd('/')
}

if (-not $env:JARVIS_LISTENER_REMOTE_BASE_URL) {
    $envLine = $null
    if (Test-Path ".env") {
        $envLine = Get-Content ".env" | Where-Object { $_ -match '^JARVIS_LISTENER_REMOTE_BASE_URL=' } | Select-Object -First 1
    }
    if ($envLine) {
        $value = ($envLine -replace '^JARVIS_LISTENER_REMOTE_BASE_URL=', '').Trim()
        if ($value) { $env:JARVIS_LISTENER_REMOTE_BASE_URL = $value }
    }
}

if (-not $env:JARVIS_LISTENER_REMOTE_BASE_URL) {
    throw "Manca l'URL di Emergent. Avvia con: .\run-listener.ps1 -RemoteBaseUrl https://TUO-PROGETTO.preview.emergentagent.com"
}

Write-Host "[JARVIS] Emergent: $env:JARVIS_LISTENER_REMOTE_BASE_URL"
Write-Host "[JARVIS] Il browser non userà il microfono: il listener Windows gestisce wake word e conversazione."
Write-Host "[JARVIS] Dica 'Jarvis' per iniziare. Ctrl+C per fermare il listener."

& $python -m jarvis.remote_listener
