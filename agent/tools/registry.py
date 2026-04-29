"""Registro central de tools.

Permite descubrir, listar y obtener `ToolDefinition`s. Genera la lista de
`core.Tool` que se envía al provider. Las implementaciones concretas se
auto-registran al importar sus módulos.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from core.messages import Tool as ProviderTool
from tools.base import RiskLevel, ToolDefinition, ToolNotFoundError


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    # ─── Registro ───────────────────────────────────────────────────────────

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._tools:
            raise ValueError(f"tool ya registrado: {definition.name}")
        self._tools[definition.name] = definition

    def replace(self, definition: ToolDefinition) -> None:
        """Re-registra (útil en tests)."""
        self._tools[definition.name] = definition

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def clear(self) -> None:
        self._tools.clear()

    # ─── Acceso ─────────────────────────────────────────────────────────────

    def get(self, name: str) -> ToolDefinition:
        if name not in self._tools:
            raise ToolNotFoundError(f"tool desconocido: {name}")
        return self._tools[name]

    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return sorted(self._tools.keys())

    def __iter__(self) -> Iterator[ToolDefinition]:
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    # ─── Filtros ────────────────────────────────────────────────────────────

    def by_risk(self, *risks: RiskLevel) -> list[ToolDefinition]:
        wanted = set(risks)
        return [t for t in self._tools.values() if t.risk in wanted]

    def by_category(self, category: str) -> list[ToolDefinition]:
        return [t for t in self._tools.values() if t.category == category]

    # ─── Exposición al modelo ───────────────────────────────────────────────

    def to_provider_tools(
        self, only: Iterable[str] | None = None
    ) -> list[ProviderTool]:
        """Convierte las definiciones a `core.Tool` para enviar al provider.

        `only` permite filtrar por nombre (ej. cuando una sesión sólo quiere
        exponer un subset).
        """
        names = set(only) if only is not None else None
        out: list[ProviderTool] = []
        for definition in self._tools.values():
            if names is not None and definition.name not in names:
                continue
            out.append(
                ProviderTool(
                    name=definition.name,
                    description=definition.description,
                    input_schema=definition.input_schema,
                )
            )
        return out


# ─── Registro global ────────────────────────────────────────────────────────


_default = ToolRegistry()


def default_registry() -> ToolRegistry:
    """Devuelve el registro global por defecto.

    Las implementaciones de tools se auto-registran aquí al importarse.
    Para tests o sesiones aisladas, instancia un `ToolRegistry()` propio.
    """
    return _default


def register(definition: ToolDefinition) -> ToolDefinition:
    """Conveniencia para módulos: `register(ToolDefinition(...))`."""
    _default.register(definition)
    return definition
