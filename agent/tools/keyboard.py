"""Tools de teclado."""

from __future__ import annotations

from tools.base import RiskLevel, ToolDefinition, ToolResult
from tools.registry import register


def _import_pyautogui():  # type: ignore[no-untyped-def]
    try:
        import pyautogui

        pyautogui.FAILSAFE = False
        return pyautogui
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def _keyboard_type(text: str, interval: float = 0.02) -> ToolResult:
    pa = _import_pyautogui()
    if isinstance(pa, tuple):
        return ToolResult(output=f"pyautogui no disponible: {pa[1]}", is_error=True)
    pa.write(text, interval=interval)
    return ToolResult(output=f"tipeado: {len(text)} chars")


def _keyboard_key(key: str) -> ToolResult:
    pa = _import_pyautogui()
    if isinstance(pa, tuple):
        return ToolResult(output=f"pyautogui no disponible: {pa[1]}", is_error=True)
    pa.press(key)
    return ToolResult(output=f"tecla: {key}")


def _keyboard_shortcut(keys: list[str]) -> ToolResult:
    if not keys:
        return ToolResult(output="lista de teclas vacía", is_error=True)
    pa = _import_pyautogui()
    if isinstance(pa, tuple):
        return ToolResult(output=f"pyautogui no disponible: {pa[1]}", is_error=True)
    pa.hotkey(*keys)
    return ToolResult(output=f"shortcut: {'+'.join(keys)}")


KEYBOARD_TYPE_DEFINITION = ToolDefinition(
    name="keyboard.type",
    description="Escribe el texto carácter por carácter en el foco actual.",
    input_schema={
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "interval": {"type": "number"},
        },
        "required": ["text"],
    },
    risk=RiskLevel.CONFIRM,
    executor=_keyboard_type,
    capabilities_required=["input:emulate"],
    category="input",
)

KEYBOARD_KEY_DEFINITION = ToolDefinition(
    name="keyboard.key",
    description="Pulsa una tecla individual (ej. 'Return', 'Escape', 'Tab').",
    input_schema={
        "type": "object",
        "properties": {"key": {"type": "string"}},
        "required": ["key"],
    },
    risk=RiskLevel.SAFE,
    executor=_keyboard_key,
    capabilities_required=["input:emulate"],
    category="input",
)

KEYBOARD_SHORTCUT_DEFINITION = ToolDefinition(
    name="keyboard.shortcut",
    description="Combina teclas en orden (ej. ['ctrl','c']).",
    input_schema={
        "type": "object",
        "properties": {"keys": {"type": "array", "items": {"type": "string"}}},
        "required": ["keys"],
    },
    risk=RiskLevel.CONFIRM,
    executor=_keyboard_shortcut,
    capabilities_required=["input:emulate"],
    category="input",
)


def register_all() -> None:
    register(KEYBOARD_TYPE_DEFINITION)
    register(KEYBOARD_KEY_DEFINITION)
    register(KEYBOARD_SHORTCUT_DEFINITION)


__all__ = [
    "KEYBOARD_KEY_DEFINITION",
    "KEYBOARD_SHORTCUT_DEFINITION",
    "KEYBOARD_TYPE_DEFINITION",
    "register_all",
]
