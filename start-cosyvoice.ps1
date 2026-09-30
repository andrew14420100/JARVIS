param(
    [switch]$Background
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$condaCommand = Get-Command conda -ErrorAction SilentlyContinue
if (-not $condaCommand) {
    throw "Conda non trovato. Esegui prima setup-cosyvoice.ps1."
}

$condaBase = (& conda info --base).Trim()
$condaExe = Join-Path $condaBase "Scripts\conda.exe"
if (-not (Test-Path $condaExe)) {
    $condaExe = $condaCommand.Source
}

$cosyRepo = Join-Path $PSScriptRoot ".local\cosyvoice\CosyVoice"
$modelDir = Join-Path $PSScriptRoot ".local\cosyvoice\models\Fun-CosyVoice3-0.5B"
$referenceAudio = Join-Path $PSScriptRoot "private\voices\jarvis.wav"
$referenceText = Join-Path $PSScriptRoot "private\voices\jarvis.txt"
$server = Join-Path $PSScriptRoot "local_voice\cosyvoice_server.py"

foreach ($item in @(
    @{ Path = $cosyRepo; Label = "repository CosyVoice" },
    @{ Path = $modelDir; Label = "modello CosyVoice" },
    @{ Path = $referenceAudio; Label = "campione vocale private\voices\jarvis.wav" },
    @{ Path = $referenceText; Label = "trascrizione private\voices\jarvis.txt" }
)) {
    if (-not (Test-Path $item.Path)) {
        throw "Manca $($item.Label)."
    }
}

$argsList = @(
    "run", "--no-capture-output", "-n", "jarvis-cosyvoice",
    "python", $server,
    "--cosyvoice-repo", $cosyRepo,
    "--model-dir", $modelDir,
    "--reference-audio", $referenceAudio,
    "--reference-text", $referenceText,
    "--port", "8765"
)

if ($Background) {
    $process = Start-Process -FilePath $condaExe -ArgumentList $argsList -WindowStyle Hidden -PassThru
    Write-Host "CosyVoice avviato in background (PID $($process.Id))."
    exit 0
}

Write-Host "Avvio CosyVoice 3 locale. Il primo caricamento del modello richiede qualche istante..."
& $condaExe @argsList
