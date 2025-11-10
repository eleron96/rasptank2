#!/usr/bin/env python3
"""Helpers for driving the on-board buzzer on GPIO18."""
import os

from threading import Lock
from gpiozero import Buzzer

_PIN = int(os.getenv("BUZZER_GPIO", "18"))

class _BuzzerControl:
    def __init__(self):
        self._buzzer = Buzzer(_PIN, active_high=True)
        self._lock = Lock()

    def _beep(self, on_time: float, off_time: float, n: int) -> None:
        # gpiozero handles background beeping; serialize calls to avoid overlap
        with self._lock:
            self._buzzer.beep(on_time=on_time, off_time=off_time, n=n, background=True)

    def tick(self):
        self._beep(0.05, 0.0, 1)

    def double(self):
        self._beep(0.05, 0.05, 2)

    def alert(self):
        self._beep(0.2, 0.05, 2)


_BUZZER = _BuzzerControl()


def tick():
    _BUZZER.tick()


def double():
    _BUZZER.double()


def alert():
    _BUZZER.alert()
