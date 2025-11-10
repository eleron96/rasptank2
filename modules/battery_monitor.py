#!/usr/bin/env python3
"""Read battery voltage from ADS7830 (Robot HAT V3.1) and map to percentage."""
import json
import os
import threading
import time
import weakref
from pathlib import Path
import logging

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

_MIN_VOLT = float(os.getenv("BATTERY_VOLT_MIN", "6.8"))
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

_DEFAULT_CAL = {
    "scale": _VOLT_SCALE,
    "factor": _CAL_FACTOR,
    "offset": _CAL_OFFSET,
    "min_voltage": _MIN_VOLT,
    "max_voltage": _MAX_VOLT,
}
_CAL_LOCK = threading.Lock()
# Track live monitor instances so calibration changes propagate immediately.
_ACTIVE_MONITORS = weakref.WeakSet()
try:
    from core.events import event_bus
except Exception:
    event_bus = None

logger = logging.getLogger("rasptank")


def _save_calibration(data: dict) -> None:
    try:
        with _CAL_LOCK:
            _CAL_FILE.write_text(json.dumps(data, indent=2))
    except Exception as exc:
        logger.error({"evt": "battery_calibration_save_error", "error": str(exc)})


def _load_calibration() -> None:
    global _VOLT_SCALE, _CAL_FACTOR, _CAL_OFFSET, _MIN_VOLT, _MAX_VOLT
    if not _CAL_FILE.is_file():
        _save_calibration(_DEFAULT_CAL)
        return
    try:
        data = json.loads(_CAL_FILE.read_text())
        if "scale" in data:
            _VOLT_SCALE = float(data["scale"])
        if "factor" in data:
            _CAL_FACTOR = float(data["factor"])
        if "offset" in data:
            _CAL_OFFSET = float(data["offset"])
        if "min_voltage" in data:
            _MIN_VOLT = float(data["min_voltage"])
        if "max_voltage" in data:
            _MAX_VOLT = float(data["max_voltage"])
    except Exception as exc:
        logger.error({"evt": "battery_calibration_load_error", "error": str(exc)})


_load_calibration()


def get_calibration() -> dict:
    return {
        "scale": _VOLT_SCALE,
        "factor": _CAL_FACTOR,
        "offset": _CAL_OFFSET,
        "min_voltage": _MIN_VOLT,
        "max_voltage": _MAX_VOLT,
    }


def _apply_calibration_to_all(scale: float, factor: float, offset: float) -> dict:
    global _VOLT_SCALE, _CAL_FACTOR, _CAL_OFFSET, _MAX_VOLT
    _VOLT_SCALE = float(scale)
    _MAX_VOLT = float(scale)
    _CAL_FACTOR = float(factor)
    _CAL_OFFSET = float(offset)
    data = get_calibration()
    _save_calibration(data)
    for monitor in list(_ACTIVE_MONITORS):
        try:
            monitor.update_calibration(_VOLT_SCALE, _CAL_FACTOR, _CAL_OFFSET)
        except Exception as exc:
            logger.warning({"evt": "battery_monitor_update_error", "error": str(exc)})
    return data


def _get_active_monitor():
    for monitor in list(_ACTIVE_MONITORS):
        return monitor
    return None


def sample_status(samples: int = 5, delay: float = 0.05) -> dict:
    monitor = _get_active_monitor()
    created = False
    if monitor is None:
        monitor = BatteryMonitor(interval=0.0)
        created = True
    try:
        raw = monitor.sample_voltage(calibrated=False, samples=samples, delay=delay)
        calibrated = monitor.sample_voltage(calibrated=True, samples=samples, delay=delay)
        return {
            "raw_voltage": raw,
            "voltage": calibrated,
        }
    finally:
        if created:
            monitor.close()


def calibrate_to_voltage(actual_voltage: float, samples: int = 20, delay: float = 0.05) -> dict:
    if actual_voltage <= 0:
        raise ValueError("actual_voltage must be positive")
    monitor = _get_active_monitor()
    created = False
    if monitor is None:
        monitor = BatteryMonitor(interval=0.0)
        created = True
    try:
        raw = monitor.sample_voltage(calibrated=False, samples=samples, delay=delay)
        if raw <= 0:
            raise RuntimeError("Unable to read battery voltage for calibration")
        factor = actual_voltage / raw
        data = _apply_calibration_to_all(monitor.scale_base, factor, monitor.cal_offset)
        data.update({"actual_voltage": actual_voltage, "raw_voltage": raw})
        if event_bus:
            event_bus.publish("battery_calibration", data.copy())
        return data
    finally:
        if created:
            monitor.close()


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
        self._last_raw = 0.0
        self._setup()
        _ACTIVE_MONITORS.add(self)

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

    def update_calibration(self, scale: float, factor: float, offset: float) -> None:
        with self._lock:
            self._scale_base = float(scale)
            self._cal_factor = float(factor)
            self._cal_offset = float(offset)

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
        raw_voltage = round(self._raw_to_voltage(raw, calibrated=False), 2)
        percentage = _to_percentage(voltage)
        changed = False
        with self._lock:
            if (
                not isclose(self._voltage, voltage, abs_tol=0.01)
                or not isclose(getattr(self, "_last_raw", raw_voltage), raw_voltage, abs_tol=0.01)
                or self._percentage != percentage
            ):
                changed = True
            self._voltage = voltage
            self._percentage = percentage
            self._last_raw = raw_voltage
        if changed and event_bus:
            event_bus.publish(
                "battery_status",
                {
                    "voltage": voltage,
                    "raw_voltage": raw_voltage,
                    "percentage": percentage,
                },
            )

    def run(self):
        while self._running.is_set():
            try:
                self._update()
            except Exception as exc:
                logger.error({"evt": "battery_monitor_error", "error": str(exc)})
            time.sleep(self._interval)

    def stop(self):
        self._running.clear()
        _ACTIVE_MONITORS.discard(self)

    def close(self):
        if self._use_smbus and self._bus is not None:
            close = getattr(self._bus, "close", None)
            if callable(close):
                close()
        _ACTIVE_MONITORS.discard(self)
