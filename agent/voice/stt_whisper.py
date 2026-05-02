"""STT local con faster-whisper.

faster-whisper usa CTranslate2, lo que da el mismo resultado que Whisper
de OpenAI con ~4x menos memoria y ~2x más rápido en CPU. Modelos
soportados van desde `tiny` (39MB) hasta `large-v3` (~1.5GB).

Detección de hardware:
  - GPU CUDA compatible → usa float16 sobre CUDA.
  - CPU → usa int8 (menor memoria, latencia aceptable para frases cortas).

Política de privacidad: el audio nunca sale del equipo. faster-whisper
ejecuta el modelo en proceso local. No hay llamadas de red.
"""

from __future__ import annotations

import io
import wave
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from voice.provider import (
    STTCapabilities,
    STTProvider,
    STTUnavailableError,
    UnsupportedLanguageError,
)
from voice.types import (
    AudioBuffer,
    TranscribeRequest,
    Transcript,
    TranscriptSegment,
)

if TYPE_CHECKING:
    pass


# Modelos soportados, en orden de menor → mayor calidad/tamaño.
MODEL_TINY = "tiny"
MODEL_BASE = "base"
MODEL_SMALL = "small"
MODEL_MEDIUM = "medium"
MODEL_LARGE_V3 = "large-v3"

_AVAILABLE_MODELS: list[str] = [
    MODEL_TINY,
    MODEL_BASE,
    MODEL_SMALL,
    MODEL_MEDIUM,
    MODEL_LARGE_V3,
]

# Idiomas soportados por Whisper (ISO-639-1). Lista parcial — Whisper
# soporta ~99 idiomas; aquí mantenemos los más comunes para validación.
# La validación real (raise UnsupportedLanguageError) sólo dispara si el
# idioma no es válido para Whisper.
_WHISPER_LANGUAGES: set[str] = {
    "en", "es", "fr", "de", "it", "pt", "nl", "pl", "ru", "uk", "tr",
    "ar", "hi", "zh", "ja", "ko", "vi", "id", "th", "el", "hu", "fi",
    "sv", "no", "da", "cs", "sk", "ro", "bg", "ca", "eu", "gl",
}


def _cuda_is_compatible() -> bool:
    """True si hay GPU CUDA compatible con faster-whisper / CTranslate2."""
    try:
        import torch  # type: ignore[import-untyped]
        if not torch.cuda.is_available():
            return False
        for i in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(i)
            cc = props.major * 10 + props.minor
            # CTranslate2 con CUDA requiere sm_60+
            if cc >= 60:
                return True
        return False
    except Exception:  # noqa: BLE001
        return False


@dataclass
class WhisperConfig:
    """Configuración del provider faster-whisper."""

    model_name: str = MODEL_BASE
    """Identificador del modelo. Default 'base' (~140MB) — buen balance."""
    device: str | None = None
    """None = auto. 'cpu' o 'cuda' para forzar."""
    compute_type: str | None = None
    """None = auto. 'int8' (CPU), 'float16' (GPU), 'int8_float16' (GPU mixto)."""
    download_root: str | None = None
    """Directorio donde cachear modelos. None = default de la librería."""
    beam_size: int = 5
    """Beam search size. Mayor = mejor calidad, más lento."""
    vad_filter: bool = True
    """Filtra silencios con VAD antes de transcribir."""


def _resolve_device_and_compute(cfg: WhisperConfig) -> tuple[str, str]:
    """Resuelve (device, compute_type) según config + hardware."""
    if cfg.device is not None:
        device = cfg.device
    else:
        device = "cuda" if _cuda_is_compatible() else "cpu"

    if cfg.compute_type is not None:
        compute_type = cfg.compute_type
    elif device == "cuda":
        compute_type = "float16"
    else:
        compute_type = "int8"

    return device, compute_type


