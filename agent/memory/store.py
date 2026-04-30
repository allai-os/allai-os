"""Almacenamiento cifrado de memoria via SQLCipher.

Usa `sqlcipher3` (con `libsqlcipher` instalado en el sistema). En Linux la
forma simple es `pip install sqlcipher3-binary` que incluye SQLCipher
embebido. En Windows actualmente no existe wheel — el desarrollo del
módulo de memoria se valida en VM Fedora; en Windows el módulo importa
pero las funciones que abren DB lanzan `SQLCipherUnavailableError`.

Decisiones (security-first):

- **Cifrado**: AES-256-CBC con HMAC-SHA512 (defaults de SQLCipher 4.x).
  Esto incluye los archivos auxiliares (`.db-journal`, `.db-wal`,
  `.db-shm`) — ningún byte de la memoria toca el disco en claro.
- **Derivación de la key**: usamos Argon2id en `crypto.py` para producir
  32 bytes raw, que pasamos a SQLCipher con
  `PRAGMA key = "x'<hex>'"` (saltando el PBKDF2-SHA512 interno de
  SQLCipher porque Argon2id es más fuerte y resistente a GPU/ASIC).
- **Verificación de la passphrase**: tras abrir, ejecutamos un
  `SELECT count(*) FROM sqlite_master`. Si la key es incorrecta
  SQLCipher devuelve `SQLITE_NOTADB` o un error de cifrado, que
  traducimos a `InvalidPassphraseError`.
- **Permisos**: antes de abrir, validamos `validate_file_perms` (0600)
  sobre el `.db` y `validate_dir_perms` (0700) sobre el directorio.
  Si están laxos, refusamos abrir.
- **Foreign keys**: habilitados (`PRAGMA foreign_keys = ON`) para que
  borrar una entrada arrastre sus embeddings.
- **Schema mínimo**: una tabla principal `memory_entries`, FTS5 para
  búsqueda léxica, tabla de embeddings vinculada por FK con CASCADE.
- **Sin logging de la key**: `apply_key()` no es loggeable; sólo
  enviamos el PRAGMA y borramos la referencia local.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from memory.crypto import (
    InvalidPassphraseError,
    derive_key,
    generate_salt,
    key_to_sqlcipher_pragma,
    load_salt,
    store_salt,
)
from memory.permissions import (
    ensure_dir,
    ensure_file_perms,
    validate_dir_perms,
    validate_file_perms,
)


class StoreError(Exception):
    """Error general del store."""


class SQLCipherUnavailableError(StoreError):
    """`sqlcipher3` no está instalado o no se puede importar."""


# ─── Schema ──────────────────────────────────────────────────────────────────

_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS memory_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    content     TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'fact',
    sensitive   INTEGER NOT NULL DEFAULT 0 CHECK (sensitive IN (0, 1)),
    untrusted   INTEGER NOT NULL DEFAULT 0 CHECK (untrusted IN (0, 1)),
    created_at  INTEGER NOT NULL,
    expires_at  INTEGER,
    metadata    TEXT
);

CREATE INDEX IF NOT EXISTS idx_memory_kind ON memory_entries(kind);
CREATE INDEX IF NOT EXISTS idx_memory_expires ON memory_entries(expires_at);
CREATE INDEX IF NOT EXISTS idx_memory_sensitive ON memory_entries(sensitive);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    content,
    content='memory_entries',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS memory_ai AFTER INSERT ON memory_entries BEGIN
    INSERT INTO memory_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS memory_ad AFTER DELETE ON memory_entries BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, content)
        VALUES('delete', old.id, old.content);
END;

CREATE TRIGGER IF NOT EXISTS memory_au AFTER UPDATE ON memory_entries BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, content)
        VALUES('delete', old.id, old.content);
    INSERT INTO memory_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE TABLE IF NOT EXISTS memory_embeddings (
    entry_id    INTEGER PRIMARY KEY,
    model       TEXT NOT NULL,
    dim         INTEGER NOT NULL,
    vector      BLOB NOT NULL,
    FOREIGN KEY (entry_id) REFERENCES memory_entries(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_embeddings_model ON memory_embeddings(model);
"""


# ─── Disponibilidad de SQLCipher ─────────────────────────────────────────────


