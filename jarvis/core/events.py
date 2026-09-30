from dataclasses import dataclass
from datetime import datetime


@dataclass
class JarvisEvent:
    type: str
    data: dict | None = None
    timestamp: str = datetime.now().isoformat()


class EventBus:

    def __init__(self):
        self.listeners = {}

    def subscribe(self, event_type, callback):
        self.listeners.setdefault(event_type, []).append(callback)

    def emit(self, event):

        callbacks = self.listeners.get(event.type, [])

        for callback in callbacks:
            callback(event)