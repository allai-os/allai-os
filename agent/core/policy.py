"""Política de enrutamiento.

Define las preferencias del usuario sobre cuándo usar Claude (cloud) vs
Ollama (local) y cómo se comporta el router ante incertidumbre.

Esta capa es pura — no toca proveedores ni red.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RoutingMode(str, Enum):
    """Modos generales de enrutamiento."""

    AUTO = "auto"
    """Router decide según tarea, costo y privacidad. Default sensato."""

    CLOUD_FIRST = "cloud_first"
    """Prefiere Claude. Cae a Ollama si Claude no está disponible."""

    LOCAL_FIRST = "local_first"
    """Prefiere Ollama. Cae a Claude si el modelo local no puede."""

    CLOUD_ONLY = "cloud_only"
    """Sólo Claude. Falla si no está disponible."""

    LOCAL_ONLY = "local_only"
    """Sólo Ollama. Útil para modo privacy/offline."""


@dataclass(frozen=True, slots=True)
class CostBudget:
    """Presupuesto de costo por sesión y mensual.

    Si la sesión actual ya gastó más que `session_usd`, el router prefiere
    proveedores locales para el resto de turns. Si el mes superó `monthly_usd`,
    se rechaza ir a Claude.

    `None` significa sin tope.
    """

    session_usd: float | None = None
    monthly_usd: float | None = None
    spent_session_usd: float = 0.0
    spent_monthly_usd: float = 0.0

    def session_exhausted(self) -> bool:
        return (
            self.session_usd is not None
            and self.spent_session_usd >= self.session_usd
        )

    def monthly_exhausted(self) -> bool:
        return (
            self.monthly_usd is not None
            and self.spent_monthly_usd >= self.monthly_usd
        )


@dataclass(slots=True)
class RoutingPolicy:
    """Política completa del router.

    `mode` es la preferencia general. Los demás campos son ajustes finos.
    """

    mode: RoutingMode = RoutingMode.AUTO
    """Modo general."""

    force_local_for_pii: bool = True
    """Si se detecta PII en el contenido, fuerza local incluso en CLOUD_FIRST."""

    allow_cloud_fallback_when_offline: bool = False
    """Si está offline, ¿esperamos a que vuelva la red? Por defecto no — caemos a local."""

    preferred_cloud_model: str | None = None
    """Modelo preferido cuando ruteamos a cloud. None = el default del provider."""

    preferred_local_model: str | None = None
    """Modelo preferido cuando ruteamos a local. None = el default del provider."""

    cost_budget: CostBudget = field(default_factory=CostBudget)
    """Tope de costo. Si se agota, se prefiere local."""

    require_vision_when_images_present: bool = True
    """Si la request lleva imágenes, sólo enviar a modelos con visión."""

    require_computer_use_provider: bool = True
    """Si hay ComputerUseTool, enviar a un provider que lo soporte (idealmente nativo)."""

    @classmethod
    def offline(cls) -> RoutingPolicy:
        """Atajo para política offline / privacidad máxima."""
        return cls(mode=RoutingMode.LOCAL_ONLY)

    @classmethod
    def cloud_first(cls) -> RoutingPolicy:
        return cls(mode=RoutingMode.CLOUD_FIRST)

    @classmethod
    def auto(cls) -> RoutingPolicy:
        return cls(mode=RoutingMode.AUTO)
