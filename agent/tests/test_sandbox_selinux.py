"""Tests de sandbox.selinux.

Cubre:
  - Parser puro de SELinuxContext (formatos válidos / inválidos).
  - Parser de líneas AVC del audit.log.
  - Disponibilidad: returns False sin libselinux (Windows / sin paquete).
  - Funciones que requieren libselinux levantan SELinuxUnavailableError.
  - is_allai_module_loaded retorna False cuando semodule no existe.
  - recent_denials_for_domain con archivo inexistente / sin permisos.

Tests integrales (que invocan libselinux real) sólo se ejecutan en
Linux con `python3-libselinux` instalado y SELinux habilitado.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast

import pytest

from sandbox.selinux import (
    ALLAI_DAEMON_TYPE,
    ALLAI_SANDBOXED_TYPE,
    AVCDenial,
    SELinuxContext,
    SELinuxContextError,
    SELinuxUnavailableError,
    current_mode,
    current_process_context,
    is_allai_module_loaded,
    is_selinux_available,
    parse_avc_line,
    recent_denials_for_domain,
)


# ─── SELinuxContext.parse ───────────────────────────────────────────────────


def test_parse_basic_four_fields() -> None:
    ctx = SELinuxContext.parse("system_u:system_r:allai_t:s0")
    assert ctx.user == "system_u"
    assert ctx.role == "system_r"
    assert ctx.type_ == "allai_t"
    assert ctx.sensitivity == "s0"
    assert ctx.categories is None


def test_parse_with_simple_categories() -> None:
    ctx = SELinuxContext.parse("staff_u:staff_r:staff_t:s0:c0")
    assert ctx.categories == "c0"


def test_parse_with_mls_range_and_categories() -> None:
    """Fedora targeted con MLS pleno: `s0-s0:c0.c1023` tiene `:` interno."""
    ctx = SELinuxContext.parse("staff_u:staff_r:staff_t:s0-s0:c0.c1023")
    assert ctx.user == "staff_u"
    assert ctx.role == "staff_r"
    assert ctx.type_ == "staff_t"
    assert ctx.sensitivity == "s0-s0"
    assert ctx.categories == "c0.c1023"


def test_parse_unconfined_user() -> None:
    ctx = SELinuxContext.parse("unconfined_u:object_r:allai_data_t:s0")
    assert ctx.type_ == "allai_data_t"


def test_parse_rejects_empty_string() -> None:
    with pytest.raises(SELinuxContextError, match="vacío"):
        SELinuxContext.parse("")


def test_parse_rejects_too_few_fields() -> None:
    with pytest.raises(SELinuxContextError, match="al menos 4"):
        SELinuxContext.parse("user:role:type")


def test_parse_rejects_non_string() -> None:
    with pytest.raises(SELinuxContextError, match="str"):
        SELinuxContext.parse(cast(str, 42))


def test_parse_rejects_field_with_colon() -> None:
    """Los campos individuales no pueden contener `:` literalmente
    (sólo el separador entre campos los usa)."""
    # Construir un contexto tras parsear pasa, pero construir uno
    # directamente con un campo conteniendo ':' debe fallar.
    with pytest.raises(SELinuxContextError, match="contener"):
        SELinuxContext(
            user="a:b", role="r", type_="t", sensitivity="s0"
        )


def test_str_roundtrip_no_categories() -> None:
    raw = "system_u:system_r:allai_t:s0"
    ctx = SELinuxContext.parse(raw)
    assert str(ctx) == raw


def test_str_roundtrip_with_categories() -> None:
    raw = "staff_u:staff_r:staff_t:s0:c0.c1023"
    ctx = SELinuxContext.parse(raw)
    assert str(ctx) == raw


def test_context_is_frozen() -> None:
    ctx = SELinuxContext.parse("u:r:t:s0")
    with pytest.raises(Exception):
        ctx.user = "other"  # type: ignore[misc]


def test_is_allai_domain_true_for_daemon() -> None:
    ctx = SELinuxContext.parse(f"u:r:{ALLAI_DAEMON_TYPE}:s0")
    assert ctx.is_allai_domain() is True


def test_is_allai_domain_true_for_sandboxed() -> None:
    ctx = SELinuxContext.parse(f"u:r:{ALLAI_SANDBOXED_TYPE}:s0")
    assert ctx.is_allai_domain() is True


def test_is_allai_domain_false_for_other_type() -> None:
    ctx = SELinuxContext.parse("u:r:firefox_t:s0")
    assert ctx.is_allai_domain() is False


# ─── parse_avc_line ─────────────────────────────────────────────────────────


_REAL_AVC = (
    'type=AVC msg=audit(1714502400.123:42): avc:  denied  { read } '
    'for  pid=1234 comm="allaid" path="/etc/shadow" dev="dm-0" ino=12345 '
    'scontext=system_u:system_r:allai_t:s0 '
    'tcontext=system_u:object_r:shadow_t:s0 '
    'tclass=file permissive=0'
)


def test_parse_avc_extracts_basic_fields() -> None:
    denial = parse_avc_line(_REAL_AVC)
    assert denial is not None
    assert denial.timestamp == 1714502400.123
    assert "allai_t" in denial.source_context
    assert "shadow_t" in denial.target_context
    assert denial.target_class == "file"
    assert "read" in denial.permissions


def test_parse_avc_multiple_permissions() -> None:
    line = _REAL_AVC.replace("{ read }", "{ read write open }")
    denial = parse_avc_line(line)
    assert denial is not None
    assert set(denial.permissions) == {"read", "write", "open"}


def test_parse_avc_returns_none_for_non_avc_line() -> None:
    assert parse_avc_line("type=SYSCALL msg=...") is None
    assert parse_avc_line("random log entry") is None
    assert parse_avc_line("") is None


def test_parse_avc_returns_none_for_granted() -> None:
    """Sólo nos interesan denials, no granted."""
    line = _REAL_AVC.replace(" denied ", " granted ")
    assert parse_avc_line(line) is None


def test_parse_avc_handles_malformed_timestamp() -> None:
    line = (
        'type=AVC msg=audit(notatimestamp:1): avc: denied { x } '
        'scontext=u:r:allai_t:s0 tcontext=u:r:t_t:s0 tclass=file'
    )
    denial = parse_avc_line(line)
    assert denial is not None
    assert denial.timestamp == 0.0  # fallback


def test_parse_avc_preserves_raw() -> None:
    denial = parse_avc_line(_REAL_AVC)
    assert denial is not None
    assert denial.raw == _REAL_AVC


# ─── recent_denials_for_domain ──────────────────────────────────────────────


def test_recent_denials_missing_log_returns_empty(tmp_path: Path) -> None:
    result = recent_denials_for_domain(
        log_path=tmp_path / "audit.log",
    )
    assert result == []


def test_recent_denials_filters_by_domain(tmp_path: Path) -> None:
    log = tmp_path / "audit.log"
    other_avc = (
        'type=AVC msg=audit(1714502400.0:1): avc:  denied  { read } '
        'for  pid=1 comm="other" '
        'scontext=system_u:system_r:firefox_t:s0 '
        'tcontext=system_u:object_r:shadow_t:s0 '
        'tclass=file'
    )
    log.write_text(
        _REAL_AVC + "\n" + other_avc + "\n",
        encoding="utf-8",
    )
    denials = recent_denials_for_domain(
        domain_type=ALLAI_DAEMON_TYPE, log_path=log
    )
    assert len(denials) == 1
    assert "allai_t" in denials[0].source_context


def test_recent_denials_respects_limit(tmp_path: Path) -> None:
    log = tmp_path / "audit.log"
    lines = "\n".join([_REAL_AVC] * 10) + "\n"
    log.write_text(lines, encoding="utf-8")
    denials = recent_denials_for_domain(log_path=log, limit=3)
    assert len(denials) == 3


def test_recent_denials_returns_most_recent_first(tmp_path: Path) -> None:
    """audit.log es append-only ordenado por tiempo; el más reciente
    está al final del archivo. Nuestra función lo devuelve primero."""
    log = tmp_path / "audit.log"
    older = _REAL_AVC.replace("1714502400.123", "1714502300.000")
    newer = _REAL_AVC.replace("1714502400.123", "1714502500.000")
    log.write_text(older + "\n" + newer + "\n", encoding="utf-8")
    denials = recent_denials_for_domain(log_path=log, limit=2)
    assert len(denials) == 2
    assert denials[0].timestamp > denials[1].timestamp


def test_recent_denials_handles_garbage_lines(tmp_path: Path) -> None:
    log = tmp_path / "audit.log"
    log.write_text(
        "garbage line 1\n" + _REAL_AVC + "\nmore garbage\n", encoding="utf-8"
    )
    denials = recent_denials_for_domain(log_path=log)
    assert len(denials) == 1


# ─── Disponibilidad ─────────────────────────────────────────────────────────


def test_is_selinux_available_returns_bool() -> None:
    assert isinstance(is_selinux_available(), bool)


def test_is_selinux_available_false_in_windows() -> None:
    if os.name == "nt":
        assert is_selinux_available() is False


def test_current_mode_raises_when_no_libselinux(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forzamos el escenario 'sin libselinux' aunque corramos en Linux."""
    import sandbox.selinux as mod

    def boom() -> object:
        raise SELinuxUnavailableError("simulado")

    monkeypatch.setattr(mod, "_import_selinux", boom)
    with pytest.raises(SELinuxUnavailableError):
        current_mode()


