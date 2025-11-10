"""Central coordinator that wires together independent functional modules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Protocol

from .events import EventBus, event_bus as global_event_bus


class CommandHandler(Protocol):
    """Typed callable for command handlers."""

    def __call__(self, payload: Optional[Dict[str, Any]] = None) -> Any: ...


class Module(Protocol):
    """Protocol describing the interface the core expects from modules."""

    name: str

    def attach(self, core: "Core") -> None: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def get_command_map(self) -> Dict[str, CommandHandler]: ...


@dataclass
class CommandResult:
    """Standard response envelope returned by `Core.dispatch`."""

    command: str
    handled: bool
    payload: Optional[Any] = None


class Core:
    """Application kernel that owns shared state and routes commands."""

    def __init__(
        self,
        modules: Optional[Iterable[Module]] = None,
        *,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        self.event_bus = event_bus or global_event_bus
        self._modules: Dict[str, Module] = {}
        self._command_registry: Dict[str, CommandHandler] = {}
        if modules:
            for module in modules:
                self.register_module(module)

    @property
    def modules(self) -> Dict[str, Module]:
        """Expose registered modules (read-only)."""
        return dict(self._modules)

    def register_module(self, module: Module) -> None:
        """Attach a module and register its command handlers."""
        if module.name in self._modules:
            raise ValueError(f"Module '{module.name}' already registered")
        module.attach(self)
        command_map = module.get_command_map()
        for command, handler in command_map.items():
            if command in self._command_registry:
                raise ValueError(f"Command '{command}' already bound")
            self._command_registry[command] = handler
        self._modules[module.name] = module
        module.start()

    def unregister_module(self, name: str) -> None:
        """Remove a module and its handlers."""
        module = self._modules.pop(name, None)
        if module is None:
            return
        command_map = module.get_command_map()
        for command in command_map:
            self._command_registry.pop(command, None)
        module.stop()

    def dispatch(self, command: str, payload: Optional[Dict[str, Any]] = None) -> CommandResult:
        """Send a command into the system."""
        handler = self._command_registry.get(command)
        if handler is None:
            return CommandResult(command=command, handled=False)
        result = handler(payload or {})
        return CommandResult(command=command, handled=True, payload=result)

    def broadcast(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Helper to publish events system-wide."""
        self.event_bus.publish(event_type, payload)


__all__ = ["Core", "CommandResult", "Module"]
