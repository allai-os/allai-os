"""Loop de Computer Use con Gemini (modelo preview).

Gemini Computer Use usa una API distinta a Claude: el tool nativo es
`computer_use` con un `environment` (BROWSER/DESKTOP), y las acciones
emitidas por el modelo son funciones predefinidas como `click_at`,
`type_text_at`, `key_combination`, `scroll_at`, etc.

Aquí mapeamos esas acciones a nuestros tools locales (pyautogui).

Doc: https://ai.google.dev/gemini-api/docs/computer-use
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tools


DEFAULT_MODEL = "gemini-2.5-computer-use-preview-10-2025"


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

Tienes la herramienta `computer_use` para mover el cursor, hacer click,
tipear y tomar screenshots.

Trabaja en pasos pequeños. Cuando la tarea esté lista, responde con texto
que diga "TAREA COMPLETADA: <breve resumen>". Si te atascas, di
"ME ATASQUÉ: <razón>".

Sé conservador: si algo parece destructivo, detente y explica antes de
ejecutar."""


def _action_to_local(action_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Traduce las acciones de Gemini Computer Use a nuestros tools.

    Lista de acciones reconocidas. Las que no estén en la lista se ejecutan
    "best effort" — lanzando el tool más parecido o devolviendo error.
    """
    a = action_name.lower()
    if a in {"click_at", "left_click_at"}:
        return {"kind": "click", "x": int(args.get("x", 0)), "y": int(args.get("y", 0))}
    if a in {"right_click_at"}:
        return {
            "kind": "click",
            "x": int(args.get("x", 0)),
            "y": int(args.get("y", 0)),
            "button": "right",
        }
    if a in {"double_click_at"}:
        return {
            "kind": "click",
            "x": int(args.get("x", 0)),
            "y": int(args.get("y", 0)),
            "clicks": 2,
        }
    if a in {"hover_at", "move_at", "mouse_move_at"}:
        return {"kind": "move", "x": int(args.get("x", 0)), "y": int(args.get("y", 0))}
    if a in {"type_text_at"}:
        # Click + tipear
        return {
            "kind": "type_at",
            "x": int(args.get("x", 0)),
            "y": int(args.get("y", 0)),
            "text": str(args.get("text", "")),
        }
    if a == "type_text":
        return {"kind": "type", "text": str(args.get("text", ""))}
    if a == "key_combination":
        keys = args.get("keys", [])
        if isinstance(keys, str):
            keys = [k.strip() for k in keys.split("+")]
        return {"kind": "shortcut", "keys": list(keys)}
    if a == "scroll_at":
        direction = args.get("direction", "down")
        magnitude = int(args.get("magnitude", args.get("amount", 3)))
        scroll = -magnitude if direction == "down" else magnitude
        return {
            "kind": "scroll",
            "x": int(args.get("x", 0)),
            "y": int(args.get("y", 0)),
            "amount": scroll,
        }
    if a == "drag_and_drop":
        return {
            "kind": "drag",
            "x1": int(args.get("start_x", args.get("x1", 0))),
            "y1": int(args.get("start_y", args.get("y1", 0))),
            "x2": int(args.get("end_x", args.get("x2", 0))),
            "y2": int(args.get("end_y", args.get("y2", 0))),
        }
    if a == "wait":
        return {"kind": "wait", "duration": float(args.get("duration", 1))}
    if a in {"screenshot", "take_screenshot"}:
        return {"kind": "screenshot"}
    if a in {"open_web_browser", "navigate_to"}:
        return {"kind": "open_url", "url": str(args.get("url", ""))}
    return {"kind": "unknown", "action": action_name, "args": args}


def _execute_local(plan: dict[str, Any]) -> dict[str, Any]:
    kind = plan["kind"]
    if kind == "click":
        tools.mouse_click(
            plan["x"],
            plan["y"],
            button=plan.get("button", "left"),
            clicks=plan.get("clicks", 1),
        )
        return {"type": "ok"}
    if kind == "move":
        tools.mouse_move(plan["x"], plan["y"])
        return {"type": "ok"}
    if kind == "type":
        tools.keyboard_type(plan["text"])
        return {"type": "ok"}
    if kind == "type_at":
        tools.mouse_click(plan["x"], plan["y"])
        tools.keyboard_type(plan["text"])
        return {"type": "ok"}
    if kind == "shortcut":
        keys = plan["keys"]
        if len(keys) > 1:
            tools.keyboard_shortcut(*keys)
        elif keys:
            tools.keyboard_key(keys[0])
        return {"type": "ok"}
    if kind == "scroll":
        if "x" in plan and "y" in plan:
            tools.mouse_move(plan["x"], plan["y"])
        tools.mouse_scroll(plan["amount"])
        return {"type": "ok"}
    if kind == "drag":
        tools.mouse_drag(plan["x1"], plan["y1"], plan["x2"], plan["y2"])
        return {"type": "ok"}
    if kind == "wait":
        tools.wait(plan["duration"])
        return {"type": "ok"}
    if kind == "screenshot":
        return {"type": "image", "image": tools.screenshot()}
    if kind == "open_url":
        tools.app_launch("firefox", )  # mejor esfuerzo
        tools.wait(2.0)
        tools.keyboard_shortcut("ctrl", "l")
        tools.keyboard_type(plan["url"])
        tools.keyboard_key("Return")
        return {"type": "ok"}
    return {"type": "error", "message": f"acción desconocida: {plan}"}


def run(config: RunConfig) -> RunResult:
    started = time.monotonic()
    log_dir = config.log_dir
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)

    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        return RunResult(
            success=False,
            iterations=0,
            duration_s=0.0,
            tool_calls=0,
            final_text="",
            error=f"google-genai no instalado: {exc}",
            log_dir=log_dir,
        )

    client = genai.Client()  # usa GOOGLE_API_KEY del env
    width, height = tools.get_screen_size()

    # Tool de Computer Use
    try:
        cu_tool = types.Tool(computer_use=types.ComputerUse(environment="ENVIRONMENT_BROWSER"))
    except (TypeError, AttributeError) as exc:
        return RunResult(
            success=False,
            iterations=0,
            duration_s=0.0,
            tool_calls=0,
            final_text="",
            error=f"Tu versión de google-genai no soporta ComputerUse: {exc}",
            log_dir=log_dir,
        )

    config_obj = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT
        + ("\n\n" + config.extra_system if config.extra_system else ""),
        tools=[cu_tool],
        temperature=0,
    )

    # Primera screenshot
    initial_shot = tools.screenshot()
    contents: list[Any] = [
        types.Content(
            role="user",
            parts=[
                types.Part(text=f"Tarea: {config.task}\nResolución pantalla: {width}x{height}"),
                types.Part(
                    inline_data=types.Blob(
                        mime_type="image/png",
                        data=initial_shot.to_png_bytes(),
                    )
                ),
            ],
        )
    ]

    transcript: list[dict] = []
    tool_calls = 0
    final_text = ""
    success = False
    error: str | None = None
    iteration = 0

    try:
        for iteration in range(config.max_iterations):
            response = client.models.generate_content(
                model=config.model,
                contents=contents,
                config=config_obj,
            )

            candidate = response.candidates[0] if response.candidates else None
            parts = candidate.content.parts if candidate and candidate.content else []

            iter_tool_calls: list[Any] = []
            iter_texts: list[str] = []
            for part in parts:
                if getattr(part, "text", None):
                    iter_texts.append(part.text)
                if getattr(part, "function_call", None) and part.function_call.name:
                    iter_tool_calls.append(part.function_call)

            transcript.append(
                {
                    "iter": iteration,
                    "texts": [t[:120] for t in iter_texts],
                    "tool_calls": [
                        {"name": fc.name, "args": dict(fc.args or {})}
                        for fc in iter_tool_calls
                    ],
                }
            )

            # Append turno del modelo al historial
            contents.append(
                types.Content(role="model", parts=parts)
            )

            text_concat = "\n".join(iter_texts)
            if not iter_tool_calls:
                final_text = text_concat
                success = "TAREA COMPLETADA" in final_text.upper()
                break

            # Ejecutar function calls y devolver function_responses
            response_parts: list[Any] = []
            for fc in iter_tool_calls:
                tool_calls += 1
                if log_dir:
                    _log_action(log_dir, iteration, tool_calls, fc.name, dict(fc.args or {}))
                plan = _action_to_local(fc.name, dict(fc.args or {}))
                result = _execute_local(plan)
                response_parts.append(_build_function_response(fc, result, types))

            contents.append(types.Content(role="user", parts=response_parts))

        else:
            error = f"max_iterations ({config.max_iterations}) reached"

    except Exception as exc:
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


def _build_function_response(fc: Any, result: dict[str, Any], types: Any) -> Any:
    """Construye un function_response para devolver al modelo."""
    if result["type"] == "image":
        # Gemini permite imágenes en parts separadas, no dentro de
        # function_response. Devolvemos screenshot como Part inline_data.
        shot = result["image"]
        return types.Part(
            inline_data=types.Blob(
                mime_type="image/png",
                data=shot.to_png_bytes(),
            )
        )
    if result["type"] == "error":
        return types.Part(
            function_response=types.FunctionResponse(
                name=fc.name,
                response={"error": result["message"]},
            )
        )
    return types.Part(
        function_response=types.FunctionResponse(
            name=fc.name,
            response={"output": "ok"},
        )
    )


def _log_action(
    log_dir: Path, iteration: int, call_n: int, name: str, args: dict[str, Any]
) -> None:
    log_file = log_dir / "actions.log"
    with log_file.open("a", encoding="utf-8") as f:
        ts = time.strftime("%H:%M:%S")
        f.write(f"[{ts}] iter={iteration} call={call_n} {name}({args})\n")
