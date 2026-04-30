"""Provider de Google Gemini (google-genai SDK).

Características:
  - Modelos: Gemini 2.5 Pro, 2.5 Flash, 2.5 Flash-Lite, y el preview de
    Computer Use (ID configurable, los nombres de previews cambian seguido).
  - Vision nativa (Gemini procesa imágenes en cualquier modelo 2.5).
  - Function calling: soporte nativo, lo mapeamos a Tool/ToolUseBlock.
  - Computer Use: se activa cuando la request lleva `ComputerUseTool`. Las
    acciones de Gemini (`click_at`, `type_text_at`, `key_combination`, etc.)
    son distintas de las de Claude (`left_click`, `type`, `key`); en este
    provider devolvemos los `ToolUseBlock` con el nombre tal cual de Gemini
    para que el caller adapte. El prototipo `gemini_loop.py` hace ese mapeo.
  - Context caching todavía no aprovechado (lo activaremos en una iteración
    posterior cuando el flujo de sesión persista contenidos).

google-genai expone un cliente nuevo (`google.genai.Client`). Si tienes el
SDK viejo `google.generativeai`, este provider no lo soporta — instala
`pip install google-genai`.
"""

from __future__ import annotations

import base64
import os
from collections.abc import Iterator
from typing import Any, cast

from core.errors import (
    AuthenticationError,
    InvalidRequestError,
    ProviderError,
    ProviderUnavailableError,
    RateLimitError,
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
    ToolUseStart,
    Usage,
)
from core.provider import ModelInfo, Provider, ProviderCapabilities


# Modelo default y modelo de Computer Use. Estos IDs los puede sobrescribir
# el caller pasando `model=` en la request.
_DEFAULT_MODEL = "gemini-2.5-flash"
_DEFAULT_COMPUTER_USE_MODEL = "gemini-2.5-computer-use-preview-10-2025"

# Modelos vigentes a la fecha de redacción (2026-04). Los costos están en
# USD/M tokens según pricing público de Google.
_MODELS: list[ModelInfo] = [
    ModelInfo(
        id="gemini-2.5-pro",
        context_window=2_000_000,
        max_output_tokens=64_000,
        supports_vision=True,
        supports_tools=True,
        supports_computer_use=False,
        supports_caching=True,
        cost_per_million_input=2.50,
        cost_per_million_output=10.00,
    ),
    ModelInfo(
        id="gemini-2.5-flash",
        context_window=1_000_000,
        max_output_tokens=8_192,
        supports_vision=True,
        supports_tools=True,
        supports_computer_use=False,
        supports_caching=True,
        cost_per_million_input=0.30,
        cost_per_million_output=2.50,
    ),
    ModelInfo(
        id="gemini-2.5-flash-lite",
        context_window=1_000_000,
        max_output_tokens=8_192,
        supports_vision=True,
        supports_tools=True,
        supports_computer_use=False,
        supports_caching=True,
        cost_per_million_input=0.10,
        cost_per_million_output=0.40,
    ),
    ModelInfo(
        id=_DEFAULT_COMPUTER_USE_MODEL,
        context_window=1_000_000,
        max_output_tokens=8_192,
        supports_vision=True,
        supports_tools=True,
        supports_computer_use=True,
        supports_caching=False,
        cost_per_million_input=None,  # preview, sin precio público estable
        cost_per_million_output=None,
    ),
]


_FINISH_REASON_MAP: dict[str, StopReason] = {
    "STOP": "end_turn",
    "MAX_TOKENS": "max_tokens",
    "SAFETY": "error",
    "RECITATION": "error",
    "OTHER": "error",
    "TOOL_USE": "tool_use",
    "FUNCTION_CALL": "tool_use",
}


