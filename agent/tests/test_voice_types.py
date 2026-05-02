"""Tests de voice.types — tipos provider-agnostic de audio y transcripción."""

from __future__ import annotations

from voice.types import (
    AudioBuffer,
    SynthesisResult,
    SynthesizeRequest,
    TranscribeRequest,
    Transcript,
    TranscriptSegment,
    VoiceInfo,
)


# ─── AudioBuffer ─────────────────────────────────────────────────────────────


def test_audio_buffer_default_format_pcm() -> None:
    buf = AudioBuffer(data=b"\x00" * 32000)
    assert buf.format == "pcm_s16le"
    assert buf.sample_rate == 16000
    assert buf.channels == 1


def test_audio_buffer_duration_pcm_mono() -> None:
    # 16000 samples/s, 1 channel, 2 bytes/sample → 32000 bytes/s = 1 segundo
    buf = AudioBuffer(data=b"\x00" * 32000)
    assert abs(buf.duration_seconds - 1.0) < 1e-6


def test_audio_buffer_duration_pcm_stereo() -> None:
    # 16000 samples/s, 2 channels, 2 bytes/sample → 64000 bytes/s = 1 segundo
    buf = AudioBuffer(data=b"\x00" * 64000, channels=2)
    assert abs(buf.duration_seconds - 1.0) < 1e-6


def test_audio_buffer_duration_zero_for_non_pcm() -> None:
    # Para formatos contenedor no calculamos duración a ciegas
    buf = AudioBuffer(data=b"ID3" + b"\x00" * 1000, format="mp3")
    assert buf.duration_seconds == 0.0


def test_audio_buffer_is_frozen() -> None:
    buf = AudioBuffer(data=b"\x00" * 100)
    try:
        buf.sample_rate = 22050  # type: ignore[misc]
    except (AttributeError, Exception):
        pass
    else:
        raise AssertionError("AudioBuffer debería ser inmutable")


# ─── Transcript ──────────────────────────────────────────────────────────────


def test_transcript_default_is_empty() -> None:
    t = Transcript(text="")
    assert t.text == ""
    assert t.segments == []
    assert t.language == ""
    assert t.duration_seconds == 0.0


def test_transcript_segment_fields() -> None:
    seg = TranscriptSegment(text="hola", start=0.0, end=0.5, confidence=0.92)
    assert seg.text == "hola"
    assert seg.confidence == 0.92


def test_transcript_with_segments() -> None:
    segs = [
        TranscriptSegment(text="hola", start=0.0, end=0.5),
        TranscriptSegment(text="qué tal", start=0.5, end=1.2),
    ]
    t = Transcript(text="hola qué tal", segments=segs, language="es")
    assert len(t.segments) == 2
    assert t.language == "es"


# ─── TranscribeRequest ───────────────────────────────────────────────────────


def test_transcribe_request_defaults() -> None:
    req = TranscribeRequest(audio=AudioBuffer(data=b"\x00" * 100))
    assert req.language == ""
    assert req.prompt == ""
    assert req.translate_to_english is False


def test_transcribe_request_with_language() -> None:
    req = TranscribeRequest(audio=AudioBuffer(data=b"\x00" * 100), language="es")
    assert req.language == "es"


# ─── VoiceInfo / TTS ─────────────────────────────────────────────────────────


def test_voice_info_defaults() -> None:
    v = VoiceInfo(id="es_ES-mls-low", language="es")
    assert v.gender == "unknown"
    assert v.sample_rate == 22050


def test_synthesize_request_defaults() -> None:
    req = SynthesizeRequest(text="hola mundo")
    assert req.voice_id == ""
    assert req.speed == 1.0
    assert req.output_format == "wav"


def test_synthesis_result_carries_metadata() -> None:
    audio = AudioBuffer(data=b"RIFF\x00\x00\x00\x00WAVE", format="wav")
    result = SynthesisResult(audio=audio, voice_id="es_ES-mls-low", text="hola")
    assert result.voice_id == "es_ES-mls-low"
    assert result.text == "hola"
    assert result.audio.format == "wav"
