"""Provider de Ollama (modelos locales).

Características:
  - Detecta modelos instalados localmente con `ollama list`.
  - Mapea capabilities (vision/tools) heurísticamente por nombre del modelo.
  - Vision: codifica imágenes como base64 en el campo `images` de Ollama.
  - Tools: usa el campo nativo `tools` cuando el modelo lo soporta; emula con
    prompt + JSON parsing cuando no.
  - Computer Use: emulado siempre, no es nativo de Ollama.

Esta capa es honestamente más frágil que ClaudeProvider porque Ollama y los
modelos open-source todavía evolucionan rápido en formatos. La interfaz
externa es la misma y los tests cubren los casos reproducibles.
"""

from __future__ import annotations

import base64
import json
import uuid
from collections.abc import Iterator
from typing import Any, cast

import ollama as ollama_sdk
from ollama import ResponseError as OllamaResponseError

from core.errors import (
    InvalidRequestError,
    ProviderError,
    ProviderUnavailableError,
)
from core.messages import (
    ChatRequest,
    ChatResponse,
    ComputerUseTool,
    ContentBlock,
    ImageBlock,
    Message,
    MessageStop,
    StopReason,
    StreamEvent,
    TextBlock,
    TextDelta,
    Tool,
    ToolResultBlock,
    ToolUseBlock,
    ToolUseDelta,
    ToolUseStart,
    Usage,
)
from core.provider import ModelInfo, Provider, ProviderCapabilities


# Modelos que sabemos que soportan visión, por substring en su nombre.
_VISION_MARKERS = (
    "vl",
    "vision",
    "llava",
    "minicpm-v",
    "qwen2.5vl",
    "qwen2-vl",
    "llama3.2-vision",
)

# Modelos con tool-use nativo en Ollama (creciente con el tiempo).
_NATIVE_TOOLS_MARKERS = (
    "qwen2.5",
    "qwen3",
    "llama3.1",
    "llama3.2",
    "llama3.3",
    "mistral",
    "command-r",
)

_DEFAULT_MODEL = "qwen2.5vl:7b"

# System prompt que añadimos cuando el modelo NO tiene tool-use nativo y hay
# tools en la request. Le pedimos al modelo que devuelva un JSON.
_TOOL_EMULATION_SYSTEM = (
    "Tienes acceso a las siguientes herramientas. Para usar una, responde "
    "EXCLUSIVAMENTE con un objeto JSON con esta forma:\n"
    '{"tool": "<nombre>", "input": { ... }}\n'
    "Si no necesitas una herramienta, responde con texto natural.\n\n"
    "Herramientas disponibles:\n"
)

def _computer_use_emulation_prompt(width: int, height: int) -> str:
    """System prompt para emular Computer Use cuando hay un ComputerUseTool."""
    return (
        "Tienes control sobre un escritorio Linux. Para actuar, responde "
        "EXCLUSIVAMENTE con un objeto JSON con esta forma:\n"
        '{"tool": "computer", "input": {"action": "<one of: screenshot, '
        "left_click, right_click, double_click, type, key, scroll, mouse_move, "
        'wait>", ...}}\n'
        f"Coordenadas en píxeles desde top-left. La pantalla es {width}x{height}.\n"
    )


