#!/usr/bin/env python3
"""One-stop installer for the Adeept RaspTank 2 software stack.

This script replaces the legacy `setup.py` / `setup_HAT_V3.1.py` helpers.
It installs apt/pip dependencies, prepares create_ap, and wires
`startup_rasptank.sh` + `/etc/rc.local` to launch `main.py` on boot.
"""

from __future__ import annotations

import argparse
import os
import pwd
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent

APT_PACKAGES = [
    "git",
    "build-essential",
    "python3-dev",
    "python3-pigpio",
    "python3-gpiozero",
    "python3-picamera2",
    "python3-opencv",
    "python3-pyaudio",
    "python3-pyqt5",
    "python3-opengl",
    "python3-spidev",
    "python3-libgpiod",
    "python3-libcamera",
    "python3-picamera2",
    "opencv-data",
    "util-linux",
    "procps",
    "hostapd",
    "iproute2",
    "iw",
    "haveged",
    "dnsmasq",
]

CREATE_AP_REPO = "https://github.com/oblique/create_ap"

PIP_PACKAGES = [
    "flask",
    "Flask-Cors",
    "RPi.GPIO",
    "gpiozero",
    "imutils",
    "pyzmq",
    "websockets==13.0",
    "psutil",
    "pybase64",
    "greenlet",
    "rpi_ws281x",
    "smbus2",
    "adafruit-circuitpython-pca9685",
    "adafruit-circuitpython-motor",
    "adafruit-circuitpython-servokit",
    "adafruit-circuitpython-ads7830",
    "adafruit-blinka",
    "opencv-python-headless",
    "numpy<2.0",
    "lgpio",
]

STARTUP_FILENAME = "startup_rasptank.sh"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install dependencies and configure boot startup for RaspTank2."
    )
    parser.add_argument(
        "--entrypoint",
        default="main.py",
        help="Relative path to the Python file launched at boot (default: main.py).",
    )
    parser.add_argument(
        "--python-bin",
        default="/usr/bin/python3",
        help="Python interpreter used in the startup script.",
    )
    parser.add_argument(
        "--startup-delay",
        type=int,
        default=5,
        help="Seconds to wait before launching the app at boot.",
    )
    parser.add_argument(
        "--user",
        default=None,
        help="Target user that owns the repo and should run the app (default: SUDO_USER or current user).",
    )
    parser.add_argument(
        "--skip-apt",
        action="store_true",
        help="Skip apt packages installation.",
    )
    parser.add_argument(
        "--skip-pip",
        action="store_true",
        help="Skip pip packages installation.",
    )
    parser.add_argument(
        "--skip-create-ap",
        action="store_true",
        help="Skip cloning/building create_ap.",
    )
    parser.add_argument(
        "--skip-startup",
        action="store_true",
        help="Skip startup script + rc.local wiring.",
    )
    parser.add_argument(
        "--auto-reboot",
        action="store_true",
        help="Reboot automatically once finished.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Retry count for apt/pip/create_ap commands.",
    )
    return parser.parse_args()


def require_root() -> None:
    if os.geteuid() != 0:
        sys.exit("Please run this script with sudo/root privileges.")


def resolve_user(target_user: Optional[str]) -> tuple[str, Path]:
    username = (
        target_user
        or os.environ.get("SUDO_USER")
        or os.environ.get("USER")
        or os.getlogin()
    )
    try:
        user_info = pwd.getpwnam(username)
    except KeyError as exc:
        raise SystemExit(f"User '{username}' not found on this system.") from exc
    return username, Path(user_info.pw_dir)


def run_cmd(
    cmd: Sequence[str],
    *,
    retries: int = 1,
    cwd: Optional[Path] = None,
    description: Optional[str] = None,
) -> None:
    human = description or " ".join(cmd)
    for attempt in range(1, retries + 1):
        print(f"[{attempt}/{retries}] {human}")
        result = subprocess.run(cmd, cwd=cwd, check=False)
        if result.returncode == 0:
            return
        if attempt < retries:
            time.sleep(2)
    raise SystemExit(f"Command failed after {retries} attempts: {' '.join(cmd)}")


