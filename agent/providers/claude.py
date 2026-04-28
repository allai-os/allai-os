"""Provider de Claude (Anthropic).

Características:
  - Soporta los 3 modelos vigentes: Opus 4.7, Sonnet 4.6, Haiku 4.5.
  - Prompt caching automático en system prompt y tool definitions.
  - Computer Use tool (`computer_20250124`) cuando el request lo incluye.
  - Streaming con `messages.stream`.
"""

from __future__ import annotations

import base64
import os
from collections.abc import Iterator
from typing import Any, cast

import anthropic
from anthropic import Anthropic
from anthropic._exceptions import (
    APIConnectionError,
    APIStatusError,
    AuthenticationError as AnthropicAuthError,
    RateLimitError as AnthropicRateLimitError,
)

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
    ToolUseDelta,
    ToolUseStart,
    Usage,
)
from core.provider import ModelInfo, Provider, ProviderCapabilities


COMPUTER_USE_TOOL_TYPE = "computer_20250124"
COMPUTER_USE_BETA = "computer-use-2025-01-24"
PROMPT_CACHING_BETA = "prompt-caching-2024-07-31"


# Modelos canónicos. Costo aproximado USD/M tokens.
_MODELS: list[ModelInfo] = [
    ModelInfo(
        id="claude-opus-4-7",
        context_window=200_000,
        max_output_tokens=32_000,
        supports_vision=True,
        supports_tools=True,
        supports_computer_use=True,
        supports_caching=True,
        cost_per_million_input=15.0,
        cost_per_million_output=75.0,
    ),
    ModelInfo(
        id="claude-sonnet-4-6",
        context_window=200_000,
        max_output_tokens=64_000,
        supports_vision=True,
        supports_tools=True,
        supports_computer_use=True,
        supports_caching=True,
        cost_per_million_input=3.0,
        cost_per_million_output=15.0,
    ),
    ModelInfo(
        id="claude-haiku-4-5-20251001",
        context_window=200_000,
        max_output_tokens=8_000,
        supports_vision=True,
        supports_tools=True,
        supports_computer_use=False,
        supports_caching=True,
        cost_per_million_input=0.80,
        cost_per_million_output=4.0,
    ),
]
_DEFAULT_MODEL = "claude-opus-4-7"


_STOP_REASON_MAP: dict[str, StopReason] = {
    "end_turn": "end_turn",
    "tool_use": "tool_use",
    "max_tokens": "max_tokens",
    "stop_sequence": "stop_sequence",
}


class ClaudeProvider(Provider):
    name = "claude"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: Anthropic | None = None,
        default_model: str = _DEFAULT_MODEL,
        enable_prompt_caching: bool = True,
    ) -> None:
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._client: Anthropic | None = client
        self._default_model = default_model
        self._enable_caching = enable_prompt_caching

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
            response = client.messages.create(**params)
        except AnthropicAuthError as exc:
            raise AuthenticationError(str(exc), provider=self.name) from exc
        except AnthropicRateLimitError as exc:
            retry_after = _retry_after_from_headers(getattr(exc, "response", None))
            raise RateLimitError(
                str(exc), provider=self.name, retry_after=retry_after
            ) from exc
        except APIConnectionError as exc:
            raise ProviderUnavailableError(str(exc), provider=self.name) from exc
        except APIStatusError as exc:
            if exc.status_code == 400:
                raise InvalidRequestError(str(exc), provider=self.name) from exc
            raise ProviderError(
                str(exc), provider=self.name, status_code=exc.status_code
            ) from exc

        return _decode_response(response)

    def chat_stream(self, request: ChatRequest) -> Iterator[StreamEvent]:
        client = self._get_client()
        params = self._build_params(request)
        try:
            with client.messages.stream(**params) as stream:
                yield from _decode_stream(stream)
        except AnthropicAuthError as exc:
            raise AuthenticationError(str(exc), provider=self.name) from exc
        except AnthropicRateLimitError as exc:
            retry_after = _retry_after_from_headers(getattr(exc, "response", None))
            raise RateLimitError(
                str(exc), provider=self.name, retry_after=retry_after
            ) from exc
        except APIConnectionError as exc:
            raise ProviderUnavailableError(str(exc), provider=self.name) from exc

    # ─── Internals ──────────────────────────────────────────────────────────

    def _get_client(self) -> Anthropic:
        if self._client is None:
            if not self._api_key:
                raise AuthenticationError(
                    "ANTHROPIC_API_KEY no configurado", provider=self.name
                )
            self._client = Anthropic(api_key=self._api_key)
        return self._client

    def _build_params(self, request: ChatRequest) -> dict[str, Any]:
        model = request.model or self._default_model

        anthropic_messages = [_encode_message(m) for m in request.messages]
        anthropic_tools = self._encode_tools(request.tools)
        system = self._encode_system(request.system)

        params: dict[str, Any] = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": request.max_tokens,
        }
        if system is not None:
            params["system"] = system
        if anthropic_tools:
            params["tools"] = anthropic_tools
        if request.temperature is not None:
            params["temperature"] = request.temperature

        betas = self._collect_betas(request)
        if betas:
            params["betas"] = list(betas)

        # extra wins over our defaults intentionally; allows escape hatch
        params.update(request.extra)
        return params

    def _encode_tools(
        self, tools: list[Tool | ComputerUseTool]
    ) -> list[dict[str, Any]]:
        encoded: list[dict[str, Any]] = []
        for tool in tools:
            if isinstance(tool, ComputerUseTool):
                encoded.append(
                    {
                        "type": COMPUTER_USE_TOOL_TYPE,
                        "name": "computer",
                        "display_width_px": tool.display_width_px,
                        "display_height_px": tool.display_height_px,
                        "display_number": tool.display_number,
                    }
                )
            else:
                entry: dict[str, Any] = {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                }
                encoded.append(entry)

        # Cachear el último tool definition aprovecha el cache de prefijo de
        # Anthropic: si los tools no cambian entre turnos, los releemos del cache.
        if self._enable_caching and encoded:
            encoded[-1] = {**encoded[-1], "cache_control": {"type": "ephemeral"}}
        return encoded

    def _encode_system(self, system: str | None) -> list[dict[str, Any]] | None:
        if not system:
            return None
        block: dict[str, Any] = {"type": "text", "text": system}
        if self._enable_caching:
            block["cache_control"] = {"type": "ephemeral"}
        return [block]

    def _collect_betas(self, request: ChatRequest) -> set[str]:
        betas: set[str] = set()
        if any(isinstance(t, ComputerUseTool) for t in request.tools):
            betas.add(COMPUTER_USE_BETA)
        # PROMPT_CACHING_BETA está GA en SDK actual, no necesitamos pedirlo
        # explícitamente, pero lo exponemos por si la API lo requiere.
        # Lo omitimos para evitar warnings.
        return betas


