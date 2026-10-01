from __future__ import annotations

import platform
import subprocess
import threading
from typing import Any

import psutil


def get_cpu_usage() -> dict[str, object]:
    return {"percent": psutil.cpu_percent(interval=0.2)}


def get_ram_usage() -> dict[str, object]:
    vm = psutil.virtual_memory()
    gib = 1024 ** 3
    return {
        "percent": vm.percent,
        "used_gb": round(vm.used / gib, 2),
        "available_gb": round(vm.available / gib, 2),
        "total_gb": round(vm.total / gib, 2),
    }


def get_system_information() -> dict[str, object]:
    disk = psutil.disk_usage("/")
    gib = 1024 ** 3
    return {
        "os": platform.system(),
        "os_release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": platform.python_version(),
        "disk_total_gb": round(disk.total / gib, 2),
        "disk_free_gb": round(disk.free / gib, 2),
    }


def _windows_only() -> str | None:
    if platform.system() != "Windows":
        return "Questo controllo di sistema è disponibile solo su Windows."
    return None


_VOLUME_CSHARP = r'''
using System;
using System.Runtime.InteropServices;
[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IAudioEndpointVolume {
  void A(); void B(); void C(); void D();
  int SetMasterVolumeLevelScalar(float level, Guid context);
  void F();
  int GetMasterVolumeLevelScalar(out float level);
}
[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IMMDevice { int Activate(ref Guid id, int clsCtx, IntPtr p, [MarshalAs(UnmanagedType.IUnknown)] out object o); }
[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IMMDeviceEnumerator { void A(); int GetDefaultAudioEndpoint(int flow, int role, out IMMDevice device); }
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
public class MMDeviceEnumerator {}
'''


def _volume_script(body: str) -> str:
    return (
        f"Add-Type -TypeDefinition @'\n{_VOLUME_CSHARP}\n'@ -Language CSharp -ErrorAction SilentlyContinue;"
        "$e=[MMDeviceEnumerator] -as [IMMDeviceEnumerator];"
        "$d=$null; $null=$e.GetDefaultAudioEndpoint(0,1,[ref]$d);"
        "$g=[Guid]'5CDF2C82-841E-4546-9722-0CF74078229A';"
        "$v=$null; $null=$d.Activate([ref]$g,1,[IntPtr]::Zero,[ref]$v);"
        + body
    )


def get_volume() -> dict[str, object]:
    error = _windows_only()
    if error:
        return {"success": False, "error": error}
    script = _volume_script("$f=0.0; $null=$v.GetMasterVolumeLevelScalar([ref]$f); [int]($f*100)")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", script], capture_output=True, text=True, timeout=10)
    raw = result.stdout.strip()
    return {"success": raw.isdigit(), "volume": int(raw) if raw.isdigit() else None, "error": result.stderr.strip() or None}


def set_volume(level: int) -> dict[str, object]:
    error = _windows_only()
    if error:
        return {"success": False, "error": error}
    level = max(0, min(100, int(level)))
    scalar = level / 100.0
    script = _volume_script(f"$null=$v.SetMasterVolumeLevelScalar({scalar},[Guid]::Empty)")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", script], capture_output=True, text=True, timeout=10)
    return {"success": result.returncode == 0, "volume": level, "error": result.stderr.strip() or None}


def get_clipboard() -> dict[str, object]:
    error = _windows_only()
    if error:
        return {"success": False, "error": error}
    result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", "Get-Clipboard -Raw"], capture_output=True, text=True, timeout=5)
    return {"success": result.returncode == 0, "text": result.stdout.rstrip("\r\n")}


def set_clipboard(text: str) -> dict[str, object]:
    error = _windows_only()
    if error:
        return {"success": False, "error": error}
    process = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", "$input | Set-Clipboard"],
        input=text,
        capture_output=True,
        text=True,
        timeout=5,
    )
    return {"success": process.returncode == 0, "characters": len(text)}


def show_notification(title: str, message: str) -> dict[str, object]:
    error = _windows_only()
    if error:
        return {"success": False, "error": error}
    safe_title = title.replace("'", "''")[:120]
    safe_message = message.replace("'", "''")[:500]
    script = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$n=New-Object System.Windows.Forms.NotifyIcon;"
        "$n.Icon=[System.Drawing.SystemIcons]::Information;"
        "$n.Visible=$true;"
        f"$n.ShowBalloonTip(5000,'{safe_title}','{safe_message}',[System.Windows.Forms.ToolTipIcon]::Info);"
        "Start-Sleep -Milliseconds 600; $n.Dispose()"
    )
    result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", script], capture_output=True, text=True, timeout=8)
    return {"success": result.returncode == 0, "title": title}


_timers: list[threading.Timer] = []
_timers_lock = threading.RLock()


def set_timer(seconds: int, message: str = "Timer completato") -> dict[str, object]:
    seconds = max(1, min(int(seconds), 7 * 24 * 3600))
    timer_ref: dict[str, threading.Timer] = {}

    def callback() -> None:
        try:
            show_notification("JARVIS", message)
        finally:
            timer = timer_ref.get("timer")
            if timer is not None:
                with _timers_lock:
                    try:
                        _timers.remove(timer)
                    except ValueError:
                        pass

    timer = threading.Timer(seconds, callback)
    timer.daemon = True
    timer_ref["timer"] = timer
    with _timers_lock:
        _timers[:] = [item for item in _timers if item.is_alive()]
        _timers.append(timer)
    try:
        timer.start()
    except Exception:
        with _timers_lock:
            try:
                _timers.remove(timer)
            except ValueError:
                pass
        raise
    return {"success": True, "seconds": seconds, "message": message}


def lock_screen() -> dict[str, object]:
    error = _windows_only()
    if error:
        return {"success": False, "error": error}
    subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
    return {"success": True}


def power_command(action: str) -> dict[str, Any]:
    error = _windows_only()
    if error:
        return {"success": False, "error": error}
    action = action.lower().strip()
    if action == "shutdown":
        subprocess.Popen(["shutdown.exe", "/s", "/t", "10"])
    elif action == "restart":
        subprocess.Popen(["shutdown.exe", "/r", "/t", "10"])
    elif action == "sleep":
        subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0", "1", "0"])
    else:
        return {"success": False, "error": "Usa shutdown, restart oppure sleep."}
    return {"success": True, "action": action}
