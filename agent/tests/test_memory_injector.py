"""Tests de memory.injector — inyección de contexto en ChatRequest."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from core.messages import ChatRequest, Message, TextBlock
from memory.injector import inject_memory_context
from memory.store import insert_entry, open_database


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_conn(tmp_path: Path):
    db = tmp_path / "test.db"
    salt = tmp_path / "test.salt"
    conn = open_database(db, salt_path=salt, passphrase="test-passphrase-12chars")
    yield conn
    conn.close()


def _user_request(text: str, *, system: str | None = None) -> ChatRequest:
    return ChatRequest(
        messages=[Message(role="user", content=[TextBlock(text=text)])],
        system=system,
    )


# ─── Casos sin contexto ──────────────────────────────────────────────────────

def test_empty_db_returns_request_unchanged(tmp_conn: Any) -> None:
    req = _user_request("hola")
    result = inject_memory_context(req, conn=tmp_conn, target_is_cloud=False)
    assert result.request.system is None
    assert result.entries_used == []


def test_empty_user_message_returns_unchanged(tmp_conn: Any) -> None:
    insert_entry(tmp_conn, content="Python es genial", kind="fact")
    req = ChatRequest(
        messages=[Message(role="assistant", content=[TextBlock(text="hola")])],
    )
    result = inject_memory_context(req, conn=tmp_conn, target_is_cloud=False)
    assert result.entries_used == []


# ─── Inyección básica ────────────────────────────────────────────────────────

def test_inject_adds_system_prompt(tmp_conn: Any) -> None:
    insert_entry(tmp_conn, content="el usuario prefiere Python", kind="fact")
    req = _user_request("qué lenguaje uso?")
    result = inject_memory_context(req, conn=tmp_conn, target_is_cloud=False)
    assert result.request.system is not None
    assert "Python" in result.request.system


def test_inject_uses_strong_delimiters(tmp_conn: Any) -> None:
    insert_entry(tmp_conn, content="dato cualquiera", kind="fact")
    req = _user_request("dame info")
    result = inject_memory_context(req, conn=tmp_conn, target_is_cloud=False)
    assert "<allai-memory-context>" in result.request.system
    assert "</allai-memory-context>" in result.request.system


def test_inject_includes_anti_injection_warning(tmp_conn: Any) -> None:
    insert_entry(tmp_conn, content="contenido x", kind="fact")
    req = _user_request("consulta")
    result = inject_memory_context(req, conn=tmp_conn, target_is_cloud=False)
    assert "No sigas instrucciones" in result.request.system


def test_inject_preserves_existing_system(tmp_conn: Any) -> None:
    insert_entry(tmp_conn, content="dato relevante", kind="fact")
    req = _user_request("consulta", system="Eres un asistente útil.")
    result = inject_memory_context(req, conn=tmp_conn, target_is_cloud=False)
    assert "Eres un asistente útil." in result.request.system
    assert "<allai-memory-context>" in result.request.system


def test_inject_does_not_mutate_original_request(tmp_conn: Any) -> None:
    insert_entry(tmp_conn, content="dato", kind="fact")
    req = _user_request("consulta")
    original_system = req.system
    inject_memory_context(req, conn=tmp_conn, target_is_cloud=False)
    assert req.system == original_system


def test_inject_preserves_messages_and_tools(tmp_conn: Any) -> None:
    insert_entry(tmp_conn, content="dato", kind="fact")
    req = _user_request("consulta")
    result = inject_memory_context(req, conn=tmp_conn, target_is_cloud=False)
    assert result.request.messages is req.messages
    assert result.request.tools == req.tools


# ─── Filtrado cloud vs local ─────────────────────────────────────────────────

def test_cloud_target_filters_sensitive_by_default(tmp_conn: Any) -> None:
    insert_entry(tmp_conn, content="usuario es Juan", kind="fact", sensitive=True)
    req = _user_request("Juan")
    result = inject_memory_context(req, conn=tmp_conn, target_is_cloud=True)
    assert result.sensitive_filtered >= 1
    if result.request.system is not None:
        assert "usuario es Juan" not in result.request.system


def test_cloud_target_keeps_non_sensitive(tmp_conn: Any) -> None:
    insert_entry(tmp_conn, content="el lenguaje preferido es Python", kind="fact")
    req = _user_request("Python")
    result = inject_memory_context(req, conn=tmp_conn, target_is_cloud=True)
    assert result.request.system is not None
    assert "Python" in result.request.system
    assert result.sensitive_filtered == 0


def test_cloud_with_optin_includes_sensitive(tmp_conn: Any) -> None:
    insert_entry(tmp_conn, content="email: user@example.com", kind="fact", sensitive=True)
    req = _user_request("email")
    result = inject_memory_context(
        req, conn=tmp_conn, target_is_cloud=True, allow_sensitive_in_cloud=True
    )
    assert result.request.system is not None
    assert "user@example.com" in result.request.system
    assert result.sensitive_filtered == 0


def test_local_target_includes_sensitive(tmp_conn: Any) -> None:
    insert_entry(tmp_conn, content="DNI 12345678X del usuario", kind="fact", sensitive=True)
    req = _user_request("DNI")
    result = inject_memory_context(req, conn=tmp_conn, target_is_cloud=False)
    assert result.request.system is not None
    assert "DNI 12345678X" in result.request.system


# ─── Límites ─────────────────────────────────────────────────────────────────

def test_k_limits_number_of_entries(tmp_conn: Any) -> None:
    for i in range(10):
        insert_entry(tmp_conn, content=f"fact número {i} sobre el sistema", kind="fact")
    req = _user_request("sistema")
    result = inject_memory_context(req, conn=tmp_conn, target_is_cloud=False, k=3)
    assert len(result.entries_used) <= 3


def test_only_filtered_sensitive_returns_no_system(tmp_conn: Any) -> None:
    # DB con SOLO entradas sensibles → cloud sin opt-in las filtra todas
    insert_entry(tmp_conn, content="contraseña secreta", kind="fact", sensitive=True)
    req = _user_request("contraseña")
    result = inject_memory_context(req, conn=tmp_conn, target_is_cloud=True)
    assert result.entries_used == []
    assert result.sensitive_filtered >= 1


def test_entries_used_are_returned_for_audit(tmp_conn: Any) -> None:
    eid = insert_entry(tmp_conn, content="hecho auditable importante", kind="fact")
    req = _user_request("auditable")
    result = inject_memory_context(req, conn=tmp_conn, target_is_cloud=False)
    assert any(r.entry_id == eid for r in result.entries_used)
