"""Audit log append-only con hash-chain (estilo Merkle).

Cada operación que toca la memoria del agente se registra como una línea
JSON en `audit.jsonl`. Cada línea incluye:

  - `seq`: número secuencial (1-based).
  - `ts`: epoch UTC (segundos).
  - `op`: nombre de la operación (`remember`, `forget`, `recall`,
    `export`, `import`, `rotate_key`, `purge`, etc.).
  - `target`: identificador opaco del objeto afectado (ej. `entry:42`).
  - `actor`: quién originó la operación (`user`, `agent`, `system`).
  - `extra`: dict opcional con detalles específicos de la operación.
  - `prev_hmac`: hex del HMAC de la línea anterior (o el genesis para
    la primera).
  - `hmac`: hex del HMAC-SHA256 de `canonical(payload_sin_hmac) ||
    prev_hmac`, calculado con la subkey HKDF derivada para audit.

`verify(path, key)` recorre todo el archivo y revalida la cadena. Si
alguien:
  - modifica una línea → cambia su HMAC → el HMAC de la siguiente línea
    deja de coincidir.
  - borra una línea de la mitad → el `prev_hmac` de la línea siguiente
    no encaja con el HMAC de su predecesora real.
  - inserta una línea → mismo efecto.
  - reescribe el archivo entero con una key distinta → todos los HMACs
    cambian, pero como el genesis es fijo y conocido, la primera
    verificación falla.

El audit log NO está cifrado (es metadato verificable, no secreto). Sus
líneas pueden contener referencias (`entry:42`) pero no contenido. Si
una operación incluye contenido sensible, ponerlo sólo en la DB
cifrada — el audit log sólo loggea el hecho.

Permisos: 0600 sobre el archivo, 0700 sobre el directorio. La
verificación de permisos la hace el caller usando `permissions.py`.
"""

from __future__ import annotations

import hmac
import json
import os
import time
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterator

# Genesis: HMAC inicial fijo (32 bytes de cero en hex). La primera entrada
# del log lleva este valor como `prev_hmac`. Es público; no es un secreto.
GENESIS_HMAC = "00" * 32

# Info HKDF para derivar la subkey del audit a partir de la master.
# Versionada — si cambia el formato del audit, incrementar la versión
# implica reset (y el log viejo queda inverificable bajo la nueva key).
AUDIT_HKDF_INFO = b"allai-memory-audit-hmac-v1"


class AuditError(Exception):
    """Error base del audit log."""


class TamperedAuditError(AuditError):
    """La cadena de HMACs no valida — el log fue modificado."""


# ─── Append ──────────────────────────────────────────────────────────────────


def append(
    log_path: Path,
    *,
    op: str,
    target: str,
    key: bytes,
    actor: str = "user",
    extra: dict[str, Any] | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    """Anexa una entrada al log y devuelve el dict completo escrito.

    Si `log_path` no existe, la primera entrada usa `GENESIS_HMAC` como
    `prev_hmac`. Si existe, leemos sólo la última línea para obtener el
    `prev_hmac` — no recargamos todo el archivo (eficiente para logs
    grandes).

    Args:
      log_path: archivo .jsonl. Padre debe existir con permisos correctos.
      op: nombre de la operación.
      target: id opaco del objeto afectado.
      key: subkey HMAC derivada (cualquier longitud aceptada por HMAC,
        recomendado 32 bytes).
      actor: quién origina la operación.
      extra: dict serializable a JSON (None → {}).
      now: epoch UTC para tests; None → time.time().

    Raises:
      AuditError: si el dict no es serializable o el archivo no se puede
        escribir.
    """
    if not key:
        raise AuditError("HMAC key vacía")

    prev_hmac, prev_seq = _last_hmac_and_seq(log_path)
    seq = prev_seq + 1
    payload: dict[str, Any] = {
        "seq": seq,
        "ts": int(now if now is not None else time.time()),
        "op": op,
        "target": target,
        "actor": actor,
        "extra": extra or {},
        "prev_hmac": prev_hmac,
    }
    digest = _hmac_payload(payload, key)
    payload["hmac"] = digest

    line = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    fd = os.open(log_path, flags, 0o600)
    try:
        os.write(fd, line.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    if os.name == "posix" and not (log_path.stat().st_mode & 0o077 == 0):
        os.chmod(log_path, 0o600)
    return payload


# ─── Verify ──────────────────────────────────────────────────────────────────


def verify(log_path: Path, key: bytes) -> int:
    """Recorre `log_path` y valida la cadena de HMACs.

    Args:
      log_path: archivo .jsonl.
      key: misma subkey HMAC usada en `append`.

    Returns:
      Número de entradas válidas verificadas.

    Raises:
      FileNotFoundError: si el archivo no existe.
      TamperedAuditError: si alguna línea no valida (cadena rota,
        secuencia desordenada, HMAC inválido).
    """
    count = 0
    expected_prev = GENESIS_HMAC
    expected_seq = 1
    with log_path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise TamperedAuditError(
                    f"línea {lineno}: JSON inválido: {exc}"
                ) from exc
            if payload.get("seq") != expected_seq:
                raise TamperedAuditError(
                    f"línea {lineno}: seq={payload.get('seq')} esperado {expected_seq}"
                )
            if payload.get("prev_hmac") != expected_prev:
                raise TamperedAuditError(
                    f"línea {lineno}: prev_hmac no encadena con la anterior"
                )
            stored_hmac = payload.pop("hmac", None)
            if not isinstance(stored_hmac, str):
                raise TamperedAuditError(f"línea {lineno}: hmac ausente o inválido")
            recomputed = _hmac_payload(payload, key)
            if not hmac.compare_digest(stored_hmac, recomputed):
                raise TamperedAuditError(f"línea {lineno}: hmac no valida")
            expected_prev = stored_hmac
            expected_seq += 1
            count += 1
    return count


# ─── Lectura sin verificar ───────────────────────────────────────────────────


def read_all(log_path: Path) -> Iterator[dict[str, Any]]:
    """Itera entradas en orden sin verificar la cadena.

    Útil para presentar el historial al usuario o para queries puntuales.
    Para auditoría real, llamar a `verify()` primero.
    """
    if not log_path.exists():
        return
    with log_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


# ─── Helpers internos ────────────────────────────────────────────────────────


def _hmac_payload(payload: dict[str, Any], key: bytes) -> str:
    """HMAC-SHA256 sobre `canonical(payload)` (sin el campo `hmac`).

    Canonicalización: JSON con `sort_keys=True` y separadores compactos.
    Esto garantiza que dos representaciones del mismo dict producen los
    mismos bytes — independiente del orden o el espaciado.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hmac.new(key, canonical, sha256).hexdigest()


def _last_hmac_and_seq(log_path: Path) -> tuple[str, int]:
    """Devuelve `(prev_hmac, prev_seq)` para la nueva entrada a anexar.

    Si el archivo no existe o está vacío → `(GENESIS_HMAC, 0)`.
    No verifica la cadena entera; sólo lee la última línea.
    """
    if not log_path.exists() or log_path.stat().st_size == 0:
        return GENESIS_HMAC, 0
    last: dict[str, Any] | None = None
    # Para archivos pequeños es OK leerlo entero; para tamaños grandes
    # podríamos optimizar con seek desde el final, pero esa optimización
    # se evalúa cuando llegue el caso. La mayoría de logs personales
    # quedan en KBs.
    with log_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                last = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AuditError(
                    f"audit log corrupto al leer última entrada: {exc}"
                ) from exc
    if last is None:
        return GENESIS_HMAC, 0
    return last["hmac"], int(last["seq"])
