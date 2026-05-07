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
    "BwrapNotAvailableError",
    "BwrapProfile",
    "Capability",
    "CapabilityGrant",
    "CapabilityNotGrantedError",
    "CapabilityParseError",
    "DemoModeBlockedError",
    "SandboxAuditCallback",
    "SandboxAuditEvent",
    "SandboxMode",
    "SandboxPolicy",
    "build_bwrap_argv",
    "is_bwrap_available",
    "mode_requires_confirmation",
]
