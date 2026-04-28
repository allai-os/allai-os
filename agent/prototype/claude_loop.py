"""
Loop de Computer Use con Claude.

Usa el tool `computer_20250124` de Anthropic. La API recibe screenshots y
devuelve acciones (click, type, key, etc.) que ejecutamos y volvemos a
loggear de vuelta hasta que la tarea esté completa o se agoten iteraciones.

Documentación: https://docs.anthropic.com/en/docs/build-with-claude/computer-use
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anthropic

import tools


COMPUTER_TOOL_VERSION = "computer_20250124"
DEFAULT_MODEL = "claude-opus-4-7"


@dataclass
class RunConfig:
    task: str
    model: str = DEFAULT_MODEL
    max_iterations: int = 30
    log_dir: Path | None = None
    extra_system: str = ""


@dataclass
class RunResult:
    success: bool
    iterations: int
    duration_s: float
    tool_calls: int
    final_text: str
    log_dir: Path | None = None
    error: str | None = None
    transcript: list[dict] = field(default_factory=list)


SYSTEM_PROMPT = """Eres un agente que controla un escritorio Linux Fedora.

Tienes la herramienta `computer` para mover el cursor, hacer click, tipear y tomar screenshots.
Para tareas que requieran shell, ten paciencia: abre la app Terminal y tipea los comandos ahí.

Trabajo en pasos pequeños:
1. Toma un screenshot.
2. Decide la siguiente acción mínima.
3. Ejecútala.
4. Repite hasta completar.

Cuando la tarea esté lista, responde con un texto final que diga "TAREA COMPLETADA: <breve resumen>".
Si te atascas y no puedes avanzar, di "ME ATASQUÉ: <razón>".

