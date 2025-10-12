#!/usr/bin/env python3
"""
Simple standalone test to blink the LED connected to GPIO11 (Pin 23).
Run:  python3 examples/led_gpio11_test.py
Stop: Ctrl+C
"""
from time import sleep

from gpiozero import LED


def main():
    led = LED(11)  # GPIO pin 11
    print("Starting LED blink test on GPIO11. Press Ctrl+C to stop.")

    try:
        while True:
            led.on()
            sleep(1)
            led.off()
            sleep(1)
    except KeyboardInterrupt:
        print("\nStopping LED test...")
    finally:
        led.off()


if __name__ == "__main__":
    main()
