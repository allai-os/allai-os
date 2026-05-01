"""Memoria de sesión — short-term in-memory.

Almacena hechos y mensajes de la sesión activa en RAM. No persiste nada
al disco sin opt-in explícito del usuario (ver store.py para persistencia).

Diseño:
- Ventana deslizante de tamaño configurable (default 50 entradas).
- Cada entrada tiene un kind ('fact' | 'message' | 'observation'),
  un flag sensitive y un timestamp.
- Thread-safe (lock interno).
- Método flush_to_store() para persistir opt-in al SQLCipher store.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Literal

from memory.pii import is_sensitive as _is_sensitive


Kind = Literal["fact", "message", "observation"]

DEFAULT_MAX_ENTRIES = 50


@dataclass(slots=True)
class SessionEntry:
    content: str
    kind: Kind
    sensitive: bool
    created_at: float = field(default_factory=time.monotonic)
    metadata: dict[str, object] = field(default_factory=dict)


class SessionMemory:
    """Memoria de sesión en RAM con ventana deslizante."""

    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        if max_entries < 1:
            raise ValueError("max_entries debe ser ≥ 1")
        self._max = max_entries
        self._entries: list[SessionEntry] = []
        self._lock = threading.Lock()

    # ─── Escritura ───────────────────────────────────────────────────────────

    def add(
        self,
        content: str,
        *,
        kind: Kind = "fact",
        sensitive: bool | None = None,
        metadata: dict[str, object] | None = None,
    ) -> SessionEntry:
        """Añade una entrada. Detecta PII automáticamente si sensitive=None."""
        if not content or not content.strip():
            raise ValueError("content no puede estar vacío")
        auto_sensitive = _is_sensitive(content) if sensitive is None else sensitive
        entry = SessionEntry(
            content=content.strip(),
            kind=kind,
            sensitive=auto_sensitive,
            metadata=metadata or {},
        )
        with self._lock:
            self._entries.append(entry)
            if len(self._entries) > self._max:
                self._entries = self._entries[-self._max :]
        return entry

    def clear(self) -> int:
        """Elimina todas las entradas. Devuelve cuántas había."""
        with self._lock:
            count = len(self._entries)
            self._entries = []
        return count

    # ─── Lectura ─────────────────────────────────────────────────────────────

    def all(self, *, include_sensitive: bool = True) -> list[SessionEntry]:
        """Devuelve todas las entradas (copia)."""
        with self._lock:
            entries = list(self._entries)
        if not include_sensitive:
            entries = [e for e in entries if not e.sensitive]
        return entries

    def recent(
        self, n: int, *, include_sensitive: bool = True
    ) -> list[SessionEntry]:
        """Devuelve las últimas `n` entradas."""
        return self.all(include_sensitive=include_sensitive)[-n:]

    def by_kind(self, kind: Kind) -> list[SessionEntry]:
        """Filtra por kind."""
        with self._lock:
            return [e for e in self._entries if e.kind == kind]

    def search(self, query: str, *, include_sensitive: bool = True) -> list[SessionEntry]:
        """Búsqueda léxica simple (substring case-insensitive)."""
        q = query.lower()
        return [
            e
            for e in self.all(include_sensitive=include_sensitive)
            if q in e.content.lower()
        ]

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._entries)

    @property
    def max_entries(self) -> int:
        return self._max

    # ─── Resumen para inyección en contexto ──────────────────────────────────

    def context_snippet(
        self,
        n: int = 10,
        *,
        allow_sensitive: bool = False,
    ) -> str:
        """Genera un bloque de texto listo para inyectar al agente.

        Solo incluye entradas no-sensibles a menos que allow_sensitive=True.
        """
        entries = self.recent(n, include_sensitive=allow_sensitive)
        if not entries:
            return ""
        lines = [f"[{e.kind}] {e.content}" for e in entries]
        return "\n".join(lines)
