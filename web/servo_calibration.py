#!/usr/bin/env python3
"""Persistent calibration settings for the robotic arm servos."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Callable, Dict, Optional


_CALIBRATION_FILE = Path(__file__).with_name("servo_calibration.json")
_LOCK = threading.Lock()

_DEFAULT_SHOULDER = {
    "base_angle": 90,
    "raise_angle": 60,
}

_current = {
    "shoulder": dict(_DEFAULT_SHOULDER),
}

_shoulder_observers: "set[Callable[[Dict[str, float]], None]]" = set()


def _ensure_loaded() -> None:
    """Load calibration data from disk if present."""
    if _CALIBRATION_FILE.exists():
        try:
            data = json.loads(_CALIBRATION_FILE.read_text())
        except (ValueError, OSError):
            return
        shoulder = data.get("shoulder")
        if isinstance(shoulder, dict):
            for key in ("base_angle", "raise_angle"):
                value = shoulder.get(key)
                if isinstance(value, (int, float)):
                    _current["shoulder"][key] = float(value)
        if _drop_legacy_fields():
            _serialize()


def _drop_legacy_fields() -> bool:
    allowed = {"base_angle", "raise_angle"}
    extras = set(_current["shoulder"].keys()) - allowed
    changed = False
    for key in extras:
        _current["shoulder"].pop(key, None)
        changed = True
    return changed


def _serialize() -> None:
    """Persist the current calibration to disk."""
    try:
        payload = json.dumps(
            {
                "shoulder": {
                    "base_angle": _current["shoulder"]["base_angle"],
                    "raise_angle": _current["shoulder"]["raise_angle"],
                }
            },
            indent=2,
            sort_keys=True,
        )
        _CALIBRATION_FILE.write_text(payload)
    except OSError as exc:
        print(f"Failed to write servo calibration: {exc}")


def _clamp_angle(value: float, label: str) -> float:
    if not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    if value < 0 or value > 180:
        raise ValueError(f"{label} must be between 0 and 180")
    return float(value)


def get_shoulder_calibration() -> Dict[str, Optional[float]]:
    """Return a copy of the stored shoulder calibration."""
    with _LOCK:
        _ensure_loaded()
        return dict(_current["shoulder"])


def update_shoulder_calibration(
    *,
    base_angle: float,
    raise_angle: float,
) -> Dict[str, Optional[float]]:
    """Validate, persist, and return the updated shoulder calibration."""
    base = _clamp_angle(base_angle, "base_angle")
    raise_val = _clamp_angle(raise_angle, "raise_angle")

    if base + raise_val > 180:
        raise ValueError("base_angle + raise_angle must not exceed 180")

    with _LOCK:
        _ensure_loaded()
        _current["shoulder"]["base_angle"] = base
        _current["shoulder"]["raise_angle"] = raise_val
        _serialize()
        snapshot = dict(_current["shoulder"])

    _notify_shoulder(snapshot)
    return snapshot


def register_shoulder_observer(callback: Callable[[Dict[str, float]], None]) -> None:
    """Register a callback for live shoulder calibration updates."""
    with _LOCK:
        _shoulder_observers.add(callback)


def unregister_shoulder_observer(callback: Callable[[Dict[str, float]], None]) -> None:
    """Remove a previously registered shoulder calibration observer."""
    with _LOCK:
        _shoulder_observers.discard(callback)


def _notify_shoulder(snapshot: Dict[str, float]) -> None:
    observers = list(_shoulder_observers)
    for callback in observers:
        try:
            callback(dict(snapshot))
        except Exception as exc:
            print(f"Shoulder calibration observer error: {exc}")


# Ensure defaults are loaded at import time so callers get up-to-date values.
with _LOCK:
    _ensure_loaded()
