#!/usr/bin/env python3
"""
Helpers for working with the PCA9685 controller across BlinkA and raw smbus.
"""
from __future__ import annotations

import time
from typing import Optional

try:
    from smbus2 import SMBus  # type: ignore
except ImportError:
    try:
        from smbus import SMBus  # type: ignore
    except ImportError:
        SMBus = None  # type: ignore

__all__ = [
    "_SMBusPCA9685",
    "angle_to_us",
    "announce_driver",
    "us_to_ticks",
]


def angle_to_us(angle: float, min_us: int = 500, max_us: int = 2400) -> int:
    """Clamp angle to 0..180 and convert to pulse width in microseconds."""
    angle = max(0.0, min(180.0, float(angle)))
    return int(round(min_us + (max_us - min_us) * (angle / 180.0)))


def us_to_ticks(us: float, freq: int = 50) -> int:
    """Convert pulse width (µs) to PCA9685 ticks for the given frequency."""
    ticks = int(round(us * freq * 4096 / 1_000_000))
    return max(0, min(4095, ticks))


_ANNOUNCED = {}


def announce_driver(context: str, driver: str, reason: Optional[Exception] = None) -> None:
    """
    Print a one-off message describing which backend is used.

    context: short label, e.g. "servos" or "motors".
    driver:  "adafruit" | "smbus".
    """
    key = f"{context}:{driver}"
    if key in _ANNOUNCED:
        return
    if driver == "adafruit":
        print(f"Using Adafruit/Blinka PCA9685 driver for {context}")
    else:
        msg = f"Fallback to smbus PCA9685 driver for {context}"
        if reason:
            msg += f": {reason}"
        print(msg)
    _ANNOUNCED[key] = True


class _SMBusPCA9685:
    """Minimal PCA9685 driver using smbus to avoid Blinka dependency."""

    MODE1 = 0x00
    MODE2 = 0x01
    PRESCALE = 0xFE
    LED0_ON_L = 0x06
    ALL_LED_ON_L = 0xFA
    ALL_LED_OFF_L = 0xFC
    RESTART = 0x80
    SLEEP = 0x10
    ALLCALL = 0x01
    OUTDRV = 0x04

    def __init__(self, bus: int = 1, addr: int = 0x5F, freq: int = 50):
        if SMBus is None:
            raise RuntimeError("I2C fallback requires smbus or smbus2 to be installed.")
        self._bus = SMBus(bus)
        self.address = addr
        self._frequency = None  # type: Optional[int]
        self.set_pwm_freq(freq)

    @property
    def frequency(self) -> Optional[int]:
        return self._frequency

    @frequency.setter
    def frequency(self, value: int) -> None:
        self.set_pwm_freq(value)

    def set_pwm_freq(self, freq: int) -> None:
        if freq <= 0:
            raise ValueError("Frequency must be positive.")
        prescale = int(round(25_000_000 / 4096 / freq - 1))
        # Go to sleep, set prescale, then wake and restart.
        self._write8(self.MODE1, self.SLEEP | self.ALLCALL)
        time.sleep(0.005)
        self._write8(self.PRESCALE, prescale)
        self._write8(self.MODE1, self.ALLCALL)
        time.sleep(0.005)
        self._write8(self.MODE1, self.ALLCALL | self.RESTART)
        self._write8(self.MODE2, self.OUTDRV)
        self._frequency = freq

    def set_pwm(self, channel: int, on: int, off: int) -> None:
        reg = self.LED0_ON_L + 4 * channel
        data = [on & 0xFF, on >> 8, off & 0xFF, off >> 8]
        self._bus.write_i2c_block_data(self.address, reg, data)

    def all_off(self) -> None:
        self._bus.write_i2c_block_data(self.address, self.ALL_LED_ON_L, [0, 0, 0, 0])
        self._bus.write_i2c_block_data(self.address, self.ALL_LED_OFF_L, [0, 0, 0, 0])

    def deinit(self) -> None:
        try:
            self.all_off()
        finally:
            try:
                self._bus.close()
            except Exception:
                pass

    def _write8(self, reg: int, value: int) -> None:
        self._bus.write_byte_data(self.address, reg, value)
