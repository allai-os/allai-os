"""Demo de integración del agente real (L.1+L.2+L.3) end-to-end.

A diferencia del benchmark simple (`run.py`) que prueba sólo Computer Use con
Claude directamente, este script ejercita la arquitectura productiva:

  ChatRequest → Router → Provider (Claude o Ollama) → ToolUseBlock →
  ToolExecutor → ToolResultBlock → siguiente ChatRequest → ...

Tareas que vale la pena demostrar (sin display):

  - "lista los archivos .py en agent/core"  (fs.glob)
  - "cuál es la fecha y la hora del sistema" (shell.run con date)
  - "lee el archivo agent/README.md y resúmemelo" (fs.read)
  - "envíame una notificación que diga 'allAI funciona'" (notify.send)

Uso:

    cd agent/
    source .venv/bin/activate
    export ANTHROPIC_API_KEY="sk-ant-..."   # opcional si tienes Ollama
    python prototype/integration_demo.py "lista los .py en agent/core"

    # forzar local
    python prototype/integration_demo.py --policy local_only "..."

    # con Ollama corriendo y un modelo con tools (qwen2.5:7b)
    ollama serve &
    ollama pull qwen2.5:7b
    python prototype/integration_demo.py --policy local_only "lista archivos en /tmp"
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Permite ejecutar desde agent/ sin instalar.
_AGENT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_AGENT_ROOT))

from core import (  # noqa: E402
    ChatRequest,
    Message,
    NoProviderAvailableError,
    Router,
    RoutingMode,
    RoutingPolicy,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from providers import ClaudeProvider, OllamaProvider  # noqa: E402
from tools import (  # noqa: E402
    AllCapabilitiesGranted,
    AlwaysConfirm,
    GatePolicy,
    ToolExecutor,
    default_registry,
    register_default_tools,
)


SYSTEM_PROMPT = """Eres allAI, un agente que opera la computadora del usuario.

Cuando el usuario pida algo:

1. Si necesitas información, usa los tools disponibles (fs.read, fs.list,
   shell.run, etc.).
2. Si el resultado es suficiente, responde con texto natural y termina.
3. Mantén las cadenas cortas: 1-3 tool calls deberían bastar para tareas
   simples.

Sé breve y útil. Si no puedes hacer algo, dilo y termina."""


def _build_router(policy_mode: str) -> Router:
    providers = []

    if "ANTHROPIC_API_KEY" in os.environ:
        try:
            cp = ClaudeProvider()
            if cp.is_available():
                providers.append(cp)
                print("[providers] claude listo")
        except Exception as exc:  # noqa: BLE001
            print(f"[providers] claude no disponible: {exc}")

    try:
        op = OllamaProvider()
        if op.is_available():
            providers.append(op)
            print("[providers] ollama listo (modelos detectados)")
    except Exception as exc:  # noqa: BLE001
        print(f"[providers] ollama no disponible: {exc}")

    if not providers:
        raise SystemExit(
            "Ningún provider disponible. Define ANTHROPIC_API_KEY o corre `ollama serve`."
        )

    mode = RoutingMode(policy_mode)
    return Router(providers, policy=RoutingPolicy(mode=mode))


def _build_executor() -> ToolExecutor:
    register_default_tools()
    registry = default_registry()
    return ToolExecutor(
        registry,
        confirmer=AlwaysConfirm(),  # demo: auto-confirmar
        capabilities=AllCapabilitiesGranted(),  # demo: todas concedidas
        gate_policy=GatePolicy(mode="trust_after_first"),
    )


def run(task: str, *, policy_mode: str, max_iterations: int = 8) -> int:
    router = _build_router(policy_mode)
    executor = _build_executor()
    registry = default_registry()
    tools_for_provider = registry.to_provider_tools()
    print(f"[tools] {len(tools_for_provider)} tools registrados")

    messages: list[Message] = [
        Message(role="user", content=[TextBlock(text=task)])
    ]

    for iteration in range(max_iterations):
        request = ChatRequest(
            messages=messages,
            system=SYSTEM_PROMPT,
            tools=list(tools_for_provider),
            max_tokens=2048,
        )

        try:
            decision = router.route(request)
            print(
                f"\n[iter {iteration}] -> {decision.primary.provider.name}/"
                f"{decision.primary.model}  "
                f"(razón: {decision.reason})"
            )
            response = router.chat(request)
        except NoProviderAvailableError as exc:
            print(f"[error] sin provider: {exc}")
            return 1

        # Imprimir texto si hay
        for block in response.content:
            if isinstance(block, TextBlock) and block.text.strip():
                print(f"  [assistant] {block.text}")

        # Ejecutar tool_uses si los hay
        tool_uses = [b for b in response.content if isinstance(b, ToolUseBlock)]
        if not tool_uses:
            print("[done] sin más tool_uses, terminamos")
            return 0

        # Append assistant turn (con sus tool_use blocks)
        messages.append(Message(role="assistant", content=list(response.content)))

        # Ejecutar y construir el turn de user con resultados
        results: list[ToolResultBlock] = []
        for tu in tool_uses:
            print(f"  [tool_use] {tu.name}({_fmt_input(tu.input)})")
            block = executor.execute_to_block(tu)
            preview = _preview(block.content)
            print(f"  [tool_result] {'ERR ' if block.is_error else ''}{preview}")
            results.append(block)

        messages.append(Message(role="user", content=list(results)))

    print(f"[done] alcanzó max_iterations={max_iterations}")
    return 0


def _fmt_input(payload: dict) -> str:
    items = list(payload.items())
    if not items:
        return ""
    return ", ".join(f"{k}={_short(v)}" for k, v in items[:3])


def _short(value: object, length: int = 40) -> str:
    text = repr(value)
    return text if len(text) <= length else text[: length - 3] + "..."


def _preview(content) -> str:  # type: ignore[no-untyped-def]
    if isinstance(content, str):
        return _short(content, 200)
    if isinstance(content, list):
        return f"<{len(content)} blocks>"
    return _short(content)


def main() -> int:
    parser = argparse.ArgumentParser(description="Demo de integración allAI")
    parser.add_argument("task", help="Tarea en lenguaje natural")
    parser.add_argument(
        "--policy",
        choices=[m.value for m in RoutingMode],
        default=RoutingMode.AUTO.value,
        help="Modo de routing",
    )
    parser.add_argument("--max-iterations", type=int, default=8)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)

    return run(
        args.task,
        policy_mode=args.policy,
        max_iterations=args.max_iterations,
    )


if __name__ == "__main__":
    sys.exit(main())
