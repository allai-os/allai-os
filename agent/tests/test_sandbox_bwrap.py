"""Tests de sandbox.bwrap — generación pura del argv, sin ejecutar bwrap.

Cubre:
  - Flags de aislamiento default (--unshare-all, --die-with-parent, etc.).
  - Mapeo de capabilities a --ro-bind / --bind / --share-net.
  - Profiles paranoid / demo modifican el set de binds.
  - Modo DEMO bloquea network aunque haya grant.
  - --clearenv + minimal env, sin propagar API keys del host.
  - command argv viene al final tras `--`.
  - Resolución de ~ en scopes con home inyectable.
  - bwrap_path explícito vs búsqueda en PATH.
  - require_bwrap=True lanza si falta el binario.
  - Validación de command vacío.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sandbox.bwrap import (
    BwrapNotAvailableError,
    BwrapProfile,
    build_bwrap_argv,
    is_bwrap_available,
)
from sandbox.policy import SandboxMode, SandboxPolicy


# ─── Helpers ────────────────────────────────────────────────────────────────


def _argv_to_str(argv: list[str]) -> str:
    """Une el argv con separadores claros para hacer asserts legibles."""
    return " | ".join(argv)


def _has_flag(argv: list[str], flag: str) -> bool:
    return flag in argv


def _flag_value(argv: list[str], flag: str) -> str | None:
    """Devuelve el siguiente token tras el flag, o None si no está."""
    try:
        idx = argv.index(flag)
    except ValueError:
        return None
    if idx + 1 >= len(argv):
        return None
    return argv[idx + 1]


def _all_flag_values(argv: list[str], flag: str) -> list[str]:
    """Todos los tokens que siguen a cada ocurrencia de flag."""
    out: list[str] = []
    for i, token in enumerate(argv):
        if token == flag and i + 1 < len(argv):
            out.append(argv[i + 1])
    return out


def _bind_pairs(argv: list[str], flag: str) -> list[tuple[str, str]]:
    """Para flags como --ro-bind-try src dst, devuelve la lista de (src, dst)."""
    pairs: list[tuple[str, str]] = []
    for i, token in enumerate(argv):
        if token == flag and i + 2 < len(argv):
            pairs.append((argv[i + 1], argv[i + 2]))
    return pairs


# ─── Defaults ────────────────────────────────────────────────────────────────


def test_argv_starts_with_bwrap_binary() -> None:
    policy = SandboxPolicy()
    argv = build_bwrap_argv(policy, ["echo", "hi"])
    # El primer token debe ser "bwrap" o una ruta que lo contenga.
    assert "bwrap" in argv[0]


def test_argv_ends_with_double_dash_then_command() -> None:
    policy = SandboxPolicy()
    argv = build_bwrap_argv(policy, ["echo", "hola"])
    # Encuentra el primer `--` que actúa de separador (no debe haber otros).
    sep_idx = argv.index("--")
    assert argv[sep_idx + 1 :] == ["echo", "hola"]


def test_command_with_args_preserved_in_order() -> None:
    policy = SandboxPolicy()
    cmd = ["python3", "-c", "print('a','b','c')"]
    argv = build_bwrap_argv(policy, cmd)
    sep_idx = argv.index("--")
    assert argv[sep_idx + 1 :] == cmd


def test_empty_command_raises() -> None:
    policy = SandboxPolicy()
    with pytest.raises(ValueError, match="command"):
        build_bwrap_argv(policy, [])


# ─── Isolation flags ────────────────────────────────────────────────────────


def test_default_includes_unshare_all() -> None:
    policy = SandboxPolicy()
    argv = build_bwrap_argv(policy, ["true"])
    assert _has_flag(argv, "--unshare-all")


def test_default_includes_die_with_parent() -> None:
    policy = SandboxPolicy()
    argv = build_bwrap_argv(policy, ["true"])
    assert _has_flag(argv, "--die-with-parent")


def test_default_includes_new_session() -> None:
    policy = SandboxPolicy()
    argv = build_bwrap_argv(policy, ["true"])
    assert _has_flag(argv, "--new-session")


def test_default_includes_no_new_privs() -> None:
    policy = SandboxPolicy()
    argv = build_bwrap_argv(policy, ["true"])
    assert _has_flag(argv, "--no-new-privs")


def test_default_includes_cap_drop_all() -> None:
    policy = SandboxPolicy()
    argv = build_bwrap_argv(policy, ["true"])
    assert _flag_value(argv, "--cap-drop") == "ALL"


def test_profile_can_disable_die_with_parent() -> None:
    policy = SandboxPolicy()
    profile = BwrapProfile(die_with_parent=False)
    argv = build_bwrap_argv(policy, ["true"], profile=profile)
    assert not _has_flag(argv, "--die-with-parent")


def test_share_flags_added_when_profile_disables_unshare() -> None:
    policy = SandboxPolicy()
    profile = BwrapProfile(
        unshare_user=False,
        unshare_pid=False,
        unshare_ipc=False,
        unshare_uts=False,
        unshare_cgroup=False,
    )
    argv = build_bwrap_argv(policy, ["true"], profile=profile)
    for flag in (
        "--share-user",
        "--share-pid",
        "--share-ipc",
        "--share-uts",
        "--share-cgroup",
    ):
        assert _has_flag(argv, flag), f"esperaba {flag}"


# ─── System binds ───────────────────────────────────────────────────────────


def test_default_ro_binds_system_paths() -> None:
    policy = SandboxPolicy()
    argv = build_bwrap_argv(policy, ["true"])
    pairs = _bind_pairs(argv, "--ro-bind-try")
    sources = {src for src, _ in pairs}
    # Al menos los esenciales del default profile
    assert "/usr" in sources
    assert "/etc" in sources
    assert "/lib" in sources
    # Cada bind debe tener src == dst (no tocamos paths)
    for src, dst in pairs:
        assert src == dst


def test_default_tmpfs_includes_tmp() -> None:
    policy = SandboxPolicy()
    argv = build_bwrap_argv(policy, ["true"])
    tmpfs_targets = _all_flag_values(argv, "--tmpfs")
    assert "/tmp" in tmpfs_targets


def test_default_proc_and_dev_mounted() -> None:
    policy = SandboxPolicy()
    argv = build_bwrap_argv(policy, ["true"])
    assert _flag_value(argv, "--proc") == "/proc"
    assert _flag_value(argv, "--dev") == "/dev"


def test_profile_can_omit_proc_and_dev() -> None:
    policy = SandboxPolicy()
    profile = BwrapProfile(proc_path="", dev_path="")
    argv = build_bwrap_argv(policy, ["true"], profile=profile)
    assert "--proc" not in argv
    assert "--dev" not in argv


def test_paranoid_profile_includes_var_in_tmpfs() -> None:
    policy = SandboxPolicy()
    argv = build_bwrap_argv(policy, ["true"], profile=BwrapProfile.paranoid())
    tmpfs = _all_flag_values(argv, "--tmpfs")
    assert "/var" in tmpfs


def test_paranoid_profile_drops_bin_sbin_from_ro_binds() -> None:
    policy = SandboxPolicy()
    argv = build_bwrap_argv(policy, ["true"], profile=BwrapProfile.paranoid())
    pairs = _bind_pairs(argv, "--ro-bind-try")
    sources = {src for src, _ in pairs}
    assert "/bin" not in sources
    assert "/sbin" not in sources


# ─── Capability mapping ────────────────────────────────────────────────────


def test_read_fs_grant_adds_ro_bind(tmp_path: Path) -> None:
    policy = SandboxPolicy()
    policy.grant("read-fs:~/Documents")
    argv = build_bwrap_argv(policy, ["true"], home_dir=tmp_path)
    pairs = _bind_pairs(argv, "--ro-bind-try")
    expected = str(tmp_path / "Documents").replace("\\", "/")
    found = [s for s, _ in pairs if s.replace("\\", "/").endswith("Documents")]
    assert found, f"esperaba bind a Documents, vino {pairs}"
    # Y no debe haber un --bind-try a Documents (write)
    write_pairs = _bind_pairs(argv, "--bind-try")
    assert all("Documents" not in s for s, _ in write_pairs), (
        f"read-fs no debería generar --bind-try, vino {write_pairs}"
    )
    _ = expected  # silencia unused si la aserción anterior con replace pasa


def test_write_fs_grant_adds_bind_try(tmp_path: Path) -> None:
    policy = SandboxPolicy()
    policy.grant("write-fs:~/Pictures")
    argv = build_bwrap_argv(policy, ["true"], home_dir=tmp_path)
    pairs = _bind_pairs(argv, "--bind-try")
    found = [s for s, _ in pairs if "Pictures" in s]
    assert found


def test_no_fs_grant_no_user_binds(tmp_path: Path) -> None:
    """Sin capabilities fs, no hay binds del HOME."""
    policy = SandboxPolicy()
    argv = build_bwrap_argv(policy, ["true"], home_dir=tmp_path)
    user_pairs = [
        (s, d)
        for s, d in _bind_pairs(argv, "--ro-bind-try") + _bind_pairs(argv, "--bind-try")
        if str(tmp_path) in s
    ]
    assert user_pairs == []


def test_network_any_grant_adds_share_net() -> None:
    policy = SandboxPolicy()
    policy.grant("network:any")
    argv = build_bwrap_argv(policy, ["true"])
    assert _has_flag(argv, "--share-net")


def test_network_specific_grant_also_adds_share_net() -> None:
    """bwrap es todo-o-nada para network. El filtrado por host vendrá
    en una iteración futura con slirp4netns."""
    policy = SandboxPolicy()
    policy.grant("network:api.openai.com")
    argv = build_bwrap_argv(policy, ["true"])
    assert _has_flag(argv, "--share-net")


def test_no_network_grant_no_share_net() -> None:
    policy = SandboxPolicy()
    argv = build_bwrap_argv(policy, ["true"])
    assert not _has_flag(argv, "--share-net")


def test_demo_mode_blocks_network_even_with_grant() -> None:
    """Defensa en profundidad: en demo mode, --share-net no se añade
    aunque haya network:any concedida."""
    policy = SandboxPolicy(mode=SandboxMode.DEMO)
    # Grant directo evitando assert_capability (que falla en demo)
    policy.grants[next(iter(_make_network_caps()))] = _grant_for_network()
    argv = build_bwrap_argv(policy, ["true"])
    assert not _has_flag(argv, "--share-net")


def _make_network_caps() -> list:
    from sandbox.policy import Capability

    return [Capability("network", "any")]


def _grant_for_network():
    from sandbox.policy import Capability, CapabilityGrant

    return CapabilityGrant(
        capability=Capability("network", "any"),
        granted_at=0,
    )


# ─── Mode-driven profile selection ───────────────────────────────────────────


def test_mode_normal_uses_default_profile() -> None:
    policy = SandboxPolicy(mode=SandboxMode.NORMAL)
    argv = build_bwrap_argv(policy, ["true"])
    pairs = _bind_pairs(argv, "--ro-bind-try")
    sources = {s for s, _ in pairs}
    assert "/bin" in sources  # default incluye /bin
    assert "/sbin" in sources


def test_mode_paranoid_uses_paranoid_profile() -> None:
    policy = SandboxPolicy(mode=SandboxMode.PARANOID)
    argv = build_bwrap_argv(policy, ["true"])
    pairs = _bind_pairs(argv, "--ro-bind-try")
    sources = {s for s, _ in pairs}
    assert "/bin" not in sources
    tmpfs = _all_flag_values(argv, "--tmpfs")
    assert "/var" in tmpfs


def test_explicit_profile_overrides_mode() -> None:
    policy = SandboxPolicy(mode=SandboxMode.NORMAL)
    argv = build_bwrap_argv(policy, ["true"], profile=BwrapProfile.paranoid())
    tmpfs = _all_flag_values(argv, "--tmpfs")
    assert "/var" in tmpfs


# ─── Env handling ───────────────────────────────────────────────────────────


def test_argv_includes_clearenv() -> None:
    policy = SandboxPolicy()
    argv = build_bwrap_argv(policy, ["true"])
    assert _has_flag(argv, "--clearenv")


def test_minimal_env_sets_path_home_user_lang() -> None:
    policy = SandboxPolicy()
    argv = build_bwrap_argv(policy, ["true"])
    setenv_keys = []
    for i, t in enumerate(argv):
        if t == "--setenv" and i + 2 < len(argv):
            setenv_keys.append(argv[i + 1])
    for key in ("PATH", "HOME", "USER", "LANG"):
        assert key in setenv_keys, f"falta {key} en --setenv"


def test_blocked_env_vars_not_set_even_if_added_to_extra(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    policy = SandboxPolicy()
    profile = BwrapProfile(extra_env={"ANTHROPIC_API_KEY": "leaked-key-123"})
    argv = build_bwrap_argv(policy, ["true"], profile=profile)
    # --setenv ANTHROPIC_API_KEY ... NO debe aparecer
    for i, t in enumerate(argv):
        if t == "--setenv" and i + 1 < len(argv):
            assert argv[i + 1] != "ANTHROPIC_API_KEY"


def test_extra_env_propagates_safe_vars() -> None:
    policy = SandboxPolicy()
    profile = BwrapProfile(extra_env={"ALLAI_SESSION_ID": "abc-123"})
    argv = build_bwrap_argv(policy, ["true"], profile=profile)
    found = False
    for i, t in enumerate(argv):
        if (
            t == "--setenv"
            and i + 2 < len(argv)
            and argv[i + 1] == "ALLAI_SESSION_ID"
            and argv[i + 2] == "abc-123"
        ):
            found = True
            break
    assert found


# ─── home_dir injection ─────────────────────────────────────────────────────


def test_home_dir_replaces_tilde_in_grants(tmp_path: Path) -> None:
    policy = SandboxPolicy()
    policy.grant("read-fs:~/secrets")
    argv = build_bwrap_argv(policy, ["true"], home_dir=tmp_path)
    pairs = _bind_pairs(argv, "--ro-bind-try")
    expected_path = str(tmp_path / "secrets")
    matched = [s for s, _ in pairs if s == expected_path or s.endswith("secrets")]
    assert matched


def test_absolute_path_grant_used_as_is(tmp_path: Path) -> None:
    policy = SandboxPolicy()
    abs_scope = str(tmp_path / "data")
    policy.grant(f"read-fs:{abs_scope}")
    argv = build_bwrap_argv(policy, ["true"])
    pairs = _bind_pairs(argv, "--ro-bind-try")
    sources = {s for s, _ in pairs}
    # El path absoluto debe estar (normalizado)
    assert any(s.endswith("data") for s in sources)


# ─── bwrap binary resolution ────────────────────────────────────────────────


def test_explicit_bwrap_path_used_as_is(tmp_path: Path) -> None:
    """Si pasamos bwrap_path explícito, no buscamos en PATH."""
    fake = tmp_path / "fake-bwrap"
    fake.write_text("")
    argv = build_bwrap_argv(
        SandboxPolicy(), ["true"], bwrap_path=str(fake)
    )
    assert argv[0] == str(fake)


def test_missing_bwrap_with_require_raises(tmp_path: Path) -> None:
    bogus = tmp_path / "definitely-not-bwrap-12345"
    with pytest.raises(BwrapNotAvailableError):
        build_bwrap_argv(
            SandboxPolicy(), ["true"], bwrap_path=str(bogus), require_bwrap=True
        )


def test_missing_bwrap_without_require_uses_literal(tmp_path: Path) -> None:
    """Sin require_bwrap, devuelve el literal — útil para tests/Windows."""
    bogus = tmp_path / "definitely-not-bwrap-12345"
    argv = build_bwrap_argv(
        SandboxPolicy(), ["true"], bwrap_path=str(bogus), require_bwrap=False
    )
    assert argv[0] == str(bogus)


def test_is_bwrap_available_returns_bool() -> None:
    result = is_bwrap_available()
    assert isinstance(result, bool)


def test_is_bwrap_available_false_for_bogus_path(tmp_path: Path) -> None:
    bogus = tmp_path / "no-such-binary-xyz"
    assert is_bwrap_available(str(bogus)) is False


# ─── Smoke: argv structure invariant ────────────────────────────────────────


def test_separator_appears_exactly_once() -> None:
    policy = SandboxPolicy()
    argv = build_bwrap_argv(policy, ["echo", "--", "literal-dashes"])
    # El bwrap argv tiene un único `--` antes del comando del usuario.
    # Los `--` que aparecen como argumentos del comando vienen DESPUÉS
    # del primer `--` y no cuentan como separadores adicionales para
    # bwrap (bwrap procesa tokens hasta el primer `--`).
    first = argv.index("--")
    # Que exista un `--` literal después es OK (parte del comando).
    assert first < len(argv) - 1
    assert argv[first + 1 :] == ["echo", "--", "literal-dashes"]