class GeminiProvider(Provider):
    name = "gemini"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: Any | None = None,
        default_model: str = _DEFAULT_MODEL,
        computer_use_model: str = _DEFAULT_COMPUTER_USE_MODEL,
    ) -> None:
        self._api_key = api_key or os.environ.get("GOOGLE_API_KEY") or os.environ.get(
            "GEMINI_API_KEY"
        )
        self._client: Any | None = client
        self._default_model = default_model
        self._computer_use_model = computer_use_model

    # ─── Capabilities ───────────────────────────────────────────────────────

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            name=self.name,
            supports_streaming=True,
            supports_tools=True,
            supports_vision=True,
            supports_computer_use=True,
            supports_prompt_caching=True,
            is_local=False,
            requires_network=True,
            available_models=list(_MODELS),
        )

    def is_available(self) -> bool:
        return bool(self._api_key) or self._client is not None

    # ─── Chat ───────────────────────────────────────────────────────────────

    def chat(self, request: ChatRequest) -> ChatResponse:
        client = self._get_client()
        params = self._build_params(request)
        try:
            response = client.models.generate_content(**params)
        except Exception as exc:
            self._raise_translated(exc)
        return _decode_response(response, params["model"])

    def chat_stream(self, request: ChatRequest) -> Iterator[StreamEvent]:
        client = self._get_client()
        params = self._build_params(request)
        try:
            stream = client.models.generate_content_stream(**params)
        except Exception as exc:
            self._raise_translated(exc)
        yield from _decode_stream(stream)

    # ─── Internals ──────────────────────────────────────────────────────────

    def _get_client(self) -> Any:
        if self._client is None:
            if not self._api_key:
                raise AuthenticationError(
                    "GOOGLE_API_KEY/GEMINI_API_KEY no configurado", provider=self.name
                )
            try:
                from google import genai
            except ImportError as exc:
                raise ProviderUnavailableError(
                    "instala google-genai: pip install google-genai",
                    provider=self.name,
                ) from exc
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def _build_params(self, request: ChatRequest) -> dict[str, Any]:
        # Elige modelo: si la request lleva ComputerUseTool y no pasaron uno
        # explícitamente, ruteamos al modelo de Computer Use.
        has_computer_use = any(isinstance(t, ComputerUseTool) for t in request.tools)
        model = request.model or (
            self._computer_use_model if has_computer_use else self._default_model
        )

        contents = _encode_contents(request.messages)
        config = self._build_config(request, has_computer_use)

        params: dict[str, Any] = {
            "model": model,
            "contents": contents,
        }
        if config is not None:
            params["config"] = config

        # Permite que `extra` agregue campos específicos del SDK.
        params.update(request.extra)
        return params

    def _build_config(
        self, request: ChatRequest, has_computer_use: bool
    ) -> Any | None:
        try:
            from google.genai import types
        except ImportError:
            return None

        kwargs: dict[str, Any] = {}
        if request.system:
            kwargs["system_instruction"] = request.system
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.max_tokens:
            kwargs["max_output_tokens"] = request.max_tokens

        gemini_tools = _encode_tools(request.tools, types, has_computer_use)
        if gemini_tools:
            kwargs["tools"] = gemini_tools

        if not kwargs:
            return None
        return types.GenerateContentConfig(**kwargs)

    def _raise_translated(self, exc: Exception) -> None:
        """Traduce excepciones del SDK a nuestra jerarquía y propaga."""
        message = str(exc)
        status = _extract_status(exc)
        if status == 401 or "authentication" in message.lower() or "api key" in message.lower():
            raise AuthenticationError(message, provider=self.name) from exc
        if status == 429 or "rate" in message.lower() or "quota" in message.lower():
            raise RateLimitError(message, provider=self.name) from exc
        if status == 400 or "invalid" in message.lower():
            raise InvalidRequestError(message, provider=self.name) from exc
        if isinstance(exc, ConnectionError) or "connection" in message.lower():
            raise ProviderUnavailableError(message, provider=self.name) from exc
        raise ProviderError(message, provider=self.name, status_code=status) from exc


# ─── Encoding ───────────────────────────────────────────────────────────────