def install_apt_packages(retries: int) -> None:
    run_cmd(["apt-get", "update"], retries=retries, description="apt-get update")
    install_cmd = ["apt-get", "install", "-y", "--no-install-recommends"]
    run_cmd(install_cmd + APT_PACKAGES, retries=retries, description="apt-get install base packages")


def should_use_break_system_packages() -> bool:
    try:
        version_raw = Path("/etc/debian_version").read_text().strip()
        major = int(version_raw.split(".")[0])
    except Exception:
        return False
    return major >= 12


def install_pip_packages(retries: int) -> None:
    base_cmd: List[str] = ["pip3", "install", "--no-cache-dir"]
    if should_use_break_system_packages():
        base_cmd.append("--break-system-packages")
    run_cmd(base_cmd + PIP_PACKAGES, retries=retries, description="pip3 install dependencies")


def ensure_create_ap(username: str, user_home: Path, retries: int) -> None:
    repo_path = user_home / "create_ap"
    if repo_path.exists():
        run_cmd(
            ["sudo", "-u", username, "git", "-C", str(repo_path), "pull", "--ff-only"],
            retries=retries,
            description="update create_ap",
        )
    else:
        run_cmd(
            ["sudo", "-u", username, "git", "clone", CREATE_AP_REPO, str(repo_path)],
            retries=retries,
            description="clone create_ap",
        )
    run_cmd(["make", "install"], cwd=repo_path, retries=retries, description="install create_ap")


def write_startup_script(
    username: str,
    user_home: Path,
    entrypoint: Path,
    python_bin: str,
    delay: int,
) -> Path:
    startup_path = user_home / STARTUP_FILENAME
    template = textwrap.dedent(
        f"""\
        #!/bin/sh
        sleep {delay}
        cd {REPO_ROOT}
        exec sudo -u {username} -H {python_bin} {entrypoint}
        """
    )
    startup_path.write_text(template)
    os.chmod(startup_path, 0o755)
    os.chown(startup_path, pwd.getpwnam(username).pw_uid, pwd.getpwnam(username).pw_gid)
    print(f"Wrote startup script to {startup_path}")
    return startup_path


def ensure_rc_local(startup_path: Path) -> None:
    rc_path = Path("/etc/rc.local")
    call_line = f"{startup_path}"
    if rc_path.exists():
        lines = rc_path.read_text().splitlines()
    else:
        lines = ["#!/bin/sh -e", "exit 0"]

    if any(call_line in line for line in lines):
        print("rc.local already references startup script.")
        return

    new_lines: List[str] = []
    inserted = False
    for line in lines:
        if not inserted and line.strip().lower() == "exit 0":
            new_lines.append(call_line)
            inserted = True
        new_lines.append(line)

    if not inserted:
        new_lines.append(call_line)

    rc_path.write_text("\n".join(new_lines) + "\n")
    os.chmod(rc_path, 0o755)
    print(f"Updated {rc_path} to launch the startup script.")


def main() -> None:
    args = parse_args()
    require_root()
    username, user_home = resolve_user(args.user)
    entrypoint = (REPO_ROOT / args.entrypoint).resolve()
    if not entrypoint.exists():
        raise SystemExit(f"Entrypoint not found: {entrypoint}")

    print(f"Using repository root: {REPO_ROOT}")
    print(f"Launching entrypoint: {entrypoint}")
    print(f"Target user: {username} (home={user_home})")

    if not args.skip_apt:
        install_apt_packages(args.retries)
    else:
        print("Skipping apt packages.")

    if not args.skip_pip:
        install_pip_packages(args.retries)
    else:
        print("Skipping pip packages.")

    if not args.skip_create_ap:
        ensure_create_ap(username, user_home, args.retries)
    else:
        print("Skipping create_ap setup.")

    if not args.skip_startup:
        startup_path = write_startup_script(
            username=username,
            user_home=user_home,
            entrypoint=entrypoint,
            python_bin=args.python_bin,
            delay=args.startup_delay,
        )
        ensure_rc_local(startup_path)
    else:
        print("Skipping startup wiring.")

    if args.auto_reboot:
        print("Rebooting in 3 seconds...")
        time.sleep(3)
        run_cmd(["reboot"], description="reboot")
    else:
        print("Setup complete. Reboot the Raspberry Pi to apply all changes.")


if __name__ == "__main__":
    main()
