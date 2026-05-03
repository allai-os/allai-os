"""Tests de voice.pipewire — captura y reproducción de audio.

Los tests usan mocks de sounddevice para no depender de hardware real.
Los pocos tests `slow` requieren un dispositivo de audio funcional.
"""

from __future__ import annotations

import io
import wave
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from voice.pipewire import (
    AudioBackendUnavailableError,
    AudioCapture,
    AudioDevice,
    AudioIOError,
    AudioPlayback,
    CaptureConfig,
    PlaybackConfig,
    _to_audio_device,
    is_available,
    list_input_devices,
    list_output_devices,
)
from voice.types import AudioBuffer


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _fake_devices() -> list[dict[str, Any]]:
    return [
        {
            "name": "Built-in Microphone",
            "max_input_channels": 1,
            "max_output_channels": 0,
            "default_samplerate": 44100.0,
        },
        {
            "name": "USB Speakers",
            "max_input_channels": 0,
            "max_output_channels": 2,
            "default_samplerate": 48000.0,
        },
        {
            "name": "Headset",
            "max_input_channels": 1,
            "max_output_channels": 2,
            "default_samplerate": 16000.0,
        },
    ]


def _silence_pcm_buffer(seconds: float = 0.1, sample_rate: int = 16000) -> AudioBuffer:
    n = int(seconds * sample_rate)
    return AudioBuffer(
        data=b"\x00\x00" * n, sample_rate=sample_rate, channels=1, format="pcm_s16le"
    )


def _silence_wav_buffer(seconds: float = 0.1, sample_rate: int = 16000) -> AudioBuffer:
    n = int(seconds * sample_rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n)
    return AudioBuffer(data=buf.getvalue(), format="wav", sample_rate=sample_rate)


# ─── _to_audio_device ────────────────────────────────────────────────────────

def test_to_audio_device_input_only() -> None:
    info = _fake_devices()[0]
    dev = _to_audio_device(0, info)
    assert dev.is_input is True
    assert dev.is_output is False
    assert dev.name == "Built-in Microphone"
    assert dev.default_sample_rate == 44100.0


def test_to_audio_device_output_only() -> None:
    info = _fake_devices()[1]
    dev = _to_audio_device(1, info)
    assert dev.is_input is False
    assert dev.is_output is True
    assert dev.max_output_channels == 2


def test_to_audio_device_duplex() -> None:
    info = _fake_devices()[2]
    dev = _to_audio_device(2, info)
    assert dev.is_input is True
    assert dev.is_output is True


def test_audio_device_is_immutable() -> None:
    dev = AudioDevice(
        index=0,
        name="x",
        max_input_channels=1,
        max_output_channels=0,
        default_sample_rate=16000.0,
        is_input=True,
        is_output=False,
    )
    with pytest.raises(Exception):
        dev.name = "y"  # type: ignore[misc]


# ─── list_input_devices / list_output_devices ────────────────────────────────

def test_list_input_devices_filters_input_only() -> None:
    fake_sd = MagicMock()
    fake_sd.query_devices.return_value = _fake_devices()
    with patch("voice.pipewire._import_sounddevice", return_value=fake_sd):
        inputs = list_input_devices()
    names = {d.name for d in inputs}
    assert names == {"Built-in Microphone", "Headset"}


def test_list_output_devices_filters_output_only() -> None:
    fake_sd = MagicMock()
    fake_sd.query_devices.return_value = _fake_devices()
    with patch("voice.pipewire._import_sounddevice", return_value=fake_sd):
        outputs = list_output_devices()
    names = {d.name for d in outputs}
    assert names == {"USB Speakers", "Headset"}


def test_list_devices_empty_when_no_hardware() -> None:
    fake_sd = MagicMock()
    fake_sd.query_devices.return_value = []
    with patch("voice.pipewire._import_sounddevice", return_value=fake_sd):
        assert list_input_devices() == []
        assert list_output_devices() == []


# ─── is_available ────────────────────────────────────────────────────────────

