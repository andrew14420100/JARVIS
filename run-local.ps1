$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    py -m venv .venv
}

$python = ".\.venv\Scripts\python.exe"

Write-Host "[1/5] Aggiorno Python e dipendenze locali..."
& $python -m pip install --upgrade pip
& $python -m pip install -r requirements-local.txt

Write-Host "[2/5] Controllo modelli wake-word..."
& $python -c "from openwakeword import utils; utils.download_models()"

Write-Host "[3/5] Preparo configurazione..."
if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Creato .env da .env.example."
}

Write-Host "[4/5] Compilo la UI React/WebGL..."
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

Write-Host "[5/5] Avvio JARVIS locale..."
Write-Host "Assicurati che LM Studio sia aperto con il server su http://127.0.0.1:1234/v1"
& $python -m jarvis.desktop
