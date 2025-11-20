#!/usr/bin/env python3
"""Persistent per-servo step settings shared between the UI and control loop."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Dict, Iterable


SERVO_STEP_KEYS: tuple[str, ...] = ("shoulder", "wrist", "rotate", "gripper", "camera")
_STEPS_FILE = Path(__file__).with_name("servo_steps.json")
_LOCK = threading.Lock()
_LOADED = False


def _read_env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


_MIN_STEP = max(1, _read_env_int("SERVO_STEP_MIN", 1))
_MAX_STEP = max(_MIN_STEP, _read_env_int("SERVO_STEP_MAX", 10))


def _clamp(value) -> int:
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            raise ValueError("Step value must be numeric")
        try:
            value = float(candidate)
        except ValueError as exc:
            raise ValueError("Step value must be numeric") from exc
    if not isinstance(value, (int, float)):
        raise ValueError("Step value must be numeric")
    value = int(round(value))
    return max(_MIN_STEP, min(_MAX_STEP, value))


def _env_default(name: str, fallback: int) -> int:
    env_name = f"SERVO_STEP_{name.upper()}"
    return _clamp(_read_env_int(env_name, fallback))


_DEFAULT_STEPS: Dict[str, int] = {
    key: _env_default(key, _MIN_STEP) for key in SERVO_STEP_KEYS
}
_STATE: Dict[str, int] = dict(_DEFAULT_STEPS)


def _ensure_loaded_locked() -> None:
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    if not _STEPS_FILE.exists():
        _serialize_locked()
        return
    try:
        data = json.loads(_STEPS_FILE.read_text())
    except (OSError, ValueError):
        _serialize_locked()
        return
    steps = data.get("steps") if isinstance(data, dict) else {}
    changed = False
    for key in SERVO_STEP_KEYS:
        raw_value = steps.get(key)
        if raw_value is None:
            if key not in steps:
                if _STATE.get(key) != _DEFAULT_STEPS[key]:
                    _STATE[key] = _DEFAULT_STEPS[key]
                    changed = True
            continue
        try:
            parsed = _clamp(raw_value)
        except ValueError:
            parsed = _DEFAULT_STEPS[key]
            changed = True
        if _STATE.get(key) != parsed:
            _STATE[key] = parsed
    if any(key not in steps for key in SERVO_STEP_KEYS):
        changed = True
    if changed:
        _serialize_locked()


def _serialize_locked() -> None:
    payload = {
        "steps": _STATE,
        "limits": {"min": _MIN_STEP, "max": _MAX_STEP},
    }
    try:
        _STEPS_FILE.write_text(json.dumps(payload, indent=2, sort_keys=True))
    except OSError as exc:
        print(f"Failed to persist servo steps: {exc}")


def get_steps() -> Dict[str, int]:
    with _LOCK:
        _ensure_loaded_locked()
        return dict(_STATE)


def get_step(name: str) -> int:
    name = str(name).lower()
    if name not in SERVO_STEP_KEYS:
        raise KeyError(f"Unknown servo '{name}'")
    with _LOCK:
        _ensure_loaded_locked()
        return _STATE[name]


def get_limits() -> Dict[str, int]:
    return {"min": _MIN_STEP, "max": _MAX_STEP}


def update_steps(updates: Dict[str, int]) -> Dict[str, int]:
    if not updates:
        raise ValueError("No step values provided")
    normalized: Dict[str, int] = {}
    for key, value in updates.items():
        if key not in SERVO_STEP_KEYS:
            continue
        normalized[key] = _clamp(value)

    if not normalized:
        raise ValueError("No valid servo keys provided")

    with _LOCK:
        _ensure_loaded_locked()
        changed = False
        for key, value in normalized.items():
            if _STATE.get(key) != value:
                _STATE[key] = value
                changed = True
        if changed:
            _serialize_locked()
        return dict(_STATE)


def iter_defaults() -> Iterable[tuple[str, int]]:
    return tuple(_DEFAULT_STEPS.items())


__all__ = [
    "SERVO_STEP_KEYS",
    "get_steps",
    "get_step",
    "get_limits",
    "update_steps",
    "iter_defaults",
]
