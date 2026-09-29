from __future__ import annotations

import os
import platform
import shutil
import subprocess


WINDOWS_ALIASES: dict[str, list[str]] = {
    "blocco note": ["notepad.exe"],
    "notepad": ["notepad.exe"],
    "calcolatrice": ["calc.exe"],
    "calculator": ["calc.exe"],
    "esplora file": ["explorer.exe"],
    "file explorer": ["explorer.exe"],
    "powershell": ["powershell.exe"],
    "cmd": ["cmd.exe"],
    "visual studio code": ["code"],
    "vscode": ["code"],
    "chrome": ["chrome.exe"],
    "spotify": ["spotify.exe"],
}


def _resolve_windows_command(application: str) -> list[str] | None:
    key = application.strip().lower()
    if key in WINDOWS_ALIASES:
        return WINDOWS_ALIASES[key]

    candidate = shutil.which(application)
    if candidate:
        return [candidate]
    if not application.lower().endswith(".exe"):
        candidate = shutil.which(f"{application}.exe")
        if candidate:
            return [candidate]
    return None


def open_application(application: str) -> dict[str, object]:
    if platform.system() != "Windows":
        return {
            "success": False,
            "application": application,
            "error": "open_application è disponibile solo su Windows in questa versione.",
        }

    command = _resolve_windows_command(application)
    if command:
        try:
            subprocess.Popen(command, shell=False)
            return {"success": True, "application": application, "method": "executable"}
        except OSError as exc:
            return {"success": False, "application": application, "error": str(exc)}

    if hasattr(os, "startfile"):
        try:
            os.startfile(application)  # type: ignore[attr-defined]
            return {"success": True, "application": application, "method": "startfile"}
        except OSError:
            pass

    return {
        "success": False,
        "application": application,
        "error": "Applicazione non trovata. Usa il nome di un'app installata o disponibile nel PATH.",
    }
