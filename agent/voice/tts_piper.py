"""TTS local con Piper.

[Piper](https://github.com/OHF-Voice/piper1-gpl) sintetiza voz neural de
alta calidad en CPU. Cada "voz" es un par de archivos:
  - `<voice>.onnx` — pesos del modelo VITS.
  - `<voice>.onnx.json` — config (sample rate, espeak phonemes, etc.).

Las voces se descargan de https://huggingface.co/rhasspy/piper-voices
y se referencian por path local. Esto evita que Piper descargue de
internet sin que el usuario lo sepa — la política de allAI OS exige
que el usuario controle qué modelos vivene en su máquina.

Política de privacidad: el texto nunca sale del equipo. Piper ejecuta
la inferencia en proceso local. No hay llamadas de red.
"""

from __future__ import annotations

import io
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from voice.provider import (
    TTSCapabilities,
    TTSProvider,
    TTSUnavailableError,
    UnsupportedVoiceError,
)
from voice.types import (
    AudioBuffer,
    SynthesisResult,
    SynthesizeRequest,
    VoiceInfo,
)


@dataclass
class PiperConfig:
    """Configuración del provider Piper."""

    model_path: Path | str
    """Ruta al archivo .onnx del modelo de voz."""
    config_path: Path | str | None = None
    """Ruta al .onnx.json. Si None, asume `<model_path>.json`."""
    voice_id: str = ""
    """Identificador lógico de la voz. Si vacío, se infiere del model_path."""
    language: str = ""
    """Código ISO-639-1, ej. 'es'. Se infiere del nombre del modelo si vacío."""
    use_cuda: bool = False
    """Si True, intenta GPU vía onnxruntime-gpu."""
    length_scale_default: float = 1.0
    """1.0 = velocidad natural. Se invierte al mapear desde request.speed."""


def _infer_voice_id(model_path: Path | str) -> str:
    """Deduce el voice_id del nombre del archivo. Ej: 'es_ES-mls-low'."""
    name = Path(model_path).name
    for suffix in (".onnx", ".onnx.json"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _infer_language(voice_id: str) -> str:
    """Deduce el código ISO-639-1 del voice_id (ej. 'es_ES-...' → 'es')."""
    if not voice_id:
        return ""
    head = voice_id.split("_", 1)[0].split("-", 1)[0]
    return head.lower() if len(head) == 2 else ""


def _pcm_to_wav(pcm: bytes, sample_rate: int, sample_width: int, channels: int) -> bytes:
    """Envuelve PCM lineal en un contenedor WAV mínimo."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


class PiperTTSProvider(TTSProvider):
    """TTS provider basado en Piper.

    Una instancia carga UNA voz. Para multi-voz, instancia varios providers
    o registra varios en un router (TODO en una iteración futura).
    """

    name = "piper"

    def __init__(self, config: PiperConfig) -> None:
        self._cfg = config
        self._voice_id = config.voice_id or _infer_voice_id(config.model_path)
        self._language = config.language or _infer_language(self._voice_id)
        self._voice: Any = None  # lazy
        self._sample_rate: int = 22050  # placeholder hasta cargar

    def _load(self) -> None:
        if self._voice is not None:
            return
        try:
            from piper import PiperVoice  # type: ignore[import-untyped]
        except ImportError as exc:
            raise TTSUnavailableError(
                "piper-tts no está instalado. Ejecuta: pip install piper-tts"
            ) from exc

        model_path = Path(self._cfg.model_path)
        if not model_path.exists():
            raise TTSUnavailableError(
                f"modelo de voz no encontrado: {model_path}. "
                "Descarga desde https://huggingface.co/rhasspy/piper-voices"
            )

        cfg_path = (
            Path(self._cfg.config_path)
            if self._cfg.config_path is not None
            else Path(str(model_path) + ".json")
        )

        self._voice = PiperVoice.load(
            model_path,
            config_path=cfg_path if cfg_path.exists() else None,
            use_cuda=self._cfg.use_cuda,
        )
        # Sample rate viene en config.sample_rate del modelo cargado.
        self._sample_rate = int(getattr(self._voice.config, "sample_rate", 22050))

    # ─── TTSProvider API ────────────────────────────────────────────────────

    def capabilities(self) -> TTSCapabilities:
        return TTSCapabilities(
            name=self.name,
            is_local=True,
            supports_streaming=True,
            available_voices=[
                VoiceInfo(
                    id=self._voice_id,
                    language=self._language,
                    sample_rate=self._sample_rate,
                    description=f"Piper voice loaded from {self._cfg.model_path}",
                )
            ],
        )

    def is_available(self) -> bool:
        try:
            import piper  # noqa: F401  # type: ignore[import-untyped]
        except ImportError:
            return False
        return Path(self._cfg.model_path).exists()

    def synthesize(self, request: SynthesizeRequest) -> SynthesisResult:
        if request.voice_id and request.voice_id != self._voice_id:
            raise UnsupportedVoiceError(request.voice_id)

        self._load()

        from piper import SynthesisConfig  # type: ignore[import-untyped]

        # speed > 1.0 = más rápido = length_scale < 1.0
        length_scale = (
            (1.0 / request.speed) if request.speed > 0 else self._cfg.length_scale_default
        )

        syn_cfg = SynthesisConfig(length_scale=length_scale)

        chunks_pcm: list[bytes] = []
        sample_width = 2
        channels = 1
        for chunk in self._voice.synthesize(request.text, syn_config=syn_cfg):
            chunks_pcm.append(chunk.audio_int16_bytes)
            sample_width = chunk.sample_width
            channels = chunk.sample_channels

        pcm = b"".join(chunks_pcm)

        if request.output_format == "wav":
            data = _pcm_to_wav(pcm, self._sample_rate, sample_width, channels)
            audio = AudioBuffer(
                data=data,
                sample_rate=self._sample_rate,
                channels=channels,
                format="wav",
            )
        elif request.output_format == "pcm_s16le":
            audio = AudioBuffer(
                data=pcm,
                sample_rate=self._sample_rate,
                channels=channels,
                format="pcm_s16le",
            )
        else:
            raise TTSUnavailableError(
                f"output_format {request.output_format!r} no soportado por Piper. "
                "Usa 'wav' o 'pcm_s16le'."
            )

        return SynthesisResult(
            audio=audio,
            voice_id=self._voice_id,
            text=request.text,
        )

    # ─── Convenience ────────────────────────────────────────────────────────

    @property
    def voice_id(self) -> str:
        return self._voice_id

    @property
    def language(self) -> str:
        return self._language

    @property
    def sample_rate(self) -> int:
        return self._sample_rate


__all__ = [
    "PiperConfig",
    "PiperTTSProvider",
]
