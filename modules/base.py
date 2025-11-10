"""Base classes for domain modules."""

from __future__ import annotations

from typing import Any, Dict, Optional

from core.core import CommandHandler, Core


class BaseModule:
    """Default implementation that other modules can extend."""

    name = "base"

    def __init__(self) -> None:
        self.core: Optional[Core] = None
        self._command_map: Dict[str, CommandHandler] = {}

    # Lifecycle -----------------------------------------------------------
    def attach(self, core: Core) -> None:
        self.core = core
        self._command_map = self.build_command_map() or {}

    def start(self) -> None:  # pragma: no cover - default no-op
        pass

    def stop(self) -> None:  # pragma: no cover - default no-op
        pass

    # Command registration ------------------------------------------------
    def register_command(self, name: str, handler: CommandHandler) -> None:
        if name in self._command_map:
            raise ValueError(f"Command '{name}' already registered in module '{self.name}'")
        self._command_map[name] = handler

    def build_command_map(self) -> Dict[str, CommandHandler]:
        """Modules override to declare commands -> handlers."""
        return {}

    def get_command_map(self) -> Dict[str, CommandHandler]:
        return dict(self._command_map)

    # Utilities -----------------------------------------------------------
    def dispatch(self, command: str, payload: Optional[Dict[str, Any]] = None):
        if self.core is None:
            raise RuntimeError("Module is not attached to a core")
        return self.core.dispatch(command, payload or {})

    def publish(self, event_type: str, payload: Dict[str, Any]) -> None:
        if self.core is None:
            raise RuntimeError("Module is not attached to a core")
        self.core.broadcast(event_type, payload)
