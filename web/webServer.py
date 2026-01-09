#!/usr/bin/env/python
# File name   : server.py
# Production  : picar-b
# Website     : www.adeept.com
# Author      : devin

import time
import threading
import logging
import math
import glob
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
import os
import socket

from core.events import event_bus
from modules import automation as functions
from modules import battery_monitor
from modules import camera as camera_opencv
from modules import imu_sensor
from modules import servo_calibration
from modules import servo_steps
from modules import ultra
from modules import movement as move
from modules.lighting import LightingController
from utils import buzzer
from utils import info
from utils import switch
from utils import rpi_servo as RPIservo
from utils.pca9685_driver import angle_to_us

#websocket
import asyncio
import websockets
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

import json
from . import app

OLED_connection = 0


functionMode = 0
speed_set = 100
rad = 0.5
turnWiggle = 60

SHOULDER_SERVO_CHANNEL = 0
LVC_DISABLED = os.getenv("SHOULDER_LVC_DISABLE", "1").strip() in ("1", "true", "on")
LVC_LOWER_V = float(os.getenv("SHOULDER_LVC_LOWER", "6.0"))
LVC_UPPER_V = float(os.getenv("SHOULDER_LVC_UPPER", "6.2"))
LVC_EMA_ALPHA = float(os.getenv("SHOULDER_LVC_ALPHA", "0.2"))
logger = logging.getLogger("rasptank")

def _read_env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default

_distance_lock = threading.Lock()
_distance_state = {"value": None, "timestamp": 0.0}
_distance_event_lock = threading.Lock()
_distance_event_state = {"value": None, "timestamp": 0.0, "status": None}
_DISTANCE_IDLE_TIMEOUT = float(os.getenv("DISTANCE_IDLE_TIMEOUT", "60"))
_DISTANCE_POLL_ACTIVE = max(0.05, _read_env_float("DISTANCE_POLL_ACTIVE", 0.2))
_DISTANCE_POLL_STANDBY = max(0.1, _read_env_float("DISTANCE_POLL_STANDBY", 1.5))
_DISTANCE_POLL_ECO = max(0.2, _read_env_float("DISTANCE_POLL_ECO", 3.0))
_distance_monitor_lock = threading.Lock()
_distance_monitor_state = {
    "enabled": True,
    "paused": False,
    "last_motion_ts": time.time(),
    "last_value": None,
}
_COMMAND_EXECUTOR = ThreadPoolExecutor(max_workers=1)
_shoulder_state = {
    "mode": "IDLE",
    "last_cmd": None,
    "last_cmd_ts": 0.0,
}

_shoulder_timeout_lock = threading.Lock()
_shoulder_timeout = None


_lvc_state = {"ema": None, "blocked": False}

SYSTEM_MODES = ("STANDBY", "ACTIVE", "ECO")
_LEGACY_MODE_ALIASES = {"STABILITY": "STANDBY"}


def _normalize_mode_name(value: Optional[str]) -> str:
    if value is None:
        return "ACTIVE"
    mode = str(value).strip().upper()
    return _LEGACY_MODE_ALIASES.get(mode, mode)


_system_mode = _normalize_mode_name(os.getenv("SYSTEM_MODE_DEFAULT", "ACTIVE"))
if _system_mode not in SYSTEM_MODES:
    _system_mode = "ACTIVE"

_distance_user_enabled = True
_MODE_COMMANDS = {"modeStandby", "modeStability", "modeActive", "modeEco"}
_CPU_GOVERNOR_PATH = "/sys/devices/system/cpu"
_CPU_GOVERNOR_DEFAULT = os.getenv("CPU_GOVERNOR_ACTIVE", "ondemand")
_CPU_GOVERNOR_LOW = os.getenv("CPU_GOVERNOR_LOW", "powersave")
_camera_high_quality = False

_MODE_IDLE_TIMEOUT = float(os.getenv("MODE_IDLE_TIMEOUT", "120"))
_last_activity_ts = time.time()

scGear = RPIservo.ServoCtrl()
# scGear.setup()
scGear.moveInit()

P_sc = RPIservo.ServoCtrl()
P_sc.start()
P_sc.set_direction(2, -1)

T_sc = RPIservo.ServoCtrl()
T_sc.start()

H1_sc = RPIservo.ServoCtrl()
H1_sc.start()
H1_sc.set_direction(0, -1)

H2_sc = RPIservo.ServoCtrl()
H2_sc.start()

G_sc = RPIservo.ServoCtrl()
G_sc.start()
G_sc.set_direction(3, -1)

lighting = LightingController()


def _servo_drive_speed(name: str) -> int:
    """Fetch the latest configured step for a servo channel."""
    try:
        return servo_steps.get_step(name)
    except Exception:
        return 1


def _clamp_speed(value, minimum=1, maximum=10):
    return max(minimum, min(maximum, value))

ARM_SERVO_SPEED = _clamp_speed(int(os.getenv("ARM_SERVO_SPEED", "10")))


def _clamp_angle(value, minimum=0, maximum=180):
    return max(minimum, min(maximum, value))


_shoulder_calibration = {
    "base_angle": 0.0,
    "raise_angle": 180.0,
}


