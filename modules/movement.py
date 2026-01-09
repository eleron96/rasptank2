#!/usr/bin/env python3
# coding=utf-8
# File name   : move.py
# Description : Control Motor
# Website     : www.adeept.com
# Author      : Adeept
# Date        : 2025/03/10
import os
import threading
import time

try:
    from core.events import event_bus as _event_bus
except Exception:
    _event_bus = None

try:
    from board import SCL, SDA
    import busio
    from adafruit_pca9685 import PCA9685 as AdafruitPCA9685
    from adafruit_motor import motor as adafruit_motor
    _HAVE_ADAFRUIT = True
except Exception:
    SCL = SDA = None
    busio = None
    AdafruitPCA9685 = None
    adafruit_motor = None
    _HAVE_ADAFRUIT = False

from utils.pca9685_driver import _SMBusPCA9685, announce_driver

MOTOR_M1_IN1 = 15      # Define the positive pole of M1
MOTOR_M1_IN2 = 14      # Define the negative pole of M1
MOTOR_M2_IN1 = 12      # Define the positive pole of M2
MOTOR_M2_IN2 = 13      # Define the negative pole of M2
MOTOR_M3_IN1 = 11      # Define the positive pole of M3
MOTOR_M3_IN2 = 10      # Define the negative pole of M3
MOTOR_M4_IN1 = 8       # Define the positive pole of M4
MOTOR_M4_IN2 = 9       # Define the negative pole of M4

M1_Direction = 1
M2_Direction = 1

left_forward = 1
left_backward = 0

right_forward = 0
right_backward = 1

TL_LEFT_Offset = 10
TL_RIGHT_Offset = 0

pwn_A = 0
pwm_B = 0
FREQ = 50

def _read_env_float(name, default):
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        print(f"Invalid {name}='{value}', using default {default}.")
        return default


def _read_env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "on", "yes")


_MOTOR_RAMP_ENABLED = _read_env_bool("MOTOR_RAMP_ENABLE", True)
_MOTOR_ACCEL_LIMIT = max(0.0, _read_env_float("MOTOR_ACCEL_LIMIT", 200.0))
_MOTOR_RAMP_HZ = max(1.0, _read_env_float("MOTOR_RAMP_HZ", 50.0))
_MOTOR_RAMP_INTERVAL = 1.0 / _MOTOR_RAMP_HZ

motor1 = None
motor2 = None
motor3 = None
motor4 = None
pwm_motor = None
_use_fallback = False

_motor_targets = [0.0, 0.0, 0.0, 0.0]
_motor_currents = [0.0, 0.0, 0.0, 0.0]
_motor_lock = threading.Lock()
_motor_thread = None
_motor_stop_event = threading.Event()


class _FallbackDCMotor:
    """Simple DC motor helper mimicking adafruit_motor.DCMotor.throttle API."""

    def __init__(self, driver, channel_a, channel_b):
        self._driver = driver
        self._channel_a = channel_a
        self._channel_b = channel_b
        self._throttle = 0.0
        self.decay_mode = None

    @property
    def throttle(self):
        return self._throttle

    @throttle.setter
    def throttle(self, value):
        if value is None:
            value = 0.0
        value = max(-1.0, min(1.0, float(value)))
        self._throttle = value
        duty = int(round(abs(value) * 4095))
        if duty <= 0:
            self._driver.set_pwm(self._channel_a, 0, 0)
            self._driver.set_pwm(self._channel_b, 0, 0)
            return
        if value > 0:
            self._driver.set_pwm(self._channel_a, 0, duty)
            self._driver.set_pwm(self._channel_b, 0, 0)
        else:
            self._driver.set_pwm(self._channel_a, 0, 0)
            self._driver.set_pwm(self._channel_b, 0, duty)

    def release(self):
        self.throttle = 0.0


'''
Motor interface.
    xx  _____  xx
       |     |
       |     |
       |     |
    M2 |_____| M1
'''


def map(x, in_min, in_max, out_min, out_max):
    return (x - in_min) / (in_max - in_min) * (out_max - out_min) + out_min


def _clamp_speed_value(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(100.0, value))


def _signed_speed(direction, motor_speed):
    speed = _clamp_speed_value(motor_speed)
    return -speed if direction == -1 else speed


def _apply_motor_output(index, speed):
    throttle = max(-1.0, min(1.0, speed / 100.0))
    if index == 0 and motor1:
        motor1.throttle = throttle
    elif index == 1 and motor2:
        motor2.throttle = throttle
    elif index == 2 and motor3:
        motor3.throttle = throttle
    elif index == 3 and motor4:
        motor4.throttle = throttle


