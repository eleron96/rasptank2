"""Core package exposing the central coordinator and shared utilities."""

from .core import Core
from .events import EventBus, event_bus

__all__ = ["Core", "EventBus", "event_bus"]
