#!/usr/bin/env python3
"""Interactive helper to calibrate the battery monitor scaling."""
import sys

from battery_monitor import calibrate_to_voltage, get_calibration, sample_status


def _print_status() -> None:
    status = sample_status()
    cal = get_calibration()
    raw = float(status.get("raw_voltage", 0.0) or 0.0)
    voltage = float(status.get("voltage", 0.0) or 0.0)
    print(
        "Current reading: "
        f"raw={raw:.3f} V, calibrated={voltage:.3f} V "
        f"(scale={cal['scale']}, factor={cal['factor']:.4f}, offset={cal['offset']})"
    )


def main() -> int:
    _print_status()
    actual_str = input("Enter actual battery voltage (e.g. multimeter reading): ").strip()
    if not actual_str:
        print("Calibration cancelled.")
        return 1
    actual_voltage = float(actual_str)
    result = calibrate_to_voltage(actual_voltage)
    print(f"Calibration saved (factor={result['factor']:.4f}).")
    _print_status()
    return 0


if __name__ == "__main__":
    sys.exit(main())
