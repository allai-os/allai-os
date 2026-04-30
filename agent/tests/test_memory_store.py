"""Tests del store cifrado de memoria.

Tests divididos en dos categorías:

1. **Sin SQLCipher**: validan que el módulo se importa, que los errores
   son explícitos cuando sqlcipher3 no está disponible, y que las
   funciones de validación de archivos (sin tocar DB) funcionan.

2. **Con SQLCipher** (skip si no está disponible): validan apertura,
   passphrase incorrecta, schema, CRUD básico, FTS, expiración y
   transacciones. Estos corren en Linux/macOS con
   `pip install sqlcipher3-binary`. En Windows se skipan automáticamente.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from memory.crypto import generate_salt, store_salt
from memory.store import (
    SQLCipherUnavailableError,
    delete_entry,
    get_entry,
    insert_entry,
    is_sqlcipher_available,
    list_entries,
    open_database,
    purge_expired,
    search_fts,
    transaction,
)

from memory.crypto import InvalidPassphraseError as _InvalidPassphraseError  # re-export

# Skip mark común para tests que necesitan SQLCipher real
_NEEDS_SQLCIPHER = pytest.mark.skipif(
    not is_sqlcipher_available(),
    reason="sqlcipher3 no instalado (instala sqlcipher3-binary en Linux/macOS)",
)


# ─── Tests sin SQLCipher ─────────────────────────────────────────────────────


def test_module_imports_without_sqlcipher() -> None:
    """El módulo debe importar incluso si sqlcipher3 no está instalado."""
    # Ya importó arriba sin error → pasa
    assert True


def test_open_database_raises_explicit_error_without_sqlcipher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si sqlcipher3 no está, open_database lanza error claro y útil."""
    # Forzar el estado "no disponible" mockeando el import
    import memory.store as store_mod

    def _raise(*args: object, **kwargs: object) -> None:  # noqa: ARG001
        raise SQLCipherUnavailableError("simulado: sqlcipher3 no instalado")

    monkeypatch.setattr(store_mod, "_import_sqlcipher", _raise)

    with pytest.raises(SQLCipherUnavailableError, match="sqlcipher"):
        open_database(
            tmp_path / "memory.db",
            salt_path=tmp_path / "memory.salt",
            passphrase="hunter2",
        )


def test_is_sqlcipher_available_returns_bool() -> None:
    result = is_sqlcipher_available()
    assert isinstance(result, bool)


# ─── Tests con SQLCipher real ────────────────────────────────────────────────


@_NEEDS_SQLCIPHER
def test_open_database_creates_db_and_salt(tmp_path: Path) -> None:
    db = tmp_path / "memory.db"
    salt = tmp_path / "memory.salt"
    conn = open_database(db, salt_path=salt, passphrase="hunter2")
    try:
        assert db.exists()
        assert salt.exists()
        # Schema aplicado
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        names = {r[0] for r in rows}
        assert "memory_entries" in names
        assert "memory_embeddings" in names
    finally:
        conn.close()


@_NEEDS_SQLCIPHER
def test_open_database_rejects_wrong_passphrase(tmp_path: Path) -> None:
    db = tmp_path / "memory.db"
    salt = tmp_path / "memory.salt"
    conn = open_database(db, salt_path=salt, passphrase="hunter2")
    insert_entry(conn, content="dato secreto")
    conn.close()

    with pytest.raises(_InvalidPassphraseError):
        open_database(db, salt_path=salt, passphrase="wrong-passphrase")


@_NEEDS_SQLCIPHER
def test_open_database_refuses_when_create_disabled_and_missing(
    tmp_path: Path,
) -> None:
    db = tmp_path / "memory.db"
    salt = tmp_path / "memory.salt"
    # Sin salt previo y create_if_missing=False
    with pytest.raises(FileNotFoundError):
        open_database(
            db, salt_path=salt, passphrase="x", create_if_missing=False
        )


@_NEEDS_SQLCIPHER
def test_open_database_refuses_db_missing_with_existing_salt(
    tmp_path: Path,
) -> None:
    db = tmp_path / "memory.db"
    salt = tmp_path / "memory.salt"
    store_salt(salt, generate_salt())
    with pytest.raises(FileNotFoundError):
        open_database(
            db, salt_path=salt, passphrase="x", create_if_missing=False
        )


@_NEEDS_SQLCIPHER
def test_db_file_is_actually_encrypted(tmp_path: Path) -> None:
    """El archivo .db en disco no debe contener el contenido en claro."""
    db = tmp_path / "memory.db"
    conn = open_database(
        db, salt_path=tmp_path / "memory.salt", passphrase="hunter2"
    )
    insert_entry(conn, content="cadena súper distintiva 12345abcXYZ")
    conn.close()

    raw = db.read_bytes()
    assert b"cadena super distintiva" not in raw
    assert b"cadena s" not in raw
    assert b"12345abcXYZ" not in raw


