"""Recuperación híbrida de memoria: vector semántico + BM25 léxico (FTS5).

Estrategia de dos etapas:
  1. FTS5 (SQLite full-text search) — recupera candidatos léxicos rápido.
  2. Re-ranking semántico con embeddings locales — reordena por similitud.

Si no hay embeddings disponibles, devuelve solo los resultados FTS5.
Si no hay términos léxicos en la query, usa solo embeddings sobre todos
los registros cargados en memoria (menos eficiente, acotado por max_scan).

Diseño de privacidad:
  - Los embeddings se computan localmente en EmbeddingsModel.
  - No se envía nada a APIs externas.
  - Los registros sensitive sólo se incluyen si include_sensitive=True.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from memory.embeddings import EmbeddingsModel
from memory.store import get_entry, list_entries, search_fts


_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _to_fts_query(query: str) -> str:
    """Convierte una query de lenguaje natural en una query FTS5 segura.

    FTS5 trata caracteres como `?`, `!`, `:`, `*`, `"`, `(`, `)`, `+`, `-` como
    operadores. Una query del usuario con esos signos rompe la sintaxis. Aquí
    extraemos sólo tokens alfanuméricos Unicode y los unimos con espacios
    (FTS5 los une con AND implícito, lo que da recall razonable).
    """
    tokens = _WORD_RE.findall(query)
    return " ".join(tokens)


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    entry_id: int
    content: str
    kind: str
    sensitive: bool
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


def retrieve(
    query: str,
    conn: Any,
    *,
    model: EmbeddingsModel | None = None,
    k: int = 5,
    fts_candidates: int = 20,
    include_sensitive: bool = False,
    min_score: float = 0.0,
) -> list[RetrievalResult]:
    """Recupera las `k` entradas más relevantes para `query`.

    Flujo:
      1. FTS5 sobre `query` → hasta `fts_candidates` filas.
      2. Si hay modelo: re-rank semántico → top-k.
         Si no hay modelo: devuelve FTS5 ordenado por rowid desc.

    Args:
        query:            Texto de búsqueda.
        conn:             Conexión SQLCipher abierta (de open_database()).
        model:            EmbeddingsModel precargado (opcional).
        k:                Número máximo de resultados.
        fts_candidates:   Candidatos FTS5 a considerar antes del re-rank.
        include_sensitive: Incluir entradas marcadas como sensibles.
        min_score:        Filtrar resultados con score < min_score.

    Returns:
        Lista de RetrievalResult ordenada por score desc.
    """
    if not query or not query.strip():
        return []

    # ── Paso 1: candidatos léxicos ──────────────────────────────────────────
    # Sanitiza la query para FTS5 (sólo tokens \w+). Si tras sanear no queda
    # nada (p.ej. query era pura puntuación), saltamos directamente al fallback.
    fts_query = _to_fts_query(query)
    fts_rows: list[dict[str, Any]] = []
    if fts_query:
        fts_rows = search_fts(
            conn,
            fts_query,
            limit=fts_candidates,
            include_sensitive=include_sensitive,
        )

    if not fts_rows:
        # Si FTS no encontró nada, intentamos búsqueda semántica pura
        # sobre todas las entradas (acotado a fts_candidates para rendimiento)
        fts_rows = list_entries(
            conn,
            include_sensitive=include_sensitive,
            limit=fts_candidates,
        )

    if not fts_rows:
        return []

    # ── Paso 2: re-ranking semántico ────────────────────────────────────────
    if model is None or not model.is_available():
        # Sin modelo: devuelve los k primeros del FTS5 con score uniforme
        results = []
        for row in fts_rows[:k]:
            results.append(
                RetrievalResult(
                    entry_id=row["id"],
                    content=row["content"],
                    kind=row["kind"],
                    sensitive=bool(row["sensitive"]),
                    score=1.0,
                    metadata=_parse_metadata(row.get("metadata")),
                )
            )
        return results

    import numpy as np

    texts = [row["content"] for row in fts_rows]
    corpus = model.encode(texts)          # (N, dim)
    q_vec = model.encode_one(query)       # (dim,)

    top = model.top_k(q_vec, corpus, k=k)

    results = []
    for idx, score in top:
        if score < min_score:
            continue
        row = fts_rows[idx]
        results.append(
            RetrievalResult(
                entry_id=row["id"],
                content=row["content"],
                kind=row["kind"],
                sensitive=bool(row["sensitive"]),
                score=score,
                metadata=_parse_metadata(row.get("metadata")),
            )
        )
    return results


def _parse_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    import json
    try:
        return json.loads(raw)  # type: ignore[no-any-return]
    except (ValueError, TypeError):
        return {}
