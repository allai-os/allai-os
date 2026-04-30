"""Registro de tools para allAI OS.

Importar este paquete con `register_default_tools()` registra el set base
en el registro global. Para sesiones aisladas, usa un `ToolRegistry()`
propio y registra sólo lo que quieras.
"""

from __future__ import annotations

from tools import app, browser, clipboard, fs, keyboard, mouse, notify, screen, shell
from tools.base import (
    CapabilityDeniedError,
    ConfirmationDeniedError,
    RiskLevel,
    ToolDefinition,
    ToolError,
    ToolNotFoundError,
    ToolResult,
    ToolValidationError,
)
from tools.executor import (
    AllCapabilitiesGranted,
    AlwaysConfirm,
    CapabilityCheckerProtocol,
    ConfirmationProtocol,
    GatePolicy,
    NeverConfirm,
    NoCapabilities,
    ToolExecutor,
)
from tools.registry import ToolRegistry, default_registry, register


def register_default_tools() -> None:
    """Registra el set completo de tools en el registro global.

    Idempotente: si los tools ya están registrados, no falla. Útil
    al inicio de una sesión.
    """
    registry = default_registry()
    modules = [screen, mouse, keyboard, shell, fs, app, clipboard, notify, browser]
    for module in modules:
        for definition in _iter_module_definitions(module):
            registry.replace(definition)


def _iter_module_definitions(module):  # type: ignore[no-untyped-def]
    for name in dir(module):
        if name.endswith("_DEFINITION"):
            obj = getattr(module, name)
            if isinstance(obj, ToolDefinition):
                yield obj


__all__ = [
    "AllCapabilitiesGranted",
    "AlwaysConfirm",
    "CapabilityCheckerProtocol",
    "CapabilityDeniedError",
    "ConfirmationDeniedError",
    "ConfirmationProtocol",
    "GatePolicy",
    "NeverConfirm",
    "NoCapabilities",
    "RiskLevel",
    "ToolDefinition",
    "ToolError",
    "ToolExecutor",
    "ToolNotFoundError",
    "ToolRegistry",
    "ToolResult",
    "ToolValidationError",
    "default_registry",
    "register",
    "register_default_tools",
]
