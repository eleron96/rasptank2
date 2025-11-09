#!/usr/bin/python3
# File name   : Ultrasonic.py
# Description : Detection distance and tracking with ultrasonic
# Website     : www.adeept.com
# Author      : Adeept (refined for Docker/Pi 5)
# Date        : 2024/03/10

import atexit
import logging
import math
import threading
import time
import warnings
from typing import Optional

logger = logging.getLogger("rasptank.ultra")

try:  # pragma: no cover - requires Raspberry Pi GPIO hardware
    import RPi.GPIO as GPIO
except (RuntimeError, ImportError) as exc:
    GPIO = None
    logger.debug({"evt": "ultra_gpio_import_failed", "error": str(exc)})

try:  # pragma: no cover - optional dependency
    from gpiozero import DistanceSensor
    try:
        from gpiozero.input_devices import PWMSoftwareFallback  # type: ignore
    except Exception:  # pragma: no cover - optional
        PWMSoftwareFallback = None
    else:  # pragma: no cover - optional, runtime-only
        warnings.filterwarnings("ignore", category=PWMSoftwareFallback)
except Exception as exc:  # pragma: no cover - optional dependency
    DistanceSensor = None
    logger.debug({"evt": "ultra_gpiozero_import_failed", "error": str(exc)})

TRIG_PIN = 23
ECHO_PIN = 24
_GPIO_INIT_LOCK = threading.Lock()
_GPIO_INITIALIZED = False
_GPIO_DISABLED = False

_GPIOZERO_SENSOR = None
_GPIOZERO_LOCK = threading.Lock()
_GPIOZERO_DISABLED = False


def _setup_gpio() -> bool:
    global _GPIO_INITIALIZED, _GPIO_DISABLED
    if GPIO is None or _GPIO_DISABLED:
        return False
    if _GPIO_INITIALIZED:
        return True
    with _GPIO_INIT_LOCK:
        if _GPIO_INITIALIZED:
            return True
        try:
            GPIO.setwarnings(False)
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(TRIG_PIN, GPIO.OUT)
            GPIO.setup(ECHO_PIN, GPIO.IN)
            GPIO.output(TRIG_PIN, False)
            _GPIO_INITIALIZED = True
        except Exception as exc:
            _GPIO_DISABLED = True
            error_text = str(exc)
            log_method = logger.warning
            expected_patterns = (
                "peripheral base address",
                "Permission denied",
                "No such file or directory",
                "operation not permitted",
            )
            if any(pattern.lower() in error_text.lower() for pattern in expected_patterns):
                log_method = logger.info
            log_method({"evt": "ultra_gpio_setup_failed", "error": error_text})
            return False
    return True


def _measure_pulse(timeout_s: float = 0.03) -> Optional[float]:
    if not _setup_gpio():
        return None

    # send 10us trigger pulse
    GPIO.output(TRIG_PIN, True)
    time.sleep(0.00001)
    GPIO.output(TRIG_PIN, False)

    start = time.perf_counter()
    timeout = start + timeout_s
    while GPIO.input(ECHO_PIN) == 0:
        start = time.perf_counter()
        if start >= timeout:
            return None

    stop = time.perf_counter()
    timeout = stop + timeout_s
    while GPIO.input(ECHO_PIN) == 1:
        stop = time.perf_counter()
        if stop >= timeout:
            return None

    return stop - start


def _initialize_gpiozero() -> bool:
    global _GPIOZERO_SENSOR, _GPIOZERO_DISABLED
    if DistanceSensor is None or _GPIOZERO_DISABLED:
        return False
    if _GPIOZERO_SENSOR is not None:
        return True
    with _GPIOZERO_LOCK:
        if _GPIOZERO_SENSOR is not None:
            return True
        try:
            sensor = DistanceSensor(echo=ECHO_PIN, trigger=TRIG_PIN, max_distance=2.0, queue_len=3)
            _GPIOZERO_SENSOR = sensor
        except Exception as exc:
            _GPIOZERO_DISABLED = True
            logger.warning({"evt": "ultra_gpiozero_init_failed", "error": str(exc)})
            return False
    return True


def _measure_gpiozero_distance() -> Optional[float]:
    if not _initialize_gpiozero():
        return None
    sensor = _GPIOZERO_SENSOR
    if sensor is None:
        return None
    try:
        distance_m = sensor.distance
    except Exception as exc:
        logger.warning({"evt": "ultra_gpiozero_read_failed", "error": str(exc)})
        return None
    if distance_m is None or not math.isfinite(distance_m):
        return None
    return distance_m


def checkdist() -> Optional[float]:
    pulse = _measure_pulse()
    if pulse is not None:
        distance_cm = pulse * 34300.0 / 2.0
        return round(distance_cm, 2)

    fallback_distance = _measure_gpiozero_distance()
    if fallback_distance is None:
        return None
    return round(fallback_distance * 100.0, 2)


def cleanup() -> None:
    global _GPIO_INITIALIZED, _GPIOZERO_SENSOR
    if GPIO is not None and _GPIO_INITIALIZED:
        try:
            GPIO.cleanup((TRIG_PIN, ECHO_PIN))
        except Exception:
            pass
        _GPIO_INITIALIZED = False
    if _GPIOZERO_SENSOR is not None:
        try:
            _GPIOZERO_SENSOR.close()
        except Exception:
            pass
        _GPIOZERO_SENSOR = None


atexit.register(cleanup)


if __name__ == "__main__":
    try:
        logging.basicConfig(level=logging.INFO)
        while True:
            distance = checkdist()
            if distance is None:
                print("timeout")
            else:
                print(f"{distance:.2f} cm")
            time.sleep(0.05)
    finally:
        cleanup()
