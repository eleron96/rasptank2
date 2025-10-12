#!/usr/bin/env python3
"""Read battery voltage from ADS7830 (Robot HAT V3.1) and map to percentage."""
import json
import os
import threading
import time
from pathlib import Path

from math import isclose

try:
    import board  # type: ignore
    import busio  # type: ignore
except Exception:
    board = None
    busio = None

try:
    import adafruit_ads7830.ads7830 as _ads7830  # type: ignore
    from adafruit_ads7830.analog_in import AnalogIn  # type: ignore
except Exception:
    _ads7830 = None  # type: ignore
    AnalogIn = None  # type: ignore

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
_CHANNEL = int(os.getenv("BATTERY_ADC_CHANNEL", "0"))

_CAL_FILE = Path(
    os.getenv(
        "BATTERY_CAL_FILE",
        os.path.join(os.path.dirname(__file__), "battery_calibration.json"),
    )
)
_VOLT_SCALE = float(os.getenv("BATTERY_VOLT_SCALE", str(_MAX_VOLT)))
_CAL_FACTOR = float(os.getenv("BATTERY_CAL_FACTOR", "1.0"))
_CAL_OFFSET = float(os.getenv("BATTERY_CAL_OFFSET", "0.0"))


def _load_calibration() -> None:
    global _VOLT_SCALE, _CAL_FACTOR, _CAL_OFFSET
    if not _CAL_FILE.is_file():
        return
    try:
        data = json.loads(_CAL_FILE.read_text())
        if "scale" in data:
            _VOLT_SCALE = float(data["scale"])
        if "factor" in data:
            _CAL_FACTOR = float(data["factor"])
        if "offset" in data:
            _CAL_OFFSET = float(data["offset"])
    except Exception as exc:
        print(f"Battery calibration load error: {exc}")


_load_calibration()

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
        self._adc = None
        self._analog_channel = None
        self._raw_full_scale = 65535.0
        self._scale_base = _VOLT_SCALE
        self._cal_factor = _CAL_FACTOR
        self._cal_offset = _CAL_OFFSET
        self._setup()

    def _setup(self):
        if _ads7830 and AnalogIn and board is not None:
            try:
                i2c = None
                try:
                    i2c = board.I2C()  # type: ignore[attr-defined]
                except Exception:
                    if busio:
                        i2c = busio.I2C(board.SCL, board.SDA)  # type: ignore[attr-defined]
                if i2c is not None:
                    # Prefer Adafruit driver when available for higher-resolution readings
                    self._adc = _ads7830.ADS7830(i2c, ADS7830_ADDRESS)
                    self._analog_channel = AnalogIn(self._adc, _CHANNEL)
                    return
            except Exception:
                self._adc = None
                self._analog_channel = None

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
        if self._analog_channel is not None:
            return self._analog_channel.value
        # ADS7830 command byte: 1 0 START A2 A1 A0 PD1 PD0
        cmd = 0x84 | ((_CHANNEL & 0x07) << 4)
        if self._bus is None:
            raise RuntimeError("ADS7830 bus not initialized")
        raw8 = self._bus.read_byte_data(ADS7830_ADDRESS, cmd)
        return raw8 * 257

    def _raw_to_voltage(self, raw: int, calibrated: bool = True) -> float:
        base = (raw / self._raw_full_scale) * self._scale_base
        if calibrated:
            base = base * self._cal_factor + self._cal_offset
        return base

    def sample_voltage(self, calibrated: bool = True, samples: int = 1, delay: float = 0.0) -> float:
        total = 0.0
        count = 0
        for _ in range(max(1, samples)):
            raw = self._read_channel()
            total += self._raw_to_voltage(raw, calibrated=calibrated)
            count += 1
            if delay:
                time.sleep(delay)
        return total / count

    @property
    def scale_base(self) -> float:
        return self._scale_base

    @property
    def cal_factor(self) -> float:
        return self._cal_factor

    @property
    def cal_offset(self) -> float:
        return self._cal_offset

    @property
    def calibration_file(self) -> Path:
        return _CAL_FILE

    def _update(self):
        raw = self._read_channel()
        voltage = self._raw_to_voltage(raw, calibrated=True)
        voltage = round(voltage, 2)
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

    def close(self):
        if self._use_smbus and self._bus is not None:
            close = getattr(self._bus, "close", None)
            if callable(close):
                close()