def test_current_process_context_raises_when_no_libselinux(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sandbox.selinux as mod

    def boom() -> object:
        raise SELinuxUnavailableError("simulado")

    monkeypatch.setattr(mod, "_import_selinux", boom)
    with pytest.raises(SELinuxUnavailableError):
        current_process_context()


def test_is_allai_module_loaded_false_without_selinux(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sandbox.selinux as mod

    monkeypatch.setattr(mod, "is_selinux_available", lambda: False)
    assert is_allai_module_loaded() is False


def test_is_allai_module_loaded_handles_missing_semodule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Aunque is_selinux_available devuelva True, si `semodule` no
    existe, la función no debe levantar — retorna False."""
    import sandbox.selinux as mod

    monkeypatch.setattr(mod, "is_selinux_available", lambda: True)

    def fake_run(*args: object, **kwargs: object) -> object:
        raise FileNotFoundError("semodule")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    assert is_allai_module_loaded() is False


# ─── AVCDenial dataclass ────────────────────────────────────────────────────


def test_avc_denial_is_frozen() -> None:
    denial = AVCDenial(
        timestamp=1.0,
        source_context="u:r:allai_t:s0",
        target_context="u:r:t:s0",
        target_class="file",
        permissions=("read",),
        raw="...",
    )
    with pytest.raises(Exception):
        denial.timestamp = 2.0  # type: ignore[misc]


def test_avc_denial_is_hashable() -> None:
    denial = AVCDenial(
        timestamp=1.0,
        source_context="u:r:allai_t:s0",
        target_context="u:r:t:s0",
        target_class="file",
        permissions=("read",),
        raw="...",
    )
    s = {denial, denial}
    assert len(s) == 1