def _apply_shoulder_calibration(calibration):
    global _shoulder_calibration
    if not isinstance(calibration, dict):
        return
    base = _clamp_angle(float(calibration.get("base_angle", 0.0)))
    span = _clamp_angle(float(calibration.get("raise_angle", 180.0)))
    span = max(5.0, min(span, 180.0))

    lower_angle = max(0.0, base - span)
    upper_angle = min(180.0, base + span)

    if upper_angle - lower_angle < 2.0:
        # expand to a minimal workable window around the base
        span = max(span, 5.0)
        lower_angle = max(0.0, base - span)
        upper_angle = min(180.0, base + span)
        if upper_angle - lower_angle < 2.0:
            lower_angle = max(0.0, min(base, 178.0))
            upper_angle = min(180.0, lower_angle + 2.0)

    _shoulder_calibration = {
        "base_angle": base,
        "raise_angle": span,
    }

    try:
        target_angle = max(lower_angle, min(upper_angle, base))
        target = int(round(target_angle))
        H1_sc.initConfig(SHOULDER_SERVO_CHANNEL, target, 1)
        H1_sc.maxPos[SHOULDER_SERVO_CHANNEL] = int(round(upper_angle))
        H1_sc.minPos[SHOULDER_SERVO_CHANNEL] = int(round(lower_angle))
        H1_sc.goalPos[SHOULDER_SERVO_CHANNEL] = target
        H1_sc.nowPos[SHOULDER_SERVO_CHANNEL] = target
        H1_sc.lastPos[SHOULDER_SERVO_CHANNEL] = target
        H1_sc.bufferPos[SHOULDER_SERVO_CHANNEL] = float(target)
        H1_sc.stopWiggle()
        _shoulder_state["mode"] = "IDLE"
        _log_shoulder_state("shoulder_calibrated", target=target)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error({"evt": "shoulder_calibration_error", "error": str(exc)})


# modeSelect = 'none'
modeSelect = 'PT'

init_pwm0 = scGear.initPos[0]
init_pwm1 = scGear.initPos[1]
init_pwm2 = scGear.initPos[2]
init_pwm3 = scGear.initPos[3]
init_pwm4 = scGear.initPos[4]

fuc = functions.Functions()
fuc.setup()
fuc.start()

curpath = os.path.realpath(__file__)
thisPath = "/" + os.path.dirname(curpath)

direction_command = 'no'
turn_command = 'no'
battery = None

def log_servo_action(action, **extra):
    payload = {"evt": "servo_action", "action": action}
    payload.update(extra)
    logger.info(payload)

def _get_shoulder_angle() -> Optional[float]:
    try:
        angle = H1_sc.nowPos[SHOULDER_SERVO_CHANNEL]
    except Exception:
        return None
    if angle is None:
        return None
    try:
        return float(angle)
    except (TypeError, ValueError):
        return None

def _log_shoulder_action(action: str, **extra) -> None:
    angle = _get_shoulder_angle()
    if angle is not None:
        extra.setdefault("angle_deg", round(angle, 2))
    log_servo_action(action, **extra)

def log_led_action(action, **extra):
    payload = {"evt": "led_action", "action": action}
    payload.update(extra)
    logger.info(payload)


def _update_distance_cache(value: Optional[float]) -> None:
    with _distance_lock:
        _distance_state["value"] = value
        _distance_state["timestamp"] = time.time()


def _get_distance_snapshot() -> tuple[Optional[float], float]:
    with _distance_lock:
        return _distance_state["value"], _distance_state["timestamp"]


def _distance_monitor_snapshot() -> dict:
    with _distance_monitor_lock:
        return dict(_distance_monitor_state)


def _distance_monitor_status(snapshot: Optional[dict] = None) -> str:
    if snapshot is None:
        snapshot = _distance_monitor_snapshot()
    if not snapshot.get("enabled"):
        return "disabled"
    if snapshot.get("paused"):
        return "paused"
    return "active"


def _set_distance_monitor_enabled(enabled: bool, remember: bool = True) -> None:
    global _distance_user_enabled
    if remember:
        _distance_user_enabled = enabled
    with _distance_monitor_lock:
        previous = _distance_monitor_state["enabled"]
        if previous == enabled:
            snapshot = dict(_distance_monitor_state)
        else:
            _distance_monitor_state["enabled"] = enabled
            if enabled:
                _distance_monitor_state["paused"] = False
                _distance_monitor_state["last_motion_ts"] = time.time()
            else:
                _distance_monitor_state["paused"] = True
            snapshot = dict(_distance_monitor_state)
    if previous != enabled:
        value = snapshot.get("last_value") if enabled else None
        status = _distance_monitor_status(snapshot)
        logger.info({"evt": "distance_monitor_toggle", "enabled": enabled})
        _broadcast_distance_update(value, status=status)


def _set_distance_monitor_paused(paused: bool) -> None:
    with _distance_monitor_lock:
        if not _distance_monitor_state["enabled"] and not paused:
            return
        previous = _distance_monitor_state["paused"]
        if previous == paused:
            return
        _distance_monitor_state["paused"] = paused
        snapshot = dict(_distance_monitor_state)
    _broadcast_distance_update(snapshot.get("last_value"), status=_distance_monitor_status(snapshot))


def _note_distance_motion(active: bool) -> None:
    if not active:
        return
    with _distance_monitor_lock:
        _distance_monitor_state["last_motion_ts"] = time.time()
        if not (_distance_monitor_state["enabled"] and _distance_monitor_state["paused"]):
            return
        _distance_monitor_state["paused"] = False
        snapshot = dict(_distance_monitor_state)
    _broadcast_distance_update(snapshot.get("last_value"), status=_distance_monitor_status(snapshot))


def _maybe_pause_distance_monitor(now: float) -> bool:
    with _distance_monitor_lock:
        if (
            _distance_monitor_state["enabled"]
            and not _distance_monitor_state["paused"]
            and now - _distance_monitor_state["last_motion_ts"] >= _DISTANCE_IDLE_TIMEOUT
        ):
            _distance_monitor_state["paused"] = True
            snapshot = dict(_distance_monitor_state)
        else:
            return False
    _broadcast_distance_update(snapshot.get("last_value"), status=_distance_monitor_status(snapshot))
    return True


