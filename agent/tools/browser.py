"""Tools de navegador.

Stub: la implementación productiva usará Chrome DevTools Protocol (CDP)
contra Firefox/Chromium con flag de debug local (ver docs/architecture.md).
Por ahora exponemos las firmas para que el modelo pueda planear, y
`browser.open` arranca el navegador del sistema con la URL dada.

CDP completo (DOM, evaluate, screenshot, click sobre elemento) llega en la
fase Launch.
"""

from __future__ import annotations

import shutil
import subprocess

from tools.base import RiskLevel, ToolDefinition, ToolResult
from tools.registry import register


def _browser_open(url: str) -> ToolResult:
    if not (url.startswith("http://") or url.startswith("https://")):
        return ToolResult(
            output=f"url inválida (sólo http/https): {url}", is_error=True
        )
    opener = (
        shutil.which("xdg-open")
        or shutil.which("gio")
        or shutil.which("firefox")
        or shutil.which("google-chrome")
        or shutil.which("chromium")
    )
    if opener is None:
        return ToolResult(output="no hay opener disponible", is_error=True)
    cmd = [opener, "open", url] if opener.endswith("gio") else [opener, url]
    try:
        subprocess.Popen(  # noqa: S603 - args controlados
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except OSError as exc:
        return ToolResult(output=f"error abriendo {url}: {exc}", is_error=True)
    return ToolResult(output=f"abierto: {url}", structured={"url": url})


def _browser_navigate(url: str) -> ToolResult:  # noqa: ARG001
    return ToolResult(
        output=(
            "browser.navigate aún no implementado (requiere CDP). "
            "Usa browser.open por ahora."
        ),
        is_error=True,
    )


def _browser_dom(selector: str) -> ToolResult:  # noqa: ARG001
    return ToolResult(
        output="browser.dom aún no implementado (requiere CDP).", is_error=True
    )


BROWSER_OPEN_DEFINITION = ToolDefinition(
    name="browser.open",
    description="Abre una URL en el navegador por defecto del sistema.",
    input_schema={
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    },
    risk=RiskLevel.CONFIRM,
    executor=_browser_open,
    capabilities_required=["browser:control"],
    category="browser",
)

BROWSER_NAVIGATE_DEFINITION = ToolDefinition(
    name="browser.navigate",
    description="(stub) Navega una pestaña ya abierta vía CDP. No implementado todavía.",
    input_schema={
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    },
    risk=RiskLevel.CONFIRM,
    executor=_browser_navigate,
    capabilities_required=["browser:control"],
    category="browser",
)

BROWSER_DOM_DEFINITION = ToolDefinition(
    name="browser.dom",
    description="(stub) Lee elementos del DOM por selector. No implementado todavía.",
    input_schema={
        "type": "object",
        "properties": {"selector": {"type": "string"}},
        "required": ["selector"],
    },
    risk=RiskLevel.SAFE,
    executor=_browser_dom,
    capabilities_required=["browser:control"],
    category="browser",
)


def register_all() -> None:
    register(BROWSER_OPEN_DEFINITION)
    register(BROWSER_NAVIGATE_DEFINITION)
    register(BROWSER_DOM_DEFINITION)


__all__ = [
    "BROWSER_DOM_DEFINITION",
    "BROWSER_NAVIGATE_DEFINITION",
    "BROWSER_OPEN_DEFINITION",
    "register_all",
]
