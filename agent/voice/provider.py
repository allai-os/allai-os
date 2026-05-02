"""Interfaces abstractas para STT y TTS providers.

El loop del agente y los tests hablan sólo con estas interfaces. Las
implementaciones concretas (faster-whisper, Piper) viven en
`voice.stt_whisper` y `voice.tts_piper` y traducen entre estos tipos
y los SDKs de cada motor.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

from voice.types import (
    SynthesisResult,
    SynthesizeRequest,
    TranscribeRequest,
    Transcript,
    VoiceInfo,
)


# ─── STT ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class STTCapabilities:
    """Resumen estático de qué puede hacer un STT provider."""

    name: str
    """Identificador, ej. 'faster-whisper'."""
    is_local: bool
    """Para allAI OS los STT son siempre locales por privacidad. Mantenemos
    el flag para hacer la política explícita en código."""
    supports_streaming: bool
    """Si admite transcripción incremental con audio recibido por trozos."""
    supports_translation: bool
    """Si puede traducir directamente a inglés en la transcripción."""
    available_languages: list[str] = field(default_factory=list)
    """ISO-639-1 codes. Si está vacío, el provider acepta auto-detección."""
    available_models: list[str] = field(default_factory=list)
    """Ej.: ['tiny', 'base', 'small', 'medium', 'large-v3']."""


class STTProvider(ABC):
    """Contrato común para cualquier motor de speech-to-text.

    Política de privacidad: en allAI OS los STT son siempre locales. Un
    provider remoto requeriría aprobación arquitectónica explícita y
    confirmación humana cada uso.
    """

    name: str

    @abstractmethod
    def capabilities(self) -> STTCapabilities:
        """Capacidades estáticas + modelos/idiomas disponibles ahora."""

    @abstractmethod
    def is_available(self) -> bool:
        """¿Puede atender una petición ahora? (modelo cargado, deps presentes)."""

    @abstractmethod
    def transcribe(self, request: TranscribeRequest) -> Transcript:
        """Transcribe un audio completo y devuelve el resultado."""


# ─── TTS ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class TTSCapabilities:
    """Resumen estático de qué puede hacer un TTS provider."""

    name: str
    is_local: bool
    supports_streaming: bool
    """Si admite emitir audio en chunks mientras sintetiza."""
    available_voices: list[VoiceInfo] = field(default_factory=list)


class TTSProvider(ABC):
    """Contrato común para cualquier motor de text-to-speech.

    Igual que STT, los TTS de allAI OS son locales por defecto.
    """

    name: str

    @abstractmethod
    def capabilities(self) -> TTSCapabilities:
        ...

    @abstractmethod
    def is_available(self) -> bool:
        ...

    @abstractmethod
    def synthesize(self, request: SynthesizeRequest) -> SynthesisResult:
        """Sintetiza el texto a un único `SynthesisResult`."""


# ─── Errores ────────────────────────────────────────────────────────────────


class VoiceError(Exception):
    """Base de errores de voz."""


class STTUnavailableError(VoiceError):
    """El motor STT no está disponible (modelo no cargado, deps faltantes)."""


class TTSUnavailableError(VoiceError):
    """El motor TTS no está disponible."""


class UnsupportedLanguageError(VoiceError):
    """El provider no soporta el idioma pedido."""

    def __init__(self, language: str) -> None:
        super().__init__(f"idioma no soportado: {language}")
        self.language = language


class UnsupportedVoiceError(VoiceError):
    """El TTS provider no tiene la voz pedida."""

    def __init__(self, voice_id: str) -> None:
        super().__init__(f"voz no disponible: {voice_id}")
        self.voice_id = voice_id


__all__ = [
    "STTCapabilities",
    "STTProvider",
    "STTUnavailableError",
    "TTSCapabilities",
    "TTSProvider",
    "TTSUnavailableError",
    "UnsupportedLanguageError",
    "UnsupportedVoiceError",
    "VoiceError",
]
