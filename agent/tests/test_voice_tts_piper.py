"""Tests de voice.tts_piper — provider Piper TTS."""

from __future__ import annotations

import io
import wave
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from voice.provider import (
    TTSCapabilities,
    TTSProvider,
    TTSUnavailableError,
    UnsupportedVoiceError,
)
from voice.tts_piper import (
    PiperConfig,
    PiperTTSProvider,
    _infer_language,
    _infer_voice_id,
    _pcm_to_wav,
)
from voice.types import (
    AudioBuffer,
    SynthesisResult,
    SynthesizeRequest,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_chunk(pcm: bytes, sample_rate: int = 22050) -> Any:
    chunk = MagicMock()
    chunk.audio_int16_bytes = pcm
    chunk.sample_rate = sample_rate
    chunk.sample_width = 2
    chunk.sample_channels = 1
    return chunk


@pytest.fixture
def fake_model(tmp_path: Path) -> Path:
    model = tmp_path / "es_ES-mls-low.onnx"
    model.write_bytes(b"\x00" * 16)
    cfg = tmp_path / "es_ES-mls-low.onnx.json"
    cfg.write_text('{"sample_rate": 22050}')
    return model


# ─── Helpers internos ────────────────────────────────────────────────────────

def test_infer_voice_id_strips_onnx_suffix() -> None:
    assert _infer_voice_id("/path/es_ES-mls-low.onnx") == "es_ES-mls-low"


def test_infer_voice_id_strips_onnx_json_suffix() -> None:
    assert _infer_voice_id("es_ES-mls-low.onnx.json") == "es_ES-mls-low"


def test_infer_voice_id_no_extension() -> None:
    assert _infer_voice_id("custom-name") == "custom-name"


def test_infer_language_from_voice_id() -> None:
    assert _infer_language("es_ES-mls-low") == "es"
    assert _infer_language("en_US-amy-medium") == "en"


def test_infer_language_empty_voice_id() -> None:
    assert _infer_language("") == ""


def test_infer_language_no_iso_prefix() -> None:
    # "abc" no es ISO-639-1 (2 chars). El helper devuelve "" si no parece código.
    assert _infer_language("custom-voice") == ""


# ─── PCM → WAV ───────────────────────────────────────────────────────────────

def test_pcm_to_wav_produces_valid_wav() -> None:
    pcm = b"\x00\x01" * 1000
    data = _pcm_to_wav(pcm, sample_rate=22050, sample_width=2, channels=1)
    with wave.open(io.BytesIO(data), "rb") as wf:
        assert wf.getframerate() == 22050
        assert wf.getsampwidth() == 2
        assert wf.getnchannels() == 1
        assert wf.readframes(wf.getnframes()) == pcm


# ─── PiperTTSProvider — capabilities y disponibilidad ────────────────────────

def test_provider_implements_interface(fake_model: Path) -> None:
    p = PiperTTSProvider(PiperConfig(model_path=fake_model))
    assert isinstance(p, TTSProvider)


def test_provider_name_is_piper(fake_model: Path) -> None:
    p = PiperTTSProvider(PiperConfig(model_path=fake_model))
    assert p.name == "piper"


def test_voice_id_inferred_from_model_path(fake_model: Path) -> None:
    p = PiperTTSProvider(PiperConfig(model_path=fake_model))
    assert p.voice_id == "es_ES-mls-low"


def test_explicit_voice_id_overrides_inferred(fake_model: Path) -> None:
    p = PiperTTSProvider(PiperConfig(model_path=fake_model, voice_id="custom-id"))
    assert p.voice_id == "custom-id"


def test_language_inferred_from_voice_id(fake_model: Path) -> None:
    p = PiperTTSProvider(PiperConfig(model_path=fake_model))
    assert p.language == "es"


def test_explicit_language_overrides_inferred(fake_model: Path) -> None:
    p = PiperTTSProvider(PiperConfig(model_path=fake_model, language="ca"))
    assert p.language == "ca"


def test_capabilities_returns_local_provider(fake_model: Path) -> None:
    p = PiperTTSProvider(PiperConfig(model_path=fake_model))
    caps = p.capabilities()
    assert isinstance(caps, TTSCapabilities)
    assert caps.is_local is True


def test_capabilities_reports_loaded_voice(fake_model: Path) -> None:
    p = PiperTTSProvider(PiperConfig(model_path=fake_model))
    voices = p.capabilities().available_voices
    assert len(voices) == 1
    assert voices[0].id == "es_ES-mls-low"
    assert voices[0].language == "es"


def test_is_available_true_with_existing_model(fake_model: Path) -> None:
    p = PiperTTSProvider(PiperConfig(model_path=fake_model))
    assert p.is_available() is True


def test_is_available_false_when_model_missing(tmp_path: Path) -> None:
    p = PiperTTSProvider(PiperConfig(model_path=tmp_path / "nonexistent.onnx"))
    assert p.is_available() is False


# ─── Synthesize — validaciones y mocks ───────────────────────────────────────

def test_synthesize_unsupported_voice_raises(fake_model: Path) -> None:
    p = PiperTTSProvider(PiperConfig(model_path=fake_model))
    req = SynthesizeRequest(text="hola", voice_id="otra-voz")
    with pytest.raises(UnsupportedVoiceError):
        p.synthesize(req)


def test_synthesize_missing_model_raises_unavailable(tmp_path: Path) -> None:
    p = PiperTTSProvider(PiperConfig(model_path=tmp_path / "missing.onnx"))
    req = SynthesizeRequest(text="hola")
    with pytest.raises(TTSUnavailableError):
        p.synthesize(req)


def _patch_voice(p: PiperTTSProvider, chunks: list[Any], sample_rate: int = 22050) -> Any:
    fake_voice = MagicMock()
    fake_voice.synthesize.return_value = iter(chunks)
    fake_voice.config = MagicMock(sample_rate=sample_rate)
    p._voice = fake_voice  # type: ignore[attr-defined]
    p._sample_rate = sample_rate  # type: ignore[attr-defined]
    return fake_voice


def test_synthesize_returns_wav_by_default(fake_model: Path) -> None:
    p = PiperTTSProvider(PiperConfig(model_path=fake_model))
    pcm = b"\x10\x00" * 500
    _patch_voice(p, [_make_chunk(pcm)])

    result = p.synthesize(SynthesizeRequest(text="hola"))
    assert isinstance(result, SynthesisResult)
    assert result.audio.format == "wav"
    # Verifica que es WAV válido
    with wave.open(io.BytesIO(result.audio.data), "rb") as wf:
        assert wf.getframerate() == 22050


def test_synthesize_returns_pcm_when_requested(fake_model: Path) -> None:
    p = PiperTTSProvider(PiperConfig(model_path=fake_model))
    pcm = b"\x10\x00" * 500
    _patch_voice(p, [_make_chunk(pcm)])

    result = p.synthesize(SynthesizeRequest(text="hola", output_format="pcm_s16le"))
    assert result.audio.format == "pcm_s16le"
    assert result.audio.data == pcm


def test_synthesize_concatenates_multiple_chunks(fake_model: Path) -> None:
    p = PiperTTSProvider(PiperConfig(model_path=fake_model))
    chunk1 = _make_chunk(b"\x01\x00" * 100)
    chunk2 = _make_chunk(b"\x02\x00" * 100)
    chunk3 = _make_chunk(b"\x03\x00" * 100)
    _patch_voice(p, [chunk1, chunk2, chunk3])

    result = p.synthesize(SynthesizeRequest(text="hola", output_format="pcm_s16le"))
    assert len(result.audio.data) == 600
    # Verifica orden
    assert result.audio.data[:200] == b"\x01\x00" * 100
    assert result.audio.data[200:400] == b"\x02\x00" * 100


def test_synthesize_speed_inverts_length_scale(fake_model: Path) -> None:
    p = PiperTTSProvider(PiperConfig(model_path=fake_model))
    fake_voice = _patch_voice(p, [_make_chunk(b"\x00\x00")])

    p.synthesize(SynthesizeRequest(text="hola", speed=2.0))
    _, kwargs = fake_voice.synthesize.call_args
    syn_cfg = kwargs["syn_config"]
    # speed=2.0 → length_scale=0.5 (más rápido)
    assert syn_cfg.length_scale == 0.5


def test_synthesize_speed_one_uses_neutral_length_scale(fake_model: Path) -> None:
    p = PiperTTSProvider(PiperConfig(model_path=fake_model))
    fake_voice = _patch_voice(p, [_make_chunk(b"\x00\x00")])

    p.synthesize(SynthesizeRequest(text="hola", speed=1.0))
    _, kwargs = fake_voice.synthesize.call_args
    assert kwargs["syn_config"].length_scale == 1.0


def test_synthesize_unsupported_format_raises(fake_model: Path) -> None:
    p = PiperTTSProvider(PiperConfig(model_path=fake_model))
    _patch_voice(p, [_make_chunk(b"\x00\x00")])

    req = SynthesizeRequest(text="hola", output_format="mp3")
    with pytest.raises(TTSUnavailableError):
        p.synthesize(req)


def test_synthesize_passes_text_to_voice(fake_model: Path) -> None:
    p = PiperTTSProvider(PiperConfig(model_path=fake_model))
    fake_voice = _patch_voice(p, [_make_chunk(b"\x00\x00")])

    p.synthesize(SynthesizeRequest(text="texto exacto"))
    args, _ = fake_voice.synthesize.call_args
    assert args[0] == "texto exacto"


def test_synthesize_result_contains_voice_id(fake_model: Path) -> None:
    p = PiperTTSProvider(PiperConfig(model_path=fake_model))
    _patch_voice(p, [_make_chunk(b"\x00\x00")])

    result = p.synthesize(SynthesizeRequest(text="hola"))
    assert result.voice_id == "es_ES-mls-low"
    assert result.text == "hola"
