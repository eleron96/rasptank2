#!/usr/bin/env python3
"""Lightweight server-sent event broadcaster for the web control stack."""

from __future__ import annotations

import queue
import threading
import time
from typing import Any, Dict


class EventBus:
    """Publish/subscribe helper for SSE endpoints."""

    def __init__(self) -> None:
        self._listeners: set[queue.Queue] = set()
        self._lock = threading.Lock()

    def listen(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._listeners.add(q)
        return q

    def remove(self, q: queue.Queue) -> None:
        with self._lock:
            self._listeners.discard(q)

    def publish(self, event_type: str, payload: Dict[str, Any]) -> None:
        message = {
            "type": event_type,
            "payload": payload,
            "ts": time.time(),
        }
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener.put_nowait(message)
            except queue.Full:
                # Drop messages if a listener falls behind; avoids blocking publishers.
                continue


event_bus = EventBus()
