"""Tool de captura de pantalla.

En producción usa `xdg-desktop-portal-screenshot` (ver ADR-003). Aquí
proveemos una implementación basada en `mss` (multiplataforma) como
fallback de desarrollo y para el prototipo.
"""

from __future__ import annotations

import io
from typing import Any

from tools.base import RiskLevel, ToolDefinition, ToolResult
from tools.registry import register


def _screenshot(monitor: int = 1) -> ToolResult:
    """Captura el monitor indicado y devuelve PNG.

    Implementación con mss porque es ligera y multiplataforma. La versión
    sandboxeada con portal vendrá en fase Launch.
    """
    try:
        import mss
        from PIL import Image
    except ImportError as exc:
        return ToolResult(
            output=f"dependencia faltante: {exc.name}", is_error=True
        )

    with mss.mss() as sct:
        if monitor < 1 or monitor > len(sct.monitors) - 1:
            monitor = 1
        raw = sct.grab(sct.monitors[monitor])
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return ToolResult(
        output=f"screenshot capturado ({img.width}x{img.height})",
        images=[buf.getvalue()],
        structured={"width": img.width, "height": img.height, "monitor": monitor},
    )


SCREENSHOT_DEFINITION: ToolDefinition = ToolDefinition(
    name="screen.screenshot",
    description="Captura la pantalla principal y devuelve la imagen.",
    input_schema={
        "type": "object",
        "properties": {
            "monitor": {
                "type": "integer",
                "description": "Índice del monitor (1 = primario).",
            }
        },
        "required": [],
    },
    risk=RiskLevel.SAFE,
    executor=_screenshot,
    capabilities_required=["screen:capture"],
    category="screen",
)


def register_all() -> None:
    register(SCREENSHOT_DEFINITION)


__all__ = ["SCREENSHOT_DEFINITION", "register_all"]
