from __future__ import annotations

import os
import platform
import subprocess
import tempfile
import time
from pathlib import Path


def _windows_only() -> str | None:
    if platform.system() != "Windows":
        return "Questo strumento desktop è disponibile solo su Windows."
    return None


def _pyautogui():
    import pyautogui

    # Keep the library's emergency corner failsafe enabled.
    pyautogui.FAILSAFE = True
    return pyautogui


def get_open_windows() -> dict[str, object]:
    error = _windows_only()
    if error:
        return {"success": False, "error": error}
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "Get-Process | Where-Object {$_.MainWindowTitle} | Select-Object -ExpandProperty MainWindowTitle",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    windows = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return {"success": result.returncode == 0, "windows": windows[:100]}


def focus_window(title: str) -> dict[str, object]:
    error = _windows_only()
    if error:
        return {"success": False, "error": error}
    safe = title.replace("'", "''")
    script = (
        f"$p=Get-Process | Where-Object {{$_.MainWindowTitle -like '*{safe}*'}} | Select-Object -First 1;"
        "if(-not $p){Write-Output 'NOT_FOUND'; exit 2};"
        "Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public class W {"
        "[DllImport(\"user32.dll\")] public static extern bool SetForegroundWindow(IntPtr h);"
        "[DllImport(\"user32.dll\")] public static extern bool ShowWindow(IntPtr h,int n); }';"
        "[W]::ShowWindow($p.MainWindowHandle,9) | Out-Null;"
        "[W]::SetForegroundWindow($p.MainWindowHandle) | Out-Null;"
        "Write-Output $p.MainWindowTitle"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if "NOT_FOUND" in result.stdout:
        return {"success": False, "error": f"Nessuna finestra trovata per: {title}"}
    return {"success": result.returncode == 0, "window": result.stdout.strip()}


def _windows_ocr(image_path: Path) -> list[dict[str, object]]:
    escaped = str(image_path).replace("'", "''")
    script = rf"""
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder,Windows.Foundation,ContentType=WindowsRuntime]
function Await($operation, $resultType) {{
  $methods=[System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {{ $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 }}
  $method=$methods | Select-Object -First 1
  $task=$method.MakeGenericMethod($resultType).Invoke($null,@($operation))
  $task.Wait(); $task.Result
}}
$stream=[System.IO.File]::OpenRead('{escaped}')
$ras=[System.IO.WindowsRuntimeStreamExtensions]::AsRandomAccessStream($stream)
$decoder=Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($ras)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap=Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$engine=[Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
$result=Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
$out=@()
foreach($line in $result.Lines) {{
  if($line.Words.Count -gt 0) {{
    $x1=($line.Words | % {{$_.BoundingRect.X}} | Measure-Object -Minimum).Minimum
    $y1=($line.Words | % {{$_.BoundingRect.Y}} | Measure-Object -Minimum).Minimum
    $x2=($line.Words | % {{$_.BoundingRect.X+$_.BoundingRect.Width}} | Measure-Object -Maximum).Maximum
    $y2=($line.Words | % {{$_.BoundingRect.Y+$_.BoundingRect.Height}} | Measure-Object -Maximum).Maximum
    $out += [PSCustomObject]@{{text=$line.Text; x=[int](($x1+$x2)/2); y=[int](($y1+$y2)/2)}}
  }}
}}
$stream.Dispose()
$out | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []
    import json

    parsed = json.loads(result.stdout)
    if isinstance(parsed, dict):
        parsed = [parsed]
    return [item for item in parsed if isinstance(item, dict)]


def read_screen_text() -> dict[str, object]:
    error = _windows_only()
    if error:
        return {"success": False, "error": error}
    try:
        pyautogui = _pyautogui()
        temp_path = Path(tempfile.gettempdir()) / "jarvis_screen_ocr.png"
        pyautogui.screenshot().save(temp_path)
        items = _windows_ocr(temp_path)
        return {"success": True, "items": items[:300], "count": len(items)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def find_text_on_screen(text: str) -> dict[str, object]:
    result = read_screen_text()
    if not result.get("success"):
        return result
    target = text.casefold().strip()
    items = result.get("items", [])
    best: dict[str, object] | None = None
    best_score = 0
    wanted = set(target.split())
    for item in items if isinstance(items, list) else []:
        content = str(item.get("text", ""))
        folded = content.casefold()
        if target and target in folded:
            return {"success": True, "match": content, "x": item.get("x"), "y": item.get("y"), "exact": True}
        score = len(wanted & set(folded.split()))
        if score > best_score:
            best_score = score
            best = item
    if best and best_score:
        return {"success": True, "match": best.get("text"), "x": best.get("x"), "y": best.get("y"), "exact": False}
    return {"success": False, "error": f"Testo non trovato sullo schermo: {text}"}


def move_mouse(x: int, y: int) -> dict[str, object]:
    error = _windows_only()
    if error:
        return {"success": False, "error": error}
    _pyautogui().moveTo(x, y, duration=0.15)
    return {"success": True, "x": x, "y": y}


def click_at(x: int, y: int, button: str = "left") -> dict[str, object]:
    error = _windows_only()
    if error:
        return {"success": False, "error": error}
    pyautogui = _pyautogui()
    if button == "double":
        pyautogui.doubleClick(x, y, interval=0.12)
    elif button == "right":
        pyautogui.rightClick(x, y)
    else:
        pyautogui.click(x, y)
    return {"success": True, "x": x, "y": y, "button": button}


def type_text(text: str) -> dict[str, object]:
    error = _windows_only()
    if error:
        return {"success": False, "error": error}
    time.sleep(0.10)
    _pyautogui().write(text, interval=0.015)
    return {"success": True, "characters": len(text)}


def press_key(keys: str) -> dict[str, object]:
    error = _windows_only()
    if error:
        return {"success": False, "error": error}
    parts = [part.strip().lower() for part in keys.split("+") if part.strip()]
    if not parts:
        return {"success": False, "error": "Nessun tasto specificato."}
    _pyautogui().hotkey(*parts)
    return {"success": True, "keys": parts}


def scroll_screen(direction: str, amount: int = 3) -> dict[str, object]:
    error = _windows_only()
    if error:
        return {"success": False, "error": error}
    amount = max(1, min(abs(amount), 20))
    delta = amount if direction.lower() == "up" else -amount
    _pyautogui().scroll(delta)
    return {"success": True, "direction": direction, "amount": amount}


def take_screenshot(filename: str = "") -> dict[str, object]:
    error = _windows_only()
    if error:
        return {"success": False, "error": error}
    desktop = Path.home() / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)
    safe_name = os.path.basename(filename.strip()) if filename.strip() else f"jarvis_{int(time.time())}.png"
    if not safe_name.lower().endswith(".png"):
        safe_name += ".png"
    path = desktop / safe_name
    _pyautogui().screenshot().save(path)
    return {"success": True, "path": str(path)}
