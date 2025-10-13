# Adeept RaspTank-V4 Smart Car Kit for Raspberry Pi
Adeept RaspTank is an open source intelligent robotics product for artificial intelligence, robotics enthusiasts and students. This product is based on the Raspberry Pi motherboard using the python language and is compatible with the following Raspberry Pi models: 3B,3B+,4,5, etc.

## Resources Links

[RobotName]: Adeept RaspTank-V4 \
[Item Code]: ADR013-V4 \
[Official Raspberry Pi website]: https://www.raspberrypi.org/downloads/    \
[Official website]:  https://www.adeept.com/     \
[GitHub]: https://github.com/adeept/adeept_rasptank2/     


## Docker Compose Deployment

The project now ships with a two-container stack: the application (`rasptank2`) and an nginx reverse proxy that exposes everything on port 80 while tunnelling WebSocket traffic via `/ws`.

1. Copy the repo to your Raspberry Pi (see `make sync`).
2. Run `docker compose up -d --build` in the project root. The compose file automatically:
   - builds the `rasptank2:latest` image,
   - maps `/dev/i2c-1` and `/dev/gpiomem`,
   - injects `PCA9685_ADDR`/`BLINKA_FORCE*`/`SERVO_RELAX` environment variables,
   - enables an automatic camera backend (`CAMERA_BACKEND=auto`) that tries Picamera2 first and falls back to OpenCV `/dev/video0`,
   - brings up nginx with the supplied `nginx.conf`.
3. Open `http://<pi-ip>/` for the UI. The browser will connect to the WebSocket endpoint at `ws(s)://<pi-ip>/ws`.

`make run`/`make restart` are thin wrappers around `docker compose` and handle both containers. Logs from servo arm/gripper actions are streamed to `docker compose logs`.

### Environment Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `PCA9685_ADDR` | `0x5F` | I²C address for the PCA9685 servo driver. |
| `PWM_LED_CHANNEL` | `5` | PCA9685 channel dedicated to the headlight LED (0‑based). |
| `PWM_LED_FREQ` | `50` | PWM frequency used for the LED driver fallback. |
| `SERVO_RELAX` | `1` | Relax servos when idle (`0` keeps torque applied). |
| `ARM_SERVO_SPEED` | `10` | Default shoulder servo wiggle speed (1–10). |
| `CAMERA_BACKEND` | `auto` | Camera selection (`picamera2`, `opencv`, `mock`). |
| `BATTERY_VOLT_MIN` | `6.0` | Voltage treated as 0 % in battery gauge. |
| `BATTERY_VOLT_MAX` | `8.4` | Voltage treated as 100 % in battery gauge. |
| `BATTERY_ADC_CHANNEL` | `0` | ADS7830 channel index for voltage sensing. |
| `BATTERY_CAL_FACTOR / BATTERY_CAL_OFFSET` | `1.0 / 0.0` | Manual calibration overrides. |
| `LOG_LEVEL` | `INFO` | Python logging threshold (`DEBUG`, `INFO`, …). |

All variables can be provided via `.env` or the compose file.

### Service Ports and Streams

| Path/Port | Protocol | Description |
| --- | --- | --- |
| `:80/` | HTTP | Vue-based control UI served by nginx. |
| `:80/ws` | WebSocket | Control channel proxied to the Python `webServer.py` (`8888`). |
| `:80/api/events` | SSE | Server-sent events for telemetry (battery, calibration). |
| `:80/api/calibration` | REST | Battery calibration GET/POST (ETag-aware). |
| `:80/video_feed` | MJPEG | Camera stream. |

### Diagnostics & Lag Checks

- **Power first** – verify the battery reports ≥ 7 V in the UI or via `curl -H "Accept: application/json" http://<pi>/api/calibration`.
- **Servo bus** – ensure the shoulder servo sits on PCA9685 channel 0–7 and that `PCA9685_ADDR` matches the jumper setting.
- **Throttle logging noise** – set `LOG_LEVEL=DEBUG` temporarily to capture structured events like `{"evt": "command_queue", ...}`. Return to `INFO` after diagnosis.
- **Disable video** – comment out `/video_feed` in the UI or stop the camera service if you suspect USB bandwidth issues; command processing now runs in a dedicated executor and should stay responsive.
- **Network** – monitor `/api/events` (SSE) with `curl -N http://<pi>/api/events` to ensure updates arrive without stalling.

### Updating Without Downtime

1. Pull new images: `docker compose pull`.
2. Rebuild the app if required: `docker compose build rasptank2`.
3. Deploy seamlessly: `docker compose up -d` (only refreshed containers restart).
4. Validate: `docker compose ps` and `docker compose logs -f rasptank2` for the structured `{"evt": "startup"}` entry.

The nginx proxy remains up while the application container restarts, keeping WebSocket/SSE connections retrying automatically.


## Getting Support or Providing Advice

Adeept provides free and responsive product and technical support, including but not limited to:   
* Product quality issues 
* Product use and build issues
* Questions regarding the technology employed in our products for learning and education
* Your input and opinions are always welcome

We also encourage your ideas and suggestions for new products and product improvements
For any of the above, you may send us an email to:     \
Technical support: support@adeept.com      \
Customer Service: service@adeept.com


## About Adeept

Adeept was founded in 2015 and is a company dedicated to open source hardware and STEM education services. The Adeept technical team continuously develops new technologies, uses excellent products as technology and service carriers, and provides comprehensive tutorials and after-sales technical support to help users combine learning with entertainment. The main products include various learning kits and robots for Arduino, Raspberry Pi, ESP32 and BBC micro:bit.    \
Adeept is committed to assist customers in their education of robotics, programming and electronic circuits so that they may transform their creative ideas into prototypes and new and innovative products. To this end, our services include but are not limited to:   
* Educational and Entertaining Project Kits for Robots, Smart Cars and Drones
* Educational Kits to Learn Robotic Software Systems for Arduino, Raspberry Pi and micro: bit
* Electronic Component Assortments, Electronic Modules and Specialized Tools
* Product Development and Customization Services


## Copyright

Adeept brand and logo are copyright of Shenzhen Adeept Technology Co., Ltd. and cannot be used without written permission.