def _set_motor_target(channel, signed_speed):
    idx = channel - 1
    if idx < 0 or idx >= len(_motor_targets):
        return
    with _motor_lock:
        _motor_targets[idx] = max(-100.0, min(100.0, float(signed_speed)))


def _drive_worker():
    last_ts = time.monotonic()
    while not _motor_stop_event.is_set():
        now = time.monotonic()
        dt = now - last_ts
        if dt <= 0:
            dt = _MOTOR_RAMP_INTERVAL
        last_ts = now

        with _motor_lock:
            targets = list(_motor_targets)
            currents = list(_motor_currents)

        if _MOTOR_ACCEL_LIMIT <= 0:
            next_values = targets
        else:
            max_delta = _MOTOR_ACCEL_LIMIT * dt
            next_values = []
            for current, target in zip(currents, targets):
                if target > current + max_delta:
                    next_values.append(current + max_delta)
                elif target < current - max_delta:
                    next_values.append(current - max_delta)
                else:
                    next_values.append(target)

        _ensure_driver()
        for idx, speed in enumerate(next_values):
            speed = max(-100.0, min(100.0, speed))
            _apply_motor_output(idx, speed)
            next_values[idx] = speed

        with _motor_lock:
            for idx, value in enumerate(next_values):
                _motor_currents[idx] = value

        time.sleep(_MOTOR_RAMP_INTERVAL)


def _ensure_drive_worker():
    if not _MOTOR_RAMP_ENABLED:
        return
    global _motor_thread
    if _motor_thread and _motor_thread.is_alive():
        return
    _motor_stop_event.clear()
    _motor_thread = threading.Thread(target=_drive_worker, name="motor_ramp", daemon=True)
    _motor_thread.start()


def _ensure_driver():
    global motor1, motor2, motor3, motor4, pwm_motor, _use_fallback
    if pwm_motor is not None:
        return
    fallback_reason = None
    if _HAVE_ADAFRUIT:
        try:
            i2c = busio.I2C(SCL, SDA)
            pwm = AdafruitPCA9685(i2c, address=0x5f)  # default 0x40
            pwm.frequency = FREQ
            motor1 = adafruit_motor.DCMotor(pwm.channels[MOTOR_M1_IN1], pwm.channels[MOTOR_M1_IN2])
            motor2 = adafruit_motor.DCMotor(pwm.channels[MOTOR_M2_IN1], pwm.channels[MOTOR_M2_IN2])
            motor3 = adafruit_motor.DCMotor(pwm.channels[MOTOR_M3_IN1], pwm.channels[MOTOR_M3_IN2])
            motor4 = adafruit_motor.DCMotor(pwm.channels[MOTOR_M4_IN1], pwm.channels[MOTOR_M4_IN2])
            motor1.decay_mode = adafruit_motor.SLOW_DECAY
            motor2.decay_mode = adafruit_motor.SLOW_DECAY
            motor3.decay_mode = adafruit_motor.SLOW_DECAY
            motor4.decay_mode = adafruit_motor.SLOW_DECAY
            pwm_motor = pwm
            _use_fallback = False
            announce_driver("motors", "adafruit")
            return
        except Exception as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            fallback_reason = exc
    else:
        fallback_reason = Exception("Blinka not available")
    pwm = _SMBusPCA9685(address=0x5f, frequency=FREQ)
    motor1 = _FallbackDCMotor(pwm, MOTOR_M1_IN1, MOTOR_M1_IN2)
    motor2 = _FallbackDCMotor(pwm, MOTOR_M2_IN1, MOTOR_M2_IN2)
    motor3 = _FallbackDCMotor(pwm, MOTOR_M3_IN1, MOTOR_M3_IN2)
    motor4 = _FallbackDCMotor(pwm, MOTOR_M4_IN1, MOTOR_M4_IN2)
    pwm_motor = pwm
    _use_fallback = True
    announce_driver("motors", "smbus", fallback_reason)


def setup():  # Motor initialization
    _ensure_driver()
    if pwm_motor.frequency != FREQ:
        pwm_motor.frequency = FREQ
    _ensure_drive_worker()


