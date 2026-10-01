$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$command = Get-Command nemo-speech -ErrorAction SilentlyContinue
if (-not $command) {
    throw "nemo-speech non trovato. Esegui prima .\setup-nvidia-asr.ps1, poi riapri PowerShell."
}

function Test-NvidiaAsrReady {
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:8080/ready" -TimeoutSec 2 | Out-Null
        return $true
    } catch {
        return $false
    }
}

if (Test-NvidiaAsrReady) {
    Write-Host "NVIDIA Nemotron 3.5 ASR e' gia' attivo su http://127.0.0.1:8080." -ForegroundColor Green
    exit 0
}

Write-Host "Preparo il modello NVIDIA Nemotron 3.5 ASR..."
& $command.Source pull nemotron-3.5

Write-Host "Avvio NeMo-Speech.cpp ASR realtime..."
$argsList = @(
    "serve",
    "--asr-model", "nemotron-3.5",
    "--host", "127.0.0.1",
    "--port", "8080",
    "--no-ui",
    "--asr.endpointing.enable=false",
    "--asr.streaming.rnnt_right_context", "0"
)

$process = Start-Process -FilePath $command.Source -ArgumentList $argsList -WindowStyle Hidden -PassThru
Write-Host "NeMo-Speech.cpp avviato (PID $($process.Id))."

for ($i = 0; $i -lt 90; $i++) {
    Start-Sleep -Seconds 1
    if (Test-NvidiaAsrReady) {
        Write-Host "NVIDIA Nemotron 3.5 ASR pronto." -ForegroundColor Green
        exit 0
    }
}

throw "NVIDIA Nemotron 3.5 non e' diventato pronto entro 90 secondi."