@_NEEDS_SQLCIPHER
def test_insert_and_get_entry(tmp_path: Path) -> None:
    conn = open_database(
        tmp_path / "memory.db",
        salt_path=tmp_path / "memory.salt",
        passphrase="hunter2",
    )
    try:
        eid = insert_entry(
            conn, content="me gusta el café sin azúcar", kind="preference"
        )
        row = get_entry(conn, eid)
        assert row is not None
        assert row["content"] == "me gusta el café sin azúcar"
        assert row["kind"] == "preference"
        assert row["sensitive"] is False
        assert row["untrusted"] is False
    finally:
        conn.close()


@_NEEDS_SQLCIPHER
def test_list_entries_filters_sensitive(tmp_path: Path) -> None:
    conn = open_database(
        tmp_path / "memory.db",
        salt_path=tmp_path / "memory.salt",
        passphrase="hunter2",
    )
    try:
        insert_entry(conn, content="público")
        insert_entry(conn, content="privado", sensitive=True)
        all_rows = list_entries(conn)
        assert len(all_rows) == 2
        non_sensitive = list_entries(conn, include_sensitive=False)
        assert len(non_sensitive) == 1
        assert non_sensitive[0]["content"] == "público"
    finally:
        conn.close()


@_NEEDS_SQLCIPHER
def test_delete_entry(tmp_path: Path) -> None:
    conn = open_database(
        tmp_path / "memory.db",
        salt_path=tmp_path / "memory.salt",
        passphrase="hunter2",
    )
    try:
        eid = insert_entry(conn, content="borrar")
        assert delete_entry(conn, eid) is True
        assert get_entry(conn, eid) is None
        assert delete_entry(conn, 9999) is False
    finally:
        conn.close()


@_NEEDS_SQLCIPHER
def test_purge_expired(tmp_path: Path) -> None:
    conn = open_database(
        tmp_path / "memory.db",
        salt_path=tmp_path / "memory.salt",
        passphrase="hunter2",
    )
    try:
        insert_entry(conn, content="viejo", expires_at=100, now=50)
        insert_entry(conn, content="vigente", expires_at=10_000, now=50)
        insert_entry(conn, content="permanente", now=50)
        purged = purge_expired(conn, now=200)
        assert purged == 1
        rows = list_entries(conn, now=200)
        contents = sorted(r["content"] for r in rows)
        assert contents == ["permanente", "vigente"]
    finally:
        conn.close()


@_NEEDS_SQLCIPHER
def test_search_fts_finds_matches(tmp_path: Path) -> None:
    conn = open_database(
        tmp_path / "memory.db",
        salt_path=tmp_path / "memory.salt",
        passphrase="hunter2",
    )
    try:
        insert_entry(conn, content="me gusta el café sin azúcar")
        insert_entry(conn, content="prefiero el té verde por la mañana")
        insert_entry(conn, content="el almuerzo suele ser ligero")

        rows = search_fts(conn, "café")
        assert len(rows) == 1
        assert "café" in rows[0]["content"]

        rows = search_fts(conn, "té OR almuerzo")
        assert len(rows) == 2
    finally:
        conn.close()


@_NEEDS_SQLCIPHER
def test_search_fts_excludes_sensitive_when_asked(tmp_path: Path) -> None:
    conn = open_database(
        tmp_path / "memory.db",
        salt_path=tmp_path / "memory.salt",
        passphrase="hunter2",
    )
    try:
        insert_entry(conn, content="café público")
        insert_entry(conn, content="café privado", sensitive=True)
        rows = search_fts(conn, "café", include_sensitive=False)
        assert len(rows) == 1
        assert rows[0]["content"] == "café público"
    finally:
        conn.close()


@_NEEDS_SQLCIPHER
def test_transaction_rollback_on_exception(tmp_path: Path) -> None:
    conn = open_database(
        tmp_path / "memory.db",
        salt_path=tmp_path / "memory.salt",
        passphrase="hunter2",
    )
    try:
        with pytest.raises(RuntimeError, match="boom"):
            with transaction(conn):
                insert_entry(conn, content="dentro de tx")
                raise RuntimeError("boom")
        # La entrada NO debe existir tras rollback
        rows = list_entries(conn)
        assert rows == []
    finally:
        conn.close()


@_NEEDS_SQLCIPHER
def test_transaction_commit_on_success(tmp_path: Path) -> None:
    conn = open_database(
        tmp_path / "memory.db",
        salt_path=tmp_path / "memory.salt",
        passphrase="hunter2",
    )
    try:
        with transaction(conn):
            insert_entry(conn, content="persistente")
        rows = list_entries(conn)
        assert len(rows) == 1
    finally:
        conn.close()


@_NEEDS_SQLCIPHER
def test_reopen_with_correct_passphrase_finds_data(tmp_path: Path) -> None:
    db = tmp_path / "memory.db"
    salt = tmp_path / "memory.salt"
    conn = open_database(db, salt_path=salt, passphrase="correcto")
    insert_entry(conn, content="persistente entre sesiones")
    conn.close()

    conn2 = open_database(db, salt_path=salt, passphrase="correcto")
    try:
        rows = list_entries(conn2)
        assert len(rows) == 1
        assert rows[0]["content"] == "persistente entre sesiones"
    finally:
        conn2.close()
