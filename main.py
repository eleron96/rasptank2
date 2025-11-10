#!/usr/bin/env python3
"""Project entry point. Bootstraps the application core and web server."""

from core import Core
from web import webServer


def build_core() -> Core:
    """Register system modules with the core (placeholder for future expansion)."""
    return Core()


def main() -> None:
    core = build_core()
    # TODO: wire web server to core-dispatched modules.
    webServer.main()


if __name__ == "__main__":
    main()