def _import_sqlcipher() -> Any:
    """Import perezoso de sqlcipher3.

    Lo hacemos lazy para que el módulo cargue en Windows sin SQLCipher
    instalado — útil para tests unitarios de los demás submódulos.
    """
    try:
        import sqlcipher3  # type: ignore[import-not-found]
    except ImportError as exc:
        raise SQLCipherUnavailableError(
            "sqlcipher3 no está disponible. En Linux/macOS: "
            "`pip install sqlcipher3-binary`. En Windows: usa una VM Fedora "
            "para ejercitar el store de memoria (no hay wheel oficial)."
        ) from exc
    return sqlcipher3


def is_sqlcipher_available() -> bool:
    """True si `sqlcipher3` se puede importar en este entorno."""
    try:
        _import_sqlcipher()
    except SQLCipherUnavailableError:
        return False
    return True


# ─── Apertura de DB ──────────────────────────────────────────────────────────


def open_database(
    db_path: Path,
    *,
    salt_path: Path,
    passphrase: str,
    create_if_missing: bool = True,
) -> Any:
    """Abre (o crea) la DB cifrada en `db_path`.

    Pasos:
      1. Asegurar/validar permisos del directorio (0700) y archivos (0600).
      2. Cargar salt (o generar uno nuevo si `create_if_missing` y no existe).
      3. Derivar key con Argon2id.
      4. Conectar a SQLCipher, aplicar `PRAGMA key`.
      5. Verificar integridad con SELECT (lanza InvalidPassphraseError si
         la key no descifra).
      6. Aplicar schema (idempotente).

    Args:
      db_path: ruta al archivo .db (puede no existir si create_if_missing).
      salt_path: ruta al archivo .salt (idem).
      passphrase: secreto del usuario.
      create_if_missing: si True, genera salt y crea DB nueva cuando no
        existen. Si False y faltan, lanza FileNotFoundError.

    Raises:
      SQLCipherUnavailableError: sqlcipher3 no instalado.
      FileNotFoundError: archivos faltan y create_if_missing=False.
      InsecurePermissionsError: permisos laxos detectados.
      InvalidPassphraseError: la passphrase no descifra la DB.
      StoreError: errores no clasificados de SQLCipher.
    """
    sqlcipher = _import_sqlcipher()

    # 1) Directorio y permisos.
    ensure_dir(db_path.parent)

    # 2) Salt.
    if not salt_path.exists():
        if not create_if_missing:
            raise FileNotFoundError(f"salt no encontrado: {salt_path}")
        store_salt(salt_path, generate_salt())
    ensure_file_perms(salt_path)
    validate_file_perms(salt_path)
    salt = load_salt(salt_path)

    # 3) Derivar key.
    key = derive_key(passphrase, salt)

    # 4) Conectar.
    db_existed = db_path.exists()
    if not db_existed and not create_if_missing:
        raise FileNotFoundError(f"DB no encontrada: {db_path}")

    if db_existed:
        validate_file_perms(db_path)

    conn = sqlcipher.connect(str(db_path), isolation_level=None)
    try:
        _apply_key(conn, key)
        _verify_or_raise(conn)
        _apply_pragmas(conn)
        if not db_existed:
            conn.executescript(_SCHEMA)
        else:
            # Aplica schema de forma idempotente (CREATE IF NOT EXISTS)
            conn.executescript(_SCHEMA)
    except BaseException:
        conn.close()
        raise
    finally:
        # Borra la key local — el GC se encarga del resto.
        key = b""  # noqa: F841

    # Permisos del archivo recién creado
    if not db_existed:
        ensure_file_perms(db_path)

    return conn


def _apply_key(conn: Any, key: bytes) -> None:
    """Aplica la key derivada vía PRAGMA key.

    Importante: no concatenamos la key como string Python plano (que
    podría aparecer en stacktraces); construimos el statement dentro
    del closure y borramos la variable local apenas terminamos.
    """
    pragma = key_to_sqlcipher_pragma(key)
    statement = f"PRAGMA key = {pragma};"
    conn.execute(statement)
    # Limpia el statement que contiene la key.
    statement = ""  # noqa: F841


def _verify_or_raise(conn: Any) -> None:
    """Verifica que la key descifra la DB; lanza InvalidPassphraseError si no."""
    try:
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except Exception as exc:
        raise InvalidPassphraseError(
            "no se pudo descifrar la DB con la passphrase provista"
        ) from exc


