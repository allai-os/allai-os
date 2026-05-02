"""Tests de memory.embeddings — embeddings locales con sentence-transformers."""

from __future__ import annotations

import numpy as np
import pytest

from memory.embeddings import (
    EmbeddingsConfig,
    EmbeddingsModel,
    EmbeddingsUnavailableError,
    MODEL_MULTILINGUAL_MINI,
    _cuda_is_compatible,
    _select_defaults,
)


# ─── Detección de hardware ────────────────────────────────────────────────────

def test_cuda_is_compatible_returns_bool() -> None:
    result = _cuda_is_compatible()
    assert isinstance(result, bool)


def test_select_defaults_cpu_forced() -> None:
    cfg = EmbeddingsConfig(device="cpu")
    _, device = _select_defaults(cfg)
    assert device == "cpu"


def test_select_defaults_cpu_gets_mini_model() -> None:
    cfg = EmbeddingsConfig(device="cpu")
    model, _ = _select_defaults(cfg)
    assert model == MODEL_MULTILINGUAL_MINI


def test_select_defaults_explicit_model_respected() -> None:
    cfg = EmbeddingsConfig(model_name="custom/model", device="cpu")
    model, _ = _select_defaults(cfg)
    assert model == "custom/model"


# ─── EmbeddingsModel — disponibilidad ────────────────────────────────────────

def test_is_available_returns_true() -> None:
    m = EmbeddingsModel(EmbeddingsConfig(device="cpu"))
    assert m.is_available() is True


def test_model_name_and_device_accessible_before_load() -> None:
    cfg = EmbeddingsConfig(device="cpu")
    m = EmbeddingsModel(cfg)
    assert m.device == "cpu"
    assert isinstance(m.model_name, str)


# ─── EmbeddingsModel — encode (requiere descarga del modelo) ──────────────────

@pytest.mark.slow
def test_encode_returns_correct_shape() -> None:
    m = EmbeddingsModel(EmbeddingsConfig(device="cpu"))
    vecs = m.encode(["hola mundo", "allAI OS es un proyecto"])
    assert vecs.shape == (2, m.dim)


@pytest.mark.slow
def test_encode_one_returns_1d_vector() -> None:
    m = EmbeddingsModel(EmbeddingsConfig(device="cpu"))
    v = m.encode_one("texto de prueba")
    assert v.ndim == 1
    assert len(v) == m.dim


@pytest.mark.slow
def test_encode_empty_list_returns_empty_array() -> None:
    m = EmbeddingsModel(EmbeddingsConfig(device="cpu"))
    result = m.encode([])
    assert result.shape == (0, m.dim)


@pytest.mark.slow
def test_encode_normalizes_vectors() -> None:
    m = EmbeddingsModel(EmbeddingsConfig(device="cpu", normalize=True))
    v = m.encode_one("normalización de vectores")
    norm = float(np.linalg.norm(v))
    assert abs(norm - 1.0) < 1e-5


@pytest.mark.slow
def test_similarity_identical_texts_near_one() -> None:
    m = EmbeddingsModel(EmbeddingsConfig(device="cpu"))
    v = m.encode_one("Python es un lenguaje de programación")
    score = m.similarity(v, v)
    assert score > 0.99


@pytest.mark.slow
def test_similarity_unrelated_texts_lower_than_identical() -> None:
    m = EmbeddingsModel(EmbeddingsConfig(device="cpu"))
    v1 = m.encode_one("me gusta el café por las mañanas")
    v2 = m.encode_one("me gusta el café por las mañanas")
    v3 = m.encode_one("kernels de sistema operativo en Rust")
    assert m.similarity(v1, v2) > m.similarity(v1, v3)


@pytest.mark.slow
def test_top_k_returns_k_results() -> None:
    m = EmbeddingsModel(EmbeddingsConfig(device="cpu"))
    texts = [
        "allAI OS controla el escritorio",
        "Python es el lenguaje del agente",
        "Fedora como distribución base",
        "memoria cifrada con SQLCipher",
        "el usuario usa teclado español",
    ]
    corpus = m.encode(texts)
    query = m.encode_one("qué distribución usa el sistema")
    top = m.top_k(query, corpus, k=3)
    assert len(top) == 3
    assert all(isinstance(i, int) and isinstance(s, float) for i, s in top)


@pytest.mark.slow
def test_top_k_ordered_by_score_desc() -> None:
    m = EmbeddingsModel(EmbeddingsConfig(device="cpu"))
    texts = ["Fedora como base", "cifrado de memoria", "escritorio Linux"]
    corpus = m.encode(texts)
    query = m.encode_one("distribución Linux Fedora")
    top = m.top_k(query, corpus, k=3)
    scores = [s for _, s in top]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.slow
def test_top_k_empty_corpus_returns_empty() -> None:
    m = EmbeddingsModel(EmbeddingsConfig(device="cpu"))
    query = m.encode_one("texto")
    empty = np.empty((0, m.dim), dtype="float32")
    assert m.top_k(query, empty, k=5) == []


@pytest.mark.slow
def test_dim_is_positive_integer() -> None:
    m = EmbeddingsModel(EmbeddingsConfig(device="cpu"))
    assert isinstance(m.dim, int)
    assert m.dim > 0
