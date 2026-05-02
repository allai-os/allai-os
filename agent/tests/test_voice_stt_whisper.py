"""Tests de voice.stt_whisper — provider faster-whisper."""

from __future__ import annotations

import io
import struct
import wave
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from voice.provider import (
    STTCapabilities,
    STTProvider,
    UnsupportedLanguageError,
)
from voice.stt_whisper import (
    MODEL_BASE,
    MODEL_LARGE_V3,
    MODEL_TINY,
    WhisperConfig,
    WhisperSTTProvider,
    _audio_to_pcm_array,
    _resolve_device_and_compute,
)
from voice.types import (
    AudioBuffer,
    TranscribeRequest,
    Transcript,
)


# ─── Helpers para audio sintético ─────────────────────────────────────────────

def _silence_pcm(duration_s: float = 1.0, sample_rate: int = 16000) -> AudioBuffer:
    n_samples = int(duration_s * sample_rate)
    data = b"\x00\x00" * n_samples
    return AudioBuffer(data=data, sample_rate=sample_rate, channels=1)


def _silence_wav(duration_s: float = 1.0, sample_rate: int = 16000) -> AudioBuffer:
    n_samples = int(duration_s * sample_rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n_samples)
    return AudioBuffer(data=buf.getvalue(), format="wav", sample_rate=sample_rate)


def _stereo_pcm(duration_s: float = 1.0, sample_rate: int = 16000) -> AudioBuffer:
    n_samples = int(duration_s * sample_rate)
    # 2 canales intercalados
    data = struct.pack(f"<{n_samples * 2}h", *([1000, -1000] * n_samples))
    return AudioBuffer(data=data, sample_rate=sample_rate, channels=2)


# ─── Resolución de device/compute ────────────────────────────────────────────


def test_resolve_cpu_forced() -> None:
    cfg = WhisperConfig(device="cpu")
    device, compute = _resolve_device_and_compute(cfg)
    assert device == "cpu"
    assert compute == "int8"


def test_resolve_cuda_forced_uses_float16() -> None:
    cfg = WhisperConfig(device="cuda")
    device, compute = _resolve_device_and_compute(cfg)
    assert device == "cuda"
    assert compute == "float16"


def test_resolve_explicit_compute_type_respected() -> None:
    cfg = WhisperConfig(device="cpu", compute_type="float32")
    _, compute = _resolve_device_and_compute(cfg)
    assert compute == "float32"


# ─── Conversión de audio ─────────────────────────────────────────────────────


def test_audio_to_pcm_array_pcm_input() -> None:
    audio = _silence_pcm(0.5)
    arr = _audio_to_pcm_array(audio)
    assert len(arr) == 8000  # 0.5s @ 16kHz
    assert arr.dtype.name == "float32"


def test_audio_to_pcm_array_wav_input() -> None:
    audio = _silence_wav(0.25)
    arr = _audio_to_pcm_array(audio)
    assert len(arr) == 4000


def test_audio_to_pcm_array_stereo_downmixes_to_mono() -> None:
    audio = _stereo_pcm(0.1)
    arr = _audio_to_pcm_array(audio)
    # mono = (L + R) / 2; con L=1000, R=-1000 → 0
    assert len(arr) == 1600
    assert abs(arr.mean()) < 1e-3


def test_audio_to_pcm_array_resamples_to_16k() -> None:
    # 8kHz, 1s → 8000 samples; tras resample a 16kHz → 16000
    audio = AudioBuffer(data=b"\x00\x00" * 8000, sample_rate=8000, channels=1)
    arr = _audio_to_pcm_array(audio)
    assert abs(len(arr) - 16000) < 5  # tolerancia por rounding del linspace


def test_audio_to_pcm_array_unsupported_format_raises() -> None:
    audio = AudioBuffer(data=b"ID3" + b"\x00" * 100, format="mp3")
    with pytest.raises(Exception):
        _audio_to_pcm_array(audio)


# ─── WhisperSTTProvider — capabilities y disponibilidad ──────────────────────


def test_provider_implements_interface() -> None:
    p = WhisperSTTProvider(WhisperConfig(device="cpu"))
    assert isinstance(p, STTProvider)


def test_provider_name_is_faster_whisper() -> None:
    p = WhisperSTTProvider(WhisperConfig(device="cpu"))
    assert p.name == "faster-whisper"


def test_capabilities_returns_local_provider() -> None:
    p = WhisperSTTProvider(WhisperConfig(device="cpu"))
    caps = p.capabilities()
    assert isinstance(caps, STTCapabilities)
    assert caps.is_local is True
    assert caps.supports_translation is True


def test_capabilities_lists_models() -> None:
    p = WhisperSTTProvider(WhisperConfig(device="cpu"))
    models = p.capabilities().available_models
    for m in (MODEL_TINY, MODEL_BASE, MODEL_LARGE_V3):
        assert m in models


def test_capabilities_includes_common_languages() -> None:
    p = WhisperSTTProvider(WhisperConfig(device="cpu"))
    langs = p.capabilities().available_languages
    for lang in ("es", "en", "fr", "de", "ja"):
        assert lang in langs


def test_is_available_true_when_installed() -> None:
    p = WhisperSTTProvider(WhisperConfig(device="cpu"))
    # En el venv de tests faster-whisper está instalado
    assert p.is_available() is True