def test_is_available_true_with_devices() -> None:
    fake_sd = MagicMock()
    fake_sd.query_devices.return_value = _fake_devices()
    with patch("voice.pipewire._import_sounddevice", return_value=fake_sd):
        assert is_available() is True


def test_is_available_false_when_backend_missing() -> None:
    with patch(
        "voice.pipewire._import_sounddevice",
        side_effect=AudioBackendUnavailableError("nope"),
    ):
        assert is_available() is False


# ─── AudioCapture — record (síncrono) ────────────────────────────────────────

def test_capture_default_config() -> None:
    c = AudioCapture()
    assert c._cfg.sample_rate == 16000
    assert c._cfg.channels == 1


def test_capture_record_returns_audio_buffer() -> None:
    fake_sd = MagicMock()
    # numpy array fake con tobytes()
    fake_data = MagicMock()
    fake_data.tobytes.return_value = b"\x00\x00" * 1600
    fake_sd.rec.return_value = fake_data

    c = AudioCapture(CaptureConfig(sample_rate=16000, channels=1))
    with patch("voice.pipewire._import_sounddevice", return_value=fake_sd):
        result = c.record(0.1)

    assert isinstance(result, AudioBuffer)
    assert result.sample_rate == 16000
    assert result.format == "pcm_s16le"
    assert len(result.data) == 3200


def test_capture_record_passes_config_to_sd_rec() -> None:
    fake_sd = MagicMock()
    fake_data = MagicMock()
    fake_data.tobytes.return_value = b""
    fake_sd.rec.return_value = fake_data

    c = AudioCapture(CaptureConfig(sample_rate=22050, channels=2, device=3))
    with patch("voice.pipewire._import_sounddevice", return_value=fake_sd):
        c.record(0.5)

    args, kwargs = fake_sd.rec.call_args
    assert args[0] == int(0.5 * 22050)
    assert kwargs["samplerate"] == 22050
    assert kwargs["channels"] == 2
    assert kwargs["device"] == 3
    assert kwargs["blocking"] is True


def test_capture_record_zero_duration_raises() -> None:
    c = AudioCapture()
    with pytest.raises(ValueError):
        c.record(0)


def test_capture_record_negative_duration_raises() -> None:
    c = AudioCapture()
    with pytest.raises(ValueError):
        c.record(-1.0)


def test_capture_record_propagates_io_error() -> None:
    fake_sd = MagicMock()
    fake_sd.rec.side_effect = RuntimeError("device busy")
    c = AudioCapture()
    with patch("voice.pipewire._import_sounddevice", return_value=fake_sd):
        with pytest.raises(AudioIOError):
            c.record(0.1)


# ─── AudioCapture — streaming ────────────────────────────────────────────────

def test_capture_start_stream_creates_input_stream() -> None:
    fake_sd = MagicMock()
    fake_stream = MagicMock()
    fake_sd.InputStream.return_value = fake_stream

    c = AudioCapture()
    with patch("voice.pipewire._import_sounddevice", return_value=fake_sd):
        c.start_stream(lambda chunk: None)

    fake_sd.InputStream.assert_called_once()
    fake_stream.start.assert_called_once()
    assert c.is_streaming is True


def test_capture_start_stream_callback_receives_audio_buffer() -> None:
    fake_sd = MagicMock()
    fake_stream = MagicMock()
    fake_sd.InputStream.return_value = fake_stream

    received: list[AudioBuffer] = []

    c = AudioCapture(CaptureConfig(sample_rate=16000, channels=1))
    with patch("voice.pipewire._import_sounddevice", return_value=fake_sd):
        c.start_stream(received.append)

    # Extraer el portaudio_cb que se pasó a InputStream
    portaudio_cb = fake_sd.InputStream.call_args.kwargs["callback"]
    portaudio_cb(b"\x10\x00" * 1280, 1280, None, None)

    assert len(received) == 1
    assert isinstance(received[0], AudioBuffer)
    assert received[0].sample_rate == 16000
    assert len(received[0].data) == 2560


