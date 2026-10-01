$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Set-EnvValue([string]$Name, [string]$Value) {
    $lines = @()
    if (Test-Path ".env") {
        $lines = @(Get-Content ".env")
    }

    $pattern = "^$([regex]::Escape($Name))="
    $found = $false
    $updated = foreach ($line in $lines) {
        if ($line -match $pattern) {
            $found = $true
            "$Name=$Value"
        } else {
            $line
        }
    }
    if (-not $found) {
        $updated += "$Name=$Value"
    }
    Set-Content ".env" $updated -Encoding UTF8
}

if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Host "Creato .env da .env.example."
    } else {
        New-Item -ItemType File -Path ".env" | Out-Null
    }
}

$existingKey = ""
$keyLine = Get-Content ".env" | Where-Object { $_ -match '^JARVIS_NVIDIA_API_KEY=' } | Select-Object -Last 1
if ($keyLine) {
    $existingKey = (($keyLine -split '=', 2)[1]).Trim()
}

if (-not $existingKey) {
    Write-Host "Inserisci la NVIDIA API key. Non verra' mostrata a schermo ne' salvata in GitHub." -ForegroundColor Cyan
    $secure = Read-Host "NVIDIA API key" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $existingKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
    if (-not $existingKey.Trim()) {
        throw "NVIDIA API key vuota. Configurazione annullata."
    }
}

Set-EnvValue "JARVIS_BRAIN_MODE" "cloud"
Set-EnvValue "JARVIS_NVIDIA_API_KEY" $existingKey.Trim()
Set-EnvValue "JARVIS_NVIDIA_MODEL" "nvidia/nemotron-3-ultra-550b-a55b"
Set-EnvValue "JARVIS_LM_STUDIO_FALLBACK_ENABLED" "true"
Set-EnvValue "JARVIS_LM_STUDIO_BASE_URL" "http://127.0.0.1:1234/v1"
Set-EnvValue "JARVIS_CONVERSATION_LOCAL_FIRST" "true"
Set-EnvValue "JARVIS_TTS_MODE" "cosyvoice-local"
Set-EnvValue "JARVIS_COSYVOICE_ENABLED" "true"
Set-EnvValue "JARVIS_CLOUD_TTS_ENABLED" "false"
Set-EnvValue "JARVIS_CLOUD_TTS_FALLBACK_ENABLED" "false"

Write-Host ""
Write-Host "Qwen in LM Studio: percorso realtime per la conversazione." -ForegroundColor Green
Write-Host "NVIDIA Nemotron 3 Ultra: disponibile per richieste pesanti e operative." -ForegroundColor Green
Write-Host "Voce: CosyVoice 3 con il tuo campione private\voices\jarvis.wav." -ForegroundColor Green
Write-Host "Le voci alternative cloud restano disabilitate: il timbro di JARVIS non cambia." -ForegroundColor Green
Write-Host ""
Write-Host "Lascia LM Studio aperto con Qwen caricato per ottenere la latenza minima." -ForegroundColor Yellow
Write-Host "Poi avvia: powershell -ExecutionPolicy Bypass -File .\run-local.ps1"
