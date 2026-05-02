"""Tests de voice.provider — interfaces abstractas STT/TTS y errores."""

from __future__ import annotations

import pytest

from voice.provider import (
    STTCapabilities,
    STTProvider,
    STTUnavailableError,
    TTSCapabilities,
    TTSProvider,
    TTSUnavailableError,
    UnsupportedLanguageError,
    UnsupportedVoiceError,
    VoiceError,
)
from voice.types import (
    AudioBuffer,
    SynthesisResult,
    SynthesizeRequest,
    TranscribeRequest,
    Transcript,
    VoiceInfo,
)


# ─── Errores: jerarquía ──────────────────────────────────────────────────────


def test_stt_unavailable_is_voice_error() -> None:
    assert issubclass(STTUnavailableError, VoiceError)


def test_tts_unavailable_is_voice_error() -> None:
    assert issubclass(TTSUnavailableError, VoiceError)


def test_unsupported_language_is_voice_error() -> None:
    assert issubclass(UnsupportedLanguageError, VoiceError)


def test_unsupported_language_carries_lang() -> None:
    err = UnsupportedLanguageError("xq")
    assert err.language == "xq"
    assert "xq" in str(err)


def test_unsupported_voice_carries_voice_id() -> None:
    err = UnsupportedVoiceError("voz_inexistente")
    assert err.voice_id == "voz_inexistente"
    assert "voz_inexistente" in str(err)


# ─── Capacidades ─────────────────────────────────────────────────────────────


def test_stt_capabilities_defaults() -> None:
    caps = STTCapabilities(
        name="fake",
        is_local=True,
        supports_streaming=False,
        supports_translation=False,
    )
    assert caps.name == "fake"
    assert caps.available_languages == []
    assert caps.available_models == []


def test_tts_capabilities_defaults() -> None:
    caps = TTSCapabilities(name="fake", is_local=True, supports_streaming=False)
    assert caps.name == "fake"
    assert caps.available_voices == []


# ─── Contrato STTProvider — implementación fake completa ─────────────────────


class _FakeSTT(STTProvider):
    name = "fake-stt"

    def capabilities(self) -> STTCapabilities:
        return STTCapabilities(
            name=self.name,
            is_local=True,
            supports_streaming=False,
            supports_translation=False,
            available_languages=["es", "en"],
            available_models=["base"],
        )

    def is_available(self) -> bool:
        return True

    def transcribe(self, request: TranscribeRequest) -> Transcript:
        if request.language and request.language not in ("es", "en", ""):
            raise UnsupportedLanguageError(request.language)
        return Transcript(
            text="hola mundo",
            language=request.language or "es",
            duration_seconds=request.audio.duration_seconds,
        )


def test_fake_stt_implements_interface() -> None:
    p = _FakeSTT()
    assert isinstance(p, STTProvider)
    assert p.is_available() is True


def test_fake_stt_capabilities_complete() -> None:
    p = _FakeSTT()
    caps = p.capabilities()
    assert caps.is_local is True
    assert "es" in caps.available_languages


def test_fake_stt_transcribe_returns_transcript() -> None:
    p = _FakeSTT()
    req = TranscribeRequest(audio=AudioBuffer(data=b"\x00" * 16000), language="es")
    result = p.transcribe(req)
    assert isinstance(result, Transcript)
    assert result.text == "hola mundo"
    assert result.language == "es"


def test_fake_stt_unsupported_language_raises() -> None:
    p = _FakeSTT()
    req = TranscribeRequest(audio=AudioBuffer(data=b"\x00" * 100), language="xq")
    with pytest.raises(UnsupportedLanguageError):
        p.transcribe(req)


# ─── Contrato TTSProvider — implementación fake completa ─────────────────────


class _FakeTTS(TTSProvider):
    name = "fake-tts"

    def capabilities(self) -> TTSCapabilities:
        return TTSCapabilities(
            name=self.name,
            is_local=True,
            supports_streaming=False,
            available_voices=[VoiceInfo(id="es_default", language="es")],
        )

    def is_available(self) -> bool:
        return True

    def synthesize(self, request: SynthesizeRequest) -> SynthesisResult:
        if request.voice_id and request.voice_id != "es_default":
            raise UnsupportedVoiceError(request.voice_id)
        voice_id = request.voice_id or "es_default"
        return SynthesisResult(
            audio=AudioBuffer(
                data=b"RIFF\x00\x00\x00\x00WAVE", format="wav", sample_rate=22050
            ),
            voice_id=voice_id,
            text=request.text,
        )


def test_fake_tts_implements_interface() -> None:
    p = _FakeTTS()
    assert isinstance(p, TTSProvider)
    assert p.is_available() is True


def test_fake_tts_synthesize_returns_audio() -> None:
    p = _FakeTTS()
    req = SynthesizeRequest(text="hola")
    result = p.synthesize(req)
    assert isinstance(result, SynthesisResult)
    assert result.text == "hola"
    assert result.voice_id == "es_default"


def test_fake_tts_unsupported_voice_raises() -> None:
    p = _FakeTTS()
    req = SynthesizeRequest(text="hola", voice_id="inexistente")
    with pytest.raises(UnsupportedVoiceError):
        p.synthesize(req)


# ─── La interfaz abstracta no se puede instanciar ────────────────────────────


def test_stt_provider_is_abstract() -> None:
    with pytest.raises(TypeError):
        STTProvider()  # type: ignore[abstract]


def test_tts_provider_is_abstract() -> None:
    with pytest.raises(TypeError):
        TTSProvider()  # type: ignore[abstract]
