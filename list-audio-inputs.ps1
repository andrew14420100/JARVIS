$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Ambiente .venv non trovato. Esegui prima run-local.ps1 almeno una volta."
}

& $python -c @'
import sounddevice as sd

default_in = sd.default.device[0]
print("\nIngressi audio disponibili:\n")
for i, dev in enumerate(sd.query_devices()):
    if int(dev.get("max_input_channels", 0)) <= 0:
        continue
    mark = "* DEFAULT" if i == default_in else ""
    print(f"[{i}] {dev['name']} | input={dev['max_input_channels']} | {dev['default_samplerate']:.0f} Hz {mark}")
print("\nPer fissare un microfono nel file .env:")
print("JARVIS_AUDIO_INPUT_DEVICE=nome esatto o univoco del dispositivo")
'@
