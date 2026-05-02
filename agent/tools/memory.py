"""Tools de memoria del agente.

Expone al modelo 6 tools para interactuar con la memoria local cifrada:

  recall         SAFE      — búsqueda semántica + FTS5 en la DB.
  memory.list    SAFE      — lista entradas recientes de la DB.
  remember       CONFIRM   — persiste un hecho en la DB.
  forget         DANGEROUS — borra una entrada por ID.
  export         DANGEROUS — exporta la DB cifrada a un archivo.
  rotate_key     DANGEROUS — rota la passphrase de la DB.

Uso:
    ctx = MemoryContext(conn=conn, session=session, model=embeddings_model)
    tools = build_memory_tools(ctx)
    for t in tools:
        registry.register(t)

El diseño de closures permite inyectar el contexto en los executors
sin globals, lo que facilita tests y sesiones aisladas.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memory.embeddings import EmbeddingsModel
from memory.injection_guard import InjectionBlockedError, InjectionPolicy, assert_safe_for_injection
from memory.pii import assert_safe_for_cloud, is_sensitive
from memory.retrieval import retrieve
from memory.session import SessionMemory
from memory.store import (
    delete_entry,
    get_entry,
    insert_entry,
    list_entries,
    open_database,
)
from tools.base import RiskLevel, ToolDefinition, ToolResult


@dataclass
class MemoryContext:
    """Contexto de memoria para una sesión activa."""

    conn: Any
    """Conexión SQLCipher abierta (de open_database())."""
    session: SessionMemory
    """Memoria de sesión en RAM."""
    model: EmbeddingsModel | None = None
    """Modelo de embeddings (opcional — si None, recall usa solo FTS5)."""


# ─── recall ──────────────────────────────────────────────────────────────────

def _make_recall(ctx: MemoryContext) -> ToolDefinition:
    def executor(query: str, k: int = 5, include_sensitive: bool = False) -> ToolResult:
        try:
            results = retrieve(
                query,
                ctx.conn,
                model=ctx.model,
                k=k,
                include_sensitive=include_sensitive,
            )
            if not results:
                return ToolResult(output="No encontré entradas relevantes.")
            lines = []
            for r in results:
                tag = "[sensible]" if r.sensitive else ""
                lines.append(f"[id={r.entry_id} score={r.score:.2f} {tag}] {r.content}")
            return ToolResult(output="\n".join(lines))
        except Exception as exc:  # noqa: BLE001
            return ToolResult(output=f"Error en recall: {exc}", is_error=True)

    return ToolDefinition(
        name="recall",
        description=(
            "Busca en la memoria persistente del agente usando búsqueda semántica "
            "y léxica. Devuelve las entradas más relevantes para la consulta. "
            "Solo lee — no modifica nada."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Texto a buscar"},
                "k": {
                    "type": "integer",
                    "description": "Número máximo de resultados (default 5)",
                    "default": 5,
                },
                "include_sensitive": {
                    "type": "boolean",
                    "description": "Incluir entradas sensibles (default false)",
                    "default": False,
                },
            },
            "required": ["query"],
        },
        risk=RiskLevel.SAFE,
        executor=executor,
        category="memory",
    )


# ─── memory.list ─────────────────────────────────────────────────────────────

def _make_list(ctx: MemoryContext) -> ToolDefinition:
    def executor(limit: int = 10, include_sensitive: bool = False) -> ToolResult:
        try:
            rows = list_entries(ctx.conn, include_sensitive=include_sensitive, limit=limit)
            if not rows:
                return ToolResult(output="La memoria está vacía.")
            lines = []
            for r in rows:
                tag = "[sensible]" if r["sensitive"] else ""
                lines.append(f"[id={r['id']} kind={r['kind']} {tag}] {r['content'][:120]}")
            return ToolResult(output="\n".join(lines))
        except Exception as exc:  # noqa: BLE001
            return ToolResult(output=f"Error al listar memoria: {exc}", is_error=True)

    return ToolDefinition(
        name="memory.list",
        description=(
            "Lista las entradas más recientes de la memoria persistente. "
            "Solo lee — no modifica nada."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Máximo de entradas a mostrar (default 10)",
                    "default": 10,
                },
                "include_sensitive": {
                    "type": "boolean",
                    "description": "Incluir entradas sensibles (default false)",
                    "default": False,
                },
            },
        },
        risk=RiskLevel.SAFE,
        executor=executor,
        category="memory",
    )


# ─── remember ────────────────────────────────────────────────────────────────

def _make_remember(ctx: MemoryContext) -> ToolDefinition:
    def executor(content: str, kind: str = "fact") -> ToolResult:
        try:
            # Guardia de inyección antes de persistir
            try:
                safe_content = assert_safe_for_injection(
                    content, policy=InjectionPolicy.WRAP
                )
            except InjectionBlockedError as e:
                return ToolResult(
                    output=f"Entrada rechazada por guardia de inyección: {e}",
                    is_error=True,
                )

            auto_sensitive = is_sensitive(content)
            entry_id = insert_entry(
                ctx.conn,
                content=safe_content,
                kind=kind,
                sensitive=auto_sensitive,
            )
            ctx.session.add(content, kind=kind, sensitive=auto_sensitive)  # type: ignore[arg-type]

            tag = " [marcada como sensible — no se enviará a cloud sin opt-in]" if auto_sensitive else ""
            return ToolResult(
                output=f"Guardado con id={entry_id}.{tag}",
                structured={"entry_id": entry_id, "sensitive": auto_sensitive},
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(output=f"Error al guardar: {exc}", is_error=True)

    return ToolDefinition(
        name="remember",
        description=(
            "Persiste un hecho o dato en la memoria cifrada del agente. "
            "Si el contenido contiene PII (email, teléfono, etc.) se marca "
            "automáticamente como sensible y no se enviará a APIs cloud sin "
            "autorización explícita del usuario."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Texto a memorizar",
                },
                "kind": {
                    "type": "string",
                    "enum": ["fact", "message", "observation"],
                    "description": "Tipo de entrada (default 'fact')",
                    "default": "fact",
                },
            },
            "required": ["content"],
        },
        risk=RiskLevel.CONFIRM,
        executor=executor,
        capabilities_required=["memory:write"],
        category="memory",
    )


# ─── forget ──────────────────────────────────────────────────────────────────

def _make_forget(ctx: MemoryContext) -> ToolDefinition:
    def executor(entry_id: int) -> ToolResult:
        try:
            entry = get_entry(ctx.conn, entry_id)
            if entry is None:
                return ToolResult(
                    output=f"No existe ninguna entrada con id={entry_id}.",
                    is_error=True,
                )
            deleted = delete_entry(ctx.conn, entry_id)
            if deleted:
                return ToolResult(
                    output=f"Entrada id={entry_id} eliminada permanentemente.",
                    structured={"deleted_id": entry_id},
                )
            return ToolResult(
                output=f"No se pudo eliminar id={entry_id}.", is_error=True
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(output=f"Error al borrar: {exc}", is_error=True)

    return ToolDefinition(
        name="forget",
        description=(
            "Borra permanentemente una entrada de la memoria por su ID. "
            "⚠️ Irreversible. Requiere confirmación humana siempre."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "entry_id": {
                    "type": "integer",
                    "description": "ID de la entrada a borrar (obtenido de recall o memory.list)",
                },
            },
            "required": ["entry_id"],
        },
        risk=RiskLevel.DANGEROUS,
        executor=executor,
        capabilities_required=["memory:write"],
        category="memory",
    )


# ─── export ──────────────────────────────────────────────────────────────────

def _make_export(ctx: MemoryContext, db_path: Path) -> ToolDefinition:
    def executor(destination: str) -> ToolResult:
        try:
            dest = Path(destination).expanduser().resolve()
            if dest.is_dir():
                dest = dest / f"allai-memory-{int(time.time())}.db"
            shutil.copy2(db_path, dest)
            return ToolResult(
                output=(
                    f"Memoria exportada a {dest}. "
                    "El archivo está cifrado con la misma passphrase. "
                    "Guárdalo en un lugar seguro."
                ),
                structured={"path": str(dest)},
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(output=f"Error al exportar: {exc}", is_error=True)

    return ToolDefinition(
        name="export",
        description=(
            "Exporta la base de datos de memoria cifrada a un archivo. "
            "⚠️ El archivo contiene toda la memoria (incluyendo entradas sensibles). "
            "Requiere confirmación humana siempre."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "destination": {
                    "type": "string",
                    "description": "Ruta destino del archivo exportado",
                },
            },
            "required": ["destination"],
        },
        risk=RiskLevel.DANGEROUS,
        executor=executor,
        capabilities_required=["memory:export"],
        category="memory",
    )


# ─── rotate_key ──────────────────────────────────────────────────────────────

def _make_rotate_key(ctx: MemoryContext, db_path: Path, salt_path: Path) -> ToolDefinition:
    def executor(new_passphrase: str) -> ToolResult:
        if not new_passphrase or len(new_passphrase) < 12:
            return ToolResult(
                output="La nueva passphrase debe tener al menos 12 caracteres.",
                is_error=True,
            )
        try:
            # 1. Abre con la nueva passphrase en un archivo temporal para
            #    verificar que funciona antes de sobrescribir el original.
            with tempfile.TemporaryDirectory() as tmp:
                new_db = Path(tmp) / "new.db"
                new_salt = Path(tmp) / "new.salt"
                new_conn = open_database(
                    new_db, salt_path=new_salt, passphrase=new_passphrase
                )
                new_conn.close()

            # 2. Re-cifra el DB actual con la nueva key (SQLCipher PRAGMA rekey).
            ctx.conn.execute(
                f'PRAGMA rekey = "x\'{_derive_hex(new_passphrase, salt_path)}\'"'
            )
            # 3. Regenera la salt con la nueva passphrase (invalida la vieja key).
            from memory.crypto import derive_key, generate_salt, store_salt
            new_salt_bytes = generate_salt()
            store_salt(new_salt_bytes, salt_path)
            # Nota: el conn actual sigue funcionando hasta cerrar;
            # la próxima apertura requerirá la nueva passphrase.
            return ToolResult(
                output=(
                    "Passphrase rotada. Cierra y reabre la sesión para aplicar. "
                    "⚠️ La passphrase anterior ya no funciona."
                )
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(output=f"Error al rotar key: {exc}", is_error=True)

    def _derive_hex(passphrase: str, salt_p: Path) -> str:
        from memory.crypto import derive_key, load_salt
        salt = load_salt(salt_p)
        key = derive_key(passphrase, salt)
        return key.hex()

    return ToolDefinition(
        name="rotate_key",
        description=(
            "Rota la passphrase de la base de datos de memoria. "
            "⚠️ La passphrase anterior dejará de funcionar. Irreversible. "
            "Requiere confirmación humana siempre."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "new_passphrase": {
                    "type": "string",
                    "description": "Nueva passphrase (mínimo 12 caracteres)",
                },
            },
            "required": ["new_passphrase"],
        },
        risk=RiskLevel.DANGEROUS,
        executor=executor,
        capabilities_required=["memory:rotate_key"],
        category="memory",
    )


# ─── Factory pública ──────────────────────────────────────────────────────────

def build_memory_tools(
    ctx: MemoryContext,
    *,
    db_path: Path | None = None,
    salt_path: Path | None = None,
    include_dangerous: bool = True,
) -> list[ToolDefinition]:
    """Devuelve la lista de ToolDefinition listos para registrar.

    Args:
        ctx:               Contexto de memoria (conn + session + model).
        db_path:           Ruta al archivo .db (necesaria para export).
        salt_path:         Ruta al archivo de salt (necesaria para rotate_key).
        include_dangerous: Si False, omite forget/export/rotate_key.
                           Útil para sesiones de solo lectura.
    """
    tools: list[ToolDefinition] = [
        _make_recall(ctx),
        _make_list(ctx),
        _make_remember(ctx),
    ]

    if include_dangerous:
        tools.append(_make_forget(ctx))
        if db_path is not None:
            tools.append(_make_export(ctx, db_path))
        if db_path is not None and salt_path is not None:
            tools.append(_make_rotate_key(ctx, db_path, salt_path))

    return tools
