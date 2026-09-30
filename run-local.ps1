$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    py -m venv .venv
}

$python = ".\.venv\Scripts\python.exe"

$versionOk = & $python -c "import sys; print(int(sys.version_info < (3,14)))"
if ($versionOk.Trim() -ne "1") {
    throw "OpenJarvis richiede Python >=3.10 e <3.14. Crea .venv con Python 3.11, 3.12 o 3.13."
}

Write-Host "[1/6] Aggiorno Python e dipendenze locali..."
& $python -m pip install --upgrade pip
& $python -m pip install -r requirements-local.txt

Write-Host "[2/6] Installo Hybrid Brain OpenJarvis..."
& $python -m pip install -r requirements-cognitive.txt

Write-Host "[3/6] Controllo modelli wake-word..."
& $python -c "from openwakeword import utils; utils.download_models()"

Write-Host "[4/6] Preparo configurazione..."
if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Creato .env da .env.example."
}

Write-Host "[5/6] Compilo la UI React/WebGL..."
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

Write-Host "[6/6] Avvio JARVIS ibrido locale..."
Write-Host "LM Studio deve essere aperto con il server su http://127.0.0.1:1234/v1"
Write-Host "OpenJarvis verra usato per le richieste complesse; il core locale mantiene tool e conferme."
& $python -m jarvis.desktop