def _distance_worker(poll_interval: Optional[float] = None) -> None:
    while True:
        sleep_interval = poll_interval if poll_interval is not None else _get_distance_sleep_interval()
        try:
            snapshot = _distance_monitor_snapshot()
            status = _distance_monitor_status(snapshot)
            if status == "disabled":
                time.sleep(sleep_interval)
                continue
            now = time.time()
            if status == "active" and _maybe_pause_distance_monitor(now):
                time.sleep(sleep_interval)
                continue
            snapshot = _distance_monitor_snapshot()
            status = _distance_monitor_status(snapshot)
            if status != "active":
                time.sleep(sleep_interval)
                continue
            measurement = ultra.checkdist()
            if measurement is not None and math.isfinite(measurement):
                value = max(0.0, float(measurement))
                with _distance_monitor_lock:
                    _distance_monitor_state["last_value"] = value
                    snapshot = dict(_distance_monitor_state)
                _update_distance_cache(value)
                _broadcast_distance_update(value, status=_distance_monitor_status(snapshot))
            else:
                _broadcast_distance_update(None)
        except Exception as exc:
            logger.debug({"evt": "ultrasonic_read_error", "error": str(exc)})
        time.sleep(sleep_interval)


def _get_distance_sleep_interval() -> float:
    if _system_mode == "ECO":
        return _DISTANCE_POLL_ECO
    if _system_mode == "STANDBY":
        return _DISTANCE_POLL_STANDBY
    return _DISTANCE_POLL_ACTIVE


def _distance_motion_listener() -> None:
    queue = event_bus.listen()
    while True:
        message = queue.get()
        if message.get("type") != "drive_motion":
            continue
        payload = message.get("payload") or {}
        _note_distance_motion(bool(payload.get("active")))


def _set_cpu_governor(governor: str) -> bool:
    governor = (governor or "").strip()
    if not governor or not os.path.isdir(_CPU_GOVERNOR_PATH):
        return False
    paths = glob.glob(os.path.join(_CPU_GOVERNOR_PATH, "cpu[0-9]*/cpufreq/scaling_governor"))
    if not paths:
        return False
    success = False
    for path in paths:
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(governor)
            success = True
        except Exception:
            continue
    if success:
        logger.debug({"evt": "cpu_governor_set", "value": governor})
    return success


def _sync_distance_monitor_to_user_pref() -> None:
    if _distance_user_enabled:
        _set_distance_monitor_enabled(True, remember=False)
    else:
        _set_distance_monitor_enabled(False, remember=False)


def _apply_camera_profile() -> None:
    if _system_mode == "ACTIVE" and _camera_high_quality:
        camera_opencv.set_stream_profile("ACTIVE_HIGH")
    else:
        camera_opencv.set_stream_profile(_system_mode)


def _set_camera_high_quality(enabled: bool) -> None:
    global _camera_high_quality
    if enabled and _system_mode != "ACTIVE":
        logger.info({"evt": "camera_hq_blocked", "reason": "mode", "mode": _system_mode})
        return
    if _camera_high_quality == enabled:
        return
    _camera_high_quality = enabled
    _apply_camera_profile()
    logger.info({"evt": "camera_high_quality", "enabled": enabled})


def _note_activity() -> None:
    global _last_activity_ts
    _last_activity_ts = time.time()


def _mode_idle_worker(interval: float = 2.0) -> None:
    while True:
        try:
            if _system_mode == "ACTIVE":
                idle_for = time.time() - _last_activity_ts
                if idle_for >= _MODE_IDLE_TIMEOUT:
                    _set_system_mode("STANDBY", reason="idle", auto=True)
        except Exception as exc:
            logger.debug({"evt": "mode_idle_error", "error": str(exc)})
        time.sleep(interval)


def _set_system_mode(mode: str, reason: Optional[str] = None, auto: bool = False, force: bool = False) -> bool:
    global _system_mode, _camera_high_quality
    if not mode:
        return False
    normalized = _normalize_mode_name(mode)
    if normalized not in SYSTEM_MODES:
        return False
    if not force and normalized == _system_mode:
        return False

    previous = _system_mode
    _system_mode = normalized

    if normalized == "STANDBY":
        _set_cpu_governor(_CPU_GOVERNOR_LOW)
        _camera_high_quality = False
        _apply_camera_profile()
        move.motorStop()
        fuc.pause()
        switch.set_all_switch_off()
        lighting.strip_off()
        _set_distance_monitor_enabled(False, remember=False)
    elif normalized == "ECO":
        _set_cpu_governor(_CPU_GOVERNOR_LOW)
        _camera_high_quality = False
        _apply_camera_profile()
        move.motorStop()
        fuc.pause()
        switch.set_all_switch_off()
        lighting.strip_off()
        _sync_distance_monitor_to_user_pref()
    else:
        _set_cpu_governor(_CPU_GOVERNOR_DEFAULT)
        _apply_camera_profile()
        _note_activity()
        _sync_distance_monitor_to_user_pref()

    payload = {
        "evt": "system_mode",
        "mode": normalized,
        "previous": previous,
        "auto": auto,
    }
    if reason:
        payload["reason"] = reason
    logger.info(payload)
    event_bus.publish("system_mode", {"mode": normalized})
    return True


def _ensure_mode_initialized() -> None:
    _set_system_mode(_system_mode, reason="startup", force=True)


def _maybe_wake_from_standby(command_input: str) -> None:
    if _system_mode != "STANDBY":
        return
    if not command_input:
        return
    if command_input in _MODE_COMMANDS:
        return
    if command_input in ("get_info", "distanceMonitorOn", "distanceMonitorOff"):
        return
    if command_input.startswith("mode"):
        return
    _set_system_mode("ACTIVE", reason="command", auto=True)


def _command_allowed_in_eco(command_input: str) -> bool:
    # In ECO mode all commands are allowed; hardware modules remain in low-power
    # states by default, but explicit commands take precedence.
    return True


def _handle_mode_command(command_input: str) -> bool:
    if command_input == "modeStandby":
        _set_system_mode("STANDBY", reason="user")
        return True
    if command_input == "modeStability":
        _set_system_mode("STANDBY", reason="user")
        return True
    if command_input == "modeActive":
        _set_system_mode("ACTIVE", reason="user")
        return True
    if command_input == "modeEco":
        _set_system_mode("ECO", reason="user")
        return True
    return False