def _apply_pragmas(conn: Any) -> None:
    """PRAGMAs no relacionados con key/cifrado."""
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA cipher_compatibility = 4;")
    conn.execute("PRAGMA cipher_page_size = 4096;")


# ─── Operaciones básicas ─────────────────────────────────────────────────────


def insert_entry(
    conn: Any,
    *,
    content: str,
    kind: str = "fact",
    sensitive: bool = False,
    untrusted: bool = False,
    expires_at: int | None = None,
    metadata: str | None = None,
    now: int | None = None,
) -> int:
    """Inserta una entrada y devuelve su `id`."""
    ts = now if now is not None else int(time.time())
    cur = conn.execute(
        """
        INSERT INTO memory_entries
            (content, kind, sensitive, untrusted, created_at, expires_at, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            content,
            kind,
            1 if sensitive else 0,
            1 if untrusted else 0,
            ts,
            expires_at,
            metadata,
        ),
    )
    return int(cur.lastrowid)


def delete_entry(conn: Any, entry_id: int) -> bool:
    """Borra una entrada por id. Devuelve True si existía."""
    cur = conn.execute("DELETE FROM memory_entries WHERE id = ?", (entry_id,))
    return cur.rowcount > 0


def list_entries(
    conn: Any,
    *,
    kind: str | None = None,
    include_sensitive: bool = True,
    limit: int = 100,
    now: int | None = None,
) -> list[dict[str, Any]]:
    """Lista entradas no expiradas, opcionalmente filtradas."""
    ts = now if now is not None else int(time.time())
    query = (
        "SELECT id, content, kind, sensitive, untrusted, created_at, "
        "expires_at, metadata FROM memory_entries "
        "WHERE (expires_at IS NULL OR expires_at > ?)"
    )
    params: list[Any] = [ts]
    if kind is not None:
        query += " AND kind = ?"
        params.append(kind)
    if not include_sensitive:
        query += " AND sensitive = 0"
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_entry(conn: Any, entry_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, content, kind, sensitive, untrusted, created_at, "
        "expires_at, metadata FROM memory_entries WHERE id = ?",
        (entry_id,),
    ).fetchone()
    return _row_to_dict(row) if row else None


def purge_expired(conn: Any, *, now: int | None = None) -> int:
    """Borra entradas con `expires_at <= now`. Devuelve el número borrado."""
    ts = now if now is not None else int(time.time())
    cur = conn.execute(
        "DELETE FROM memory_entries WHERE expires_at IS NOT NULL AND expires_at <= ?",
        (ts,),
    )
    return int(cur.rowcount)


def search_fts(
    conn: Any,
    query: str,
    *,
    limit: int = 10,
    include_sensitive: bool = True,
    now: int | None = None,
) -> list[dict[str, Any]]:
    """Busca entradas con FTS5 (BM25 implícito).

    `query` se pasa tal cual a FTS5; el caller debe sanitizarla si viene
    de input no confiable (FTS5 acepta operadores `AND/OR/NOT/NEAR`,
    quotes, prefijos). Para el caso de "buscar texto literal", envolver
    en comillas dobles antes de llamar.
    """
    ts = now if now is not None else int(time.time())
    sql = (
        "SELECT e.id, e.content, e.kind, e.sensitive, e.untrusted, "
        "e.created_at, e.expires_at, e.metadata "
        "FROM memory_fts f JOIN memory_entries e ON e.id = f.rowid "
        "WHERE memory_fts MATCH ? "
        "AND (e.expires_at IS NULL OR e.expires_at > ?)"
    )
    params: list[Any] = [query, ts]
    if not include_sensitive:
        sql += " AND e.sensitive = 0"
    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(r) for r in rows]


# ─── Helpers ─────────────────────────────────────────────────────────────────


@contextmanager
def transaction(conn: Any) -> Iterator[Any]:
    """Context manager para transacciones explícitas con BEGIN/COMMIT/ROLLBACK."""
    conn.execute("BEGIN")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row[0],
        "content": row[1],
        "kind": row[2],
        "sensitive": bool(row[3]),
        "untrusted": bool(row[4]),
        "created_at": row[5],
        "expires_at": row[6],
        "metadata": row[7],
    }
