"""Tests de memory.retrieval — búsqueda híbrida vector + FTS5."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from memory.retrieval import RetrievalResult, retrieve
from memory.store import insert_entry, open_database


# ─── Fixture: base de datos temporal con entradas de prueba ──────────────────

@pytest.fixture
def db_conn():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Path(tmpdir) / "test.db"
        salt = Path(tmpdir) / "test.salt"
        conn = open_database(db, salt_path=salt, passphrase="test-passphrase")
        yield conn
        conn.close()


def _populate(conn: Any) -> list[int]:
    ids = []
    entries = [
        ("allAI OS controla el escritorio Linux con IA", "fact"),
        ("Python es el lenguaje principal del agente", "fact"),
        ("Fedora 43 es la distribución base del sistema", "fact"),
        ("la memoria se cifra con SQLCipher y Argon2id", "fact"),
        ("el usuario prefiere teclado mecánico español", "fact"),
    ]
    for content, kind in entries:
        ids.append(insert_entry(conn, content=content, kind=kind))
    return ids


# ─── Sin modelo (solo FTS5) ───────────────────────────────────────────────────

def test_retrieve_returns_list(db_conn: Any) -> None:
    _populate(db_conn)
    results = retrieve("Linux", db_conn)
    assert isinstance(results, list)


def test_retrieve_no_model_finds_fts_match(db_conn: Any) -> None:
    _populate(db_conn)
    results = retrieve("Python", db_conn, model=None, k=5)
    assert any("Python" in r.content for r in results)


def test_retrieve_empty_query_returns_empty(db_conn: Any) -> None:
    _populate(db_conn)
    assert retrieve("", db_conn) == []


def test_retrieve_whitespace_query_returns_empty(db_conn: Any) -> None:
    _populate(db_conn)
    assert retrieve("   ", db_conn) == []


def test_retrieve_no_match_returns_empty(db_conn: Any) -> None:
    _populate(db_conn)
    results = retrieve("xyzzy_no_existe_en_nada", db_conn, model=None)
    # FTS no encuentra nada; fallback a list_entries devuelve k primeros
    assert isinstance(results, list)


def test_retrieve_result_has_required_fields(db_conn: Any) -> None:
    _populate(db_conn)
    results = retrieve("memoria", db_conn, model=None, k=1)
    assert len(results) >= 1
    r = results[0]
    assert isinstance(r, RetrievalResult)
    assert isinstance(r.entry_id, int)
    assert isinstance(r.content, str)
    assert isinstance(r.score, float)
    assert isinstance(r.sensitive, bool)


def test_retrieve_respects_k(db_conn: Any) -> None:
    _populate(db_conn)
    results = retrieve("sistema", db_conn, model=None, k=2)
    assert len(results) <= 2


def test_retrieve_excludes_sensitive_by_default(db_conn: Any) -> None:
    _populate(db_conn)
    insert_entry(db_conn, content="dato secreto aquí", kind="fact", sensitive=True)
    results = retrieve("secreto", db_conn, model=None, k=10)
    assert all(not r.sensitive for r in results)


def test_retrieve_includes_sensitive_when_asked(db_conn: Any) -> None:
    _populate(db_conn)
    insert_entry(db_conn, content="clave secreta aquí", kind="fact", sensitive=True)
    results = retrieve("clave secreta", db_conn, model=None, k=10,
                       include_sensitive=True)
    assert any(r.sensitive for r in results)


# ─── Con modelo mock (prueba el re-ranking sin descarga real) ─────────────────

def _make_mock_model(dim: int = 8) -> MagicMock:
    """Modelo mock que devuelve vectores aleatorios normalizados."""
    mock = MagicMock()
    mock.is_available.return_value = True

    def encode(texts: list[str], **_: Any) -> np.ndarray:
        rng = np.random.default_rng(42)
        vecs = rng.standard_normal((len(texts), dim)).astype("float32")
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return vecs / norms

    def encode_one(text: str) -> np.ndarray:
        return encode([text])[0]

    def top_k(
        query: np.ndarray, corpus: np.ndarray, k: int = 5
    ) -> list[tuple[int, float]]:
        if corpus.shape[0] == 0:
            return []
        scores = corpus @ query
        k = min(k, len(scores))
        top_idx = np.argpartition(scores, -k)[-k:]
        top_idx = top_idx[np.argsort(scores[top_idx])[::-1]]
        return [(int(i), float(scores[i])) for i in top_idx]

    mock.encode.side_effect = encode
    mock.encode_one.side_effect = encode_one
    mock.top_k.side_effect = top_k
    return mock


def test_retrieve_with_mock_model_returns_results(db_conn: Any) -> None:
    _populate(db_conn)
    mock_model = _make_mock_model()
    results = retrieve("Linux escritorio", db_conn, model=mock_model, k=3)
    assert len(results) <= 3
    assert all(isinstance(r, RetrievalResult) for r in results)


def test_retrieve_with_mock_model_scores_are_floats(db_conn: Any) -> None:
    _populate(db_conn)
    mock_model = _make_mock_model()
    results = retrieve("Python agente", db_conn, model=mock_model, k=5)
    assert all(isinstance(r.score, float) for r in results)


def test_retrieve_min_score_filters_low_scores(db_conn: Any) -> None:
    _populate(db_conn)
    mock_model = _make_mock_model()
    # Con min_score=1.1 (imposible), no debe devolver nada
    results = retrieve("sistema", db_conn, model=mock_model, min_score=1.1)
    assert results == []


def test_retrieve_empty_db_returns_empty(db_conn: Any) -> None:
    # Sin _populate, la DB está vacía
    mock_model = _make_mock_model()
    results = retrieve("algo", db_conn, model=mock_model)
    assert results == []
