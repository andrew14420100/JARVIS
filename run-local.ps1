param(
    [switch]$SkipVoice
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "JARVIS · Video Architecture" -ForegroundColor Cyan
Write-Host "Brain Grid + Foam memory + Radar + cloned voice" -ForegroundColor DarkCyan

function Require-Command([string]$Name, [string]$Hint) {
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $cmd) { throw "$Name non trovato. $Hint" }
    return $cmd.Source
}

Write-Host "[1/7] Controllo Node, npm e VS Code..."
$node = Require-Command "node" "Installa Node.js 20 o superiore."
$npm = Require-Command "npm" "Node.js deve includere npm."
$code = Require-Command "code" "Apri VS Code, esegui 'Shell Command: Install code command in PATH' oppure riavvia il terminale dopo l'installazione."
& $node --version
& $npm --version

$extensionDir = Join-Path $PSScriptRoot "extension"
$extensionPackage = Join-Path $extensionDir "package.json"
if (-not (Test-Path -LiteralPath $extensionPackage)) { throw "Estensione JARVIS mancante: $extensionPackage" }

Write-Host "[2/7] Compilo l'estensione JARVIS del video..."
$depsStamp = Join-Path $extensionDir ".deps.sha256"
$packageHash = (Get-FileHash -LiteralPath $extensionPackage -Algorithm SHA256).Hash
$installedHash = if (Test-Path $depsStamp) { (Get-Content $depsStamp -Raw).Trim() } else { "" }
if (-not (Test-Path (Join-Path $extensionDir "node_modules")) -or $installedHash -ne $packageHash) {
    Push-Location $extensionDir
    try {
        & $npm install --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw "Installazione dipendenze estensione fallita." }
        Set-Content -LiteralPath $depsStamp -Value $packageHash -Encoding ASCII
    } finally { Pop-Location }
}
Push-Location $extensionDir
try {
    & $npm run check
    if ($LASTEXITCODE -ne 0) { throw "Build estensione JARVIS fallita." }
    & $npm run package
    if ($LASTEXITCODE -ne 0) { throw "Packaging estensione JARVIS fallito." }
} finally { Pop-Location }

Write-Host "[3/7] Installo Brain Grid e Foam in VS Code..."
$vsix = Join-Path $extensionDir "jarvis-brain.vsix"
if (-not (Test-Path -LiteralPath $vsix)) { throw "Pacchetto VSIX non creato: $vsix" }
& $code --install-extension $vsix --force
if ($LASTEXITCODE -ne 0) { throw "Installazione estensione JARVIS fallita." }
try {
    & $code --install-extension "foam.foam-vscode" --force | Out-Host
} catch {
    Write-Warning "Foam non e' stato installato automaticamente. Puoi installare foam.foam-vscode da VS Code."
}

Write-Host "[4/7] Apro il cervello JARVIS..." -ForegroundColor Green
& $code $PSScriptRoot
Start-Sleep -Milliseconds 1200
try { & $code --open-url "vscode://andrew14420100.jarvis-brain/open" | Out-Null } catch {}

$claude = Get-Command claude -ErrorAction SilentlyContinue
if ($claude) {
    Write-Host "Claude Code rilevato: $($claude.Source)" -ForegroundColor Green
} else {
    Write-Warning "Claude Code non e' nel PATH. Il Brain Grid funziona comunque; il collegamento diretto al cervello Claude verra' attivato quando il comando 'claude' sara' disponibile."
}

if ($SkipVoice) {
    Write-Host "[5/7] Voce saltata per richiesta (-SkipVoice)." -ForegroundColor Yellow
    Write-Host "JARVIS Brain online." -ForegroundColor Green
    exit 0
}

Write-Host "[5/7] Preparo il runtime voce esistente..."
git submodule update --init --recursive
if ($LASTEXITCODE -ne 0) { throw "Inizializzazione del runtime voce fallita." }
$upstream = Join-Path $PSScriptRoot "personal-jarvis"
if (-not (Test-Path (Join-Path $upstream "pyproject.toml"))) { throw "Runtime voce PersonalJarvis non disponibile nel submodule." }

$venv = Join-Path $PSScriptRoot ".venv-personaljarvis"
$python = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $python)) {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        & py -3.12 -m venv $venv
        if ($LASTEXITCODE -ne 0) { & py -3.11 -m venv $venv }
    } else {
        & python -m venv $venv
    }
    if (-not (Test-Path $python)) { throw "Impossibile creare l'ambiente Python per la voce." }
}

$stamp = Join-Path $venv ".personaljarvis-v2.5.0-full"
if (-not (Test-Path $stamp)) {
    Push-Location $upstream
    try {
        & $python -m pip install --upgrade pip
        if ($LASTEXITCODE -ne 0) { throw "Aggiornamento pip fallito." }
        & $python -m pip install -e ".[full]"
        if ($LASTEXITCODE -ne 0) { throw "Installazione runtime voce fallita." }
        Set-Content -LiteralPath $stamp -Value "v2.5.0" -Encoding ASCII
    } finally { Pop-Location }
}

Write-Host "[6/7] Carico la tua voce JARVIS clonata..."
$voiceDir = Join-Path $PSScriptRoot "voice"
$voiceAudio = Join-Path $voiceDir "jarvis.mp3"
$voiceTxt = Join-Path $voiceDir "jarvis.txt"
$voicePatch = Join-Path $voiceDir "apply_voice.py"
foreach ($required in @($voiceAudio, $voiceTxt, $voicePatch)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "File voce mancante: $required" }
}
$env:JARVIS_CUSTOM_VOICE_WAV = (Resolve-Path -LiteralPath $voiceAudio).Path
$env:JARVIS_CUSTOM_VOICE_TEXT = (Get-Content -LiteralPath $voiceTxt -Raw -Encoding UTF8).Trim()
& $python $voicePatch --repo $upstream --audio $voiceAudio --text $voiceTxt --sync-config
if ($LASTEXITCODE -ne 0) { throw "Configurazione della voce JARVIS fallita." }
Write-Host "Voce clonata JARVIS pronta." -ForegroundColor Green

Write-Host "[7/7] Avvio la conversazione vocale mentre il Brain Grid resta aperto..." -ForegroundColor Green
$profileRunner = Join-Path $PSScriptRoot "custom\run_ironman_jarvis.py"
if (-not (Test-Path -LiteralPath $profileRunner)) { throw "Profilo JARVIS mancante: $profileRunner" }
Push-Location $upstream
try {
    & $python $profileRunner
} finally { Pop-Location }
