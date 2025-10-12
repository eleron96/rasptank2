#!/usr/bin/env python3
"""Read battery voltage from ADS7830 (Robot HAT V3.1) and map to percentage."""
import os
import threading
import time

from math import isclose

try:
    import board  # type: ignore
    import busio  # type: ignore
except Exception:
    board = None
    busio = None

try:
    from smbus2 import SMBus  # type: ignore
except ImportError:
    try:
        from smbus import SMBus  # type: ignore
    except ImportError:
        SMBus = None  # type: ignore

ADS7830_ADDRESS = 0x48

_MIN_VOLT = float(os.getenv("BATTERY_VOLT_MIN", "6.0"))
_MAX_VOLT = float(os.getenv("BATTERY_VOLT_MAX", "8.4"))
_CHANNEL = int(os.getenv("BATTERY_ADC_CHANNEL", "7"))

def _to_percentage(voltage: float) -> int:
    if isclose(_MAX_VOLT, _MIN_VOLT):
        return 0
    pct = (voltage - _MIN_VOLT) / (_MAX_VOLT - _MIN_VOLT) * 100.0
    return max(0, min(100, int(round(pct))))

class BatteryMonitor(threading.Thread):
    def __init__(self, interval: float = 5.0):
        super().__init__(daemon=True)
        self._interval = interval
        self._voltage = 0.0
        self._percentage = 0
        self._lock = threading.Lock()
        self._running = threading.Event()
        self._running.set()
        self._bus = None
        self._use_smbus = False
        self._setup()

    def _setup(self):
        if SMBus is not None:
            self._bus = SMBus(1)
            self._use_smbus = True
        elif board and busio:
            i2c = busio.I2C(board.SCL, board.SDA)
            # simple wrapper to match SMBus API
            class _I2CProxy:
                def __init__(self, i2c):
                    self._i2c = i2c
                def read_byte_data(self, addr, cmd):
                    out = bytearray(1)
                    self._i2c.writeto(addr, bytes([cmd]))
                    self._i2c.readfrom_into(addr, out)
                    return out[0]
            self._bus = _I2CProxy(i2c)
        else:
            raise RuntimeError("No SMBus or busio available for ADS7830")

    def read_voltage(self) -> float:
        with self._lock:
            return self._voltage

    def read_percentage(self) -> int:
        with self._lock:
            return self._percentage

    def _read_channel(self) -> int:
        # ADS7830 command byte: 1 0 START A2 A1 A0 PD1 PD0
        cmd = 0x84 | ((_CHANNEL & 0x07) << 4)
        return self._bus.read_byte_data(ADS7830_ADDRESS, cmd)

    def _update(self):
        raw = self._read_channel()
        # Map 8-bit value (0-255) to voltage, using default full-scale 8.4V
        voltage = (raw / 255.0) * _MAX_VOLT
        percentage = _to_percentage(voltage)
        with self._lock:
            self._voltage = voltage
            self._percentage = percentage

    def run(self):
        while self._running.is_set():
            try:
                self._update()
            except Exception as exc:
                print(f"BatteryMonitor error: {exc}")
            time.sleep(self._interval)

    def stop(self):
        self._running.clear()
