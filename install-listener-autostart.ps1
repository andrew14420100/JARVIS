param(
    [string]$RemoteBaseUrl = ""
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if ($RemoteBaseUrl.Trim()) {
    $envPath = Join-Path $PSScriptRoot ".env"
    if (-not (Test-Path $envPath) -and (Test-Path ".env.example")) {
        Copy-Item ".env.example" $envPath
    }
    $lines = if (Test-Path $envPath) { Get-Content $envPath } else { @() }
    $replacement = "JARVIS_LISTENER_REMOTE_BASE_URL=$($RemoteBaseUrl.Trim().TrimEnd('/'))"
    $found = $false
    $updated = foreach ($line in $lines) {
        if ($line -match '^JARVIS_LISTENER_REMOTE_BASE_URL=') {
            $found = $true
            $replacement
        } else {
            $line
        }
    }
    if (-not $found) { $updated += $replacement }
    Set-Content -Path $envPath -Value $updated -Encoding UTF8
}

$launcher = Join-Path $PSScriptRoot "run-listener.ps1"
if (-not (Test-Path $launcher)) {
    throw "run-listener.ps1 non trovato. Aggiorna prima il repository."
}

$taskName = "JARVIS Voice Listener"
$argument = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$launcher`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)

$taskParams = @{
    TaskName = $taskName
    Action = $action
    Trigger = $trigger
    Settings = $settings
    Description = "JARVIS always-on wake word and conversational microphone listener"
    Force = $true
}
Register-ScheduledTask @taskParams | Out-Null

Write-Host "[JARVIS] Avvio automatico installato: $taskName"
Write-Host "[JARVIS] Il listener partirà automaticamente all'accesso a Windows."
Write-Host "[JARVIS] Per avviarlo subito: powershell -ExecutionPolicy Bypass -File .\run-listener.ps1"