def motorStop(immediate=False):  # Motor stops
    if pwm_motor is None:
        return
    if immediate or not _MOTOR_RAMP_ENABLED:
        if motor1:
            motor1.throttle = 0
        if motor2:
            motor2.throttle = 0
        if motor3:
            motor3.throttle = 0
        if motor4:
            motor4.throttle = 0
        with _motor_lock:
            for idx in range(len(_motor_targets)):
                _motor_targets[idx] = 0.0
                _motor_currents[idx] = 0.0
        _publish_motion_event(False)
        return
    _ensure_drive_worker()
    with _motor_lock:
        for idx in range(len(_motor_targets)):
            _motor_targets[idx] = 0.0
    _publish_motion_event(False)


def Motor(channel, direction, motor_speed):
    _ensure_driver()
    signed_speed = _signed_speed(direction, motor_speed)
    if not _MOTOR_RAMP_ENABLED:
        pwm_motor.frequency = FREQ
        _apply_motor_output(channel - 1, signed_speed)
        if 1 <= channel <= len(_motor_targets):
            idx = channel - 1
            with _motor_lock:
                _motor_targets[idx] = signed_speed
                _motor_currents[idx] = signed_speed
        return
    _ensure_drive_worker()
    _set_motor_target(channel, signed_speed)


def move(speed, direction, turn, radius=0.6):   # 0 < radius <= 1
    # eg: move(100, 1, "mid")--->forward
    #     move(100, 1, "left")---> left forward
    # speed:0~100. direction:1. turn: "left", "right", "mid".
    # speed:0~100. direction:-1. turn: "no".
    if speed == 0:
        motorStop()  # all motor stop.
        return
    if direction == 1:           # forward
        if turn == 'left':       # left forward
            Motor(1, -M1_Direction, speed)
            Motor(2, M2_Direction, speed)
        elif turn == 'right':    # right forward
            Motor(1, M1_Direction, speed)
            Motor(2, -M2_Direction, speed)
        else:                    # forward  (mid)
            Motor(1, M1_Direction, speed)
            Motor(2, M2_Direction, speed)
    elif direction == -1:        # backward
        Motor(1, -M1_Direction, speed)
        Motor(2, -M2_Direction, speed)
    _publish_motion_event(True)


def destroy():
    global motor1, motor2, motor3, motor4, pwm_motor, _motor_thread
    motorStop(immediate=True)
    if _motor_thread and _motor_thread.is_alive():
        _motor_stop_event.set()
        _motor_thread.join(timeout=1.0)
    _motor_thread = None
    if pwm_motor:
        try:
            pwm_motor.deinit()
        except AttributeError:
            pass
    motor1 = motor2 = motor3 = motor4 = None
    pwm_motor = None


def trackingMove(speed, direction, turn, radius=0.6):   # 0 < radius <= 1
    if speed == 0:
        motorStop()
        return
    if direction == 1:
        if turn == 'left':
            Motor(1, -M1_Direction, speed + TL_LEFT_Offset)
            Motor(2, 0, speed + TL_RIGHT_Offset)
        elif turn == 'right':
            Motor(1, 0, speed)
            Motor(2, -M2_Direction, speed + TL_RIGHT_Offset)
        else:
            Motor(1, M1_Direction, speed + TL_LEFT_Offset)
            Motor(2, M2_Direction, speed + TL_RIGHT_Offset)
    elif direction == -1:
        Motor(1, -M1_Direction, speed + TL_LEFT_Offset)
        Motor(2, -M2_Direction, speed + TL_RIGHT_Offset)
    _publish_motion_event(True)


def video_Tracking_Move(speed, direction, turn, radius=0):
    if speed == 0:
        motorStop()
        return
    if direction == 1:
        if turn == 'left':
            Motor(1, -M1_Direction, speed)
            Motor(2, M2_Direction, speed * radius)
        elif turn == 'right':
            Motor(1, M1_Direction, speed * radius)
            Motor(2, -M2_Direction, speed)
        else:
            Motor(1, M1_Direction, speed)
            Motor(2, M2_Direction, speed)
    elif direction == -1:
        Motor(1, -M1_Direction, speed)
        Motor(2, -M2_Direction, speed)
    _publish_motion_event(True)


def _publish_motion_event(active: bool) -> None:
    if _event_bus is None:
        return
    try:
        _event_bus.publish("drive_motion", {"active": bool(active)})
    except Exception:
        pass


if __name__ == '__main__':
    try:
        speed_set = 20
        setup()
        move(speed_set, -1, 'mid', 0.8)
        time.sleep(3)
        motorStop()
        time.sleep(1)
        move(speed_set, 1, 'mid', 0.8)
        time.sleep(3)
        motorStop()
    except KeyboardInterrupt:
        destroy()