def _encode_contents(messages: list[Message]) -> list[Any]:
    """Convierte nuestros Messages al formato `Content` de Gemini.

    Gemini usa role `user` / `model`. Roles `system` van por `system_instruction`
    aparte (lo encarga `_build_config`).
    """
    try:
        from google.genai import types
    except ImportError:
        # Fallback: dicts crudos. El SDK suele aceptarlos también.
        return [_encode_message_dict(m) for m in messages]

    out: list[Any] = []
    for msg in messages:
        if msg.role == "system":
            raise InvalidRequestError(
                "El rol 'system' debe ir en ChatRequest.system, no en messages",
                provider="gemini",
            )
        role = "model" if msg.role == "assistant" else "user"
        parts = [_encode_block_to_part(b, types) for b in msg.content]
        out.append(types.Content(role=role, parts=parts))
    return out


def _encode_message_dict(message: Message) -> dict[str, Any]:
    role = "model" if message.role == "assistant" else "user"
    return {
        "role": role,
        "parts": [_encode_block_to_dict(b) for b in message.content],
    }


def _encode_block_to_part(block: ContentBlock, types: Any) -> Any:
    if isinstance(block, TextBlock):
        return types.Part(text=block.text)
    if isinstance(block, ImageBlock):
        return types.Part(
            inline_data=types.Blob(mime_type=block.mime, data=block.data)
        )
    if isinstance(block, ToolUseBlock):
        return types.Part(
            function_call=types.FunctionCall(name=block.name, args=block.input)
        )
    if isinstance(block, ToolResultBlock):
        if isinstance(block.content, str):
            response = {"output": block.content}
        else:
            response = {
                "output": "\n".join(
                    b.text for b in block.content if isinstance(b, TextBlock)
                ),
                "images": [
                    base64.b64encode(b.data).decode("ascii")
                    for b in block.content
                    if isinstance(b, ImageBlock)
                ]
                or None,
            }
        return types.Part(
            function_response=types.FunctionResponse(
                name=_lookup_function_name(block, fallback=""),
                response=response,
            )
        )
    raise InvalidRequestError(f"bloque desconocido: {type(block).__name__}")


def _encode_block_to_dict(block: ContentBlock) -> dict[str, Any]:
    if isinstance(block, TextBlock):
        return {"text": block.text}
    if isinstance(block, ImageBlock):
        return {
            "inline_data": {
                "mime_type": block.mime,
                "data": base64.b64encode(block.data).decode("ascii"),
            }
        }
    if isinstance(block, ToolUseBlock):
        return {"function_call": {"name": block.name, "args": block.input}}
    if isinstance(block, ToolResultBlock):
        if isinstance(block.content, str):
            response = {"output": block.content}
        else:
            response = {
                "output": "\n".join(
                    b.text for b in block.content if isinstance(b, TextBlock)
                ),
            }
        return {
            "function_response": {
                "name": _lookup_function_name(block, fallback=""),
                "response": response,
            }
        }
    raise InvalidRequestError(f"bloque desconocido: {type(block).__name__}")


def _lookup_function_name(block: ToolResultBlock, fallback: str) -> str:
    """Gemini exige `name` en function_response. Como nuestro ToolResultBlock
    sólo guarda `tool_use_id`, usamos el id como fallback. El caller que
    quiera fidelidad puede agregar el name al construir el block (queda como
    deuda menor — la conversión inversa funciona)."""
    return block.tool_use_id or fallback


