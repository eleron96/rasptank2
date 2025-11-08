# RaspTank2 Control Stack

This repository hosts the control software for the RaspTank2 tracked rover: Web UI, WebSocket command server, video streaming, drive train control, robotic arm, and telemetry. The implementation started from the open-source Adeept RaspTank-V4 release and has since been substantially redesigned; everything described below reflects the current custom code base.

## Overview
- Runs on Raspberry Pi 3B/3B+/4/5 paired with the Adeept Robot HAT V3.1 (PCA9685 + TB6612) and the bundled sensors.
- Serves a browser UI (Vue + Vuetify) with live video, telemetry charts, arm presets, and calibration dialogs.
- Exposes a WebSocket control channel on port 8888 plus REST/SSE endpoints for automation and battery calibration.
- Adds servo safety guards, ADS7830 battery monitoring with smoothing, and optional WS2812 lighting effects.

## Libraries Used
### System packages
- `python3-gpiozero`, `python3-pigpio` for GPIO access and PWM bridging.
- `python3-picamera2`, `python3-opencv`, `opencv-data` for camera streaming and computer vision helpers.
- `python3-pyaudio` for audio capture.
- `python3-pyqt5`, `python3-opengl` to satisfy Picamera2 preview dependencies on some Raspberry Pi OS builds.
- Networking utilities for the optional access-point mode: `util-linux`, `procps`, `hostapd`, `iproute2`, `iw`, `haveged`, `dnsmasq`, plus `create_ap`.

### Python packages
- `flask`, `flask-cors`, `websockets`, `pyzmq`, `imutils`, `pybase64`, `psutil`, `numpy`.
- Adafruit CircuitPython drivers: `adafruit-circuitpython-motor`, `adafruit-circuitpython-pca9685`, `adafruit-circuitpython-ads7830`, and the BlinkA compatibility layer.
- `rpi_ws281x` for addressable LEDs, `gpiozero` for high-level GPIO helpers.
- `picamera2` (PyPI variant) and `opencv-python` when not using the Debian packages.

### Front-end
- Vue 3, Vuetify, and Chart.js (pre-built into `web/dist`) power the browser interface.

## Installation
### 1. Prepare the Raspberry Pi
- Flash Raspberry Pi OS (64-bit, Bookworm or newer), boot, and update:  
  `sudo apt update && sudo apt full-upgrade -y`
- Enable interfaces: run `sudo raspi-config`, enable **Camera**, **I2C**, and **SPI**, then reboot.
- (Optional) enable the legacy camera stack only if you rely on older CSI modules.

### Option A: Docker Compose (recommended for quick deployment)
1. Install Docker Engine and the Compose plugin:
   ```bash
   curl -fsSL https://get.docker.com | sh
   sudo usermod -aG docker $USER
   ```
   Log out/in after adding yourself to the `docker` group.
2. Clone the repository:
   ```bash
   git clone https://github.com/your-account/rasptank2.git
   cd rasptank2
   ```
3. Review `.env.example` (create `.env` if you need to override defaults such as `PCA9685_ADDR`, `CAMERA_BACKEND`, or `SERVO_RELAX`).
4. Build and start the stack:
   ```bash
   docker compose up -d --build
   ```
   The Compose file mounts `/dev/i2c-1` and `/dev/gpiomem`, configures camera autodetection, and starts the Nginx reverse proxy on port 80.
5. Open `http://<pi-ip>/` in a browser. The UI will upgrade to WebSocket `ws://<pi-ip>/ws` automatically.
6. Inspect logs when needed: `docker compose logs -f rasptank2` and `docker compose logs -f nginx`.

### Option B: Native installation (runs directly on Raspberry Pi OS)
1. Install OS-level dependencies:
   ```bash
   sudo apt update
   sudo apt install -y python3-gpiozero python3-pigpio python3-opencv python3-picamera2 \
       python3-pyaudio python3-pyqt5 python3-opengl opencv-data \
       util-linux procps hostapd iproute2 iw haveged dnsmasq git
   ```
   If you plan to use the access-point helper, also run:
   ```bash
   git clone https://github.com/oblique/create_ap ~/create_ap
   cd ~/create_ap && sudo make install
   ```
