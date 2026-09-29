from __future__ import annotations

import platform
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
    return {
        "os": platform.system(),
        "os_release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": platform.python_version(),
    }
