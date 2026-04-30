"""Tool de notificaciones del escritorio."""

from __future__ import annotations

import shutil
import subprocess

from tools.base import RiskLevel, ToolDefinition, ToolResult
from tools.registry import register


def _notify_send(title: str, body: str = "", urgency: str = "normal") -> ToolResult:
    if urgency not in {"low", "normal", "critical"}:
        urgency = "normal"
    notify_send = shutil.which("notify-send")
    if notify_send is None:
        return ToolResult(
            output="notify-send no disponible (instala libnotify)", is_error=True
        )
    try:
        subprocess.run(  # noqa: S603 - args controlados
            [notify_send, "--urgency", urgency, "--app-name=allAI", title, body],
            check=False,
            capture_output=True,
            timeout=5.0,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(output="timeout enviando notificación", is_error=True)
    return ToolResult(output=f"notificación enviada: {title!r}")


NOTIFY_SEND_DEFINITION = ToolDefinition(
    name="notify.send",
    description="Envía una notificación al usuario vía notify-send.",
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "body": {"type": "string"},
            "urgency": {"type": "string", "enum": ["low", "normal", "critical"]},
        },
        "required": ["title"],
    },
    risk=RiskLevel.SAFE,
    executor=_notify_send,
    capabilities_required=["notify:send"],
    category="notify",
)


def register_all() -> None:
    register(NOTIFY_SEND_DEFINITION)


__all__ = ["NOTIFY_SEND_DEFINITION", "register_all"]
