"""Tests de voice.wakeword — detector openWakeWord."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from voice.types import AudioBuffer
from voice.wakeword import (
    WakewordConfig,
    WakewordDetector,
    WakewordEvent,
    WakewordUnavailableError,
    _audio_to_int16,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def fake_model_paths(tmp_path: Path) -> list[Path]:
    p1 = tmp_path / "hey_allai.onnx"
    p2 = tmp_path / "alexa.onnx"
    p1.write_bytes(b"\x00" * 16)
    p2.write_bytes(b"\x00" * 16)
    return [p1, p2]


def _silence_chunk(n_samples: int = 1280) -> bytes:
    return b"\x00\x00" * n_samples


def _patch_model(detector: WakewordDetector, scores: dict[str, float]) -> Any:
    fake = MagicMock()
    fake.predict.return_value = scores
    detector._model = fake  # type: ignore[attr-defined]
    return fake


# ─── _audio_to_int16 ─────────────────────────────────────────────────────────

def test_audio_to_int16_accepts_bytes() -> None:
    arr = _audio_to_int16(b"\x00\x00\x10\x00")
    assert len(arr) == 2
    assert arr.dtype.name == "int16"


def test_audio_to_int16_accepts_audio_buffer_pcm_16k_mono() -> None:
    buf = AudioBuffer(data=b"\x00\x00" * 100, sample_rate=16000, channels=1)
    arr = _audio_to_int16(buf)
    assert len(arr) == 100


def test_audio_to_int16_rejects_non_pcm() -> None:
    buf = AudioBuffer(data=b"RIFF", format="wav")
    with pytest.raises(ValueError):
        _audio_to_int16(buf)


def test_audio_to_int16_rejects_wrong_sample_rate() -> None:
    buf = AudioBuffer(data=b"\x00" * 100, sample_rate=22050)
    with pytest.raises(ValueError):
        _audio_to_int16(buf)


def test_audio_to_int16_rejects_stereo() -> None:
    buf = AudioBuffer(data=b"\x00" * 100, sample_rate=16000, channels=2)
    with pytest.raises(ValueError):
        _audio_to_int16(buf)


# ─── Constructor / capabilities ──────────────────────────────────────────────

def test_default_config() -> None:
    d = WakewordDetector()
    assert d._cfg.threshold == 0.5
    assert d._cfg.sample_rate == 16000
    assert d._cfg.chunk_size == 1280


def test_models_list_reflects_config(fake_model_paths: list[Path]) -> None:
    d = WakewordDetector(WakewordConfig(model_paths=fake_model_paths))
    assert len(d.models) == 2
    assert all(str(p) in d.models for p in fake_model_paths)


def test_is_available_true_with_existing_models(fake_model_paths: list[Path]) -> None:
    d = WakewordDetector(WakewordConfig(model_paths=fake_model_paths))
    assert d.is_available() is True


def test_is_available_false_when_model_missing(tmp_path: Path) -> None:
    d = WakewordDetector(
        WakewordConfig(model_paths=[tmp_path / "nonexistent.onnx"])
    )
    assert d.is_available() is False


def test_is_available_with_no_paths(fake_model_paths: list[Path]) -> None:
    # Sin paths usa los defaults bundled de openwakeword → True si lib instalada
    d = WakewordDetector(WakewordConfig(model_paths=[]))
    assert d.is_available() is True


# ─── feed — detecciones ──────────────────────────────────────────────────────

def test_feed_below_threshold_returns_no_events(fake_model_paths: list[Path]) -> None:
    d = WakewordDetector(WakewordConfig(model_paths=fake_model_paths, threshold=0.5))
    _patch_model(d, {"hey_allai": 0.3})
    events = d.feed(_silence_chunk())
    assert events == []


def test_feed_above_threshold_returns_event(fake_model_paths: list[Path]) -> None:
    d = WakewordDetector(WakewordConfig(model_paths=fake_model_paths, threshold=0.5))
    _patch_model(d, {"hey_allai": 0.85})
    events = d.feed(_silence_chunk())
    assert len(events) == 1
    assert isinstance(events[0], WakewordEvent)
    assert events[0].model_name == "hey_allai"
    assert events[0].score == pytest.approx(0.85)


def test_feed_only_above_threshold_models_fire(fake_model_paths: list[Path]) -> None:
    d = WakewordDetector(WakewordConfig(model_paths=fake_model_paths, threshold=0.6))
    _patch_model(d, {"hey_allai": 0.9, "alexa": 0.3})
    events = d.feed(_silence_chunk())
    assert len(events) == 1
    assert events[0].model_name == "hey_allai"


def test_feed_multiple_models_can_fire_simultaneously(
    fake_model_paths: list[Path],
) -> None:
    d = WakewordDetector(WakewordConfig(model_paths=fake_model_paths, threshold=0.5))
    _patch_model(d, {"hey_allai": 0.8, "alexa": 0.7})
    events = d.feed(_silence_chunk())
    assert len(events) == 2
    names = {e.model_name for e in events}
    assert names == {"hey_allai", "alexa"}


# ─── Cooldown ────────────────────────────────────────────────────────────────

def test_cooldown_suppresses_repeated_detection(fake_model_paths: list[Path]) -> None:
    d = WakewordDetector(
        WakewordConfig(
            model_paths=fake_model_paths, threshold=0.5, cooldown_seconds=10.0
        )
    )
    _patch_model(d, {"hey_allai": 0.9})

    first = d.feed(_silence_chunk())
    assert len(first) == 1

    # Inmediatamente después, debería estar en cooldown
    second = d.feed(_silence_chunk())
    assert second == []


def test_cooldown_per_model(fake_model_paths: list[Path]) -> None:
    """El cooldown de un modelo no afecta a otro."""
    d = WakewordDetector(
        WakewordConfig(
            model_paths=fake_model_paths, threshold=0.5, cooldown_seconds=10.0
        )
    )
    fake = _patch_model(d, {"hey_allai": 0.9, "alexa": 0.0})
    d.feed(_silence_chunk())  # dispara hey_allai

    fake.predict.return_value = {"hey_allai": 0.9, "alexa": 0.9}
    events = d.feed(_silence_chunk())
    # hey_allai en cooldown, alexa libre
    names = {e.model_name for e in events}
    assert names == {"alexa"}


def test_cooldown_expires(fake_model_paths: list[Path]) -> None:
    d = WakewordDetector(
        WakewordConfig(
            model_paths=fake_model_paths, threshold=0.5, cooldown_seconds=0.01
        )
    )
    _patch_model(d, {"hey_allai": 0.9})
    d.feed(_silence_chunk())
    time.sleep(0.05)
    events = d.feed(_silence_chunk())
    assert len(events) == 1


# ─── reset ───────────────────────────────────────────────────────────────────

def test_reset_clears_cooldown(fake_model_paths: list[Path]) -> None:
    d = WakewordDetector(
        WakewordConfig(
            model_paths=fake_model_paths, threshold=0.5, cooldown_seconds=10.0
        )
    )
    fake = _patch_model(d, {"hey_allai": 0.9})
    d.feed(_silence_chunk())
    d.reset()
    events = d.feed(_silence_chunk())
    assert len(events) == 1
    fake.reset.assert_called_once()


def test_reset_before_load_does_not_crash() -> None:
    d = WakewordDetector(WakewordConfig())
    # Sin _load() el _model es None — no debe explotar
    d.reset()


# ─── Errores: modelo inexistente ─────────────────────────────────────────────

def test_load_raises_unavailable_for_missing_model(tmp_path: Path) -> None:
    d = WakewordDetector(
        WakewordConfig(model_paths=[tmp_path / "missing.onnx"])
    )
    with pytest.raises(WakewordUnavailableError, match="no encontrado"):
        d.feed(_silence_chunk())


# ─── Eventos ──────────────────────────────────────────────────────────────────

def test_event_carries_timestamp(fake_model_paths: list[Path]) -> None:
    d = WakewordDetector(WakewordConfig(model_paths=fake_model_paths, threshold=0.5))
    _patch_model(d, {"hey_allai": 0.8})
    before = time.time()
    events = d.feed(_silence_chunk())
    after = time.time()
    assert before <= events[0].timestamp <= after


def test_event_score_in_zero_one_range(fake_model_paths: list[Path]) -> None:
    d = WakewordDetector(WakewordConfig(model_paths=fake_model_paths, threshold=0.0))
    _patch_model(d, {"hey_allai": 0.85})
    events = d.feed(_silence_chunk())
    assert 0.0 <= events[0].score <= 1.0
