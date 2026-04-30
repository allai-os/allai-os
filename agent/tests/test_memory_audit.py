"""Tests del audit log con hash-chain.

Cubre:
  - Append a archivo nuevo (genesis correcto, seq=1).
  - Append a archivo existente (encadena con la última entrada).
  - Verify de cadena válida.
  - Detección de tampering: modificación, inserción, borrado, swap,
    truncación, key incorrecta.
  - read_all itera sin verificar.
  - Permisos del archivo (POSIX-only).
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from memory.audit import (
    AUDIT_HKDF_INFO,
    GENESIS_HMAC,
    AuditError,
    TamperedAuditError,
    append,
    read_all,
    verify,
)
from memory.crypto import KEY_LENGTH, derive_subkey


def _audit_key() -> bytes:
    master = bytes(range(KEY_LENGTH))
    return derive_subkey(master, info=AUDIT_HKDF_INFO)


# ─── Append ──────────────────────────────────────────────────────────────────


def test_append_creates_file_with_genesis(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    entry = append(log, op="remember", target="entry:1", key=_audit_key(), now=1000)
    assert entry["seq"] == 1
    assert entry["prev_hmac"] == GENESIS_HMAC
    assert entry["op"] == "remember"
    assert entry["target"] == "entry:1"
    assert entry["actor"] == "user"
    assert entry["ts"] == 1000
    assert isinstance(entry["hmac"], str) and len(entry["hmac"]) == 64


def test_append_chains_subsequent_entries(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    key = _audit_key()
    e1 = append(log, op="remember", target="entry:1", key=key, now=1000)
    e2 = append(log, op="forget", target="entry:1", key=key, now=2000)
    assert e2["seq"] == 2
    assert e2["prev_hmac"] == e1["hmac"]


def test_append_persists_across_processes(tmp_path: Path) -> None:
    """Reabrir el archivo y anexar lee correctamente la última entrada."""
    log = tmp_path / "audit.jsonl"
    key = _audit_key()
    append(log, op="a", target="t1", key=key, now=1)
    append(log, op="b", target="t2", key=key, now=2)
    # Simular "reapertura" — la función ya lee del archivo cada vez
    e3 = append(log, op="c", target="t3", key=key, now=3)
    assert e3["seq"] == 3


def test_append_rejects_empty_key(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    with pytest.raises(AuditError, match="key"):
        append(log, op="x", target="y", key=b"")


def test_append_supports_extra_dict(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    entry = append(
        log,
        op="export",
        target="all",
        key=_audit_key(),
        extra={"format": "v1", "count": 42},
    )
    assert entry["extra"] == {"format": "v1", "count": 42}


@pytest.mark.skipif(os.name != "posix", reason="permisos POSIX")
def test_append_creates_file_with_0600(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    append(log, op="x", target="y", key=_audit_key())
    mode = stat.S_IMODE(log.stat().st_mode)
    assert mode == 0o600


# ─── Verify (camino feliz) ───────────────────────────────────────────────────


def test_verify_empty_file_returns_zero(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    log.write_text("")
    assert verify(log, _audit_key()) == 0


def test_verify_single_entry(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    append(log, op="x", target="y", key=_audit_key())
    assert verify(log, _audit_key()) == 1


def test_verify_long_chain(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    key = _audit_key()
    for i in range(20):
        append(log, op="op", target=f"entry:{i}", key=key)
    assert verify(log, key) == 20


def test_verify_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        verify(tmp_path / "ghost.jsonl", _audit_key())


# ─── Verify (tampering) ──────────────────────────────────────────────────────


def _read_lines(log: Path) -> list[str]:
    return log.read_text(encoding="utf-8").splitlines()


def _write_lines(log: Path, lines: list[str]) -> None:
    log.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def test_verify_detects_modified_target(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    key = _audit_key()
    append(log, op="remember", target="entry:1", key=key)
    # Corromper el target
    lines = _read_lines(log)
    obj = json.loads(lines[0])
    obj["target"] = "entry:99"
    lines[0] = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    _write_lines(log, lines)
    with pytest.raises(TamperedAuditError, match="hmac no valida"):
        verify(log, key)


def test_verify_detects_modified_op(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    key = _audit_key()
    append(log, op="remember", target="entry:1", key=key)
    lines = _read_lines(log)
    obj = json.loads(lines[0])
    obj["op"] = "forget"  # cambia op pero deja el hmac viejo
    lines[0] = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    _write_lines(log, lines)
    with pytest.raises(TamperedAuditError):
        verify(log, key)


def test_verify_detects_inserted_line(tmp_path: Path) -> None:
    """Si alguien inserta una línea con HMAC válido pero seq fuera de orden,
    se detecta."""
    log = tmp_path / "audit.jsonl"
    key = _audit_key()
    append(log, op="a", target="t1", key=key)
    append(log, op="b", target="t2", key=key)
    lines = _read_lines(log)
    # Duplica la primera línea — viola la unicidad del seq
    lines.insert(1, lines[0])
    _write_lines(log, lines)
    with pytest.raises(TamperedAuditError):
        verify(log, key)


def test_verify_detects_deleted_middle(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    key = _audit_key()
    append(log, op="a", target="t1", key=key)
    append(log, op="b", target="t2", key=key)
    append(log, op="c", target="t3", key=key)
    lines = _read_lines(log)
    # Borrar la del medio
    del lines[1]
    _write_lines(log, lines)
    with pytest.raises(TamperedAuditError):
        verify(log, key)


def test_verify_detects_truncated_log(tmp_path: Path) -> None:
    """Truncar al final SÍ es válido — la cadena queda más corta pero
    coherente. Esto es una limitación intencional del modelo append-only:
    no podemos distinguir 'log con 3 entradas' de 'log con 5 entradas
    truncado a 3'. La defensa contra eso vive en otra capa (e.g.
    contador autoritativo en la DB)."""
    log = tmp_path / "audit.jsonl"
    key = _audit_key()
    append(log, op="a", target="t1", key=key)
    append(log, op="b", target="t2", key=key)
    append(log, op="c", target="t3", key=key)
    lines = _read_lines(log)
    _write_lines(log, lines[:-1])  # quita la última
    # Esto NO debe lanzar — verify acepta logs cortos coherentes.
    assert verify(log, key) == 2


def test_verify_detects_wrong_key(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    append(log, op="x", target="y", key=_audit_key())
    other_key = derive_subkey(bytes(KEY_LENGTH), info=AUDIT_HKDF_INFO)
    with pytest.raises(TamperedAuditError):
        verify(log, other_key)


def test_verify_detects_corrupted_json(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    log.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(TamperedAuditError, match="JSON"):
        verify(log, _audit_key())


def test_verify_skips_blank_lines(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    key = _audit_key()
    append(log, op="x", target="y", key=key)
    # Añadir línea en blanco en medio (no afecta cadena)
    content = log.read_text(encoding="utf-8")
    log.write_text(content + "\n\n", encoding="utf-8")
    assert verify(log, key) == 1


# ─── read_all ────────────────────────────────────────────────────────────────


def test_read_all_iterates_entries(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    key = _audit_key()
    append(log, op="a", target="t1", key=key)
    append(log, op="b", target="t2", key=key)
    entries = list(read_all(log))
    assert len(entries) == 2
    assert entries[0]["op"] == "a"
    assert entries[1]["op"] == "b"


def test_read_all_handles_missing_file(tmp_path: Path) -> None:
    entries = list(read_all(tmp_path / "ghost.jsonl"))
    assert entries == []


def test_read_all_skips_blank_and_corrupt_lines(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    key = _audit_key()
    append(log, op="a", target="t1", key=key)
    content = log.read_text(encoding="utf-8")
    log.write_text(content + "\n{not json}\n", encoding="utf-8")
    entries = list(read_all(log))
    assert len(entries) == 1  # se salta la línea corrupta
