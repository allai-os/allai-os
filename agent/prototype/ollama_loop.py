"""
Loop de "Computer Use" con Ollama (Qwen2.5-VL u otro modelo de visión).

A diferencia de Claude, Ollama no tiene un tool computer estandarizado. Aquí
le pedimos al modelo que responda en JSON con la siguiente acción a ejecutar.
El parser es heurístico, esperar tasa de éxito menor.

Esta es una primera aproximación para validar viabilidad. El provider real
(fase Link, ADR-001) hará algo más serio con grammar-constrained decoding o
formatos estructurados estables.
"""

from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import ollama

import tools


DEFAULT_MODEL = "qwen2.5vl:7b"


@dataclass
class RunConfig:
    task: str
    model: str = DEFAULT_MODEL
    max_iterations: int = 25
    log_dir: Path | None = None
    host: str | None = None  # ej. http://localhost:11434


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

Vas a recibir un screenshot en cada turno. Responde EXCLUSIVAMENTE con un objeto JSON
en una de estas formas:

{"action": "click", "x": <int>, "y": <int>}
{"action": "double_click", "x": <int>, "y": <int>}
{"action": "right_click", "x": <int>, "y": <int>}
{"action": "type", "text": "<string>"}
{"action": "key", "text": "<key or combo, ej 'Return' o 'ctrl+l'>"}
{"action": "scroll", "direction": "down|up", "amount": <int>}
{"action": "wait", "duration": <float seconds>}
{"action": "launch", "name": "<app name, ej 'firefox'>"}
{"action": "screenshot"}
{"action": "done", "summary": "<breve resumen>"}
{"action": "stuck", "reason": "<por qué te atascaste>"}

Reglas:
- Un paso a la vez.
- No expliques. Solo el JSON.
- Coordenadas son píxeles desde top-left.
- Cuando termines, usa "done". Si te atascas, "stuck".
"""


_JSON_RE = re.compile(r"\{.*?\}", re.DOTALL)


def _parse_action(text: str) -> dict[str, Any] | None:
    text = text.strip()
    # Intento directo
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Buscar primer JSON en el texto
    match = _JSON_RE.search(text)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _execute(action: dict[str, Any]) -> dict[str, Any]:
    name = action.get("action")
    if name == "screenshot":
        return {"type": "image", "image": tools.screenshot()}
    if name == "click":
        tools.mouse_click(int(action["x"]), int(action["y"]))
        return {"type": "ok"}
    if name == "double_click":
        tools.mouse_click(int(action["x"]), int(action["y"]), clicks=2)
        return {"type": "ok"}
    if name == "right_click":
        tools.mouse_click(int(action["x"]), int(action["y"]), button="right")
        return {"type": "ok"}
    if name == "type":
        tools.keyboard_type(str(action.get("text", "")))
        return {"type": "ok"}
    if name == "key":
        key = str(action.get("text", ""))
        parts = [p.strip() for p in key.split("+")] if "+" in key else [key]
        if len(parts) > 1:
            tools.keyboard_shortcut(*parts)
        else:
            tools.keyboard_key(parts[0])
        return {"type": "ok"}
    if name == "scroll":
        amount = int(action.get("amount", 3))
        direction = action.get("direction", "down")
        tools.mouse_scroll(-amount if direction == "down" else amount)
        return {"type": "ok"}
    if name == "wait":
        tools.wait(float(action.get("duration", 1)))
        return {"type": "ok"}
    if name == "launch":
        tools.app_launch(str(action.get("name", "")))
        tools.wait(2.0)  # le damos un respiro
        return {"type": "ok"}
    if name == "done":
        return {"type": "done", "summary": str(action.get("summary", ""))}
    if name == "stuck":
        return {"type": "stuck", "reason": str(action.get("reason", ""))}
    return {"type": "error", "message": f"acción desconocida: {name}"}


def run(config: RunConfig) -> RunResult:
    started = time.monotonic()
    log_dir = config.log_dir
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)

    client = ollama.Client(host=config.host) if config.host else ollama.Client()

    transcript: list[dict] = []
    tool_calls = 0
    final_text = ""
    success = False
    error = None
    iteration = 0

    # Construimos historial estilo chat
    history: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    initial_screenshot = tools.screenshot()
    history.append(
        {
            "role": "user",
            "content": f"Tarea: {config.task}\n\nAquí está el escritorio. Responde con tu primera acción JSON.",
            "images": [base64.b64encode(initial_screenshot.to_png_bytes()).decode()],
        }
    )

    try:
        while iteration < config.max_iterations:
            response = client.chat(
                model=config.model,
                messages=history,
                options={"temperature": 0.1},
            )
            content = response["message"]["content"]
            transcript.append({"iter": iteration, "raw": content[:500]})

            action = _parse_action(content)
            if action is None:
                error = f"no JSON parseable en respuesta del modelo: {content[:200]}"
                break

            tool_calls += 1
            if log_dir:
                _log_action(log_dir, iteration, tool_calls, action)

            result = _execute(action)

            history.append({"role": "assistant", "content": content})

            if result["type"] == "done":
                final_text = result["summary"]
                success = True
                break
            if result["type"] == "stuck":
                final_text = f"ME ATASQUÉ: {result['reason']}"
                break
            if result["type"] == "error":
                history.append(
                    {
                        "role": "user",
                        "content": f"Error ejecutando: {result['message']}. Toma screenshot y reintenta.",
                    }
                )
                iteration += 1
                continue

            # Tomamos siempre screenshot tras la acción para retroalimentar
            shot = tools.screenshot()
            history.append(
                {
                    "role": "user",
                    "content": "Acción ejecutada. Aquí está el nuevo estado. Siguiente paso o done.",
                    "images": [base64.b64encode(shot.to_png_bytes()).decode()],
                }
            )
            iteration += 1
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


def _log_action(
    log_dir: Path, iteration: int, call_n: int, action: dict[str, Any]
) -> None:
    log_file = log_dir / "actions.log"
    with log_file.open("a", encoding="utf-8") as f:
        ts = time.strftime("%H:%M:%S")
        f.write(f"[{ts}] iter={iteration} call={call_n} action={action}\n")
