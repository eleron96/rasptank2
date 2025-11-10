#!/usr/bin/env python3
# coding=utf-8
# File name   : move.py
# Description : Control Motor
# Website     : www.adeept.com
# Author      : Adeept
# Date        : 2025/03/10
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

motor1 = None
motor2 = None
motor3 = None
motor4 = None
pwm_motor = None
_use_fallback = False


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


def motorStop():  # Motor stops
    if pwm_motor is None:
        return
    if motor1:
        motor1.throttle = 0
    if motor2:
        motor2.throttle = 0
    if motor3:
        motor3.throttle = 0
    if motor4:
        motor4.throttle = 0
    _publish_motion_event(False)


def Motor(channel, direction, motor_speed):
    _ensure_driver()
    if motor_speed > 100:
        motor_speed = 100
    elif motor_speed < 0:
        motor_speed = 0

    speed = map(motor_speed, 0, 100, 0, 1.0)
    pwm_motor.frequency = FREQ
    if direction == -1:
        speed = -speed
    if channel == 1:
        motor1.throttle = speed
    elif channel == 2:
        motor2.throttle = speed
    elif channel == 3:
        motor3.throttle = speed
    elif channel == 4:
        motor4.throttle = speed


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
    global motor1, motor2, motor3, motor4, pwm_motor
    motorStop()
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