def _extract_balanced_json(text: str) -> str | None:
    """Extrae el primer objeto JSON balanceado en text. Maneja anidamiento."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


class OllamaProvider(Provider):
    name = "ollama"

    def __init__(
        self,
        *,
        host: str | None = None,
        client: ollama_sdk.Client | None = None,
        default_model: str = _DEFAULT_MODEL,
    ) -> None:
        self._host = host
        self._client: ollama_sdk.Client | None = client
        self._default_model = default_model
        self._cached_models: list[ModelInfo] | None = None

    # ─── Capabilities ───────────────────────────────────────────────────────

    def capabilities(self) -> ProviderCapabilities:
        try:
            models = self._discover_models()
            tools_anywhere = any(m.supports_tools for m in models)
            vision_anywhere = any(m.supports_vision for m in models)
        except ProviderUnavailableError:
            models = []
            tools_anywhere = False
            vision_anywhere = False

        return ProviderCapabilities(
            name=self.name,
            supports_streaming=True,
            supports_tools=tools_anywhere,
            supports_vision=vision_anywhere,
            supports_computer_use=vision_anywhere,  # vía emulación
            supports_prompt_caching=False,
            is_local=True,
            requires_network=False,
            available_models=models,
        )

    def is_available(self) -> bool:
        try:
            self._get_client().list()
            return True
        except Exception:  # noqa: BLE001 - cualquier fallo significa indisponible
            return False

    # ─── Chat ───────────────────────────────────────────────────────────────

    def chat(self, request: ChatRequest) -> ChatResponse:
        client = self._get_client()
        model = request.model or self._default_model
        ollama_messages, extra_system = _encode_messages(request)
        full_system = _compose_system(request, extra_system, model)
        if full_system:
            ollama_messages = [{"role": "system", "content": full_system}] + ollama_messages

        params = self._build_params(request, model, ollama_messages)
        try:
            response = client.chat(**params)
        except OllamaResponseError as exc:
            raise ProviderError(str(exc), provider=self.name) from exc
        except Exception as exc:  # noqa: BLE001
            raise ProviderUnavailableError(str(exc), provider=self.name) from exc

        return _decode_response(response, model, has_tools=bool(request.tools))

    def chat_stream(self, request: ChatRequest) -> Iterator[StreamEvent]:
        client = self._get_client()
        model = request.model or self._default_model
        ollama_messages, extra_system = _encode_messages(request)
        full_system = _compose_system(request, extra_system, model)
        if full_system:
            ollama_messages = [{"role": "system", "content": full_system}] + ollama_messages

        params = self._build_params(request, model, ollama_messages)
        params["stream"] = True

        try:
            yield from _decode_stream(client.chat(**params), model)
        except OllamaResponseError as exc:
            raise ProviderError(str(exc), provider=self.name) from exc
        except Exception as exc:  # noqa: BLE001
            raise ProviderUnavailableError(str(exc), provider=self.name) from exc

    # ─── Internals ──────────────────────────────────────────────────────────

    def _get_client(self) -> ollama_sdk.Client:
        if self._client is None:
            self._client = (
                ollama_sdk.Client(host=self._host) if self._host else ollama_sdk.Client()
            )
        return self._client

    def _discover_models(self) -> list[ModelInfo]:
        if self._cached_models is not None:
            return self._cached_models
        try:
            listing = self._get_client().list()
        except Exception as exc:  # noqa: BLE001
            raise ProviderUnavailableError(
                f"Ollama no responde: {exc}", provider=self.name
            ) from exc

        raw_models = listing.get("models", []) if isinstance(listing, dict) else []
        infos: list[ModelInfo] = []
        for entry in raw_models:
            name = entry.get("name") or entry.get("model") or ""
            if not name:
                continue
            lower = name.lower()
            infos.append(
                ModelInfo(
                    id=name,
                    context_window=_guess_context_window(entry),
                    max_output_tokens=4_096,
                    supports_vision=any(m in lower for m in _VISION_MARKERS),
                    supports_tools=any(m in lower for m in _NATIVE_TOOLS_MARKERS),
                    supports_computer_use=False,
                    supports_caching=False,
                )
            )
        self._cached_models = infos
        return infos

    def _build_params(
        self,
        request: ChatRequest,
        model: str,
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        options: dict[str, Any] = {
            "num_predict": request.max_tokens,
        }
        if request.temperature is not None:
            options["temperature"] = request.temperature
        if options:
            params["options"] = options

        # Si el modelo soporta tools nativos y hay tools normales, los pasamos.
        info = next(
            (m for m in self._discover_models() if m.id == model), None
        ) if request.tools else None
        if info is not None and info.supports_tools:
            native = [
                _encode_tool_native(t)
                for t in request.tools
                if isinstance(t, Tool)
            ]
            if native:
                params["tools"] = native

        params.update(request.extra)
        return params


# ─── Helpers ────────────────────────────────────────────────────────────────


def _guess_context_window(entry: dict[str, Any]) -> int:
    """Heurística simple. Ollama no siempre expone el ctx; default conservador."""
    details = entry.get("details") or {}
    family = (details.get("family") or "").lower()
    if "qwen" in family or "llama3" in family:
        return 32_768
    return 8_192


def _compose_system(
    request: ChatRequest, extra: str | None, model: str
) -> str:
    """Junta el system del usuario con prompts de emulación si hace falta."""
    pieces: list[str] = []
    if request.system:
        pieces.append(request.system)
    if extra:
        pieces.append(extra)

    has_computer = any(isinstance(t, ComputerUseTool) for t in request.tools)
    if has_computer:
        cu = next(t for t in request.tools if isinstance(t, ComputerUseTool))
        pieces.append(
            _computer_use_emulation_prompt(cu.display_width_px, cu.display_height_px)
        )

    has_normal_tools = any(isinstance(t, Tool) for t in request.tools)
    model_supports_native = any(m in model.lower() for m in _NATIVE_TOOLS_MARKERS)
    if has_normal_tools and not model_supports_native:
        descriptions = "\n".join(
            f"- {t.name}: {t.description} | input_schema: {json.dumps(t.input_schema)}"
            for t in request.tools
            if isinstance(t, Tool)
        )
        pieces.append(_TOOL_EMULATION_SYSTEM + descriptions)

    return "\n\n".join(pieces).strip()


def _encode_tool_native(tool: Tool) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
        },
    }


def _encode_messages(
    request: ChatRequest,
) -> tuple[list[dict[str, Any]], str | None]:
    """Devuelve (messages, system_extra). Algunos blocks (tool_result) en
    Ollama se traducen a turnos de role 'tool'."""
    out: list[dict[str, Any]] = []
    extra_system = None
    for msg in request.messages:
        out.extend(_encode_message(msg))
    return out, extra_system


def _encode_message(message: Message) -> list[dict[str, Any]]:
    """Traduce un Message a uno o más mensajes Ollama.

    Reglas:
      - TextBlock se concatena en `content`.
      - ImageBlock se acumula en `images` (base64).
      - ToolUseBlock se materializa como contenido del assistant.
      - ToolResultBlock se materializa como un mensaje role=tool aparte.
    """
    out: list[dict[str, Any]] = []

    text_parts: list[str] = []
    images: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []

    for block in message.content:
        if isinstance(block, TextBlock):
            text_parts.append(block.text)
        elif isinstance(block, ImageBlock):
            images.append(base64.b64encode(block.data).decode("ascii"))
        elif isinstance(block, ToolUseBlock):
            tool_calls.append(
                {
                    "function": {
                        "name": block.name,
                        "arguments": block.input,
                    }
                }
            )
        elif isinstance(block, ToolResultBlock):
            tool_results.append(_tool_result_to_ollama(block))

    base: dict[str, Any] = {"role": message.role}
    if text_parts:
        base["content"] = "\n".join(text_parts)
    else:
        base.setdefault("content", "")
    if images:
        base["images"] = images
    if tool_calls and message.role == "assistant":
        base["tool_calls"] = tool_calls
    if base.get("content") or images or tool_calls:
        out.append(base)

    out.extend(tool_results)
    return out


def _tool_result_to_ollama(block: ToolResultBlock) -> dict[str, Any]:
    if isinstance(block.content, str):
        content = block.content
        images = None
    else:
        text_parts = [b.text for b in block.content if isinstance(b, TextBlock)]
        image_parts = [
            base64.b64encode(b.data).decode("ascii")
            for b in block.content
            if isinstance(b, ImageBlock)
        ]
        content = "\n".join(text_parts) if text_parts else ""
        images = image_parts or None
    msg: dict[str, Any] = {"role": "tool", "content": content}
    if images:
        msg["images"] = images
    if block.is_error:
        msg["content"] = f"[ERROR] {msg['content']}"
    return msg


def _decode_response(
    response: dict[str, Any], model: str, *, has_tools: bool
) -> ChatResponse:
    msg = cast("dict[str, Any]", response.get("message") or {})
    text = cast(str, msg.get("content") or "")
    blocks: list[ContentBlock] = []

    # Tool calls nativos (Qwen2.5, Llama 3.1+, etc.)
    native_calls = msg.get("tool_calls") or []
    for call in native_calls:
        fn = call.get("function") or {}
        blocks.append(
            ToolUseBlock(
                id=str(uuid.uuid4()),
                name=str(fn.get("name") or ""),
                input=cast("dict[str, Any]", fn.get("arguments") or {}),
            )
        )

    # Si no hubo tool_calls nativos pero sí había tools en la request, intentamos
    # parsear JSON del texto (modo emulación).
    if not native_calls and has_tools:
        emulated = _try_parse_emulated_tool(text)
        if emulated is not None:
            blocks.append(emulated)
            text = ""  # consumido en el tool call

    if text:
        blocks.append(TextBlock(text=text))

    stop_reason: StopReason = "tool_use" if blocks and any(
        isinstance(b, ToolUseBlock) for b in blocks
    ) else "end_turn"

    usage = Usage(
        input_tokens=int(response.get("prompt_eval_count") or 0),
        output_tokens=int(response.get("eval_count") or 0),
    )
    return ChatResponse(
        content=blocks,
        stop_reason=stop_reason,
        usage=usage,
        model=model,
        raw=response,
    )


def _try_parse_emulated_tool(text: str) -> ToolUseBlock | None:
    candidate = _extract_balanced_json(text.strip())
    if candidate is None:
        return None
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "tool" not in data:
        return None
    return ToolUseBlock(
        id=str(uuid.uuid4()),
        name=str(data.get("tool")),
        input=cast("dict[str, Any]", data.get("input") or {}),
    )


def _decode_stream(stream: Any, model: str) -> Iterator[StreamEvent]:
    """Eventos de Ollama no separan tool_use de texto durante el stream;
    emitimos texto por chunks y resolvemos tool al cierre. Para alta calidad
    de streaming en tool-use real, el provider final debería usar Qwen con
    tool_calls nativos en chunks; aquí mantenemos compatibilidad amplia."""
    final_usage = Usage()
    accumulated = ""
    tool_emitted = False

    for chunk in stream:
        msg = cast("dict[str, Any]", chunk.get("message") or {})
        text = cast(str, msg.get("content") or "")
        if text:
            accumulated += text
            yield TextDelta(text=text)

        # Tool calls nativos suelen llegar en el último chunk con done=True.
        if chunk.get("done"):
            tool_calls = msg.get("tool_calls") or []
            for call in tool_calls:
                fn = call.get("function") or {}
                tool_id = str(uuid.uuid4())
                yield ToolUseStart(id=tool_id, name=str(fn.get("name") or ""))
                yield ToolUseDelta(partial_json=json.dumps(fn.get("arguments") or {}))
                tool_emitted = True

            final_usage = Usage(
                input_tokens=int(chunk.get("prompt_eval_count") or 0),
                output_tokens=int(chunk.get("eval_count") or 0),
            )
            stop: StopReason = "tool_use" if tool_emitted else "end_turn"
            yield MessageStop(stop_reason=stop, usage=final_usage)
            return

    # Stream cerró sin done — defensivo.
    yield MessageStop(stop_reason="end_turn", usage=final_usage)
