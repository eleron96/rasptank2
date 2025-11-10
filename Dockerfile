# ===== Adeept RaspTank2 (RPi 5 • headless • I2C + GPIO via gpio-cdev • camera-ready) =====
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LANG=en_US.UTF-8 \
    LC_ALL=en_US.UTF-8 \
    PYTHONPATH=/usr/lib/python3/dist-packages

# Системные библиотеки + репозиторий Raspberry Pi для libcamera/picamera2
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gnupg \
 && curl -fsSL https://archive.raspberrypi.com/debian/raspberrypi.gpg.key \
    | gpg --dearmor \
    | tee /usr/share/keyrings/raspberrypi-archive-keyring.gpg >/dev/null \
 && echo "deb [signed-by=/usr/share/keyrings/raspberrypi-archive-keyring.gpg arch=arm64] http://archive.raspberrypi.com/debian bookworm main" \
    > /etc/apt/sources.list.d/raspi.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    python3-dev \
    python3-libcamera \
    python3-picamera2 \
    python3-spidev \
    libjpeg62-turbo \
    libopenjp2-7 \
    libtiff6 \
    libglib2.0-0 \
    libgpiod2 \
    python3-libgpiod \
    libusb-1.0-0 \
 && (apt-get install -y --no-install-recommends libcamera-ipa-rpi5 || \
     apt-get install -y --no-install-recommends libcamera-ipa-rpi || true) \
 && (apt-get install -y --no-install-recommends rpicam-apps || \
     apt-get install -y --no-install-recommends libcamera-apps || true) \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

# Python-зависимости
RUN pip install --upgrade pip && \
    pip install --no-cache-dir \
        flask \
        Flask-Cors \
        RPi.GPIO \
        gpiozero \
        imutils \
        pyzmq \
        websockets==13.0 \
        psutil \
        pybase64 \
        greenlet \
        rpi_ws281x \
        smbus2 \
        adafruit-circuitpython-pca9685 \
        adafruit-circuitpython-motor \
        adafruit-circuitpython-servokit \
        adafruit-circuitpython-ads7830 \
        adafruit-blinka \
        opencv-python-headless \
        "numpy<2.0" \
        lgpio \
    && pip cache purge


EXPOSE 5000 8888
CMD ["python", "main.py"]
