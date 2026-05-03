"""Captura y reproducción de audio a través de PipeWire.

Usa `sounddevice` (PortAudio) que en Linux moderno habla con PipeWire
vía su capa de compatibilidad PulseAudio. Esto da soporte automático
a:
  - PipeWire nativo (Fedora 35+, Ubuntu 22.10+).
  - PulseAudio puro (sistemas legacy).
  - ALSA directo (vía portaudio backend).

Diseño:
  - `AudioCapture`: micrófono → AudioBuffer / streaming a callback.
  - `AudioPlayback`: AudioBuffer → altavoces, blocking o no-blocking.
  - `list_input_devices()` / `list_output_devices()`: introspección.

Política de privacidad: el agente NO captura audio sin consentimiento
explícito. Quien construye un AudioCapture asume que el caller tiene la
autorización del usuario para abrir el micrófono. La UI debe mostrar
indicador visible mientras AudioCapture esté activo.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from voice.provider import VoiceError
from voice.types import AudioBuffer


class AudioIOError(VoiceError):
    """Error de captura o reproducción de audio."""


class AudioBackendUnavailableError(AudioIOError):
    """sounddevice/PortAudio no está instalado o no encuentra dispositivos."""


@dataclass(frozen=True, slots=True)
class AudioDevice:
    """Descriptor de un dispositivo de audio del sistema."""

    index: int
    """Índice según portaudio. Estable durante la sesión."""
    name: str
    """Nombre legible, ej. 'Built-in Audio Analog Stereo'."""
    max_input_channels: int
    max_output_channels: int
    default_sample_rate: float
    is_input: bool
    """True si tiene canales de entrada (es micrófono)."""
    is_output: bool


@dataclass
class CaptureConfig:
    """Configuración de captura de micrófono."""

    sample_rate: int = 16000
    """16kHz mono es lo que esperan Whisper y openWakeWord."""
    channels: int = 1
    chunk_size: int = 1280
    """Frames por callback en streaming. 1280 = 80ms a 16kHz."""
    device: int | str | None = None
    """Índice o nombre del dispositivo. None = default del sistema."""
    dtype: str = "int16"
    """Tipo de muestra. 'int16' es el formato común para STT/wakeword."""


@dataclass
class PlaybackConfig:
    """Configuración de reproducción."""

    device: int | str | None = None
    """Índice/nombre. None = default."""
    blocking: bool = True
    """Si True, play() retorna cuando termina; False retorna inmediatamente."""


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _import_sounddevice() -> Any:
    """Importa sounddevice o lanza AudioBackendUnavailableError."""
    try:
        import sounddevice  # type: ignore[import-untyped]
        return sounddevice
    except (ImportError, OSError) as exc:
        # OSError ocurre si PortAudio no está en el sistema (ej. Docker
        # sin libportaudio2 instalada).
        raise AudioBackendUnavailableError(
            "sounddevice/PortAudio no disponible. "
            "Instala con: pip install sounddevice && sudo dnf install portaudio"
        ) from exc


def is_available() -> bool:
    """True si sounddevice se puede importar y hay al menos un device."""
    try:
        sd = _import_sounddevice()
        return len(sd.query_devices()) > 0
    except (AudioBackendUnavailableError, Exception):  # noqa: BLE001
        return False


def list_input_devices() -> list[AudioDevice]:
    """Lista dispositivos de entrada disponibles."""
    sd = _import_sounddevice()
    devices: list[AudioDevice] = []
    for i, info in enumerate(sd.query_devices()):
        if info["max_input_channels"] > 0:
            devices.append(_to_audio_device(i, info))
    return devices


def list_output_devices() -> list[AudioDevice]:
    """Lista dispositivos de salida disponibles."""
    sd = _import_sounddevice()
    devices: list[AudioDevice] = []
    for i, info in enumerate(sd.query_devices()):
        if info["max_output_channels"] > 0:
            devices.append(_to_audio_device(i, info))
    return devices


def _to_audio_device(idx: int, info: dict[str, Any]) -> AudioDevice:
    return AudioDevice(
        index=idx,
        name=str(info.get("name", "")),
        max_input_channels=int(info.get("max_input_channels", 0)),
        max_output_channels=int(info.get("max_output_channels", 0)),
        default_sample_rate=float(info.get("default_samplerate", 0.0)),
        is_input=int(info.get("max_input_channels", 0)) > 0,
        is_output=int(info.get("max_output_channels", 0)) > 0,
    )


# ─── AudioCapture ────────────────────────────────────────────────────────────


class AudioCapture:
    """Captura de micrófono.

    Dos modos de uso:
      1. Batch: `record(duration_seconds)` bloquea y devuelve AudioBuffer.
      2. Streaming: `start_stream(callback)` no-blocking, llama callback con
         cada chunk. `stop_stream()` cierra. El callback se ejecuta en
         thread de portaudio — debe ser rápido.
    """

    def __init__(self, config: CaptureConfig | None = None) -> None:
        self._cfg = config or CaptureConfig()
        self._stream: Any = None

    def is_available(self) -> bool:
        return is_available()

    def record(self, duration_seconds: float) -> AudioBuffer:
        """Captura síncrona. Bloquea hasta que pasen `duration_seconds`."""
        if duration_seconds <= 0:
            raise ValueError("duration_seconds debe ser > 0")

        sd = _import_sounddevice()
        n_frames = int(duration_seconds * self._cfg.sample_rate)
        try:
            data = sd.rec(
                n_frames,
                samplerate=self._cfg.sample_rate,
                channels=self._cfg.channels,
                dtype=self._cfg.dtype,
                device=self._cfg.device,
                blocking=True,
            )
        except Exception as exc:  # noqa: BLE001
            raise AudioIOError(f"error capturando audio: {exc}") from exc

        return AudioBuffer(
            data=data.tobytes(),
            sample_rate=self._cfg.sample_rate,
            channels=self._cfg.channels,
            format="pcm_s16le" if self._cfg.dtype == "int16" else "pcm_s16le",
        )

    def start_stream(
        self, callback: Callable[[AudioBuffer], None]
    ) -> None:
        """Captura streaming. `callback(chunk)` se llama por cada bloque.

        El callback corre en el thread de portaudio: debe ser rápido y
        no bloquear. Si necesitas trabajo pesado, encola los chunks y
        procesa en otro thread.
        """
        if self._stream is not None:
            raise AudioIOError("stream ya activo — llama stop_stream() primero")

        sd = _import_sounddevice()

        def _portaudio_cb(
            indata: Any, frames: int, time_info: Any, status: Any
        ) -> None:
            if status:
                # Underflow/overflow no son fatales — log y continúa
                pass
            buf = AudioBuffer(
                data=bytes(indata),
                sample_rate=self._cfg.sample_rate,
                channels=self._cfg.channels,
                format="pcm_s16le",
            )
            callback(buf)

        try:
            self._stream = sd.InputStream(
                samplerate=self._cfg.sample_rate,
                channels=self._cfg.channels,
                dtype=self._cfg.dtype,
                blocksize=self._cfg.chunk_size,
                device=self._cfg.device,
                callback=_portaudio_cb,
            )
            self._stream.start()
        except Exception as exc:  # noqa: BLE001
            self._stream = None
            raise AudioIOError(f"no se pudo abrir stream: {exc}") from exc

    def stop_stream(self) -> None:
        """Cierra el stream activo. Idempotente."""
        if self._stream is None:
            return
        try:
            self._stream.stop()
            self._stream.close()
        finally:
            self._stream = None

    @property
    def is_streaming(self) -> bool:
        return self._stream is not None


# ─── AudioPlayback ───────────────────────────────────────────────────────────


class AudioPlayback:
    """Reproducción de AudioBuffer a través de los altavoces.

    Acepta PCM s16le directamente. Para WAV decodifica el header con
    `wave` stdlib. Otros formatos (mp3, ogg) requieren convertirlos
    antes — usa ffmpeg o un decoder dedicado.
    """

    def __init__(self, config: PlaybackConfig | None = None) -> None:
        self._cfg = config or PlaybackConfig()

    def is_available(self) -> bool:
        return is_available()

    def play(self, audio: AudioBuffer) -> None:
        """Reproduce un AudioBuffer. Si config.blocking, espera a que termine."""
        sd = _import_sounddevice()
        import numpy as np

        if audio.format == "wav":
            import io
            import wave
            with wave.open(io.BytesIO(audio.data), "rb") as wf:
                sample_rate = wf.getframerate()
                channels = wf.getnchannels()
                raw = wf.readframes(wf.getnframes())
        elif audio.format == "pcm_s16le":
            sample_rate = audio.sample_rate
            channels = audio.channels
            raw = audio.data
        else:
            raise AudioIOError(
                f"formato {audio.format!r} no soportado en play(). "
                "Convierte a PCM s16le o WAV primero."
            )

        samples = np.frombuffer(raw, dtype=np.int16)
        if channels > 1:
            samples = samples.reshape(-1, channels)

        try:
            sd.play(
                samples,
                samplerate=sample_rate,
                device=self._cfg.device,
                blocking=self._cfg.blocking,
            )
        except Exception as exc:  # noqa: BLE001
            raise AudioIOError(f"error reproduciendo audio: {exc}") from exc

    def stop(self) -> None:
        """Detiene cualquier reproducción en curso."""
        try:
            sd = _import_sounddevice()
            sd.stop()
        except AudioBackendUnavailableError:
            pass


__all__ = [
    "AudioBackendUnavailableError",
    "AudioCapture",
    "AudioDevice",
    "AudioIOError",
    "AudioPlayback",
    "CaptureConfig",
    "PlaybackConfig",
    "is_available",
    "list_input_devices",
    "list_output_devices",
]
