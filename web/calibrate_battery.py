#!/usr/bin/env python3
"""Interactive helper to calibrate the battery monitor scaling."""
import json
import statistics
import sys
import time
from pathlib import Path

from battery_monitor import BatteryMonitor


def _collect_samples(monitor: BatteryMonitor, count: int = 20, delay: float = 0.05) -> float:
    readings = []
    for _ in range(max(1, count)):
        readings.append(monitor.sample_voltage(calibrated=False))
        if delay:
            time.sleep(delay)
    return statistics.mean(readings)


def main() -> int:
    monitor = BatteryMonitor(interval=0.0)
    try:
        base_voltage = _collect_samples(monitor)
        print(f"Average uncalibrated voltage: {base_voltage:.3f} V")
        actual_str = input("Enter actual battery voltage (e.g. multimeter reading): ").strip()
        if not actual_str:
            print("Calibration cancelled.")
            return 1
        actual_voltage = float(actual_str)
        if base_voltage <= 0:
            print("Unable to collect valid samples; check wiring or ADS7830 driver.")
            return 2
        factor = actual_voltage / base_voltage
        data = {
            "scale": monitor.scale_base,
            "factor": factor,
            "offset": monitor.cal_offset,
        }
        out_path: Path = monitor.calibration_file
        out_path.write_text(json.dumps(data, indent=2))
        print(f"Saved calibration file to {out_path}")
        print(f"New calibrated reading would be ≈ {base_voltage * factor:.3f} V")
        print("Restart the web server to apply the updated calibration.")
        return 0
    finally:
        monitor.close()


if __name__ == "__main__":
    sys.exit(main())
