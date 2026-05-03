"""Detección de wake-word local con openWakeWord.

[openWakeWord](https://github.com/dscripka/openWakeWord) ejecuta modelos
ONNX/TFLite ligeros para detectar frases gatillo como "Hey allAI",
"Alexa", "Hey Jarvis", etc. Inferencia 100% local en CPU; latencia
típica <100ms por chunk.

Uso esperado:

    detector = WakewordDetector(WakewordConfig(model_paths=["models/hey_allai.onnx"]))
    while audio_stream.has_more():
        chunk = audio_stream.read(1280)  # 80ms @ 16kHz int16 mono
        events = detector.feed(chunk)
        for e in events:
            handle_wakeword(e)

Política de privacidad: el audio nunca sale del equipo. La detección
ocurre en proceso. Cuando el wake-word se dispara, el agente decide qué
hacer (típicamente: empezar STT con Whisper).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from voice.provider import VoiceError
from voice.types import AudioBuffer


class WakewordError(VoiceError):
    """Base de errores del wake-word."""


class WakewordUnavailableError(WakewordError):
    """openWakeWord no está instalado o no se pudo cargar el modelo."""


@dataclass(frozen=True, slots=True)
class WakewordEvent:
    """Una detección concreta de wake-word."""

    model_name: str
    """Nombre del modelo que disparó (ej. 'hey_allai')."""
    score: float
    """Confianza de la detección en [0, 1]."""
    timestamp: float
    """Tiempo Unix en el momento de la detección."""


@dataclass
class WakewordConfig:
    """Configuración del detector."""

    model_paths: list[str | Path] = field(default_factory=list)
    """Rutas a modelos .onnx/.tflite. Si vacío, usa los modelos bundled
    de openWakeWord (alexa, hey jarvis, hey mycroft, etc.)."""
    threshold: float = 0.5
    """Score mínimo para considerar detección. Por modelo, suelen
    funcionar bien valores 0.5-0.7. Más alto = menos falsos positivos."""
    sample_rate: int = 16000
    """openWakeWord espera 16kHz mono int16."""
    chunk_size: int = 1280
    """Muestras por chunk. 1280 = 80ms a 16kHz, recomendado por openWW."""
    cooldown_seconds: float = 1.5
    """Tiempo mínimo entre eventos del mismo modelo. Evita spam de
    detecciones durante una única utterance."""
    enable_noise_suppression: bool = False
    """Activa speexdsp si está disponible. Mejora robustez en entornos ruidosos."""


def _audio_to_int16(audio: bytes | AudioBuffer) -> Any:
    """Convierte input a numpy.int16 (1-D). openWakeWord requiere int16 mono.

    Acepta bytes raw (asumidos PCM s16le 16kHz mono) o AudioBuffer.
    Si el AudioBuffer no es 16kHz mono PCM, lanza ValueError.
    """
    import numpy as np

    if isinstance(audio, AudioBuffer):
        if audio.format != "pcm_s16le":
            raise ValueError(
                f"WakewordDetector requiere PCM s16le, recibido {audio.format!r}. "
                "Convierte primero o pasa bytes raw."
            )
        if audio.sample_rate != 16000:
            raise ValueError(
                f"WakewordDetector requiere 16kHz, recibido {audio.sample_rate}Hz."
            )
        if audio.channels != 1:
            raise ValueError(
                f"WakewordDetector requiere mono, recibido {audio.channels} canales."
            )
        raw = audio.data
    else:
        raw = audio

    return np.frombuffer(raw, dtype=np.int16)


class WakewordDetector:
    """Detector de wake-word con cooldown y umbral configurables.

    Mantiene estado interno: timestamps de la última detección por modelo.
    Llama a `reset()` para limpiar el estado entre sesiones independientes.
    """

    def __init__(self, config: WakewordConfig | None = None) -> None:
        self._cfg = config or WakewordConfig()
        self._model: Any = None  # lazy
        self._last_fired: dict[str, float] = {}

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            from openwakeword.model import Model  # type: ignore[import-untyped]
        except ImportError as exc:
            raise WakewordUnavailableError(
                "openwakeword no está instalado. "
                "Ejecuta: pip install openwakeword"
            ) from exc

        # Validar paths antes de instanciar
        paths = [str(p) for p in self._cfg.model_paths]
        for p in paths:
            if not Path(p).exists():
                raise WakewordUnavailableError(
                    f"modelo de wakeword no encontrado: {p}"
                )

        try:
            self._model = Model(
                wakeword_model_paths=paths,
                enable_speex_noise_suppression=self._cfg.enable_noise_suppression,
            )
        except Exception as exc:  # noqa: BLE001
            raise WakewordUnavailableError(
                f"no se pudo cargar el modelo openwakeword: {exc}"
            ) from exc

    # ─── API pública ────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """True si openwakeword está instalado y los modelos existen."""
        try:
            import openwakeword  # noqa: F401  # type: ignore[import-untyped]
        except ImportError:
            return False
        return all(Path(p).exists() for p in self._cfg.model_paths)

    def feed(self, audio: bytes | AudioBuffer) -> list[WakewordEvent]:
        """Procesa un chunk de audio y devuelve detecciones disparadas.

        Aplica el umbral configurado y el cooldown por modelo. Devuelve
        lista vacía si no hay detección o si está en cooldown.
        """
        self._load()
        samples = _audio_to_int16(audio)
        scores: dict[str, float] = self._model.predict(samples)

        now = time.time()
        events: list[WakewordEvent] = []
        for name, score in scores.items():
            if score < self._cfg.threshold:
                continue
            last = self._last_fired.get(name, 0.0)
            if now - last < self._cfg.cooldown_seconds:
                continue
            self._last_fired[name] = now
            events.append(
                WakewordEvent(model_name=name, score=float(score), timestamp=now)
            )
        return events

    def reset(self) -> None:
        """Limpia el estado interno (cooldowns + buffers del modelo)."""
        self._last_fired.clear()
        if self._model is not None:
            self._model.reset()

    @property
    def models(self) -> list[str]:
        """Lista de modelos cargados. Vacío si no se ha hecho `_load()` aún."""
        return [str(p) for p in self._cfg.model_paths]


__all__ = [
    "WakewordConfig",
    "WakewordDetector",
    "WakewordError",
    "WakewordEvent",
    "WakewordUnavailableError",
]
