#!/usr/bin/env python3
"""Utility to drive an LED on a PCA9685 servo channel."""
import os

from pca9685_driver import _SMBusPCA9685, announce_driver

try:
    from board import SCL, SDA
    import busio
    from adafruit_pca9685 import PCA9685 as AdafruitPCA9685
    _HAVE_ADAFRUIT = True
except Exception:  # pragma: no cover - executed on systems without Blinka
    SCL = SDA = None
    busio = None
    AdafruitPCA9685 = None
    _HAVE_ADAFRUIT = False


_CHANNEL = int(os.getenv("PWM_LED_CHANNEL", "5"))  # Servo port #6 (0-based index)
_FREQUENCY = int(os.getenv("PWM_LED_FREQ", "50"))


class _PwmLed:
    def __init__(self):
        self._pca = None
        self._use_fallback = False

    def _ensure_driver(self):
        if self._pca is not None:
            return
        reason = None
        if _HAVE_ADAFRUIT:
            try:
                i2c = busio.I2C(SCL, SDA)
                pca = AdafruitPCA9685(i2c, address=0x5F)
                pca.frequency = _FREQUENCY
                self._pca = pca
                self._use_fallback = False
                announce_driver("led", "adafruit")
                return
            except Exception as exc:  # pragma: no cover
                reason = exc
        else:
            reason = Exception("Blinka unavailable")
        self._pca = _SMBusPCA9685(addr=0x5F, freq=_FREQUENCY)
        self._use_fallback = True
        announce_driver("led", "smbus", reason)

    def turn_on(self):
        self._ensure_driver()
        if self._use_fallback:
            # Force output LOW (LED between V+ and SIG turns on)
            self._pca.set_pwm(_CHANNEL, 0, 0)
        else:
            self._pca.channels[_CHANNEL].duty_cycle = 0

    def turn_off(self):
        self._ensure_driver()
        if self._use_fallback:
            # Force output HIGH (LED off)
            self._pca.set_pwm(_CHANNEL, 0, 4096)
        else:
            self._pca.channels[_CHANNEL].duty_cycle = 0xFFFF


_LED = _PwmLed()


def turn_on():
    _LED.turn_on()


def turn_off():
    _LED.turn_off()
