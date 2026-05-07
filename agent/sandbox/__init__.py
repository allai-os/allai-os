"""Capa de sandbox de allAI: capabilities, modos, kill switch, integraciones.

Submódulos previstos (ver ROADMAP § Launch.5):
  - policy: estado de la sesión, capabilities, modos. **Disponible.**
  - bwrap: generador de comandos bubblewrap por policy. TODO.
  - seccomp: generador de filtro BPF whitelist. TODO.
  - selinux: carga del dominio `allai_t`. TODO.
  - injection_screen: OCR + injection_guard sobre screenshots/web/files. TODO.
  - kill_switch: panic file watcher, señales, audit chain. TODO.
"""

from sandbox.bwrap import (
    BwrapNotAvailableError,
    BwrapProfile,
    build_bwrap_argv,
    is_bwrap_available,
)
from sandbox.seccomp import (
    ALWAYS_DENIED_SYSCALLS,
    DEFAULT_BASE_SYSCALLS,
    NETWORK_SYSCALLS,
    SECCOMP_ACTION_ALLOW,
    SECCOMP_ACTION_KILL_PROCESS,
    SeccompError,
    SeccompFilter,
    SeccompProfile,
    SeccompUnavailableError,
    build_filter,
    is_seccomp_available,
)
from sandbox.policy import (
    Capability,
    CapabilityGrant,
    CapabilityNotGrantedError,
    CapabilityParseError,
    DemoModeBlockedError,
    SandboxAuditCallback,
    SandboxAuditEvent,
    SandboxMode,
    SandboxPolicy,
    mode_requires_confirmation,
)

__all__ = [
    "ALWAYS_DENIED_SYSCALLS",
    "BwrapNotAvailableError",
    "BwrapProfile",
    "Capability",
    "CapabilityGrant",
    "CapabilityNotGrantedError",
    "CapabilityParseError",
    "DEFAULT_BASE_SYSCALLS",
    "DemoModeBlockedError",
    "NETWORK_SYSCALLS",
    "SECCOMP_ACTION_ALLOW",
    "SECCOMP_ACTION_KILL_PROCESS",
    "SandboxAuditCallback",
    "SandboxAuditEvent",
    "SandboxMode",
    "SandboxPolicy",
    "SeccompError",
    "SeccompFilter",
    "SeccompProfile",
    "SeccompUnavailableError",
    "build_bwrap_argv",
    "build_filter",
    "is_bwrap_available",
    "is_seccomp_available",
    "mode_requires_confirmation",
]
