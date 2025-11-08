"""Minimal SPI-based WS2812 driver for Raspberry Pi GPIO10 (MOSI)."""
from __future__ import annotations

import math
import threading
from typing import Iterable, Sequence, Tuple

try:
    import spidev  # type: ignore
except ImportError:  # pragma: no cover - runtime dependency on Pi only
    spidev = None  # type: ignore

ColorTuple = Tuple[int, int, int]


class WS2812SPI:
    _ENCODE_ONE = 0b110
    _ENCODE_ZERO = 0b100

    def __init__(
        self,
        count: int,
        brightness: int = 255,
        bus: int = 0,
        device: int = 0,
        order: str = "GRB",
        speed_hz: int = 3_800_000,
    ) -> None:
        if spidev is None:
            raise RuntimeError("spidev module not available; install it on Raspberry Pi")
        self.count = max(1, int(count))
        self.brightness = max(0, min(255, int(brightness)))
        self.bus = bus
        self.device = device
        self.order = order.upper()
        self.speed_hz = speed_hz
        self._spi = spidev.SpiDev()
        self._lock = threading.Lock()
        self._pixels: list[ColorTuple] = [(0, 0, 0)] * self.count
        self._open = False

    # --- lifecycle -----------------------------------------------------
    def start(self) -> None:
        if self._open:
            return
        self._spi.open(self.bus, self.device)
        self._spi.max_speed_hz = self.speed_hz
        self._spi.mode = 0
        self._open = True
        self.show()

    def close(self) -> None:
        if self._open:
            try:
                self._spi.close()
            finally:
                self._open = False

    def __del__(self):  # pragma: no cover
        try:
            self.close()
        except Exception:
            pass

    # --- helpers -------------------------------------------------------
    def _apply_brightness(self, value: int) -> int:
        scaled = (value * self.brightness) // 255
        return max(0, min(255, scaled))

    def _encode_pixels(self, pixels: Sequence[ColorTuple]) -> bytearray:
        total_bits = len(pixels) * 24 * 3
        buffer = bytearray((total_bits + 7) // 8 + 1)
        bit_index = 0
        channel_map = {
            "R": 0,
            "G": 1,
            "B": 2,
        }
        order = [channel_map.get(ch, 1) for ch in self.order]
        for rgb in pixels:
            channels = [self._apply_brightness(rgb[idx]) for idx in order]
            for value in channels:
                for shift in range(7, -1, -1):
                    bit = (value >> shift) & 1
                    pattern = self._ENCODE_ONE if bit else self._ENCODE_ZERO
                    for sub in range(2, -1, -1):
                        if pattern & (1 << sub):
                            byte_pos = bit_index // 8
                            buffer[byte_pos] |= 1 << (7 - (bit_index % 8))
                        bit_index += 1
        return buffer

    def _write(self) -> None:
        if not self._open:
            raise RuntimeError("WS2812SPI driver is not started")
        payload = self._encode_pixels(self._pixels)
        self._spi.xfer2(payload)

    def show(self) -> None:
        with self._lock:
            self._write()

    # --- public API used by webServer ---------------------------------
    def setColor(self, r: int, g: int, b: int) -> None:
        with self._lock:
            self._pixels = [(r, g, b)] * self.count
            self._write()

    def set_all_led_color_data(self, r: int, g: int, b: int) -> None:
        self.setColor(r, g, b)

    def set_all_led_color(self, r: int, g: int, b: int) -> None:
        self.setColor(r, g, b)

    def fill(self, pixels: Iterable[ColorTuple]) -> None:
        with self._lock:
            values = list(pixels)[: self.count]
            if len(values) < self.count:
                values.extend([(0, 0, 0)] * (self.count - len(values)))
            self._pixels = values
            self._write()

    def pause(self) -> None:
        # no background thread, but keeping API parity with robotLight
        pass

    def resume(self) -> None:
        pass

    def breath(self, r: int, g: int, b: int) -> None:
        # simple immediate fill to mimic initial "breathing" color
        self.setColor(r, g, b)
