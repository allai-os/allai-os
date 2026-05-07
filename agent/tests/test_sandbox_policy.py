"""Tests de sandbox.policy — capability parse, coverage, grants, modos, audit.

Todos los tests son determinísticos: usan `now_provider` inyectable para
que la expiración no dependa del reloj real.
"""

from __future__ import annotations

import os
from typing import cast

import pytest

from sandbox.policy import (
    Capability,
    CapabilityNotGrantedError,
    CapabilityParseError,
    DemoModeBlockedError,
    SandboxAuditEvent,
    SandboxMode,
    SandboxPolicy,
    mode_requires_confirmation,
)
from tools.base import CapabilityDeniedError, RiskLevel


# ─── Helpers ─────────────────────────────────────────────────────────────────


class FakeClock:
    """Reloj inyectable para tests deterministas."""

    def __init__(self, t: int = 1_000_000) -> None:
        self.t = t

    def now(self) -> int:
        return self.t

    def advance(self, seconds: int) -> None:
        self.t += seconds


class AuditRecorder:
    """Registra todos los eventos del callback para inspección en tests."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str | None, str]] = []

    def __call__(
        self,
        event: SandboxAuditEvent,
        capability: Capability | None,
        detail: str,
    ) -> None:
        cap_str = str(capability) if capability is not None else None
        self.events.append((event, cap_str, detail))

    def event_kinds(self) -> list[str]:
        return [e[0] for e in self.events]


def _new_policy(
    *, mode: SandboxMode = SandboxMode.NORMAL, clock: FakeClock | None = None
) -> tuple[SandboxPolicy, AuditRecorder, FakeClock]:
    clock = clock or FakeClock()
    audit = AuditRecorder()
    policy = SandboxPolicy(
        mode=mode, audit_callback=audit, now_provider=clock.now
    )
    return policy, audit, clock


# ─── Capability.parse ────────────────────────────────────────────────────────


def test_capability_parse_basic() -> None:
    cap = Capability.parse("read-fs:~/Documents")
    assert cap.kind == "read-fs"
    assert cap.scope == "~/Documents"


def test_capability_parse_strips_whitespace() -> None:
    cap = Capability.parse("  network : api.openai.com  ")
    assert cap.kind == "network"
    assert cap.scope == "api.openai.com"


def test_capability_parse_scope_can_contain_colons() -> None:
    cap = Capability.parse("network:host:8080")
    assert cap.kind == "network"
    assert cap.scope == "host:8080"


def test_capability_parse_rejects_no_colon() -> None:
    with pytest.raises(CapabilityParseError, match="formato"):
        Capability.parse("read-fs")


def test_capability_parse_rejects_empty_scope() -> None:
    with pytest.raises(CapabilityParseError, match="scope"):
        Capability.parse("read-fs:")


def test_capability_parse_rejects_unknown_kind() -> None:
    with pytest.raises(CapabilityParseError, match="kind desconocido"):
        Capability.parse("magic:any")


def test_capability_parse_rejects_non_string() -> None:
    with pytest.raises(CapabilityParseError, match="str"):
        Capability.parse(cast(str, 42))


def test_capability_str_roundtrip() -> None:
    cap = Capability("network", "api.example.com")
    assert str(cap) == "network:api.example.com"
    assert Capability.parse(str(cap)) == cap


def test_capability_construct_rejects_unknown_kind() -> None:
    with pytest.raises(CapabilityParseError):
        Capability("magic", "any")


def test_capability_is_hashable_and_frozen() -> None:
    cap = Capability("read-fs", "~/x")
    s = {cap, cap}
    assert len(s) == 1
    with pytest.raises(Exception):
        cap.kind = "write-fs"  # type: ignore[misc]


# ─── Capability.covers ───────────────────────────────────────────────────────


def test_covers_different_kinds_returns_false() -> None:
    grant = Capability("read-fs", "~/Documents")
    requested = Capability("write-fs", "~/Documents")
    assert grant.covers(requested) is False


def test_covers_exact_match() -> None:
    cap = Capability("shell", "read-only")
    assert cap.covers(Capability("shell", "read-only")) is True


def test_covers_path_prefix_subdirectory() -> None:
    grant = Capability("read-fs", "~/Documents")
    requested = Capability("read-fs", "~/Documents/notes/diario.md")
    assert grant.covers(requested) is True


def test_covers_path_prefix_same_path() -> None:
    grant = Capability("read-fs", "~/Documents")
    assert grant.covers(grant) is True


def test_covers_path_does_not_cover_sibling() -> None:
    grant = Capability("read-fs", "~/Documents")
    requested = Capability("read-fs", "~/Pictures")
    assert grant.covers(requested) is False


def test_covers_path_does_not_cover_parent() -> None:
    grant = Capability("read-fs", "~/Documents/sub")
    requested = Capability("read-fs", "~/Documents")
    assert grant.covers(requested) is False


def test_covers_path_normalizes_traversal() -> None:
    """`..` resuelto NO debe permitir escapar del scope concedido.

    Si el grant es ~/Documents y la solicitud es ~/Documents/../Pictures,
    al normalizar la solicitud queda ~/Pictures, que está fuera.
    """
    grant = Capability("read-fs", "~/Documents")
    sneaky = Capability("read-fs", "~/Documents/../Pictures")
    assert grant.covers(sneaky) is False


def test_covers_path_handles_redundant_separators() -> None:
    grant = Capability("read-fs", "~/Documents")
    requested = Capability("read-fs", "~/Documents//notes/./file.txt")
    assert grant.covers(requested) is True


def test_covers_network_any_covers_specific() -> None:
    grant = Capability("network", "any")
    assert grant.covers(Capability("network", "api.openai.com")) is True
    assert grant.covers(Capability("network", "evil.example")) is True


def test_covers_network_specific_does_not_cover_other() -> None:
    grant = Capability("network", "api.openai.com")
    assert grant.covers(Capability("network", "evil.example")) is False


def test_covers_network_specific_does_not_cover_subdomain() -> None:
    """Sub-domains requieren grant explícita — no inferimos por dominio
    base. Esta es una decisión de seguridad: 'api.openai.com' no
    autoriza a 'malicious.openai.com'."""
    grant = Capability("network", "openai.com")
    assert grant.covers(Capability("network", "api.openai.com")) is False


def test_covers_clipboard_exact_only() -> None:
    grant = Capability("clipboard", "read")
    assert grant.covers(Capability("clipboard", "read")) is True
    assert grant.covers(Capability("clipboard", "write")) is False


# ─── SandboxPolicy.grant / revoke / deny ─────────────────────────────────────


def test_grant_basic_records_grant_and_audit() -> None:
    policy, audit, _ = _new_policy()
    grant = policy.grant("read-fs:~/Documents")
    assert grant.capability == Capability("read-fs", "~/Documents")
    assert grant.granted_by == "user"
    assert grant.persistent is False
    assert grant.expires_at is None
    assert audit.event_kinds() == ["grant"]


def test_grant_accepts_capability_object() -> None:
    policy, _, _ = _new_policy()
    cap = Capability("network", "any")
    grant = policy.grant(cap)
    assert grant.capability == cap


def test_grant_persistent_flag_is_recorded() -> None:
    policy, _, _ = _new_policy()
    grant = policy.grant("read-fs:~/Documents", persistent=True)
    assert grant.persistent is True


def test_grant_with_explicit_expiry() -> None:
    policy, _, clock = _new_policy()
    grant = policy.grant("read-fs:~/Documents", expires_at=clock.t + 60)
    assert grant.expires_at == clock.t + 60


def test_grant_overwrites_existing() -> None:
    policy, audit, clock = _new_policy()
    policy.grant("read-fs:~/Documents", note="first")
    clock.advance(10)
    grant2 = policy.grant("read-fs:~/Documents", note="second")
    assert grant2.note == "second"
    assert grant2.granted_at == clock.t
    grants = policy.list_grants()
    assert len(grants) == 1
    assert audit.event_kinds() == ["grant", "grant"]


def test_grant_rejects_when_in_denied() -> None:
    policy, audit, _ = _new_policy()
    policy.deny("sudo:any")
    with pytest.raises(CapabilityDeniedError):
        policy.grant("sudo:any")
    assert "use:denied" in audit.event_kinds()
    assert policy.is_granted("sudo:any") is False


def test_revoke_existing_returns_true_and_audits() -> None:
    policy, audit, _ = _new_policy()
    policy.grant("read-fs:~/Documents")
    assert policy.revoke("read-fs:~/Documents") is True
    assert "revoke" in audit.event_kinds()
    assert policy.is_granted("read-fs:~/Documents") is False


def test_revoke_missing_returns_false_no_audit() -> None:
    policy, audit, _ = _new_policy()
    assert policy.revoke("read-fs:~/Nope") is False
    assert "revoke" not in audit.event_kinds()


def test_deny_blocks_existing_grant() -> None:
    policy, audit, _ = _new_policy()
    policy.grant("network:any")
    policy.deny("network:any")
    assert policy.is_granted("network:any") is False
    assert "deny" in audit.event_kinds()


def test_deny_persists_across_grant_attempts() -> None:
    policy, _, _ = _new_policy()
    policy.deny("network:any")
    with pytest.raises(CapabilityDeniedError):
        policy.grant("network:any")


# ─── is_granted / assert_capability ──────────────────────────────────────────


def test_is_granted_true_after_grant() -> None:
    policy, _, _ = _new_policy()
    policy.grant("read-fs:~/Documents")
    assert policy.is_granted("read-fs:~/Documents") is True


def test_is_granted_false_for_unknown() -> None:
    policy, _, _ = _new_policy()
    assert policy.is_granted("read-fs:~/Documents") is False


def test_is_granted_uses_path_prefix() -> None:
    policy, _, _ = _new_policy()
    policy.grant("read-fs:~/Documents")
    assert policy.is_granted("read-fs:~/Documents/notes/x.md") is True
    assert policy.is_granted("read-fs:~/Pictures") is False


def test_is_granted_respects_expiration() -> None:
    policy, _, clock = _new_policy()
    policy.grant("read-fs:~/Documents", expires_at=clock.t + 10)
    assert policy.is_granted("read-fs:~/Documents") is True
    clock.advance(11)
    assert policy.is_granted("read-fs:~/Documents") is False


def test_is_granted_blocks_sudo_when_never() -> None:
    policy, _, _ = _new_policy()
    policy.grant("sudo:install")  # accidentalmente concedida
    policy.deny("sudo:never")  # política luego pone sudo:never
    assert policy.is_granted("sudo:install") is False


def test_assert_capability_returns_grant_when_allowed() -> None:
    policy, audit, _ = _new_policy()
    policy.grant("read-fs:~/Documents")
    grant = policy.assert_capability("read-fs:~/Documents/x.md")
    assert grant.capability == Capability("read-fs", "~/Documents")
    assert "use:allowed" in audit.event_kinds()


def test_assert_capability_raises_not_granted() -> None:
    policy, audit, _ = _new_policy()
    with pytest.raises(CapabilityNotGrantedError):
        policy.assert_capability("read-fs:~/Documents")
    assert "use:denied" in audit.event_kinds()


def test_assert_capability_raises_when_denied() -> None:
    policy, _, _ = _new_policy()
    policy.deny("network:any")
    with pytest.raises(CapabilityDeniedError):
        policy.assert_capability("network:any")


def test_assert_capability_distinguishes_expired_from_never_granted() -> None:
    policy, audit, clock = _new_policy()
    policy.grant("read-fs:~/Documents", expires_at=clock.t + 10)
    clock.advance(11)
    with pytest.raises(CapabilityNotGrantedError):
        policy.assert_capability("read-fs:~/Documents")
    assert "use:expired" in audit.event_kinds()


def test_assert_capability_blocks_sudo_when_never() -> None:
    policy, _, _ = _new_policy()
    policy.grant("sudo:install")
    policy.deny("sudo:never")
    with pytest.raises(CapabilityDeniedError):
        policy.assert_capability("sudo:install")


# ─── Modos ───────────────────────────────────────────────────────────────────


def test_mode_default_is_normal() -> None:
    policy = SandboxPolicy()
    assert policy.mode is SandboxMode.NORMAL


def test_set_mode_audits_transition() -> None:
    policy, audit, _ = _new_policy()
    policy.set_mode(SandboxMode.PARANOID)
    assert policy.mode is SandboxMode.PARANOID
    kind, _, detail = audit.events[-1]
    assert kind == "mode:set"
    assert "normal" in detail and "paranoid" in detail


def test_demo_mode_blocks_all_assertions_even_with_grant() -> None:
    policy, audit, _ = _new_policy(mode=SandboxMode.DEMO)
    policy.grant("read-fs:~/Documents")
    with pytest.raises(DemoModeBlockedError):
        policy.assert_capability("read-fs:~/Documents/x.md")
    assert any(e == "use:denied" for e, _, _ in audit.events)


def test_normal_mode_allows_with_grant() -> None:
    policy, _, _ = _new_policy(mode=SandboxMode.NORMAL)
    policy.grant("read-fs:~/Documents")
    policy.assert_capability("read-fs:~/Documents/x.md")  # no exception


def test_paranoid_mode_allows_with_grant_but_requires_confirmation() -> None:
    policy, _, _ = _new_policy(mode=SandboxMode.PARANOID)
    policy.grant("read-fs:~/Documents")
    # assert_capability no controla la confirmación — eso es responsabilidad
    # del executor. Aquí la grant alcanza para no bloquear.
    policy.assert_capability("read-fs:~/Documents/x.md")
    assert policy.requires_confirmation(RiskLevel.SAFE) is True


def test_requires_confirmation_table() -> None:
    p_para, _, _ = _new_policy(mode=SandboxMode.PARANOID)
    p_norm, _, _ = _new_policy(mode=SandboxMode.NORMAL)
    p_demo, _, _ = _new_policy(mode=SandboxMode.DEMO)

    for risk in RiskLevel:
        assert p_para.requires_confirmation(risk) is True

    assert p_norm.requires_confirmation(RiskLevel.SAFE) is False
    assert p_norm.requires_confirmation(RiskLevel.CONFIRM) is True
    assert p_norm.requires_confirmation(RiskLevel.DANGEROUS) is True

    for risk in RiskLevel:
        assert p_demo.requires_confirmation(risk) is True


def test_mode_requires_confirmation_function() -> None:
    assert mode_requires_confirmation(SandboxMode.NORMAL, RiskLevel.SAFE) is False
    assert mode_requires_confirmation(SandboxMode.NORMAL, RiskLevel.CONFIRM) is True
    assert mode_requires_confirmation(SandboxMode.PARANOID, RiskLevel.SAFE) is True


# ─── list_grants / purge_expired ─────────────────────────────────────────────


def test_list_grants_excludes_expired_by_default() -> None:
    policy, _, clock = _new_policy()
    policy.grant("read-fs:~/Documents", expires_at=clock.t + 10)
    policy.grant("network:any")
    clock.advance(11)
    active = policy.list_grants()
    assert len(active) == 1
    assert active[0].capability.kind == "network"


def test_list_grants_include_expired() -> None:
    policy, _, clock = _new_policy()
    policy.grant("read-fs:~/Documents", expires_at=clock.t + 10)
    clock.advance(11)
    all_grants = policy.list_grants(include_expired=True)
    assert len(all_grants) == 1


def test_purge_expired_removes_and_audits() -> None:
    policy, audit, clock = _new_policy()
    policy.grant("read-fs:~/Documents", expires_at=clock.t + 10)
    policy.grant("network:any")
    clock.advance(11)
    n = policy.purge_expired()
    assert n == 1
    assert len(policy.list_grants(include_expired=True)) == 1
    assert any(e == "expire:purge" for e, _, _ in audit.events)


def test_purge_expired_returns_zero_when_none() -> None:
    policy, audit, _ = _new_policy()
    policy.grant("network:any")
    assert policy.purge_expired() == 0
    assert "expire:purge" not in audit.event_kinds()


# ─── Audit callback robustness ───────────────────────────────────────────────


def test_audit_callback_exception_does_not_break_grant() -> None:
    def boom(event: str, cap: Capability | None, detail: str) -> None:
        raise RuntimeError("audit callback explotó")

    policy = SandboxPolicy(audit_callback=boom)
    # No debe propagar la excepción
    grant = policy.grant("read-fs:~/Documents")
    assert grant is not None
    assert policy.is_granted("read-fs:~/Documents") is True


def test_audit_callback_none_is_safe() -> None:
    policy = SandboxPolicy(audit_callback=None)
    policy.grant("network:any")
    policy.assert_capability("network:any")
    policy.revoke("network:any")
    # No exceptions = pasa


# ─── Casos con paths absolutos POSIX-like ────────────────────────────────────


def test_grant_with_absolute_path_unix_style() -> None:
    policy, _, _ = _new_policy()
    policy.grant("read-fs:/usr/share/doc")
    if os.name == "posix":
        assert policy.is_granted("read-fs:/usr/share/doc/python") is True
        assert policy.is_granted("read-fs:/etc/passwd") is False
    else:
        # En Windows, paths POSIX puros se anclan al cwd; el comportamiento
        # exacto depende del cwd. Lo que sí debe valer: el path exacto se
        # cubre a sí mismo.
        assert policy.is_granted("read-fs:/usr/share/doc") is True