def _audio_to_pcm_array(audio: AudioBuffer) -> Any:
    """Convierte un AudioBuffer a un numpy array float32 mono a 16kHz.

    faster-whisper acepta arrays float32 normalizados al rango [-1, 1].
    Este helper soporta:
      - 'pcm_s16le' directo (lo más común tras capturar de PipeWire).
      - 'wav' decodificando con `wave` stdlib.
    Otros formatos requieren ffmpeg/soundfile y se delegan al caller —
    pasarle el path al archivo a `transcribe_file()` (TODO).
    """
    import numpy as np

    if audio.format == "pcm_s16le":
        raw = audio.data
        sample_rate = audio.sample_rate
        channels = audio.channels
    elif audio.format == "wav":
        with wave.open(io.BytesIO(audio.data), "rb") as wf:
            sample_rate = wf.getframerate()
            channels = wf.getnchannels()
            raw = wf.readframes(wf.getnframes())
    else:
        raise STTUnavailableError(
            f"formato {audio.format!r} no soportado en transcribe(). "
            "Usa pcm_s16le o wav, o convierte con ffmpeg primero."
        )

    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)

    if sample_rate != 16000:
        # Resample lineal simple. Para producción usar soxr o librosa,
        # pero para inputs ya cercanos a 16k el lineal funciona.
        ratio = 16000 / sample_rate
        new_len = int(len(samples) * ratio)
        if new_len > 0:
            idx = np.linspace(0, len(samples) - 1, new_len)
            samples = np.interp(idx, np.arange(len(samples)), samples).astype(np.float32)

    return samples


class WhisperSTTProvider(STTProvider):
    """STT provider basado en faster-whisper.

    El modelo se carga perezosamente la primera vez que se llama a
    `transcribe()`. Si faster-whisper no está instalado, las llamadas
    a `transcribe()` lanzan `STTUnavailableError`; `is_available()`
    devuelve False.
    """

    name = "faster-whisper"

    def __init__(self, config: WhisperConfig | None = None) -> None:
        self._cfg = config or WhisperConfig()
        self._device, self._compute_type = _resolve_device_and_compute(self._cfg)
        self._model: Any = None  # lazy

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel  # type: ignore[import-untyped]
        except ImportError as exc:
            raise STTUnavailableError(
                "faster-whisper no está instalado. "
                "Ejecuta: pip install faster-whisper"
            ) from exc

        self._model = WhisperModel(
            self._cfg.model_name,
            device=self._device,
            compute_type=self._compute_type,
            download_root=self._cfg.download_root,
        )

    # ─── STTProvider API ────────────────────────────────────────────────────

    def capabilities(self) -> STTCapabilities:
        return STTCapabilities(
            name=self.name,
            is_local=True,
            supports_streaming=False,
            supports_translation=True,
            available_languages=sorted(_WHISPER_LANGUAGES),
            available_models=list(_AVAILABLE_MODELS),
        )

    def is_available(self) -> bool:
        try:
            import faster_whisper  # noqa: F401  # type: ignore[import-untyped]
            return True
        except ImportError:
            return False

    def transcribe(self, request: TranscribeRequest) -> Transcript:
        if request.language and request.language not in _WHISPER_LANGUAGES:
            raise UnsupportedLanguageError(request.language)

        self._load()
        samples = _audio_to_pcm_array(request.audio)

        task = "translate" if request.translate_to_english else "transcribe"

        segments_iter, info = self._model.transcribe(
            samples,
            language=request.language or None,
            initial_prompt=request.prompt or None,
            beam_size=self._cfg.beam_size,
            vad_filter=self._cfg.vad_filter,
            task=task,
        )

        segments: list[TranscriptSegment] = []
        text_parts: list[str] = []
        for seg in segments_iter:
            text_parts.append(seg.text.strip())
            segments.append(
                TranscriptSegment(
                    text=seg.text.strip(),
                    start=float(seg.start),
                    end=float(seg.end),
                    confidence=float(getattr(seg, "avg_logprob", 0.0)),
                )
            )

        full_text = " ".join(p for p in text_parts if p)
        return Transcript(
            text=full_text,
            segments=segments,
            language=getattr(info, "language", "") or request.language,
            duration_seconds=float(getattr(info, "duration", 0.0)),
        )

    # ─── Convenience ────────────────────────────────────────────────────────

    @property
    def device(self) -> str:
        return self._device

    @property
    def compute_type(self) -> str:
        return self._compute_type

    @property
    def model_name(self) -> str:
        return self._cfg.model_name


__all__ = [
    "MODEL_BASE",
    "MODEL_LARGE_V3",
    "MODEL_MEDIUM",
    "MODEL_SMALL",
    "MODEL_TINY",
    "WhisperConfig",
    "WhisperSTTProvider",
]
