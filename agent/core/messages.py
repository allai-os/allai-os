"""Tipos de mensajes provider-agnostic.

Filosofía: un único modelo de mensajes que cualquier provider puede traducir
desde/hacia su formato nativo. Esta capa la usan el router y los tools sin
saber de Claude ni de Ollama.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["user", "assistant", "system"]
StopReason = Literal["end_turn", "tool_use", "max_tokens", "stop_sequence", "error"]


# ─── Content blocks ─────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class TextBlock:
    """Texto plano. `cache=True` sugiere al provider que lo cachee si puede."""

    text: str
    cache: bool = False


@dataclass(frozen=True, slots=True)
class ImageBlock:
    """Imagen como bytes raw. El provider la codificará según necesite."""

    data: bytes
    mime: str = "image/png"


@dataclass(frozen=True, slots=True)
class ToolUseBlock:
    """Una invocación de tool emitida por el modelo."""

    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolResultBlock:
    """Resultado de ejecutar un tool, devuelto al modelo en el siguiente turno.

    `content` puede ser texto o una mezcla de texto + imágenes (ej. screenshots).
    """

    tool_use_id: str
    content: str | list[TextBlock | ImageBlock]
    is_error: bool = False


ContentBlock = TextBlock | ImageBlock | ToolUseBlock | ToolResultBlock


# ─── Mensajes ───────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: list[ContentBlock]


# ─── Tools ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Tool:
    """Tool genérico declarado al modelo."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ComputerUseTool:
    """Tool especial de control de escritorio. Algunos providers (Claude) tienen
    soporte nativo; otros (Ollama) requieren emulación con prompt + JSON.

    Las dimensiones se reportan al modelo para que coordene clicks correctos.
    """

    display_width_px: int
    display_height_px: int
    display_number: int = 1


# ─── Streaming events ───────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class TextDelta:
    text: str


@dataclass(frozen=True, slots=True)
class ToolUseStart:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class ToolUseDelta:
    """Delta JSON parcial de los argumentos de un tool en streaming."""

    partial_json: str


@dataclass(frozen=True, slots=True)
class MessageStop:
    stop_reason: StopReason
    usage: Usage


StreamEvent = TextDelta | ToolUseStart | ToolUseDelta | MessageStop


# ─── Usage ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
        )


# ─── Request / response ─────────────────────────────────────────────────────


@dataclass(slots=True)
class ChatRequest:
    """Request a un provider.

    `system` se pasa por separado en lugar de mezclado en `messages` porque
    cada provider maneja el system prompt distinto.
    """

    messages: list[Message]
    system: str | None = None
    tools: list[Tool | ComputerUseTool] = field(default_factory=list)
    max_tokens: int = 4096
    temperature: float | None = None
    model: str | None = None
    # `extra` es escotilla de escape para opciones específicas del provider
    # (ej. betas de Anthropic, format=json de Ollama). Idealmente vacía.
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChatResponse:
    content: list[ContentBlock]
    stop_reason: StopReason
    usage: Usage
    model: str
    # Acceso al objeto crudo del provider (útil para debug, no en lógica de negocio).
    raw: Any | None = None

    @property
    def text(self) -> str:
        """Concatena todos los TextBlock del response. Útil para casos simples."""
        return "\n".join(b.text for b in self.content if isinstance(b, TextBlock))

    @property
    def tool_uses(self) -> list[ToolUseBlock]:
        return [b for b in self.content if isinstance(b, ToolUseBlock)]