def _broadcast_distance_update(value: Optional[float], status: Optional[str] = None) -> None:
    now = time.time()
    payload_value = None if value is None else round(float(value), 2)
    resolved_status = status or _distance_monitor_status()
    with _distance_event_lock:
        last_value = _distance_event_state["value"]
        last_ts = _distance_event_state["timestamp"]
        last_status = _distance_event_state.get("status")
        if resolved_status == last_status:
            if payload_value is None and last_value is None and now - last_ts < 1.0:
                return
            if (
                payload_value is not None
                and last_value is not None
                and abs(last_value - payload_value) < 0.5
                and now - last_ts < 0.2
            ):
                return
        _distance_event_state["value"] = payload_value
        _distance_event_state["timestamp"] = now
        _distance_event_state["status"] = resolved_status
    display = "--" if payload_value is None else f"{payload_value:.1f}"
    if resolved_status == "disabled":
        display = "--"
    try:
        event_bus.publish(
            "distance_update",
            {"cm": payload_value, "display": display, "status": resolved_status, "ts": now},
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug({"evt": "distance_event_error", "error": str(exc)})


def servoPosInit():
    scGear.initConfig(0,init_pwm0,1)
    P_sc.initConfig(1,init_pwm1,1)
    T_sc.initConfig(2,init_pwm2,1)
    H1_sc.initConfig(3,init_pwm3,1)
    H2_sc.initConfig(3,init_pwm3,1)
    G_sc.initConfig(4,init_pwm4,1)


def replace_num(initial,new_num):   #Call this function to replace data in '.txt' file
    global r
    newline=""
    str_num=str(new_num)
    with open(thisPath+"/RPIservo.py","r") as f:
        for line in f.readlines():
            if(line.find(initial) == 0):
                line = initial+"%s" %(str_num+"\n")
            newline += line
    with open(thisPath+"/RPIservo.py","w") as f:
        f.writelines(newline)


# def FPV_thread():
#     global fpv
#     fpv=FPV.FPV()
#     fpv.capture_thread(addr[0])


def ap_thread():
    os.system("sudo create_ap wlan0 eth0 Adeept_Robot 12345678")


def functionSelect(command_input, response):
    global functionMode, _distance_user_enabled

    if 'findColor' == command_input:
        flask_app.modeselect('findColor')

    if 'motionGet' == command_input:
        flask_app.modeselect('watchDog')

    elif 'stopCV' == command_input:
        flask_app.modeselect('none')
        switch.switch(1,0)
        switch.switch(2,0)
        switch.switch(3,0)
        move.motorStop()

    elif 'KD' == command_input:
        servoPosInit()
        fuc.keepDistance()

    elif 'automatic' == command_input:
        if modeSelect == 'PT':
            fuc.automatic()
        else:
            fuc.pause()

    elif 'automaticOff' == command_input:
        lighting.strip_off()
        fuc.pause()
        move.motorStop()
        time.sleep(0.3)
        move.motorStop()

    elif 'distanceMonitorOn' == command_input:
        _distance_user_enabled = True
        if _system_mode == "STANDBY":
            _set_distance_monitor_enabled(False, remember=False)
            logger.info({"evt": "distance_monitor_request", "status": "queued_for_active"})
        else:
            _set_distance_monitor_enabled(True, remember=True)
        buzzer.tick()

    elif 'distanceMonitorOff' == command_input:
        _distance_user_enabled = False
        _set_distance_monitor_enabled(False, remember=True)
        buzzer.tick()

    elif 'cameraHQOn' == command_input:
        _set_camera_high_quality(True)
        buzzer.tick()

    elif 'cameraHQOff' == command_input:
        _set_camera_high_quality(False)
        buzzer.tick()

    elif 'wsStripOn' == command_input:
        if lighting.set_strip_color((0, 90, 255)):
            buzzer.tick()
        else:
            logger.warning({"evt": "ws_strip_failed", "action": "on"})

    elif 'wsStripOff' == command_input:
        if lighting.strip_off():
            buzzer.tick()
        else:
            logger.warning({"evt": "ws_strip_failed", "action": "off"})

    elif 'trackLine' == command_input:
        servoPosInit()
        fuc.trackLine()

    elif 'trackLineOff' == command_input:
        fuc.pause()
        move.motorStop()

    elif 'steadyCamera' == command_input:
        fuc.steady(T_sc.lastPos[2])

    elif 'steadyCameraOff' == command_input:
        fuc.pause()
        move.motorStop()




def switchCtrl(command_input, response):
    if 'Switch_1_on' in command_input:
        switch.switch(1,1)

    elif 'Switch_1_off' in command_input:
        switch.switch(1,0)

    elif 'Switch_2_on' in command_input:
        switch.switch(2,1)

    elif 'Switch_2_off' in command_input:
        switch.switch(2,0)

    elif 'Switch_3_on' in command_input:
        log_led_action('Switch_3_on')
        switch.switch(3,1)

    elif 'Switch_3_off' in command_input:
        log_led_action('Switch_3_off')
        switch.switch(3,0) 

    elif 'ledOn' == command_input:
        lighting.set_headlight(True, reason='command_ledOn')
        buzzer.tick()

    elif 'ledOff' == command_input:
        lighting.set_headlight(False, reason='command_ledOff')
        buzzer.tick()


def robotCtrl(command_input, response):
    global direction_command, turn_command
    if 'forward' == command_input:
        direction_command = 'forward'
        move.move(speed_set, 1, "mid")
        buzzer.tick()
        logger.debug({"evt": "drive_debug", "note": "forward command tick"})
    
    elif 'backward' == command_input:
        direction_command = 'backward'
        move.move(speed_set, -1, "no")
        buzzer.tick()

    elif 'DS' in command_input:
        direction_command = 'no'
        if turn_command == 'no':
            move.motorStop()


    elif 'left' == command_input:
        turn_command = 'left'
        move.move(speed_set, 1, "left")
        buzzer.tick()

    elif 'right' == command_input:
        turn_command = 'right'
        move.move(speed_set, 1, "right")
        buzzer.tick()


    elif 'TS' in command_input:
        turn_command = 'no'
        if direction_command == 'no':
            move.motorStop()

    elif 'armUp' == command_input: #servo A
        if _shoulder_guard_blocked("up"):
            return
        if _shoulder_at_edge(move_up=True):
            _shoulder_stop("limit_max")
            return
        _shoulder_state["mode"] = "UP"
        _shoulder_state["last_cmd"] = "armUp"
        _shoulder_state["last_cmd_ts"] = time.time()
        _log_shoulder_action('armUp')
        H1_sc.singleServo(SHOULDER_SERVO_CHANNEL, -1, _servo_drive_speed("shoulder"))
        _schedule_shoulder_timeout()
        _log_shoulder_state("shoulder_cmd", direction="up")
    elif 'armDown' == command_input:
        if _shoulder_guard_blocked("down"):
            return
        if _shoulder_at_edge(move_up=False):
            _shoulder_stop("limit_min")
            return
        _shoulder_state["mode"] = "DOWN"
        _shoulder_state["last_cmd"] = "armDown"
        _shoulder_state["last_cmd_ts"] = time.time()
        _log_shoulder_action('armDown')
        H1_sc.singleServo(SHOULDER_SERVO_CHANNEL, 1, _servo_drive_speed("shoulder"))
        _schedule_shoulder_timeout()
        _log_shoulder_state("shoulder_cmd", direction="down")
    elif 'armStop' in command_input:
        _shoulder_stop("manual")

    elif 'handUp' == command_input: # servo B
        log_servo_action('handUp')
        H2_sc.singleServo(1, -1, _servo_drive_speed("wrist"))
    elif 'handDown' == command_input:
        log_servo_action('handDown')
        H2_sc.singleServo(1, 1, _servo_drive_speed("wrist"))
    elif 'handStop' in command_input:
        log_servo_action('handStop')
        H2_sc.stopWiggle()

    elif 'lookleft' == command_input: # servo C
        log_servo_action('lookleft')
        P_sc.singleServo(2, 1, _servo_drive_speed("rotate"))
    elif 'lookright' == command_input:
        log_servo_action('lookright')
        P_sc.singleServo(2, -1, _servo_drive_speed("rotate"))
    elif 'LRstop' in command_input:
        log_servo_action('LRstop')
        P_sc.stopWiggle()

    elif 'grab' == command_input: # servo D
        log_servo_action('grab')
        G_sc.singleServo(3, 1, _servo_drive_speed("gripper"))
        buzzer.double()
    elif 'loose' == command_input:
        log_servo_action('loose')
        G_sc.singleServo(3, -1, _servo_drive_speed("gripper"))
        buzzer.double()
    elif 'GLstop' in command_input:
        log_servo_action('GLstop')
        G_sc.stopWiggle()

    elif 'up' == command_input: # camera
        log_servo_action('up')
        T_sc.singleServo(4, -1, _servo_drive_speed("camera"))
    elif 'down' == command_input:
        log_servo_action('down')
        T_sc.singleServo(4, 1, _servo_drive_speed("camera"))
    elif 'UDstop' in command_input:
        log_servo_action('UDstop')
        T_sc.stopWiggle()



    elif 'home' == command_input:
        _cancel_shoulder_timeout()
        log_servo_action('home')
        H1_sc.moveServoInit(0)
        H2_sc.moveServoInit(1)
        P_sc.moveServoInit(2)
        G_sc.moveServoInit(3)
        T_sc.moveServoInit(4)
        logger.debug({"evt": "servo_home"})


def configPWM(command_input, response):
    global init_pwm0, init_pwm1, init_pwm2, init_pwm3, init_pwm4

    if 'SiLeft' in command_input:
        numServo = int(command_input[7:])
        if numServo == 0:
            init_pwm0 -= 1
            H1_sc.setPWM(0,init_pwm0)
        elif numServo == 1:
            init_pwm1 -= 1
            H2_sc.setPWM(1,init_pwm1)
        elif numServo == 2:
            init_pwm2 -= 1
            P_sc.setPWM(2,init_pwm2)
        elif numServo == 3:
            init_pwm3 -= 1
            G_sc.setPWM(3,init_pwm3)
        elif numServo == 4:
            init_pwm4 -= 1
            T_sc.setPWM(4,init_pwm4)

    if 'SiRight' in command_input:
        numServo = int(command_input[8:])
        if numServo == 0:
            init_pwm0 += 1
            T_sc.setPWM(0,init_pwm0)
        elif numServo == 1:
            init_pwm1 += 1
            P_sc.setPWM(1,init_pwm1)
        elif numServo == 2:
            init_pwm2 += 1
            scGear.setPWM(2,init_pwm2)

        if numServo == 0:
            init_pwm0 += 1
            H1_sc.setPWM(0,init_pwm0)
        elif numServo == 1:
            init_pwm1 += 1
            H2_sc.setPWM(1,init_pwm1)
        elif numServo == 2:
            init_pwm2 += 1
            P_sc.setPWM(2,init_pwm2)
        elif numServo == 3:
            init_pwm3 += 1
            G_sc.setPWM(3,init_pwm3)
        elif numServo == 4:
            init_pwm4 += 1
            T_sc.setPWM(4,init_pwm4)

    if 'PWMMS' in command_input:
        numServo = int(command_input[6:])
        if numServo == 0:
            T_sc.initConfig(0, init_pwm0, 1)
            replace_num('init_pwm0 = ', init_pwm0)
        elif numServo == 1:
            P_sc.initConfig(1, init_pwm1, 1)
            replace_num('init_pwm1 = ', init_pwm1)
        elif numServo == 2:
            scGear.initConfig(2, init_pwm2, 2)
            replace_num('init_pwm2 = ', init_pwm2)


    if 'PWMINIT' == command_input:
        logger.debug({"evt": "pwm_init_readback", "value": init_pwm1})
        servoPosInit()

    elif 'PWMD' == command_input:
        init_pwm0,init_pwm1,init_pwm2,init_pwm3,init_pwm4=90,90,90,90,90
        T_sc.initConfig(0,90,1)
        replace_num('init_pwm0 = ', 90)

        P_sc.initConfig(1,90,1)
        replace_num('init_pwm1 = ', 90)

        scGear.initConfig(2,90,1)
        replace_num('init_pwm2 = ', 90)


def _process_hardware_command(command_input: str) -> None:
    try:
        logger.info({"evt": "command_queue", "cmd": command_input})
        if isinstance(command_input, str):
            _note_activity()
            _maybe_wake_from_standby(command_input)
            if _handle_mode_command(command_input):
                return
            if _system_mode == "ECO" and not _command_allowed_in_eco(command_input):
                logger.info({"evt": "mode_blocked", "mode": _system_mode, "cmd": command_input})
                return
        robotCtrl(command_input, None)
        switchCtrl(command_input, None)
        functionSelect(command_input, None)
        configPWM(command_input, None)
    except Exception as exc:
        logger.error({"evt": "command_queue_error", "cmd": command_input, "error": str(exc)})


def _dispatch_hardware_command(command_input: str) -> None:
    _COMMAND_EXECUTOR.submit(_process_hardware_command, command_input)


def _update_lvc_state(measurement: Optional[float] = None) -> bool:
    if LVC_DISABLED:
        if _lvc_state["blocked"]:
            _lvc_state["blocked"] = False
            event_bus.publish(
                "shoulder_guard",
                {"state": "released", "reason": "lvc_disabled"},
            )
        return False
    if battery is None:
        return False
    try:
        if measurement is None:
            measurement = battery.read_voltage()
    except Exception as exc:
        logger.warning({"evt": "battery_read_error", "error": str(exc)})
        return _lvc_state["blocked"]
    if measurement is None or measurement <= 0:
        return _lvc_state["blocked"]

    ema = _lvc_state["ema"]
    if ema is None:
        ema = measurement
    else:
        ema = LVC_EMA_ALPHA * measurement + (1.0 - LVC_EMA_ALPHA) * ema
    _lvc_state["ema"] = ema

    blocked = _lvc_state["blocked"]
    if blocked:
        if ema >= LVC_UPPER_V:
            _lvc_state["blocked"] = False
            event_bus.publish(
                "shoulder_guard",
                {"state": "released", "reason": "lvc_recovered", "voltage": round(ema, 2)},
            )
    else:
        if ema <= LVC_LOWER_V:
            _lvc_state["blocked"] = True
            event_bus.publish(
                "shoulder_guard",
                {"state": "blocked", "reason": "lvc", "voltage": round(ema, 2)},
            )
    return _lvc_state["blocked"]


def _log_shoulder_state(event: str, **extra) -> None:
    now_pos = _get_shoulder_angle()
    try:
        goal_pos = H1_sc.goalPos[SHOULDER_SERVO_CHANNEL]
        speed = H1_sc.scSpeed[SHOULDER_SERVO_CHANNEL]
    except Exception:
        goal_pos = speed = None

    min_angle = None
    max_angle = None
    try:
        min_angle = H1_sc.minPos[SHOULDER_SERVO_CHANNEL]
        max_angle = H1_sc.maxPos[SHOULDER_SERVO_CHANNEL]
    except Exception:
        pass

    min_us = getattr(H1_sc, "_servo_min_pulse_us", 500)
    max_us = getattr(H1_sc, "_servo_max_pulse_us", 2400)
    us_now = angle_to_us(now_pos or 0, min_us, max_us) if now_pos is not None else None
    us_goal = angle_to_us(goal_pos or 0, min_us, max_us) if goal_pos is not None else None

    edge = "none"
    if now_pos is not None and min_angle is not None and max_angle is not None:
        if now_pos <= min_angle + 1:
            edge = "min"
        elif now_pos >= max_angle - 1:
            edge = "max"

    telemetry = {
        "evt": event,
        "servo": "shoulder",
        "channel": SHOULDER_SERVO_CHANNEL,
        "state": _shoulder_state["mode"],
        "angle_deg": round(now_pos, 2) if now_pos is not None else None,
        "now": now_pos,
        "goal": goal_pos,
        "speed": speed,
        "us_now": us_now,
        "us_goal": us_goal,
        "edge": edge,
        "calibration": dict(_shoulder_calibration),
    }

    voltage = None
    if battery is not None:
        try:
            voltage = round(battery.read_voltage(), 2)
            telemetry["vbat"] = voltage
            telemetry["vbat_pct"] = battery.read_percentage()
        except Exception as exc:
            telemetry["vbat_error"] = str(exc)

    blocked = _update_lvc_state(voltage)
    telemetry["vbat_filtered"] = round(_lvc_state["ema"], 2) if _lvc_state["ema"] else None
    telemetry["lvc_blocked"] = blocked

    telemetry.update(extra)
    logger.info(telemetry)


servo_calibration.register_shoulder_observer(_apply_shoulder_calibration)
_apply_shoulder_calibration(servo_calibration.get_shoulder_calibration())


def _cancel_shoulder_timeout() -> None:
    global _shoulder_timeout
    with _shoulder_timeout_lock:
        if _shoulder_timeout is not None:
            try:
                _shoulder_timeout.cancel()
            finally:
                _shoulder_timeout = None


def _shoulder_timeout_callback() -> None:
    global _shoulder_timeout
    with _shoulder_timeout_lock:
        _shoulder_timeout = None
    if _shoulder_state.get("mode") in ("UP", "DOWN"):
        _COMMAND_EXECUTOR.submit(_shoulder_stop, "timeout_guard")


def _schedule_shoulder_timeout(delay: float = 1.2) -> None:
    global _shoulder_timeout
    with _shoulder_timeout_lock:
        if _shoulder_timeout is not None:
            try:
                _shoulder_timeout.cancel()
            finally:
                _shoulder_timeout = None
        timer = threading.Timer(delay, _shoulder_timeout_callback)
        timer.daemon = True
        _shoulder_timeout = timer
        timer.start()


def _shoulder_stop(reason: str) -> None:
    _cancel_shoulder_timeout()
    H1_sc.stopWiggle()
    _shoulder_state["mode"] = "IDLE"
    _shoulder_state["last_cmd"] = "armStop"
    _shoulder_state["last_cmd_ts"] = time.time()
    _log_shoulder_action('armStop', reason=reason)
    _log_shoulder_state("shoulder_cmd", direction="stop", reason=reason)


def _shoulder_at_edge(move_up: bool) -> bool:
    try:
        now_pos = H1_sc.nowPos[SHOULDER_SERVO_CHANNEL]
        min_angle = H1_sc.minPos[SHOULDER_SERVO_CHANNEL]
        max_angle = H1_sc.maxPos[SHOULDER_SERVO_CHANNEL]
    except Exception:
        return False
    if now_pos is None or min_angle is None or max_angle is None:
        return False
    if move_up and now_pos >= max_angle - 1:
        return True
    if not move_up and now_pos <= min_angle + 1:
        return True
    return False


def _shoulder_guard_blocked(direction: str) -> bool:
    blocked = _update_lvc_state()
    if not blocked:
        return False
    reason = "lvc"
    _shoulder_stop(reason)
    event_bus.publish(
        "shoulder_guard",
        {
            "state": "blocked",
            "reason": reason,
            "direction": direction,
            "voltage": round(_lvc_state["ema"], 2) if _lvc_state["ema"] else None,
            "threshold": LVC_LOWER_V,
        },
    )
    return True


def update_code():
    # Update local to be consistent with remote
    projectPath = thisPath[:-7]
    with open(f'{projectPath}/config.json', 'r') as f1:
        config = json.load(f1)
        if not config['production']:
            logger.info({"evt": "update_code", "status": "starting"})
            # Force overwriting local code
            if os.system(f'cd {projectPath} && sudo git fetch --all && sudo git reset --hard origin/master && sudo git pull') == 0:
                logger.info({"evt": "update_code", "status": "completed"})
                logger.info({"evt": "system", "action": "reboot"})
                os.system('sudo reboot')
            
def wifi_check():
    try:
        s =socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        s.connect(("1.1.1.1",80))
        ipaddr_check=s.getsockname()[0]
        s.close()
        logger.info({"evt": "network_ip", "ip": ipaddr_check})
    except:
        ap_threading=threading.Thread(target=ap_thread)   #Define a thread for data receiving
        ap_threading.setDaemon(True)                          #'True' means it is a front thread,it would close when the mainloop() closes
        ap_threading.start()                                  #Thread starts
        lighting.set_strip_color((0,16,50))
        time.sleep(1)

async def check_permit(websocket):
    while True:
        recv_str = await websocket.recv()
        cred_dict = recv_str.split(":")
        if cred_dict[0] == "admin" and cred_dict[1] == "123456":
            response_str = "congratulation, you have connect with server\r\nnow, you can do something else"
            await websocket.send(response_str)
            return True
        else:
            response_str = "sorry, the username or password is wrong, please submit again"
            await websocket.send(response_str)

async def recv_msg(websocket):
    global speed_set, modeSelect, battery

    while True: 
        response = {
            'status' : 'ok',
            'title' : '',
            'data' : None
        }

        data = ''
        try:
            data = await websocket.recv()
        except (ConnectionClosedOK, ConnectionClosedError) as exc:
            logger.debug({"evt": "ws_connection_closed", "code": getattr(exc, "code", None), "reason": getattr(exc, "reason", None)})
            break
        try:
            data = json.loads(data)
        except Exception as e:
            logger.debug({"evt": "ws_parse_failed", "raw": data})

        if not data:
            continue

        if isinstance(data,str):
            handled_locally = False

            if data == 'get_info':
                response['title'] = 'get_info'
                cpu_temp = info.get_cpu_tempfunc()
                cpu_use = info.get_cpu_use()
                ram_info = info.get_ram_info()
                voltage_str = 'N/A'
                percentage_str = 'N/A'
                voltage_num = None
                percentage_num = None
                charging_value = None
                distance_cm = None
                distance_display = "--"
                distance_status = _distance_monitor_status()
                cached_distance, _cached_ts = _get_distance_snapshot()
                if cached_distance is not None:
                    distance_cm = cached_distance
                    distance_display = f"{distance_cm:.1f}"
                if battery is not None:
                    try:
                        voltage_value = battery.read_voltage()
                        if voltage_value is not None:
                            voltage_num = float(voltage_value)
                            voltage_str = f"{voltage_num:.2f}"
                        percentage_value = battery.read_percentage()
                        if percentage_value is not None:
                            percentage_num = float(percentage_value)
                            percentage_str = f"{int(round(percentage_num))}"
                        charging_value = battery.read_charging()
                    except Exception as exc:
                        logger.warning({"evt": "battery_read_error", "error": str(exc)})
                if distance_cm is None and distance_status == "active":
                    try:
                        dist_measurement = ultra.checkdist()
                        if dist_measurement is not None:
                            distance_cm = max(0.0, float(dist_measurement))
                            distance_display = f"{distance_cm:.1f}"
                            _update_distance_cache(distance_cm)
                    except Exception as exc:
                        logger.debug({"evt": "ultrasonic_read_error", "error": str(exc)})

                gyro_values = ["N/A", "N/A", "N/A"]
                accel_values = ["N/A", "N/A", "N/A"]
                imu_reading = None
                try:
                    imu_reading = imu_sensor.sample()
                except Exception as exc:
                    logger.warning({"evt": "imu_sample_exception", "error": str(exc)})
                if imu_reading and isinstance(imu_reading, dict):
                    gyro_data = imu_reading.get("gyro") or {}
                    gyro_updated = []
                    accel_updated = []
                    for axis in ("x", "y", "z"):
                        try:
                            gyro_updated.append(f"{float(gyro_data.get(axis, 0.0)):.2f}")
                        except Exception:
                            gyro_updated.append("N/A")
                        accel_axis = (imu_reading.get("accel") or {}).get(axis)
                        try:
                            accel_updated.append(f"{float(accel_axis):.3f}")
                        except Exception:
                            accel_updated.append("N/A")
                    if gyro_updated:
                        gyro_values = gyro_updated
                    if accel_updated:
                        accel_values = accel_updated

                response['data'] = [
                    cpu_temp,
                    cpu_use,
                    ram_info,
                    voltage_str,
                    percentage_str,
                    gyro_values[0],
                    gyro_values[1],
                    gyro_values[2],
                    accel_values[0],
                    accel_values[1],
                    accel_values[2],
                ]
                response['gyro'] = {
                    "x": gyro_values[0],
                    "y": gyro_values[1],
                    "z": gyro_values[2],
                }
                response['battery'] = {
                    "voltage": voltage_num,
                    "voltage_display": voltage_str,
                    "percentage": percentage_num,
                    "percentage_display": percentage_str,
                    "charging": charging_value,
                }
                response['accel'] = {
                    "x": accel_values[0],
                    "y": accel_values[1],
                    "z": accel_values[2],
                }
                response['distance'] = {
                    "cm": distance_cm,
                    "display": distance_display,
                    "status": distance_status,
                }
                camera_meta = camera_opencv.get_stream_profile()
                camera_meta["mode"] = _system_mode
                camera_meta["high_quality"] = bool(_camera_high_quality and _system_mode == "ACTIVE")
                response['camera'] = camera_meta
                response['lights'] = lighting.get_status()
                response['mode'] = _system_mode
                handled_locally = True

            elif data.startswith('wsB'):
                try:
                    set_B = data.split()
                    speed_set = int(set_B[1])
                except Exception:
                    logger.debug({"evt": "speed_set_parse_failed", "raw": data})
                handled_locally = True

            # CVFL commands are lightweight camera tweaks; keep them inline.
            elif data == 'CVFL':
                flask_app.modeselect('findlineCV')
                handled_locally = True

            elif data.startswith('CVFLColorSet'):
                try:
                    color = int(data.split()[1])
                    flask_app.camera.colorSet(color)
                except Exception as exc:
                    logger.warning({"evt": "cvfl_color_error", "error": str(exc)})
                handled_locally = True

            elif data.startswith('CVFLL1'):
                try:
                    pos = int(data.split()[1])
                    flask_app.camera.linePosSet_1(pos)
                except Exception as exc:
                    logger.warning({"evt": "cvfl_line1_error", "error": str(exc)})
                handled_locally = True

            elif data.startswith('CVFLL2'):
                try:
                    pos = int(data.split()[1])
                    flask_app.camera.linePosSet_2(pos)
                except Exception as exc:
                    logger.warning({"evt": "cvfl_line2_error", "error": str(exc)})
                handled_locally = True

            elif data.startswith('CVFLSP'):
                try:
                    err = int(data.split()[1])
                    flask_app.camera.errorSet(err)
                except Exception as exc:
                    logger.warning({"evt": "cvfl_err_error", "error": str(exc)})
                handled_locally = True

            if not handled_locally and data:
                _dispatch_hardware_command(data)
                response['status'] = 'queued'


        elif(isinstance(data,dict)):
            if data['title'] == "findColorSet":
                color = data['data']
                flask_app.colorFindSet(color[0],color[1],color[2])

        logger.debug({"evt": "ws_command_processed", "payload": data})
        response = json.dumps(response)
        await websocket.send(response)

async def main_logic(websocket, path):
    try:
        await check_permit(websocket)
        await recv_msg(websocket)
    except ConnectionClosedOK:
        logger.debug({"evt": "ws_session_closed", "code": 1000})
    except ConnectionClosedError as exc:
        logger.info({"evt": "ws_session_error", "code": getattr(exc, "code", None), "reason": getattr(exc, "reason", None)})

def main() -> None:
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format='%(asctime)s %(levelname)s %(message)s',
    )
    logger.info({"evt": "startup", "component": "webServer", "log_level": log_level})

    switch.switchSetup()
    switch.set_all_switch_off()
    
    move.setup()
    HOST = ''
    PORT = 10223                              #Define port serial 
    BUFSIZ = 1024                             #Define buffer size
    ADDR = (HOST, PORT)

    global flask_app, battery
    flask_app = app.webapp()
    flask_app.startthread()

    battery = battery_monitor.BatteryMonitor()
    battery.start()

    buzzer.alert()

    distance_thread = threading.Thread(target=_distance_worker, name="distance_worker", daemon=True)
    distance_thread.start()
    motion_thread = threading.Thread(target=_distance_motion_listener, name="distance_motion", daemon=True)
    motion_thread.start()
    _broadcast_distance_update(_distance_monitor_snapshot().get("last_value"), status=_distance_monitor_status())

    _ensure_mode_initialized()

    idle_thread = threading.Thread(target=_mode_idle_worker, name="mode_idle", daemon=True)
    idle_thread.start()

    while  1:
        wifi_check()
        try:                  #Start server,waiting for client
            start_server = websockets.serve(main_logic, '0.0.0.0', 8888)
            asyncio.get_event_loop().run_until_complete(start_server)
            logger.info({"evt": "ws_server", "status": "waiting"})
            # print('...connected from :', addr)
            break
        except Exception as e:
            logger.error({"evt": "ws_server_error", "error": str(e)})
            lighting.strip_off()

        lighting.set_strip_color((0, 80, 255))
    try:
        asyncio.get_event_loop().run_forever()
    except Exception as e:
        logger.error({"evt": "ws_loop_error", "error": str(e)})
        lighting.strip_off()
        move.destroy()


if __name__ == '__main__':
    main()