2. (Optional but recommended) create a virtual environment:
   ```bash
   python3 -m venv ~/.venvs/rasptank2
   source ~/.venvs/rasptank2/bin/activate
   python -m pip install --upgrade pip
   ```
3. Install Python dependencies (use `--break-system-packages` on Debian Bookworm if you stay outside a venv):
   ```bash
   pip install flask flask-cors websockets pyzmq imutils numpy pybase64 psutil \
       adafruit-circuitpython-motor adafruit-circuitpython-pca9685 adafruit-circuitpython-ads7830 \
       rpi_ws281x gpiozero picamera2 opencv-python
   ```
4. Clone and enter the project:
   ```bash
   git clone https://github.com/your-account/rasptank2.git
   cd rasptank2
   ```
5. Start the server:
   ```bash
   python3 web/webServer.py
   ```
   The script launches the Flask video backend on port 5000 and the WebSocket interface on port 8888.
6. Browse to `http://<pi-ip>:5000/` for the direct Flask UI or use the SPA at `http://<pi-ip>:5000/index.html`. The WebSocket controller will connect automatically.

## Environment Variables
| Variable | Default | Description |
| --- | --- | --- |
| `PCA9685_ADDR` | `0x5F` | I2C address of the servo driver (Robot HAT jumpers A0-A2 high). |
| `PWM_LED_CHANNEL` | `5` | PCA9685 channel used for the headlight LED. |
| `PWM_LED_FREQ` | `50` | PWM frequency for the LED helper. |
| `SERVO_RELAX` | `1` | Release torque automatically when servos idle (`0` keeps holding torque). |
| `ARM_SERVO_SPEED` | `10` | Default shoulder servo travel speed (1-10). |
| `CAMERA_BACKEND` | `auto` | `picamera2`, `opencv`, or `mock` selection. |
| `BATTERY_VOLT_MIN` | `6.0` | Voltage mapped to 0% for the battery gauge. |
| `BATTERY_VOLT_MAX` | `8.4` | Voltage mapped to 100% (2S Li-ion). |
| `BATTERY_ADC_CHANNEL` | `0` | ADS7830 channel wired to the battery divider. |
| `BATTERY_CAL_FACTOR` / `BATTERY_CAL_OFFSET` | `1.0` / `0.0` | Manual overrides for calibration math. |
| `WS2812_DRIVER` | `auto` | `spi` (Robot HAT V3.1 port), `pwm`, or auto-detect fallback. |
| `WS2812_LED_COUNT` | `16` | Total number of WS2812 pixels (built-in + external strip). |
| `WS2812_BRIGHTNESS` | `255` | SPI strip brightness (0-255). |
| `WS2812_ALLOW_PI5` | `0` | Set to `1` to bypass the Pi 5 safety check and try driving WS2812 over SPI anyway. |
| `LOG_LEVEL` | `INFO` | Python logging threshold. |
| `SHOULDER_LVC_DISABLE` | `1` | Set to `0` to enable the low-voltage shoulder guard. |
| `SHOULDER_LVC_LOWER` / `SHOULDER_LVC_UPPER` | `6.0` / `6.2` | Voltage window to block/release shoulder motion. |
| `SHOULDER_LVC_ALPHA` | `0.2` | Smoothing factor for voltage EMA. |

Provide these through `.env`, `docker-compose.yml`, or the shell environment prior to launching the server.

## Camera Setup
- Default backend: `picamera2` (libcamera stack) via `web/camera_opencv.py`, streaming MJPEG frames through the Flask server. Install `python3-picamera2` on Raspberry Pi OS or the PyPI `picamera2` wheel alongside the `libcamera` firmware packages.
- Supported sensors: IMX219, IMX477, and other CSI modules auto-detect when `CAMERA_BACKEND=auto` (default) or when explicitly set to `picamera2`. Reseat the ribbon cable and enable the Camera interface in `raspi-config` if detection fails.
- USB cameras: set `CAMERA_BACKEND=opencv` to open `/dev/video*` through OpenCV `VideoCapture`. Adjust resolution and FPS in `web/camera_opencv.py` when necessary.
- Headless development: set `CAMERA_BACKEND=mock` to return placeholder frames without physical hardware.
- Performance tips: allocate at least 128 MB of GPU memory, close unused video streams, and tune frame size in `camera_opencv.py` for smoother WebSocket control.