Sé conservador: si algo parece destructivo, detente y explica antes de ejecutar."""


def _execute_action(action: dict[str, Any]) -> dict[str, Any]:
    """Traduce una invocación del tool computer_20250124 a nuestros tools locales."""
    name = action.get("action")

    if name == "screenshot":
        s = tools.screenshot()
        return {"type": "image", "image": s}

    if name == "left_click":
        coord = action.get("coordinate") or [0, 0]
        tools.mouse_click(coord[0], coord[1], button="left")
        return {"type": "ok"}

    if name == "right_click":
        coord = action.get("coordinate") or [0, 0]
        tools.mouse_click(coord[0], coord[1], button="right")
        return {"type": "ok"}

    if name == "middle_click":
        coord = action.get("coordinate") or [0, 0]
        tools.mouse_click(coord[0], coord[1], button="middle")
        return {"type": "ok"}

    if name == "double_click":
        coord = action.get("coordinate") or [0, 0]
        tools.mouse_click(coord[0], coord[1], clicks=2)
        return {"type": "ok"}

    if name == "mouse_move":
        coord = action.get("coordinate") or [0, 0]
        tools.mouse_move(coord[0], coord[1])
        return {"type": "ok"}

    if name == "left_click_drag":
        start = action.get("start_coordinate") or [0, 0]
        end = action.get("coordinate") or [0, 0]
        tools.mouse_drag(start[0], start[1], end[0], end[1])
        return {"type": "ok"}

    if name == "scroll":
        coord = action.get("coordinate")
        if coord:
            tools.mouse_move(coord[0], coord[1])
        amount = int(action.get("scroll_amount", 3))
        direction = action.get("scroll_direction", "down")
        tools.mouse_scroll(-amount if direction == "down" else amount)
        return {"type": "ok"}

    if name == "type":
        text = action.get("text", "")
        tools.keyboard_type(text)
        return {"type": "ok"}

    if name == "key":
        key = action.get("text", "")
        # Combinaciones tipo "ctrl+l"
        parts = [p.strip() for p in key.split("+")] if "+" in key else [key]
        if len(parts) > 1:
            tools.keyboard_shortcut(*parts)
        else:
            tools.keyboard_key(parts[0])
        return {"type": "ok"}

    if name == "wait":
        tools.wait(float(action.get("duration", 1)))
        return {"type": "ok"}

    if name == "cursor_position":
        # No exponemos esto al tool; devolvemos screenshot.
        s = tools.screenshot()
        return {"type": "image", "image": s}

    return {"type": "error", "message": f"acción desconocida: {name}"}


def _build_tool_result_content(
    tool_use_id: str, action_result: dict[str, Any]
) -> dict[str, Any]:
    if action_result["type"] == "image":
        s: tools.Screenshot = action_result["image"]
        b64 = base64.b64encode(s.to_png_bytes()).decode("ascii")
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": b64,
                    },
                }
            ],
        }
    if action_result["type"] == "error":
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "is_error": True,
            "content": action_result["message"],
        }
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": "ok",
    }


def run(config: RunConfig) -> RunResult:
    started = time.monotonic()
    log_dir = config.log_dir
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)

    client = anthropic.Anthropic()
    width, height = tools.get_screen_size()

    computer_tool = {
        "type": COMPUTER_TOOL_VERSION,
        "name": "computer",
        "display_width_px": width,
        "display_height_px": height,
        "display_number": 1,
    }

    messages: list[dict] = [
        {
            "role": "user",
            "content": [{"type": "text", "text": config.task}],
        }
    ]

    transcript: list[dict] = []
    tool_calls = 0
    final_text = ""
    success = False
    error = None

    try:
        for iteration in range(config.max_iterations):
            response = client.messages.create(
                model=config.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT + ("\n\n" + config.extra_system if config.extra_system else ""),
                tools=[computer_tool],
                messages=messages,
                betas=["computer-use-2025-01-24"],
            )

            transcript.append(
                {
                    "iter": iteration,
                    "stop_reason": response.stop_reason,
                    "content": [
                        {"type": b.type, "preview": _preview_block(b)}
                        for b in response.content
                    ],
                }
            )

            assistant_blocks = [b.model_dump() for b in response.content]
            messages.append({"role": "assistant", "content": assistant_blocks})

            if response.stop_reason == "end_turn":
                final_text = "\n".join(
                    b.text for b in response.content if b.type == "text"
                )
                success = "TAREA COMPLETADA" in final_text.upper()
                break

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                final_text = "\n".join(
                    b.text for b in response.content if b.type == "text"
                )
                break

            tool_results = []
            for tu in tool_uses:
                tool_calls += 1
                action_input = tu.input if isinstance(tu.input, dict) else {}
                if log_dir:
                    _log_action(log_dir, iteration, tool_calls, action_input)
                result = _execute_action(action_input)
                tool_results.append(_build_tool_result_content(tu.id, result))

            messages.append({"role": "user", "content": tool_results})

        else:
            error = f"max_iterations ({config.max_iterations}) reached"

    except Exception as exc:  # noqa: BLE001 - prototipo
        error = f"{type(exc).__name__}: {exc}"

    duration = time.monotonic() - started

    if log_dir:
        (log_dir / "transcript.json").write_text(json.dumps(transcript, indent=2))
        (log_dir / "summary.json").write_text(
            json.dumps(
                {
                    "task": config.task,
                    "model": config.model,
                    "success": success,
                    "iterations": iteration + 1,
                    "tool_calls": tool_calls,
                    "duration_s": round(duration, 2),
                    "final_text": final_text,
                    "error": error,
                },
                indent=2,
            )
        )

    return RunResult(
        success=success,
        iterations=iteration + 1,
        duration_s=duration,
        tool_calls=tool_calls,
        final_text=final_text,
        log_dir=log_dir,
        error=error,
        transcript=transcript,
    )


def _preview_block(block: Any) -> str:
    if block.type == "text":
        return block.text[:120]
    if block.type == "tool_use":
        return f"{block.name}({_short_input(block.input)})"
    return ""


def _short_input(payload: Any) -> str:
    if isinstance(payload, dict):
        if "action" in payload:
            tail = {k: v for k, v in payload.items() if k != "action"}
            return f"{payload['action']} {tail}" if tail else str(payload["action"])
    return str(payload)[:80]


def _log_action(
    log_dir: Path, iteration: int, call_n: int, action_input: dict[str, Any]
) -> None:
    log_file = log_dir / "actions.log"
    with log_file.open("a", encoding="utf-8") as f:
        ts = time.strftime("%H:%M:%S")
        f.write(f"[{ts}] iter={iteration} call={call_n} action={action_input}\n")
