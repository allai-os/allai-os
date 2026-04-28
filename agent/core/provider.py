"""Interfaz `Provider` y descriptores de capacidades."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field

from core.messages import ChatRequest, ChatResponse, StreamEvent


@dataclass(frozen=True, slots=True)
class ModelInfo:
    """Información sobre un modelo disponible en el provider."""

    id: str
    context_window: int
    max_output_tokens: int
    supports_vision: bool = False
    supports_tools: bool = False
    supports_computer_use: bool = False
    supports_caching: bool = False
    # Costos en USD por millón de tokens. None si es local/gratis.
    cost_per_million_input: float | None = None
    cost_per_million_output: float | None = None


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """Resumen estático de qué puede hacer un provider."""

    name: str
    supports_streaming: bool
    supports_tools: bool
    supports_vision: bool
    supports_computer_use: bool
    supports_prompt_caching: bool
    is_local: bool
    """True para Ollama y otros que corren en la máquina del usuario."""
    requires_network: bool
    available_models: list[ModelInfo] = field(default_factory=list)

    def has_model(self, model_id: str) -> bool:
        return any(m.id == model_id for m in self.available_models)

    def get_model(self, model_id: str) -> ModelInfo | None:
        return next((m for m in self.available_models if m.id == model_id), None)


class Provider(ABC):
    """Contrato común de cualquier proveedor de IA en allAI OS.

    Implementaciones concretas:
      - `providers.claude.ClaudeProvider`
      - `providers.ollama.OllamaProvider`

    Quien usa esto (router, tests, sesiones del agente) habla solamente con
    esta interfaz. Detalles de SDK no se filtran fuera.
    """

    name: str
    """Identificador corto del provider, ej. 'claude', 'ollama'."""

    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Capacidades estáticas + modelos disponibles ahora mismo."""

    @abstractmethod
    def is_available(self) -> bool:
        """¿Puede atender una request en este momento?

        Para cloud: hay credenciales y red.
        Para local: el daemon corre y hay al menos un modelo instalado.
        """

    @abstractmethod
    def chat(self, request: ChatRequest) -> ChatResponse:
        """Llamada síncrona, devuelve la respuesta completa."""

    @abstractmethod
    def chat_stream(self, request: ChatRequest) -> Iterator[StreamEvent]:
        """Llamada streaming. Cada evento se emite en orden de llegada.

        El último evento siempre es `MessageStop`.
        """
