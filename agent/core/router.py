"""Router híbrido: decide proveedor y modelo en cada request.

Implementa la lógica descrita en [ADR-001](../docs/adr/0001-lenguaje-agente-core.md)
y [docs/architecture.md](../../docs/architecture.md): Claude por defecto cuando
está disponible y la tarea lo requiere; Ollama cuando no hay red, no hay clave,
el contenido es sensible o el usuario lo prefiere.

El router NO ejecuta tools. Solo elige adónde mandar la request. El loop de
agente (fase Launch) ejecuta y vuelve a llamar al router con cada turn.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Final

from core.errors import ProviderError, ProviderUnavailableError
from core.messages import ChatRequest, ChatResponse, MessageStop, StreamEvent
from core.policy import RoutingMode, RoutingPolicy
from core.privacy import PIIMatch, detect_pii_in_messages
from core.provider import ModelInfo, Provider
from core.task_classifier import TaskHints, TaskKind, TaskProfile, classify


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RoutingCandidate:
    provider: Provider
    model: str


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """Resultado de planear una request.

    `chain` es la secuencia primaria → fallback que el router intentará en
    orden. `reason` es una explicación corta y humana, útil para audit log
    y para el indicador "¿por qué se usó este modelo?".
    """

    chain: list[RoutingCandidate]
    reason: str
    task: TaskProfile
    pii_detected: list[PIIMatch] = field(default_factory=list)

    @property
    def primary(self) -> RoutingCandidate:
        return self.chain[0]


_REASON_PRIVATE: Final = "contenido sensible detectado → forzando local"
_REASON_HINT_PRIVATE: Final = "hint=private → forzando local"
_REASON_LOCAL_ONLY: Final = "policy=local_only"
_REASON_CLOUD_ONLY: Final = "policy=cloud_only"
_REASON_BUDGET_EXHAUSTED: Final = "presupuesto cloud agotado → local"
_REASON_OFFLINE: Final = "cloud no disponible → local"
_REASON_COMPUTER_USE_NATIVE: Final = "computer_use → cloud (soporte nativo)"
_REASON_VISION: Final = "imágenes presentes → modelo con visión"
_REASON_AUTO_CLOUD: Final = "policy=auto → cloud por capacidad"
_REASON_AUTO_LOCAL: Final = "policy=auto → local suficiente"
_REASON_CLOUD_FIRST: Final = "policy=cloud_first"
_REASON_LOCAL_FIRST: Final = "policy=local_first"


class NoProviderAvailableError(ProviderError):
    """Ningún provider de los registrados puede atender esta request."""


class Router:
    """Selecciona el proveedor y modelo para cada request.

    Constructor:
      - `providers`: instancias listas (uno por backend conocido).
      - `policy`: política activa.

    Uso:
      - `route(request)` → `RoutingDecision` (no ejecuta nada).
      - `chat(request)` → `ChatResponse` (ejecuta con fallback automático).
      - `chat_stream(request)` → `Iterator[StreamEvent]`.
    """

    def __init__(
        self,
        providers: list[Provider],
        policy: RoutingPolicy | None = None,
    ) -> None:
        if not providers:
            raise ValueError("router necesita al menos un provider")
        self._providers: dict[str, Provider] = {p.name: p for p in providers}
        self._policy = policy or RoutingPolicy.auto()

    @property
    def policy(self) -> RoutingPolicy:
        return self._policy

    def set_policy(self, policy: RoutingPolicy) -> None:
        self._policy = policy

    # ─── Decisión ───────────────────────────────────────────────────────────

    def route(
        self,
        request: ChatRequest,
        hints: TaskHints | None = None,
    ) -> RoutingDecision:
        """Calcula a quién mandar la request, sin ejecutarla.

        Esta función es pura excepto por consultar `is_available()` y
        `capabilities()` de los proveedores.
        """
        hints = hints or TaskHints()
        task = classify(request)
        pii = detect_pii_in_messages(request.messages)

        force_local, reason_for_force = self._must_force_local(hints, pii)
        if force_local:
            chain = self._build_local_chain(task, request)
            if not chain:
                raise NoProviderAvailableError(
                    f"{reason_for_force} pero ningún provider local cumple los requisitos"
                )
            return RoutingDecision(
                chain=chain, reason=reason_for_force, task=task, pii_detected=pii
            )

        force_cloud, reason_force_cloud = self._must_force_cloud()
        if force_cloud:
            chain = self._build_cloud_chain(task, request)
            if not chain:
                raise NoProviderAvailableError(
                    f"{reason_force_cloud} pero ningún provider cloud cumple los requisitos"
                )
            return RoutingDecision(
                chain=chain, reason=reason_force_cloud, task=task, pii_detected=pii
            )

        chain, reason = self._plan(task, request)
        if not chain:
            raise NoProviderAvailableError(
                "Ningún provider disponible cumple los requisitos de la tarea"
            )
        return RoutingDecision(chain=chain, reason=reason, task=task, pii_detected=pii)

    # ─── Ejecución con fallback ─────────────────────────────────────────────

    def chat(
        self,
        request: ChatRequest,
        hints: TaskHints | None = None,
    ) -> ChatResponse:
        decision = self.route(request, hints)
        last_error: Exception | None = None
        for candidate in decision.chain:
            scoped = self._scope_request_to_model(request, candidate.model)
            logger.debug(
                "router.chat trying provider=%s model=%s reason=%s",
                candidate.provider.name,
                candidate.model,
                decision.reason,
            )
            try:
                return candidate.provider.chat(scoped)
            except ProviderUnavailableError as exc:
                last_error = exc
                logger.warning(
                    "router.chat provider %s unavailable, trying fallback",
                    candidate.provider.name,
                )
                continue
            except ProviderError as exc:
                # Errores de auth/rate limit/etc. propagan inmediatamente —
                # no son problema de disponibilidad.
                raise exc
        raise NoProviderAvailableError(
            f"todos los proveedores fallaron: {last_error}",
            cause=last_error,
        )

    def chat_stream(
        self,
        request: ChatRequest,
        hints: TaskHints | None = None,
    ) -> Iterator[StreamEvent]:
        decision = self.route(request, hints)
        last_error: Exception | None = None
        for candidate in decision.chain:
            scoped = self._scope_request_to_model(request, candidate.model)
            try:
                stream = candidate.provider.chat_stream(scoped)
                yield from stream
                return
            except ProviderUnavailableError as exc:
                last_error = exc
                continue
            except ProviderError:
                raise
        raise NoProviderAvailableError(
            f"todos los proveedores fallaron en streaming: {last_error}",
            cause=last_error,
        )

    # ─── Internals ──────────────────────────────────────────────────────────

    def _must_force_local(
        self, hints: TaskHints, pii: list[PIIMatch]
    ) -> tuple[bool, str]:
        if self._policy.mode is RoutingMode.LOCAL_ONLY:
            return True, _REASON_LOCAL_ONLY
        if hints.private:
            return True, _REASON_HINT_PRIVATE
        if pii and self._policy.force_local_for_pii:
            kinds = ",".join(sorted({m.kind.value for m in pii}))
            return True, f"{_REASON_PRIVATE} ({kinds})"
        if self._policy.cost_budget.monthly_exhausted():
            return True, _REASON_BUDGET_EXHAUSTED
        return False, ""

    def _must_force_cloud(self) -> tuple[bool, str]:
        if self._policy.mode is RoutingMode.CLOUD_ONLY:
            return True, _REASON_CLOUD_ONLY
        return False, ""

    def _plan(
        self, task: TaskProfile, request: ChatRequest
    ) -> tuple[list[RoutingCandidate], str]:
        if self._policy.mode is RoutingMode.CLOUD_FIRST:
            chain = self._build_cloud_chain(task, request)
            chain.extend(self._build_local_chain(task, request))
            return chain, _REASON_CLOUD_FIRST

        if self._policy.mode is RoutingMode.LOCAL_FIRST:
            chain = self._build_local_chain(task, request)
            chain.extend(self._build_cloud_chain(task, request))
            return chain, _REASON_LOCAL_FIRST

        # AUTO
        if task.kind is TaskKind.COMPUTER_USE:
            chain = self._build_cloud_chain(task, request)
            if chain:
                # local como fallback, aunque sea emulado
                chain.extend(self._build_local_chain(task, request))
                return chain, _REASON_COMPUTER_USE_NATIVE
            return self._build_local_chain(task, request), _REASON_OFFLINE

        if task.kind is TaskKind.VISION:
            chain = self._build_local_chain(task, request)
            chain.extend(self._build_cloud_chain(task, request))
            return chain, _REASON_AUTO_LOCAL + " (vision)"

        if task.kind is TaskKind.PLAIN_CHAT:
            chain = self._build_local_chain(task, request)
            if chain:
                # Para texto plano, local primero. Cloud sólo si local muere.
                chain.extend(self._build_cloud_chain(task, request))
                return chain, _REASON_AUTO_LOCAL
            return self._build_cloud_chain(task, request), _REASON_AUTO_CLOUD

        # TOOL_CHAIN: cloud por confiabilidad de tool-use, local como respaldo
        chain = self._build_cloud_chain(task, request)
        chain.extend(self._build_local_chain(task, request))
        return chain, _REASON_AUTO_CLOUD + " (tools)"

    def _build_cloud_chain(
        self, task: TaskProfile, request: ChatRequest
    ) -> list[RoutingCandidate]:
        if self._policy.cost_budget.monthly_exhausted():
            return []
        cloud = self._cloud_provider()
        if cloud is None or not cloud.is_available():
            return []
        model = self._select_model(
            cloud,
            task=task,
            request=request,
            preferred=self._policy.preferred_cloud_model,
        )
        return [RoutingCandidate(provider=cloud, model=model)] if model else []

    def _build_local_chain(
        self, task: TaskProfile, request: ChatRequest
    ) -> list[RoutingCandidate]:
        local = self._local_provider()
        if local is None or not local.is_available():
            return []
        model = self._select_model(
            local,
            task=task,
            request=request,
            preferred=self._policy.preferred_local_model,
        )
        return [RoutingCandidate(provider=local, model=model)] if model else []

    def _cloud_provider(self) -> Provider | None:
        for prov in self._providers.values():
            caps = prov.capabilities()
            if not caps.is_local:
                return prov
        return None

    def _local_provider(self) -> Provider | None:
        for prov in self._providers.values():
            caps = prov.capabilities()
            if caps.is_local:
                return prov
        return None

    def _select_model(
        self,
        provider: Provider,
        *,
        task: TaskProfile,
        request: ChatRequest,
        preferred: str | None,
    ) -> str | None:
        caps = provider.capabilities()
        models = caps.available_models

        def fits(m: ModelInfo) -> bool:
            if task.needs_vision and self._policy.require_vision_when_images_present:
                if not m.supports_vision:
                    return False
            if task.needs_computer_use and self._policy.require_computer_use_provider:
                # Aceptamos: soporte nativo o, en provider local, vision (emulado).
                if not (m.supports_computer_use or (caps.is_local and m.supports_vision)):
                    return False
            if task.needs_tools and not m.supports_tools and not caps.is_local:
                # Local puede emular tools; cloud lo exigimos.
                return False
            return True

        if preferred:
            for m in models:
                if m.id == preferred and fits(m):
                    return preferred

        # Si no hay preferencia o la preferida no encaja, ordena: vision/tools first
        ranked = sorted(
            (m for m in models if fits(m)),
            key=lambda m: (
                not m.supports_computer_use if task.needs_computer_use else False,
                not m.supports_vision if task.needs_vision else False,
                # En cloud preferimos el más barato que cumpla
                (m.cost_per_million_input or 0.0),
            ),
        )
        if ranked:
            return ranked[0].id

        if not models and caps.is_local is False:
            return None  # cloud sin modelos no debería pasar
        if not models and caps.is_local:
            # local sin modelos: deja que el provider use su default
            return None
        # Si nada encajó pero hay modelos, en local devolvemos el primero
        # (puede que las capabilities heurísticas se equivoquen).
        if caps.is_local and models:
            return models[0].id
        return None

    @staticmethod
    def _scope_request_to_model(request: ChatRequest, model: str) -> ChatRequest:
        if request.model == model:
            return request
        # Inmutabilidad ligera: copiamos sólo lo necesario.
        return ChatRequest(
            messages=request.messages,
            system=request.system,
            tools=request.tools,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            model=model,
            extra=dict(request.extra),
        )


__all__ = [
    "NoProviderAvailableError",
    "Router",
    "RoutingCandidate",
    "RoutingDecision",
]