def test_device_and_model_accessible_before_load() -> None:
    p = WhisperSTTProvider(WhisperConfig(device="cpu", model_name=MODEL_TINY))
    assert p.device == "cpu"
    assert p.compute_type == "int8"
    assert p.model_name == MODEL_TINY


# ─── transcribe — validaciones sin cargar modelo ─────────────────────────────


def test_transcribe_unsupported_language_raises() -> None:
    p = WhisperSTTProvider(WhisperConfig(device="cpu"))
    req = TranscribeRequest(audio=_silence_pcm(0.1), language="xq")
    with pytest.raises(UnsupportedLanguageError):
        p.transcribe(req)


def test_transcribe_supported_language_does_not_raise_validation() -> None:
    # Verificamos que "es" pasa la validación (sin importar el resultado real
    # del modelo, que mockeamos).
    p = WhisperSTTProvider(WhisperConfig(device="cpu"))
    fake_seg = MagicMock()
    fake_seg.text = " hola"
    fake_seg.start = 0.0
    fake_seg.end = 0.5
    fake_seg.avg_logprob = -0.2
    fake_info = MagicMock()
    fake_info.language = "es"
    fake_info.duration = 0.5

    fake_model = MagicMock()
    fake_model.transcribe.return_value = (iter([fake_seg]), fake_info)
    p._model = fake_model  # type: ignore[attr-defined]

    req = TranscribeRequest(audio=_silence_pcm(0.5), language="es")
    result = p.transcribe(req)
    assert isinstance(result, Transcript)
    assert result.text == "hola"
    assert result.language == "es"
    assert len(result.segments) == 1


def test_transcribe_returns_segments_with_timestamps() -> None:
    p = WhisperSTTProvider(WhisperConfig(device="cpu"))
    seg1 = MagicMock(text=" hola", start=0.0, end=0.4, avg_logprob=-0.1)
    seg2 = MagicMock(text=" mundo", start=0.4, end=0.9, avg_logprob=-0.15)
    info = MagicMock(language="es", duration=0.9)

    fake_model = MagicMock()
    fake_model.transcribe.return_value = (iter([seg1, seg2]), info)
    p._model = fake_model  # type: ignore[attr-defined]

    req = TranscribeRequest(audio=_silence_pcm(0.9))
    result = p.transcribe(req)
    assert len(result.segments) == 2
    assert result.segments[0].start == 0.0
    assert result.segments[1].end == 0.9
    assert result.text == "hola mundo"


def test_transcribe_translate_passes_correct_task() -> None:
    p = WhisperSTTProvider(WhisperConfig(device="cpu"))
    info = MagicMock(language="es", duration=0.1)
    fake_model = MagicMock()
    fake_model.transcribe.return_value = (iter([]), info)
    p._model = fake_model  # type: ignore[attr-defined]

    req = TranscribeRequest(audio=_silence_pcm(0.1), translate_to_english=True)
    p.transcribe(req)
    _, kwargs = fake_model.transcribe.call_args
    assert kwargs["task"] == "translate"


def test_transcribe_no_translate_uses_transcribe_task() -> None:
    p = WhisperSTTProvider(WhisperConfig(device="cpu"))
    info = MagicMock(language="es", duration=0.1)
    fake_model = MagicMock()
    fake_model.transcribe.return_value = (iter([]), info)
    p._model = fake_model  # type: ignore[attr-defined]

    req = TranscribeRequest(audio=_silence_pcm(0.1))
    p.transcribe(req)
    _, kwargs = fake_model.transcribe.call_args
    assert kwargs["task"] == "transcribe"


def test_transcribe_passes_prompt() -> None:
    p = WhisperSTTProvider(WhisperConfig(device="cpu"))
    info = MagicMock(language="es", duration=0.1)
    fake_model = MagicMock()
    fake_model.transcribe.return_value = (iter([]), info)
    p._model = fake_model  # type: ignore[attr-defined]

    req = TranscribeRequest(audio=_silence_pcm(0.1), prompt="allAI OS")
    p.transcribe(req)
    _, kwargs = fake_model.transcribe.call_args
    assert kwargs["initial_prompt"] == "allAI OS"


def test_transcribe_empty_segments_returns_empty_text() -> None:
    p = WhisperSTTProvider(WhisperConfig(device="cpu"))
    info = MagicMock(language="es", duration=0.1)
    fake_model = MagicMock()
    fake_model.transcribe.return_value = (iter([]), info)
    p._model = fake_model  # type: ignore[attr-defined]

    req = TranscribeRequest(audio=_silence_pcm(0.1))
    result = p.transcribe(req)
    assert result.text == ""
    assert result.segments == []


# ─── transcribe — integración con modelo real (slow) ─────────────────────────


@pytest.mark.slow
def test_transcribe_real_model_silence_returns_empty_or_short() -> None:
    """Carga el modelo `tiny` real y transcribe silencio.

    Whisper tiende a alucinar sobre silencio puro. Aceptamos cualquier
    resultado mientras no crashee y devuelva un Transcript válido.
    """
    p = WhisperSTTProvider(WhisperConfig(device="cpu", model_name=MODEL_TINY))
    req = TranscribeRequest(audio=_silence_pcm(1.0), language="en")
    result = p.transcribe(req)
    assert isinstance(result, Transcript)
    assert result.duration_seconds > 0
