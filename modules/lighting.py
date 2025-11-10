#!/usr/bin/env python3
"""Lighting controls for the rover (headlight + WS2812 strip)."""

from __future__ import annotations

import logging
import os
import threading
from typing import Optional, Tuple

from utils import pwm_led
from utils import robot_light as robotLight
from utils import ws2812_spi

logger = logging.getLogger("rasptank.lighting")

WS2812_DRIVER = os.getenv("WS2812_DRIVER", "auto").strip().lower()
WS2812_LED_COUNT = int(os.getenv("WS2812_LED_COUNT", "16"))
WS2812_BRIGHTNESS = int(os.getenv("WS2812_BRIGHTNESS", "255"))
WS2812_ALLOW_PI5 = os.getenv("WS2812_ALLOW_PI5", "0").strip().lower() in ("1", "true", "on", "yes")


class LightingController:
    """Owns the spotlight LED and the optional WS2812 LED strip."""

    def __init__(self) -> None:
        self._headlight_lock = threading.Lock()
        self._headlight_enabled = False

        self._ws_controller = None
        self._ws_mark = None
        self._ws_init_lock = threading.Lock()
        self._ws_status = {
            "checked": False,
            "supported": False,
            "reason": None,
            "driver": None,
        }

    # ------------------------------------------------------------------
    # Spotlight
    def set_headlight(self, enabled: bool, *, reason: str) -> bool:
        target = bool(enabled)
        with self._headlight_lock:
            if target == self._headlight_enabled:
                return False
            try:
                if target:
                    pwm_led.turn_on()
                else:
                    pwm_led.turn_off()
            except Exception as exc:  # pragma: no cover - hardware specific
                logger.warning(
                    {"evt": "headlight_error", "enabled": target, "reason": reason, "error": str(exc)}
                )
                return False
            self._headlight_enabled = target
        self._log_led_action("ledOn" if target else "ledOff", reason=reason)
        return True

    # ------------------------------------------------------------------
    # WS2812 helpers
    def _initialize_ws_driver(self, force: bool = False) -> bool:
        if self._ws_status["checked"] and not self._ws_status["supported"] and not force:
            return False
        if self._ws_controller is not None and self._ws_mark == 1 and not force:
            return True

        with self._ws_init_lock:
            state = self._ws_status
            if state["checked"] and not state["supported"] and not force:
                return False
            if self._ws_controller is not None and self._ws_mark == 1 and not force:
                return True

            try:
                robotlight_check = robotLight.check_rpi_model()
                driver_pref = (WS2812_DRIVER or "auto").strip().lower()
                driver_queue = []
                if driver_pref in ("auto", "spi"):
                    driver_queue.append("spi")
                if driver_pref in ("auto", "pwm"):
                    driver_queue.append("pwm")
                if not driver_queue:
                    driver_queue.extend(["spi", "pwm"])

                if robotlight_check == 5 and not WS2812_ALLOW_PI5 and "spi" not in driver_queue:
                    logger.warning({"evt": "ws2812_unsupported_pi5"})
                    self._ws_controller = None
                    self._ws_mark = 0
                    state.update({"checked": True, "supported": False, "reason": "unsupported_pi5", "driver": None})
                    return False

                last_error = None
                for driver in driver_queue:
                    try:
                        if driver == "spi":
                            candidate = ws2812_spi.WS2812SPI(
                                count=WS2812_LED_COUNT,
                                brightness=WS2812_BRIGHTNESS,
                            )
                            candidate.start()
                            candidate.setColor(70, 70, 255)
                        else:
                            candidate = robotLight.RobotWS2812()
                            candidate.start()
                            if hasattr(candidate, "breath"):
                                candidate.breath(70, 70, 255)
                            else:
                                candidate.setColor(70, 70, 255)
                        self._ws_controller = candidate
                        self._ws_mark = 1
                        logger.info({"evt": "ws2812_init", "driver": driver})
                        state.update({"checked": True, "supported": True, "reason": None, "driver": driver})
                        return True
                    except Exception as exc:
                        last_error = exc
                        logger.warning({"evt": "ws2812_init_failed", "driver": driver, "error": str(exc)})
                self._ws_controller = None
                self._ws_mark = 0
                if last_error:
                    logger.warning({"evt": "ws2812_init_error", "error": str(last_error)})
                state.update({"checked": True, "supported": False, "reason": "init_failed", "driver": None})
                return False
            except Exception as exc:
                logger.warning({"evt": "ws2812_init_error", "error": str(exc)})
                self._ws_controller = None
                self._ws_mark = 0
                self._ws_status.update({"checked": True, "supported": False, "reason": "init_error", "driver": None})
                return False

    def _ws_available(self) -> bool:
        state = self._ws_status
        if state["checked"] and not state["supported"]:
            return False
        if self._ws_controller is not None and self._ws_mark == 1:
            return True
        return self._initialize_ws_driver()

    def _ws_apply_color(self, r: int, g: int, b: int) -> bool:
        controller = self._ws_controller
        if controller is None:
            return False
        candidates = [
            getattr(controller, "setColor", None),
            getattr(controller, "set_all_led_color_data", None),
            getattr(controller, "set_all_led_color", None),
        ]
        for func in candidates:
            if callable(func):
                try:
                    func(r, g, b)
                    return True
                except Exception as exc:
                    logger.warning(
                        {
                            "evt": "ws2812_apply_color_failed",
                            "method": getattr(func, "__name__", str(func)),
                            "error": str(exc),
                        }
                    )
        return False

    def set_strip_color(self, rgb: Tuple[int, int, int]) -> bool:
        r, g, b = [max(0, min(255, int(x))) for x in rgb]
        if not self._ws_available():
            logger.debug({"evt": "ws2812_unavailable", "action": "set_color", "reason": self._ws_status.get("reason")})
            return False
        controller = self._ws_controller
        if controller is None:
            return False

        try:
            pause = getattr(controller, "pause", None)
            if callable(pause):
                pause()
        except Exception as exc:
            logger.debug({"evt": "ws2812_pause_failed", "error": str(exc)})

        if not self._ws_apply_color(r, g, b):
            logger.warning({"evt": "ws2812_set_color_failed", "error": "no applicable color writer"})
            return False
        self._log_led_action("wsStripColor", color=[r, g, b])
        return True

    def strip_off(self) -> bool:
        controller = self._ws_controller
        if controller is None:
            return False
        success = False
        try:
            pause = getattr(controller, "pause", None)
            if callable(pause):
                pause()
        except Exception as exc:
            logger.debug({"evt": "ws2812_pause_failed", "error": str(exc)})
        try:
            if hasattr(controller, "setColor"):
                controller.setColor(0, 0, 0)
                success = True
        except Exception as exc:
            logger.warning({"evt": "ws2812_turn_off_failed", "error": str(exc)})
        self._log_led_action("wsStripOff")
        return success

    def get_status(self) -> dict:
        return {
            "headlight": self._headlight_enabled,
            "strip": {
                "supported": bool(self._ws_mark),
                "driver": self._ws_status.get("driver"),
                "status": self._ws_status.get("reason"),
            },
        }

    # ------------------------------------------------------------------
    def _log_led_action(self, action: str, **extra) -> None:
        payload = {"evt": "led_action", "action": action}
        payload.update(extra)
        logger.info(payload)


__all__ = ["LightingController"]
