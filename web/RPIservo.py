#!/usr/bin/env python3
# File name   : RPiservo.py
# Description : Multi-threaded Control Servos
# Author      : Adeept (with fallback tweaks for Docker on BCM2712)
from __future__ import division
import os
import time
import threading

try:
    from board import SCL, SDA
    import busio
    from adafruit_motor import servo as adafruit_servo
    from adafruit_pca9685 import PCA9685 as AdafruitPCA9685
    _HAVE_ADAFRUIT = True
except Exception:
    SCL = SDA = None
    busio = None
    adafruit_servo = None
    AdafruitPCA9685 = None
    _HAVE_ADAFRUIT = False

from pca9685_driver import _SMBusPCA9685, angle_to_us, announce_driver, us_to_ticks


_PCA9685_DEFAULT_ADDR = 0x5F
_SERVO_RELAX = os.getenv("SERVO_RELAX", "1").strip().lower() in ("1", "true", "on", "yes")
_DEFAULT_FREQUENCY = 50
_PWM_LED_CHANNEL = int(os.getenv("PWM_LED_CHANNEL", "5"))  # dedicated LED channel (0-based)


def get_default_i2c_address():
    return _PCA9685_DEFAULT_ADDR


def _read_pca_address():
    env_val = os.getenv("PCA9685_ADDR")
    if not env_val:
        return _PCA9685_DEFAULT_ADDR
    env_val = env_val.strip().lower()
    base = 16 if env_val.startswith("0x") else 10
    try:
        return int(env_val, base)
    except ValueError:
        print(f"Некорректное значение PCA9685_ADDR='{env_val}', используем адрес по умолчанию.")
        return _PCA9685_DEFAULT_ADDR


PCA9685_ADDRESS = _read_pca_address()
print(f"PCA9685 address: 0x{PCA9685_ADDRESS:02x}")

init_pwm0 = 90
init_pwm1 = 90
init_pwm2 = 90
init_pwm3 = 90

init_pwm4 = 90
init_pwm5 = 90
init_pwm6 = 90
init_pwm7 = 90

servo_num = 8


