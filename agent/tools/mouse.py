"""Tools de mouse.

Implementación con pyautogui (cross-platform, X11 nativo). En Wayland real
estos llamarán a `libei` vía portal RemoteDesktop (ADR-003), pero la firma
se mantiene.
"""

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


def _mouse_move(x: int, y: int, duration: float = 0.15) -> ToolResult:
    pa = _import_pyautogui()
    if isinstance(pa, tuple):
        return ToolResult(output=f"pyautogui no disponible: {pa[1]}", is_error=True)
    pa.moveTo(x, y, duration=duration)
    return ToolResult(output=f"cursor en ({x}, {y})")


def _mouse_click(x: int, y: int, button: str = "left", clicks: int = 1) -> ToolResult:
    pa = _import_pyautogui()
    if isinstance(pa, tuple):
        return ToolResult(output=f"pyautogui no disponible: {pa[1]}", is_error=True)
    pa.click(x=x, y=y, button=button, clicks=clicks, interval=0.05)
    return ToolResult(output=f"click {button} en ({x}, {y}) x{clicks}")


def _mouse_drag(x1: int, y1: int, x2: int, y2: int, duration: float = 0.3) -> ToolResult:
    pa = _import_pyautogui()
    if isinstance(pa, tuple):
        return ToolResult(output=f"pyautogui no disponible: {pa[1]}", is_error=True)
    pa.moveTo(x1, y1)
    pa.dragTo(x2, y2, duration=duration, button="left")
    return ToolResult(output=f"drag ({x1},{y1}) → ({x2},{y2})")


def _mouse_scroll(amount: int, x: int | None = None, y: int | None = None) -> ToolResult:
    pa = _import_pyautogui()
    if isinstance(pa, tuple):
        return ToolResult(output=f"pyautogui no disponible: {pa[1]}", is_error=True)
    if x is not None and y is not None:
        pa.moveTo(x, y)
    pa.scroll(amount)
    return ToolResult(output=f"scroll {amount}")


_COORD = {"type": "integer", "description": "píxeles desde top-left"}


MOUSE_MOVE_DEFINITION = ToolDefinition(
    name="mouse.move",
    description="Mueve el cursor a coordenadas absolutas.",
    input_schema={
        "type": "object",
        "properties": {
            "x": _COORD,
            "y": _COORD,
            "duration": {"type": "number"},
        },
        "required": ["x", "y"],
    },
    risk=RiskLevel.SAFE,
    executor=_mouse_move,
    capabilities_required=["input:emulate"],
    category="input",
)

MOUSE_CLICK_DEFINITION = ToolDefinition(
    name="mouse.click",
    description="Hace click en una coordenada. Botón: left/right/middle. 1 ó 2 clicks.",
    input_schema={
        "type": "object",
        "properties": {
            "x": _COORD,
            "y": _COORD,
            "button": {"type": "string", "enum": ["left", "right", "middle"]},
            "clicks": {"type": "integer"},
        },
        "required": ["x", "y"],
    },
    risk=RiskLevel.CONFIRM,
    executor=_mouse_click,
    capabilities_required=["input:emulate"],
    category="input",
)

MOUSE_DRAG_DEFINITION = ToolDefinition(
    name="mouse.drag",
    description="Arrastra desde (x1,y1) hasta (x2,y2) manteniendo el botón izquierdo.",
    input_schema={
        "type": "object",
        "properties": {
            "x1": _COORD,
            "y1": _COORD,
            "x2": _COORD,
            "y2": _COORD,
            "duration": {"type": "number"},
        },
        "required": ["x1", "y1", "x2", "y2"],
    },
    risk=RiskLevel.CONFIRM,
    executor=_mouse_drag,
    capabilities_required=["input:emulate"],
    category="input",
)

MOUSE_SCROLL_DEFINITION = ToolDefinition(
    name="mouse.scroll",
    description="Scroll del mouse. Positivo = arriba, negativo = abajo.",
    input_schema={
        "type": "object",
        "properties": {
            "amount": {"type": "integer"},
            "x": _COORD,
            "y": _COORD,
        },
        "required": ["amount"],
    },
    risk=RiskLevel.SAFE,
    executor=_mouse_scroll,
    capabilities_required=["input:emulate"],
    category="input",
)


def register_all() -> None:
    register(MOUSE_MOVE_DEFINITION)
    register(MOUSE_CLICK_DEFINITION)
    register(MOUSE_DRAG_DEFINITION)
    register(MOUSE_SCROLL_DEFINITION)


__all__ = [
    "MOUSE_CLICK_DEFINITION",
    "MOUSE_DRAG_DEFINITION",
    "MOUSE_MOVE_DEFINITION",
    "MOUSE_SCROLL_DEFINITION",
    "register_all",
]