## Pinout and Wiring
### Power and communication buses
- Connect Robot HAT V3.1 5V and GND to the Raspberry Pi 5V (pin 2 or 4) and GND (pin 6 or 9).
- PCA9685 logic (VCC) must be tied to Pi 3.3V (pin 1). Servos draw power from the HAT V+ rail (external 6-7.4 V battery).
- I2C bus: SDA to GPIO2 (pin 3), SCL to GPIO3 (pin 5). Ensure the `PCA9685_ADDR` jumpers remain at `0x5F` unless you override the environment variable.
- ADS7830 battery monitor shares the same I2C bus at address `0x48`.

### DC motors (tracks)
| Robot HAT port | PCA9685 channels | Suggested motor | Notes |
| --- | --- | --- | --- |
| M1 | IN1=15, IN2=14 | Left track front | Swap motor leads if forward/backward is inverted. |
| M2 | IN1=12, IN2=13 | Left track rear | Shares left track direction with M1. |
| M3 | IN1=11, IN2=10 | Right track front | Channels 11/10 drive the right side. |
| M4 | IN1=8, IN2=9 | Right track rear | Mirrors M3; swap leads to correct direction. |

### Servos on PCA9685
| Channel | Function | Notes |
| --- | --- | --- |
| 0 | Shoulder lift servo | Guarded by low-voltage lockout. |
| 1 | Wrist pitch servo (arm up/down fine control) | Referred to as `hand` in the UI. |
| 2 | Arm yaw (rotate left/right) | Used by `lookleft`/`lookright` commands. |
| 3 | Gripper open/close | Triggered by `grab`/`loose`. |
| 4 | Camera tilt | `up`/`down` commands. |
| 5 | Headlight LED via `pwm_led` helper | Optional; can be reassigned. |
| 6-7 | Spare | Free for custom attachments; update code if used. |

### Sensors and auxiliary GPIO
| Component | Pi GPIO (BCM) | Notes |
| --- | --- | --- |
| HC-SR04 trigger | GPIO23 (pin 16) | Use 5V supply with a voltage divider on echo. |
| HC-SR04 echo | GPIO24 (pin 18) | Ensure 3.3 V safe input. |
| Line tracker left | GPIO22 (pin 15) | Active-low digital input. |
| Line tracker middle | GPIO27 (pin 13) | Active-low digital input. |
| Line tracker right | GPIO17 (pin 11) | Active-low digital input. |
| Buzzer | GPIO18 (pin 12) | PWM capable; controlled via `BUZZER_GPIO`. |
| WS2812 LED chain | GPIO10 (pin 19, SPI MOSI) | Two on-board pixels use indexes 0-1; daisy-chain OUT→IN for additional strips. |
| Auxiliary LED 1 | GPIO9 (pin 21) | Managed by `switch.switch(1, ...)`. |
| Auxiliary LED 2 | GPIO25 (pin 22) | Managed by `switch.switch(2, ...)`. |
| Auxiliary LED 3 | GPIO11 (pin 23) | Managed by `switch.switch(3, ...)`. |
| IMU (if present) | I2C bus | Supported through `imu_sensor.py`. |

> **WS2812 wiring:** The Robot HAT V3.1 routes the WS2812 connector to SPI MOSI (GPIO10). Enable SPI in `raspi-config`, feed the strip with 5 V and shared GND, and chain `OUT` of each section to the next `IN`. The two pixels soldered to the HAT occupy indexes 0 and 1, so external LEDs start at index 2.

## Usage
- **Docker**: `docker compose logs -f rasptank2` to watch events, `docker compose stop` to halt, `docker compose down` to tear down the stack.
- **Native**: Run `python3 web/webServer.py` inside a terminal or configure `systemd` to launch at boot. Stop with `Ctrl+C`. Optionally enable `pigpiod` via `sudo systemctl enable --now pigpiod`.
- The UI exposes calibration modals (battery, shoulder). After changing battery calibration, the values persist in `web/servo_calibration.json`.
- WebSocket API clients must authenticate with the default `admin:123456` string; update the logic in `web/webServer.py` if you require custom credentials.

## Next Steps
- Add your own automation routines by extending `web/functions.py`.
- Tweak servo limits in `web/webServer.py` and `web/RPIservo.py` to match your mechanical setup.
- Use `make sync` or your preferred deployment tooling to push updates to the robot.