class ServoCtrl(threading.Thread):

    def __init__(self, *args, **kwargs):
        self._frequency = _DEFAULT_FREQUENCY
        self._servo_min_pulse_us = 500
        self._servo_max_pulse_us = 2400
        self._use_fallback = False
        self._servo_channels = []

        # Defer I2C setup until the first command so imports in Docker on BCM2712 do not crash.
        self.pwm_servo = None
        self._health_checked = False
        self._driver_context = "servos"

        self.sc_direction = [1,1,1,1, 1,1,1,1]
        self.initPos = [init_pwm0,init_pwm1,init_pwm2,init_pwm3,
                        init_pwm4,init_pwm5,init_pwm6,init_pwm7]
        self.goalPos = [90,90,90,90, 90,90,90,90]
        self.nowPos  = [90,90,90,90, 90,90,90,90]
        self.bufferPos  = [90.0,90.0,90.0,90.0, 90.0,90.0,90.0,90.0]
        self.lastPos = [90,90,90,90, 90,90,90,90]
        self.ingGoal = [90,90,90,90, 90,90,90,90]
        self.maxPos  = [180,180,180,180, 180,180,180,180]
        self.minPos  = [0,0,0,0, 0,0,0,0]
        self.scSpeed = [0,0,0,0, 0,0,0,0]
        self.ctrlRangeMax = 180
        self.ctrlRangeMin = 0
        self.angleRange = 180

        self.scMode = 'auto'
        self.scTime = 2.0
        self.scSteps = 30

        self.scDelay = 0.09
        self.scMoveTime = 0.09

        self.goalUpdate = 0
        self.wiggleID = 0
        self.wiggleDirection = 1

        super(ServoCtrl, self).__init__(*args, **kwargs)
        self.__flag = threading.Event()
        self.__flag.clear()

    def _ensure_driver(self):
        if self.pwm_servo is not None:
            return
        fallback_reason = None
        if _HAVE_ADAFRUIT:
            try:
                i2c = busio.I2C(SCL, SDA)
                pwm = AdafruitPCA9685(i2c, address=PCA9685_ADDRESS)
                pwm.frequency = self._frequency
                channels = []
                for channel in range(servo_num):
                    if channel == _PWM_LED_CHANNEL:
                        channels.append(None)
                        continue
                    channels.append(
                        adafruit_servo.Servo(
                            pwm.channels[channel],
                            min_pulse=self._servo_min_pulse_us,
                            max_pulse=self._servo_max_pulse_us,
                            actuation_range=180,
                        )
                    )
                self._servo_channels = channels
                self.pwm_servo = pwm
                self._use_fallback = False
                announce_driver(self._driver_context, "adafruit")
                self._run_health_check()
                return
            except Exception as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                fallback_reason = exc
        else:
            fallback_reason = Exception("Blinka not available")
        self._init_fallback(fallback_reason)
        self._run_health_check()

    def _init_fallback(self, reason=None):
        self._use_fallback = True
        self._servo_channels = [None] * servo_num
        try:
            self.pwm_servo = _SMBusPCA9685(addr=PCA9685_ADDRESS, freq=self._frequency)
        except RuntimeError as exc:
            raise RuntimeError("Unable to initialize PCA9685 using smbus fallback: %s" % exc) from exc
        announce_driver(self._driver_context, "smbus", reason)

    def _release_channel(self, channel):
        self.relax(channel)

    def set_angle(self, ID, angle):
        self._ensure_driver()
        if ID == _PWM_LED_CHANNEL:
            return
        angle = max(self.ctrlRangeMin, min(self.ctrlRangeMax, angle))
        if not self._use_fallback:
            channel_obj = self._servo_channels[ID]
            if channel_obj is None:
                return
            channel_obj.angle = angle
            return
        pulse_us = angle_to_us(angle, self._servo_min_pulse_us, self._servo_max_pulse_us)
        ticks = us_to_ticks(pulse_us, self._frequency)
        self.pwm_servo.set_pwm(ID, 0, ticks)

    def pause(self):
        print('......................pause..........................')
        self.__flag.clear()
        if _SERVO_RELAX:
            self.relax()

    def resume(self):
        print('resume')
        self.__flag.set()

    def relax(self, ch=None):
        if self.pwm_servo is None:
            return
        if ch is None:
            channels = range(servo_num)
        else:
            channels = [ch]
        if self._use_fallback:
            for idx in channels:
                if idx == _PWM_LED_CHANNEL:
                    continue
                self.pwm_servo.set_pwm(idx, 0, 0)
        else:
            for idx in channels:
                if idx == _PWM_LED_CHANNEL:
                    continue
                try:
                    channel_obj = self.pwm_servo.channels[idx]
                    if channel_obj is None:
                        continue
                    channel_obj.duty_cycle = 0
                except AttributeError:
                    self.pwm_servo.set_pwm(idx, 0, 0)

    def _run_health_check(self):
        if self._health_checked or self.pwm_servo is None:
            return
        try:
            mid_us = angle_to_us(90, self._servo_min_pulse_us, self._servo_max_pulse_us)
            ticks = us_to_ticks(mid_us, self._frequency)
            if self._use_fallback:
                self.pwm_servo.set_pwm_freq(self._frequency)
                self.pwm_servo.set_pwm(0, 0, ticks)
            else:
                self.pwm_servo.frequency = self._frequency
                if self._servo_channels:
                    self._servo_channels[0].angle = 90
                else:
                    try:
                        duty = int(round(ticks / 4096 * 0xFFFF))
                        self.pwm_servo.channels[0].duty_cycle = duty
                    except Exception:
                        pass
            time.sleep(0.02)
        except Exception as exc:
            print(f"Servo health check failed: {exc}")
        finally:
            self.relax(0)
            self._health_checked = True

    def moveInit(self):
        self.scMode = 'init'
        for i in range(0, servo_num):
            self.set_angle(i, self.initPos[i])
            self.lastPos[i] = self.initPos[i]
            self.nowPos[i] = self.initPos[i]
            self.bufferPos[i] = float(self.initPos[i])
            self.goalPos[i] = self.initPos[i]
        self.pause()

    def initConfig(self, ID, initInput, moveTo):
        if initInput > self.minPos[ID] and initInput < self.maxPos[ID]:
            self.initPos[ID] = initInput
            if moveTo:
                self.set_angle(ID, self.initPos[ID])
        else:
            print('initPos Value Error.')

    def moveServoInit(self, ID):
        self.scMode = 'init'
        for i in range(0, len(ID)):
            self.set_angle(ID[i], self.initPos[ID[i]])
            self.lastPos[ID[i]] = self.initPos[ID[i]]
            self.nowPos[ID[i]] = self.initPos[ID[i]]
            self.bufferPos[ID[i]] = float(self.initPos[ID[i]])
            self.goalPos[ID[i]] = self.initPos[ID[i]]
        self.pause()

    def posUpdate(self):
        self.goalUpdate = 1
        for i in range(0, servo_num):
            self.lastPos[i] = self.nowPos[i]
        self.goalUpdate = 0

    def returnServoAngle(self, ID):
        return self.nowPos[ID]
    
    def set_direction(self, ID, direction):
        if ID < 0 or ID >= servo_num:
            raise ValueError(f"Servo index {ID} out of range 0-{servo_num-1}")
        self.sc_direction[ID] = 1 if direction >= 0 else -1

    def speedUpdate(self, IDinput, speedInput):
        for i in range(0, len(IDinput)):
            self.scSpeed[IDinput[i]] = speedInput[i]

    def moveAuto(self):
        for i in range(0, servo_num):
            self.ingGoal[i] = self.goalPos[i]

        for i in range(0, self.scSteps):
            for dc in range(0, servo_num):
                if not self.goalUpdate:
                    self.nowPos[dc] = int(round((self.lastPos[dc] + (((self.goalPos[dc] - self.lastPos[dc]) / self.scSteps) * (i + 1))), 0))
                    self.set_angle(dc, self.nowPos[dc])

                if self.ingGoal != self.goalPos:
                    self.posUpdate()
                    time.sleep(self.scTime / self.scSteps)
                    return 1
            time.sleep((self.scTime / self.scSteps - self.scMoveTime))

        self.posUpdate()
        self.pause()
        return 0

    def moveCert(self):
        for i in range(0, servo_num):
            self.ingGoal[i] = self.goalPos[i]
            self.bufferPos[i] = self.lastPos[i]

        while self.nowPos != self.goalPos:
            for i in range(0, servo_num):
                if self.lastPos[i] < self.goalPos[i]:
                    self.bufferPos[i] += self.pwmGenOut(self.scSpeed[i]) / (1 / self.scDelay)
                    newNow = int(round(self.bufferPos[i], 0))
                    if newNow > self.goalPos[i]:
                        newNow = self.goalPos[i]
                    self.nowPos[i] = newNow
                elif self.lastPos[i] > self.goalPos[i]:
                    self.bufferPos[i] -= self.pwmGenOut(self.scSpeed[i]) / (1 / self.scDelay)
                    newNow = int(round(self.bufferPos[i], 0))
                    if newNow < self.goalPos[i]:
                        newNow = self.goalPos[i]
                    self.nowPos[i] = newNow

                if not self.goalUpdate:
                    self.set_angle(i, self.nowPos[i])

                if self.ingGoal != self.goalPos:
                    self.posUpdate()
                    return 1
            self.posUpdate()
            time.sleep(self.scDelay - self.scMoveTime)
        else:
            self.pause()
            return 0

    def pwmGenOut(self, angleInput):
        return int(round(((self.ctrlRangeMax - self.ctrlRangeMin) / self.angleRange * angleInput), 0))

    def setAutoTime(self, autoSpeedSet):
        self.scTime = autoSpeedSet

    def setDelay(self, delaySet):
        self.scDelay = delaySet

    def autoSpeed(self, ID, angleInput):
        self.scMode = 'auto'
        self.goalUpdate = 1
        for i in range(0, len(ID)):
            newGoal = self.initPos[ID[i]] + self.pwmGenOut(angleInput[i]) * self.sc_direction[ID[i]]
            if newGoal > self.maxPos[ID[i]]:
                newGoal = self.maxPos[ID[i]]
            elif newGoal < self.minPos[ID[i]]:
                newGoal = self.minPos[ID[i]]
            self.goalPos[ID[i]] = newGoal
        self.goalUpdate = 0
        self.resume()

    def certSpeed(self, ID, angleInput, speedSet):
        self.scMode = 'certain'
        self.goalUpdate = 1
        for i in range(0, len(ID)):
            newGoal = self.initPos[ID[i]] + self.pwmGenOut(angleInput[i]) * self.sc_direction[ID[i]]
            if newGoal > self.maxPos[ID[i]]:
                newGoal = self.maxPos[ID[i]]
            elif newGoal < self.minPos[ID[i]]:
                newGoal = self.minPos[ID[i]]
            self.goalPos[ID[i]] = newGoal
        self.speedUpdate(ID, speedSet)
        self.goalUpdate = 0
        self.resume()

    def moveWiggle(self):
        self.bufferPos[self.wiggleID] += self.wiggleDirection * self.sc_direction[self.wiggleID] * self.pwmGenOut(self.scSpeed[self.wiggleID]) / (1 / self.scDelay)
        newNow = int(round(self.bufferPos[self.wiggleID], 0))
        if self.bufferPos[self.wiggleID] > self.maxPos[self.wiggleID]:
            self.bufferPos[self.wiggleID] = self.maxPos[self.wiggleID]
        elif self.bufferPos[self.wiggleID] < self.minPos[self.wiggleID]:
            self.bufferPos[self.wiggleID] = self.minPos[self.wiggleID]
        self.nowPos[self.wiggleID] = newNow
        self.lastPos[self.wiggleID] = newNow
        if self.bufferPos[self.wiggleID] < self.maxPos[self.wiggleID] and self.bufferPos[self.wiggleID] > self.minPos[self.wiggleID]:
            self.set_angle(self.wiggleID, self.nowPos[self.wiggleID])
        else:
            self.stopWiggle()
        time.sleep(self.scDelay - self.scMoveTime)

    def stopWiggle(self):
        self.pause()
        self.posUpdate()
        if _SERVO_RELAX:
            self._release_channel(self.wiggleID)

    def singleServo(self, ID, direcInput, speedSet):
        self.wiggleID = ID
        self.wiggleDirection = direcInput
        self.scSpeed[ID] = speedSet
        self.scMode = 'wiggle'
        self.posUpdate()
        self.resume()

    def moveAngle(self, ID, angleInput):
        self.nowPos[ID] = int(self.initPos[ID] + self.sc_direction[ID] * self.pwmGenOut(angleInput))
        if self.nowPos[ID] > self.maxPos[ID]:
            self.nowPos[ID] = self.maxPos[ID]
        elif self.nowPos[ID] < self.minPos[ID]:
            self.nowPos[ID] = self.minPos[ID]
        self.lastPos[ID] = self.nowPos[ID]
        self.set_angle(ID, self.nowPos[ID])

    def scMove(self):
        if self.scMode == 'init':
            self.moveInit()
        elif self.scMode == 'auto':
            self.moveAuto()
        elif self.scMode == 'certain':
            self.moveCert()
        elif self.scMode == 'wiggle':
            self.moveWiggle()

    def setPWM(self, ID, PWM_input):
        if ID == _PWM_LED_CHANNEL:
            return
        self.lastPos[ID] = PWM_input
        self.nowPos[ID] = PWM_input
        self.bufferPos[ID] = float(PWM_input)
        self.goalPos[ID] = PWM_input
        self.set_angle(ID, PWM_input)
        self.pause()
        if _SERVO_RELAX:
            self._release_channel(ID)

    def run(self):
        while 1:
            self.__flag.wait()
            self.scMove()
            pass


if __name__ == '__main__':
    scGear = ServoCtrl()
    scGear.moveInit()
    sc = ServoCtrl()
    sc.start()
