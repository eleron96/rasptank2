"""
Helpers for interacting with the onboard MPU6050 IMU.

The Adeept Robot HAT V3.1 exposes the chip over I2C at address 0x68.
We use the classic register layout and keep the implementation simple so
it works without extra third-party packages besides smbus/smbus2.
"""

import logging
import threading
import time
from typing import Optional, Dict, Any

try:
    from smbus2 import SMBus  # type: ignore
except ImportError:  # pragma: no cover - fallback for systems without smbus2
    try:
        from smbus import SMBus  # type: ignore
    except ImportError:  # pragma: no cover - when running off-target (e.g. macOS)
        SMBus = None  # type: ignore

LOGGER = logging.getLogger("rasptank")

_MPU6050_PRIMARY_ADDRESS = 0x68
_MPU6050_ALTERNATE_ADDRESS = 0x69
_MPU6050_ADDRESSES = (_MPU6050_PRIMARY_ADDRESS, _MPU6050_ALTERNATE_ADDRESS)
_REG_SMPLRT_DIV = 0x19
_REG_CONFIG = 0x1A
_REG_GYRO_CONFIG = 0x1B
_REG_ACCEL_CONFIG = 0x1C
_REG_PWR_MGMT_1 = 0x6B
_REG_ACCEL_XOUT_H = 0x3B

_ACCEL_SCALE = 16384.0  # LSB/g for ±2g
_GYRO_SCALE = 131.0  # LSB/(°/s) for ±250°/s


class MPU6050:
    """Lightweight MPU6050 helper."""

    def __init__(self, bus: int = 1, address: int = _MPU6050_PRIMARY_ADDRESS) -> None:
        if SMBus is None:
            raise RuntimeError("smbus/smbus2 is not available on this system")
        self._bus = SMBus(bus)
        self._address = address
        self._lock = threading.Lock()
        self._initialize()

    def _initialize(self) -> None:
        with self._lock:
            # Wake up the sensor.
            self._bus.write_byte_data(self._address, _REG_PWR_MGMT_1, 0x00)
            # Reasonable defaults for reduced noise.
            self._bus.write_byte_data(self._address, _REG_SMPLRT_DIV, 0x07)
            self._bus.write_byte_data(self._address, _REG_CONFIG, 0x06)
            self._bus.write_byte_data(self._address, _REG_GYRO_CONFIG, 0x00)
            self._bus.write_byte_data(self._address, _REG_ACCEL_CONFIG, 0x00)

    @staticmethod
    def _combine(high: int, low: int) -> int:
        value = (high << 8) | low
        if value & 0x8000:
            value = -((65536 - value) & 0xFFFF)
        return value

    def close(self) -> None:
        try:
            self._bus.close()
        except Exception:  # pragma: no cover - best effort close
            pass

    def sample(self) -> Dict[str, Any]:
        with self._lock:
            block = self._bus.read_i2c_block_data(self._address, _REG_ACCEL_XOUT_H, 14)

        ax = self._combine(block[0], block[1]) / _ACCEL_SCALE
        ay = self._combine(block[2], block[3]) / _ACCEL_SCALE
        az = self._combine(block[4], block[5]) / _ACCEL_SCALE

        raw_temp = self._combine(block[6], block[7])
        temperature = raw_temp / 340.0 + 36.53

        gx = self._combine(block[8], block[9]) / _GYRO_SCALE
        gy = self._combine(block[10], block[11]) / _GYRO_SCALE
        gz = self._combine(block[12], block[13]) / _GYRO_SCALE

        accel_ms2 = {
            "x": ax * 9.80665,
            "y": ay * 9.80665,
            "z": az * 9.80665,
        }
        gyro_rads = {
            "x": gx * (3.141592653589793 / 180.0),
            "y": gy * (3.141592653589793 / 180.0),
            "z": gz * (3.141592653589793 / 180.0),
        }

        return {
            "accel": accel_ms2,
            "gyro": gyro_rads,
            "temperature": temperature,
        }


_sensor: Optional[MPU6050] = None
_sensor_lock = threading.Lock()
_next_retry = 0.0


def _ensure_sensor() -> Optional[MPU6050]:
    global _sensor, _next_retry
    if SMBus is None:
        return None

    now = time.monotonic()
    if _sensor is not None:
        return _sensor
    if now < _next_retry:
        return None

    with _sensor_lock:
        if _sensor is not None:
            return _sensor
        if now < _next_retry:
            return _sensor
        for address in _MPU6050_ADDRESSES:
            try:
                _sensor = MPU6050(address=address)
                LOGGER.info({"evt": "imu_initialized", "address": hex(address)})
                break
            except Exception as exc:  # pragma: no cover - hardware specific
                LOGGER.warning({"evt": "imu_init_failed", "address": hex(address), "error": str(exc)})
                _sensor = None
        if _sensor is None:
            _next_retry = time.monotonic() + 30.0
    return _sensor


def sample() -> Optional[Dict[str, Any]]:
    """Return the latest IMU reading or None when unavailable."""
    global _sensor, _next_retry
    sensor = _ensure_sensor()
    if sensor is None:
        return None
    try:
        return sensor.sample()
    except Exception as exc:  # pragma: no cover - hardware/I2C failures
        LOGGER.warning({"evt": "imu_sample_failed", "error": str(exc)})
        with _sensor_lock:
            if _sensor is sensor:
                sensor.close()
                _sensor = None
                _next_retry = time.monotonic() + 10.0
        return None
