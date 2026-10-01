from __future__ import annotations

import queue
import subprocess
import threading
import time
from dataclasses import dataclass


@dataclass(slots=True)
class ProactiveAlert:
    key: str
    message: str
    created_at: float


class ProactiveMonitor:
    """Watch only important system conditions and queue concise voice alerts."""

    def __init__(
        self,
        *,
        poll_seconds: float = 15.0,
        cooldown_seconds: float = 300.0,
        cpu_percent: float = 97.0,
        memory_percent: float = 96.0,
        disk_percent: float = 96.0,
        gpu_temp_c: float = 88.0,
    ) -> None:
        self.poll_seconds = max(5.0, float(poll_seconds))
        self.cooldown_seconds = max(30.0, float(cooldown_seconds))
        self.cpu_percent = float(cpu_percent)
        self.memory_percent = float(memory_percent)
        self.disk_percent = float(disk_percent)
        self.gpu_temp_c = float(gpu_temp_c)
        self._alerts: queue.Queue[ProactiveAlert] = queue.Queue(maxsize=16)
        self._last_sent: dict[str, float] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _emit(self, key: str, message: str) -> None:
        now = time.monotonic()
        previous = self._last_sent.get(key)
        if previous is not None and now - previous < self.cooldown_seconds:
            return
        self._last_sent[key] = now
        try:
            self._alerts.put_nowait(ProactiveAlert(key, message, time.time()))
        except queue.Full:
            pass

    @staticmethod
    def _gpu_temperature() -> float | None:
        try:
            completed = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=temperature.gpu",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=2.0,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if completed.returncode != 0:
                return None
            first = completed.stdout.strip().splitlines()[0]
            return float(first)
        except Exception:
            return None

    def _check_once(self) -> None:
        try:
            import psutil

            cpu = float(psutil.cpu_percent(interval=None))
            memory = float(psutil.virtual_memory().percent)
            disk = float(psutil.disk_usage("/").percent)
            if cpu >= self.cpu_percent:
                self._emit("cpu", f"Signore, la CPU è al {cpu:.0f} per cento da controllare.")
            if memory >= self.memory_percent:
                self._emit("memory", f"Signore, la memoria di sistema è al {memory:.0f} per cento.")
            if disk >= self.disk_percent:
                self._emit("disk", f"Signore, lo spazio su disco è quasi esaurito: utilizzo {disk:.0f} per cento.")
        except Exception:
            pass

        gpu = self._gpu_temperature()
        if gpu is not None and gpu >= self.gpu_temp_c:
            self._emit("gpu-temp", f"Signore, la GPU ha raggiunto {gpu:.0f} gradi.")

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def worker() -> None:
            while not self._stop.is_set():
                self._check_once()
                self._stop.wait(self.poll_seconds)

        self._thread = threading.Thread(target=worker, daemon=True, name="jarvis-proactive-monitor")
        self._thread.start()

    def pop(self) -> ProactiveAlert | None:
        try:
            return self._alerts.get_nowait()
        except queue.Empty:
            return None

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=1.5)
