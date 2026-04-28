"""Clasificación heurística de tareas para guiar al router.

Ante una `ChatRequest`, decide qué tipo de tarea es (visión, computer use,
chat de texto, uso de tools) y qué requisitos mínimos debe cumplir el modelo.

No analiza la intención semántica del prompt — eso lo hace el modelo. Sólo
mira la forma estructural de la request: qué blocks contiene, qué tools
declara, etc.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core.messages import (
    ChatRequest,
    ComputerUseTool,
    ImageBlock,
    Tool,
    ToolUseBlock,
)


class TaskKind(str, Enum):
    COMPUTER_USE = "computer_use"
    """La request lleva ComputerUseTool — controla el escritorio."""

    VISION = "vision"
    """Lleva imágenes pero no Computer Use — análisis o conversación con imágenes."""

    TOOL_CHAIN = "tool_chain"
    """Tools normales declarados, sin Computer Use."""

    PLAIN_CHAT = "plain_chat"
    """Solo texto, sin tools, sin imágenes."""


@dataclass(frozen=True, slots=True)
class TaskHints:
    """Pistas opcionales que el caller puede pasar al router.

    Permite al usuario forzar privacidad por mensaje individual ("este es
    sensible aunque no detecte PII") o pedir explícitamente cloud/local.
    """

    private: bool = False
    """Forzar local."""

    prefer_cloud: bool = False
    prefer_local: bool = False


@dataclass(frozen=True, slots=True)
class TaskProfile:
    """Resumen de qué necesita esta tarea para correr bien."""

    kind: TaskKind
    needs_vision: bool
    needs_tools: bool
    needs_computer_use: bool
    has_images: bool
    has_tool_uses_in_history: bool
    """True si la conversación ya tiene tool_use blocks — el provider debe
    soportar respuestas continuando esos tool calls."""


def classify(request: ChatRequest) -> TaskProfile:
    has_computer = any(isinstance(t, ComputerUseTool) for t in request.tools)
    has_normal_tools = any(isinstance(t, Tool) for t in request.tools)
    has_images = any(
        isinstance(b, ImageBlock) for m in request.messages for b in m.content
    )
    has_history_tool_uses = any(
        isinstance(b, ToolUseBlock) for m in request.messages for b in m.content
    )

    if has_computer:
        kind = TaskKind.COMPUTER_USE
    elif has_images:
        kind = TaskKind.VISION
    elif has_normal_tools or has_history_tool_uses:
        kind = TaskKind.TOOL_CHAIN
    else:
        kind = TaskKind.PLAIN_CHAT

    return TaskProfile(
        kind=kind,
        needs_vision=has_images,
        needs_tools=has_normal_tools or has_history_tool_uses,
        needs_computer_use=has_computer,
        has_images=has_images,
        has_tool_uses_in_history=has_history_tool_uses,
    )
