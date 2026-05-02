"""Tipos provider-agnostic para STT (speech-to-text) y TTS (text-to-speech).

Igual que `core/messages.py` define el modelo común para chat providers,
este módulo define lo que entra y sale de cualquier voice provider sin
acoplarse a Whisper, Piper, o cualquier otra implementación.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


# Formatos de audio soportados como entrada/salida. PCM es el más común.
AudioFormat = Literal["pcm_s16le", "wav", "mp3", "ogg", "flac"]


@dataclass(frozen=True, slots=True)
class AudioBuffer:
    """Audio en memoria con metadatos suficientes para decodificar.

    `data` lleva los bytes raw. `sample_rate` y `channels` describen el
    layout PCM cuando aplica. `format` indica si los bytes ya están en un
    contenedor (wav, mp3) o son PCM lineal.
    """

    data: bytes
    sample_rate: int = 16000
    channels: int = 1
    format: AudioFormat = "pcm_s16le"

    @property
    def duration_seconds(self) -> float:
        """Duración aproximada — sólo válida para PCM s16le."""
        if self.format != "pcm_s16le":
            return 0.0
        bytes_per_sample = 2 * self.channels
        return len(self.data) / bytes_per_sample / self.sample_rate


# ─── STT ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    """Un fragmento de transcripción con timestamps.

    Útil para subtítulos, edición y para detectar puntos de pausa naturales
    cuando el agente debe responder en el flujo de la conversación.
    """

    text: str
    start: float
    """Inicio en segundos desde el comienzo del audio."""
    end: float
    """Fin en segundos desde el comienzo del audio."""
    confidence: float = 0.0
    """Confianza media de los tokens del segmento, [0, 1]. 0 si no se reporta."""


@dataclass(frozen=True, slots=True)
class Transcript:
    """Resultado completo de transcribir un audio."""

    text: str
    """Texto concatenado de todos los segmentos."""
    segments: list[TranscriptSegment] = field(default_factory=list)
    language: str = ""
    """Código ISO-639-1 detectado, ej. 'es', 'en'. Vacío si no se detectó."""
    duration_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class TranscribeRequest:
    """Petición de transcripción.

    `language` puede dejarse vacío para auto-detección. Pasarlo cuando se
    sabe ahorra tiempo y mejora calidad. `prompt` es contexto opcional que
    influye en el vocabulario (nombres propios, terminología técnica).
    """

    audio: AudioBuffer
    language: str = ""
    prompt: str = ""
    translate_to_english: bool = False


# ─── TTS ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class VoiceInfo:
    """Descriptor de una voz disponible en el TTS provider."""

    id: str
    """Identificador único, ej. 'es_ES-mls_10246-low' (Piper)."""
    language: str
    """Código ISO-639-1, ej. 'es', 'en'."""
    gender: Literal["female", "male", "neutral", "unknown"] = "unknown"
    sample_rate: int = 22050
    description: str = ""


@dataclass(frozen=True, slots=True)
class SynthesizeRequest:
    """Petición de síntesis."""

    text: str
    voice_id: str = ""
    """Si vacío, el provider usa su voz por defecto."""
    speed: float = 1.0
    """Velocidad relativa, 1.0 = natural."""
    output_format: AudioFormat = "wav"


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    """Resultado de síntesis."""

    audio: AudioBuffer
    voice_id: str
    text: str


__all__ = [
    "AudioBuffer",
    "AudioFormat",
    "SynthesisResult",
    "SynthesizeRequest",
    "TranscribeRequest",
    "Transcript",
    "TranscriptSegment",
    "VoiceInfo",
]