def _encode_tools(
    tools: list[Tool | ComputerUseTool],
    types: Any,
    has_computer_use: bool,
) -> list[Any]:
    out: list[Any] = []

    function_declarations = []
    for t in tools:
        if isinstance(t, Tool):
            function_declarations.append(
                types.FunctionDeclaration(
                    name=t.name,
                    description=t.description,
                    parameters_json_schema=t.input_schema,
                )
            )

    if function_declarations:
        out.append(types.Tool(function_declarations=function_declarations))

    if has_computer_use:
        # `ComputerUse` es un tool especial de Gemini con `environment` y
        # `excluded_predefined_functions` opcional. Aquí elegimos browser por
        # ser el caso más común; el desktop variant también existe.
        try:
            cu = types.ComputerUse(environment="ENVIRONMENT_BROWSER")
        except (TypeError, AttributeError):
            # Versión del SDK que aún no tiene `ComputerUse` — saltamos.
            return out
        out.append(types.Tool(computer_use=cu))

    return out


# ─── Decoding ───────────────────────────────────────────────────────────────


def _decode_response(response: Any, model: str) -> ChatResponse:
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return ChatResponse(
            content=[],
            stop_reason="error",
            usage=_extract_usage(response),
            model=model,
            raw=response,
        )

    candidate = candidates[0]
    content_obj = getattr(candidate, "content", None)
    parts = getattr(content_obj, "parts", []) if content_obj else []

    blocks: list[ContentBlock] = []
    saw_function_call = False
    for part in parts or []:
        text = getattr(part, "text", None)
        function_call = getattr(part, "function_call", None)
        if text:
            blocks.append(TextBlock(text=text))
        if function_call is not None and getattr(function_call, "name", None):
            saw_function_call = True
            args = getattr(function_call, "args", None) or {}
            if not isinstance(args, dict):
                args = dict(args)
            blocks.append(
                ToolUseBlock(
                    id=str(getattr(function_call, "id", "") or function_call.name),
                    name=function_call.name,
                    input=args,
                )
            )

    finish = getattr(candidate, "finish_reason", None)
    finish_str = (
        finish.name if hasattr(finish, "name") else (str(finish) if finish else "STOP")
    ).upper()
    stop_reason: StopReason = (
        "tool_use"
        if saw_function_call
        else _FINISH_REASON_MAP.get(finish_str, "end_turn")
    )

    return ChatResponse(
        content=blocks,
        stop_reason=stop_reason,
        usage=_extract_usage(response),
        model=model,
        raw=response,
    )


def _decode_stream(stream: Any) -> Iterator[StreamEvent]:
    final_usage = Usage()
    final_stop: StopReason = "end_turn"
    saw_tool = False

    for chunk in stream:
        candidates = getattr(chunk, "candidates", None) or []
        if not candidates:
            continue
        candidate = candidates[0]
        content_obj = getattr(candidate, "content", None)
        parts = getattr(content_obj, "parts", []) if content_obj else []
        for part in parts or []:
            text = getattr(part, "text", None)
            if text:
                yield TextDelta(text=text)
            fc = getattr(part, "function_call", None)
            if fc is not None and getattr(fc, "name", None):
                saw_tool = True
                yield ToolUseStart(
                    id=str(getattr(fc, "id", "") or fc.name),
                    name=fc.name,
                )

        finish = getattr(candidate, "finish_reason", None)
        if finish:
            finish_str = (
                finish.name if hasattr(finish, "name") else str(finish)
            ).upper()
            if saw_tool:
                final_stop = "tool_use"
            else:
                final_stop = _FINISH_REASON_MAP.get(finish_str, "end_turn")

        usage = _extract_usage(chunk)
        if usage.total_tokens > 0:
            final_usage = usage

    yield MessageStop(stop_reason=final_stop, usage=final_usage)


def _extract_usage(response: Any) -> Usage:
    metadata = getattr(response, "usage_metadata", None)
    if metadata is None:
        return Usage()
    return Usage(
        input_tokens=getattr(metadata, "prompt_token_count", 0) or 0,
        output_tokens=getattr(metadata, "candidates_token_count", 0) or 0,
        cache_read_tokens=getattr(metadata, "cached_content_token_count", 0) or 0,
    )


def _extract_status(exc: Exception) -> int | None:
    for attr in ("status_code", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    if response is not None:
        return cast("int | None", getattr(response, "status_code", None))
    return None
