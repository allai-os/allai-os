"""Tools de portapapeles.

En la versión productiva usaremos el portal `Clipboard` de XDG. Aquí
proveemos una implementación simple basada en `pyperclip` para el prototipo.
"""

from __future__ import annotations

from tools.base import RiskLevel, ToolDefinition, ToolResult
from tools.registry import register


def _clipboard_read() -> ToolResult:
    try:
        import pyperclip
    except ImportError:
        return ToolResult(output="pyperclip no instalado", is_error=True)
    try:
        text = pyperclip.paste()
    except Exception as exc:  # noqa: BLE001
        return ToolResult(output=f"error leyendo clipboard: {exc}", is_error=True)
    return ToolResult(output=text or "(vacío)", structured={"length": len(text or "")})


def _clipboard_write(text: str) -> ToolResult:
    try:
        import pyperclip
    except ImportError:
        return ToolResult(output="pyperclip no instalado", is_error=True)
    try:
        pyperclip.copy(text)
    except Exception as exc:  # noqa: BLE001
        return ToolResult(output=f"error escribiendo clipboard: {exc}", is_error=True)
    return ToolResult(output=f"copiado al clipboard ({len(text)} chars)")


CLIPBOARD_READ_DEFINITION = ToolDefinition(
    name="clipboard.read",
    description="Lee el portapapeles como texto.",
    input_schema={"type": "object", "properties": {}, "required": []},
    risk=RiskLevel.SAFE,
    executor=_clipboard_read,
    capabilities_required=["clipboard:read"],
    category="clipboard",
)

CLIPBOARD_WRITE_DEFINITION = ToolDefinition(
    name="clipboard.write",
    description="Reemplaza el contenido del portapapeles.",
    input_schema={
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    },
    risk=RiskLevel.CONFIRM,
    executor=_clipboard_write,
    capabilities_required=["clipboard:write"],
    category="clipboard",
)


def register_all() -> None:
    register(CLIPBOARD_READ_DEFINITION)
    register(CLIPBOARD_WRITE_DEFINITION)


__all__ = [
    "CLIPBOARD_READ_DEFINITION",
    "CLIPBOARD_WRITE_DEFINITION",
    "register_all",
]
