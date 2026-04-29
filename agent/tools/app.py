"""Tools de aplicaciones."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from tools.base import RiskLevel, ToolDefinition, ToolResult
from tools.registry import register


def _has_desktop_file(name: str) -> bool:
    candidates = [
        Path(f"/usr/share/applications/{name}.desktop"),
        Path(f"/var/lib/flatpak/exports/share/applications/{name}.desktop"),
        Path.home() / f".local/share/applications/{name}.desktop",
    ]
    return any(p.exists() for p in candidates)


def _app_launch(name: str, args: list[str] | None = None) -> ToolResult:
    args = args or []
    try:
        if shutil.which("gtk-launch") and _has_desktop_file(name):
            cmd = ["gtk-launch", name, *args]
        else:
            executable = shutil.which(name)
            if executable is None:
                return ToolResult(
                    output=f"app no encontrada: {name}", is_error=True
                )
            cmd = [executable, *args]
        proc = subprocess.Popen(  # noqa: S603 - cmd construido de input controlado
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except OSError as exc:
        return ToolResult(output=f"error lanzando {name}: {exc}", is_error=True)

    return ToolResult(
        output=f"lanzado: {name} (pid={proc.pid})",
        structured={"name": name, "pid": proc.pid, "args": args},
    )


APP_LAUNCH_DEFINITION = ToolDefinition(
    name="app.launch",
    description="Lanza una aplicación instalada (.desktop o ejecutable en PATH).",
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "args": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["name"],
    },
    risk=RiskLevel.CONFIRM,
    executor=_app_launch,
    capabilities_required=["app:launch:*"],
    category="app",
)


def register_all() -> None:
    register(APP_LAUNCH_DEFINITION)


__all__ = ["APP_LAUNCH_DEFINITION", "register_all"]
