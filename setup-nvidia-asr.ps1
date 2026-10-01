$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (Get-Command nemo-speech -ErrorAction SilentlyContinue) {
    Write-Host "NeMo-Speech.cpp e' gia' installato." -ForegroundColor Green
    nemo-speech --version
    exit 0
}

$installer = Join-Path $env:TEMP "install-nemo-speech.ps1"
$officialInstaller = "https://github.com/NVIDIA/NeMo-Speech.cpp/raw/main/scripts/install.ps1"

Write-Host "Installo NVIDIA NeMo-Speech.cpp per Windows + CUDA..."
Invoke-WebRequest -Uri $officialInstaller -OutFile $installer
powershell -ExecutionPolicy Bypass -File $installer -Backend cuda -Profile server

Write-Host ""
Write-Host "Installazione completata. Chiudi e riapri PowerShell, poi esegui:" -ForegroundColor Green
Write-Host "  nemo-speech --version"
Write-Host "  .\start-nvidia-asr.ps1"
