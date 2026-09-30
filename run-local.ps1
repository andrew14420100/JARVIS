$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    py -m venv .venv
}

$python = ".\.venv\Scripts\python.exe"

& $python -m pip install --upgrade pip
& $python -m pip install -r requirements-local.txt

if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Creato .env da .env.example."
}

Write-Host "Avvio JARVIS locale..."
Write-Host "Assicurati che LM Studio sia aperto con il server su http://127.0.0.1:1234/v1"
& $python -m jarvis.desktop