def test_capture_double_start_raises() -> None:
    fake_sd = MagicMock()
    fake_sd.InputStream.return_value = MagicMock()
    c = AudioCapture()
    with patch("voice.pipewire._import_sounddevice", return_value=fake_sd):
        c.start_stream(lambda x: None)
        with pytest.raises(AudioIOError, match="ya activo"):
            c.start_stream(lambda x: None)


def test_capture_stop_stream_closes_and_sets_none() -> None:
    fake_sd = MagicMock()
    fake_stream = MagicMock()
    fake_sd.InputStream.return_value = fake_stream

    c = AudioCapture()
    with patch("voice.pipewire._import_sounddevice", return_value=fake_sd):
        c.start_stream(lambda x: None)
        c.stop_stream()

    fake_stream.stop.assert_called_once()
    fake_stream.close.assert_called_once()
    assert c.is_streaming is False


def test_capture_stop_stream_idempotent() -> None:
    c = AudioCapture()
    c.stop_stream()  # sin start previo no debe explotar
    c.stop_stream()


def test_capture_start_stream_failure_resets_state() -> None:
    fake_sd = MagicMock()
    fake_sd.InputStream.side_effect = RuntimeError("perm denied")
    c = AudioCapture()
    with patch("voice.pipewire._import_sounddevice", return_value=fake_sd):
        with pytest.raises(AudioIOError):
            c.start_stream(lambda x: None)
    assert c.is_streaming is False


# ─── AudioPlayback ───────────────────────────────────────────────────────────

def test_playback_default_blocking_true() -> None:
    p = AudioPlayback()
    assert p._cfg.blocking is True


def test_playback_pcm_buffer() -> None:
    fake_sd = MagicMock()
    p = AudioPlayback()
    with patch("voice.pipewire._import_sounddevice", return_value=fake_sd):
        p.play(_silence_pcm_buffer(0.1))
    fake_sd.play.assert_called_once()
    _, kwargs = fake_sd.play.call_args
    assert kwargs["samplerate"] == 16000


def test_playback_wav_buffer_decodes_header() -> None:
    fake_sd = MagicMock()
    p = AudioPlayback()
    with patch("voice.pipewire._import_sounddevice", return_value=fake_sd):
        p.play(_silence_wav_buffer(0.1, sample_rate=22050))
    _, kwargs = fake_sd.play.call_args
    # El sample rate viene del WAV, no de AudioBuffer.sample_rate
    assert kwargs["samplerate"] == 22050


def test_playback_unsupported_format_raises() -> None:
    fake_sd = MagicMock()
    p = AudioPlayback()
    audio = AudioBuffer(data=b"ID3" + b"\x00" * 100, format="mp3")
    with patch("voice.pipewire._import_sounddevice", return_value=fake_sd):
        with pytest.raises(AudioIOError, match="no soportado"):
            p.play(audio)


def test_playback_propagates_io_error() -> None:
    fake_sd = MagicMock()
    fake_sd.play.side_effect = RuntimeError("output busy")
    p = AudioPlayback()
    with patch("voice.pipewire._import_sounddevice", return_value=fake_sd):
        with pytest.raises(AudioIOError):
            p.play(_silence_pcm_buffer(0.1))


def test_playback_stop_calls_sd_stop() -> None:
    fake_sd = MagicMock()
    p = AudioPlayback()
    with patch("voice.pipewire._import_sounddevice", return_value=fake_sd):
        p.stop()
    fake_sd.stop.assert_called_once()


def test_playback_stop_silent_if_backend_missing() -> None:
    p = AudioPlayback()
    with patch(
        "voice.pipewire._import_sounddevice",
        side_effect=AudioBackendUnavailableError("no portaudio"),
    ):
        p.stop()  # no debe propagar


def test_playback_passes_device_config() -> None:
    fake_sd = MagicMock()
    p = AudioPlayback(PlaybackConfig(device=5, blocking=False))
    with patch("voice.pipewire._import_sounddevice", return_value=fake_sd):
        p.play(_silence_pcm_buffer(0.1))
    _, kwargs = fake_sd.play.call_args
    assert kwargs["device"] == 5
    assert kwargs["blocking"] is False
