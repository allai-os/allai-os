"""Tipos base del registro de tools.

Define el contrato declarativo: qué es un tool, qué nivel de riesgo tiene,
qué capabilities requiere, qué entrada acepta y qué resultado produce.

Las implementaciones concretas viven en sus respectivos módulos
(`screen.py`, `mouse.py`, etc.).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.messages import ImageBlock, TextBlock


class RiskLevel(str, Enum):
    """Niveles de riesgo de una acción.

    Definidos en docs/AI_ETHICS.md y docs/architecture.md (pipeline de seguridad).

    - SAFE: read-only o cambios reversibles triviales. Sólo necesita capability.
    - CONFIRM: cambios reversibles con efecto, primer uso o "always-ask" piden ok.
    - DANGEROUS: irreversible o con impacto a terceros. Confirmación humana
      obligatoria en cada uso, sin excepción ni configuración que la salte.
    """

    SAFE = "safe"
    CONFIRM = "confirm"
    DANGEROUS = "dangerous"


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Definición declarativa de un tool.

    El campo `input_schema` es JSON Schema, que se pasa al provider tal cual.
    `executor` es la función concreta que ejecuta. `capabilities_required`
    lista los capability strings que la sesión debe tener (ej. `read-fs:~`).
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    risk: RiskLevel
    executor: Callable[..., ToolResult]
    capabilities_required: list[str] = field(default_factory=list)
    category: str = "misc"
    """Para agrupar en UI: 'screen', 'input', 'shell', 'fs', etc."""


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Resultado de ejecutar un tool.

    `output` es lo que se devuelve al modelo en el `ToolResultBlock`.
    Si hay imágenes (screenshots), se incluyen como bloques.
    """

    output: str = ""
    images: list[bytes] = field(default_factory=list)
    """Cada bytes es un PNG. El executor las traduce a ImageBlock."""

    structured: dict[str, Any] | None = None
    """Datos estructurados que el modelo puede no necesitar pero el caller sí."""

    is_error: bool = False
    duration_ms: float = 0.0

    def to_blocks(self) -> list[TextBlock | ImageBlock]:
        """Convierte el resultado en blocks para inyectar en un ToolResultBlock."""
        blocks: list[TextBlock | ImageBlock] = []
        if self.output:
            blocks.append(TextBlock(text=self.output))
        for png in self.images:
            blocks.append(ImageBlock(data=png, mime="image/png"))
        return blocks


# ─── Errores ────────────────────────────────────────────────────────────────


class ToolError(Exception):
    """Base de errores de tool."""


class ToolNotFoundError(ToolError):
    """No existe un tool con ese nombre en el registro."""


class ToolValidationError(ToolError):
    """La entrada no pasó la validación contra el schema."""


class CapabilityDeniedError(ToolError):
    """El usuario no concedió alguna capability requerida."""

    def __init__(self, capability: str) -> None:
        super().__init__(f"capability denegada: {capability}")
        self.capability = capability


class ConfirmationDeniedError(ToolError):
    """El usuario rechazó confirmar una acción de riesgo."""

    def __init__(self, tool_name: str, risk: RiskLevel) -> None:
        super().__init__(f"el usuario denegó la acción {tool_name} (riesgo={risk.value})")
        self.tool_name = tool_name
        self.risk = risk