# ─── Encoding / decoding ────────────────────────────────────────────────────


def _encode_message(message: Message) -> dict[str, Any]:
    if message.role == "system":
        # System se pasa por param `system`, no en messages.
        raise InvalidRequestError(
            "El rol 'system' debe ir en ChatRequest.system, no en messages",
            provider="claude",
        )
    return {
        "role": message.role,
        "content": [_encode_block(b) for b in message.content],
    }


def _encode_block(block: ContentBlock) -> dict[str, Any]:
    if isinstance(block, TextBlock):
        out: dict[str, Any] = {"type": "text", "text": block.text}
        if block.cache:
            out["cache_control"] = {"type": "ephemeral"}
        return out
    if isinstance(block, ImageBlock):
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": block.mime,
                "data": base64.b64encode(block.data).decode("ascii"),
            },
        }
    if isinstance(block, ToolUseBlock):
        return {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": block.input,
        }
    if isinstance(block, ToolResultBlock):
        out_result: dict[str, Any] = {
            "type": "tool_result",
            "tool_use_id": block.tool_use_id,
            "is_error": block.is_error,
        }
        if isinstance(block.content, str):
            out_result["content"] = block.content
        else:
            out_result["content"] = [_encode_block(b) for b in block.content]
        return out_result
    raise InvalidRequestError(f"bloque desconocido: {type(block).__name__}")


def _decode_response(response: anthropic.types.Message) -> ChatResponse:
    blocks: list[ContentBlock] = []
    for raw in response.content:
        block_type = getattr(raw, "type", None)
        if block_type == "text":
            blocks.append(TextBlock(text=raw.text))  # type: ignore[union-attr]
        elif block_type == "tool_use":
            tu = cast("anthropic.types.ToolUseBlock", raw)
            blocks.append(
                ToolUseBlock(
                    id=tu.id,
                    name=tu.name,
                    input=cast("dict[str, Any]", tu.input),
                )
            )

    usage = response.usage
    decoded_usage = Usage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
    )

    stop_reason = _STOP_REASON_MAP.get(response.stop_reason or "end_turn", "error")
    return ChatResponse(
        content=blocks,
        stop_reason=stop_reason,
        usage=decoded_usage,
        model=response.model,
        raw=response,
    )


def _decode_stream(stream: Any) -> Iterator[StreamEvent]:
    """Traduce los eventos del SDK de Anthropic a nuestros StreamEvent."""
    pending_tool: dict[int, dict[str, Any]] = {}
    final_usage = Usage()
    final_stop: StopReason = "end_turn"

    for event in stream:
        kind = getattr(event, "type", "")
        if kind == "content_block_start":
            block = event.content_block
            if block.type == "tool_use":
                pending_tool[event.index] = {"id": block.id, "name": block.name}
                yield ToolUseStart(id=block.id, name=block.name)
        elif kind == "content_block_delta":
            delta = event.delta
            if delta.type == "text_delta":
                yield TextDelta(text=delta.text)
            elif delta.type == "input_json_delta":
                yield ToolUseDelta(partial_json=delta.partial_json)
        elif kind == "message_delta":
            sr = getattr(event.delta, "stop_reason", None)
            if sr:
                final_stop = _STOP_REASON_MAP.get(sr, "error")
            usage_obj = getattr(event, "usage", None)
            if usage_obj is not None:
                final_usage = Usage(
                    input_tokens=getattr(usage_obj, "input_tokens", 0) or 0,
                    output_tokens=getattr(usage_obj, "output_tokens", 0) or 0,
                    cache_read_tokens=getattr(usage_obj, "cache_read_input_tokens", 0)
                    or 0,
                    cache_write_tokens=getattr(
                        usage_obj, "cache_creation_input_tokens", 0
                    )
                    or 0,
                )
        elif kind == "message_stop":
            yield MessageStop(stop_reason=final_stop, usage=final_usage)
            return

    # Si el stream terminó sin message_stop explícito
    yield MessageStop(stop_reason=final_stop, usage=final_usage)


def _retry_after_from_headers(response: Any) -> float | None:
    if response is None:
        return None
    try:
        headers = response.headers
    except AttributeError:
        return None
    raw = headers.get("retry-after") if hasattr(headers, "get") else None
    if not raw:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None
