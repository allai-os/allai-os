"""Política de sandbox: capabilities por sesión, modos y consentimientos.

Este módulo define **el contrato** que `bwrap.py`, `seccomp.py` y el
`ToolExecutor` consultan para decidir qué tiene permitido hacer la
sesión actual. No ejecuta nada por sí mismo — sólo gestiona estado.

Conceptos clave:

- **`Capability`**: par `(kind, scope)` que representa un permiso
  granular. Ejemplos: `read-fs:~/Documents`, `network:api.openai.com`,
  `shell:read-only`, `sudo:never`. Inmutable.

- **`SandboxMode`**: tres modos operativos con políticas distintas:
  `paranoid` (confirma todo), `normal` (default; confirma confirm/dangerous),
  `demo` (dry-run total — bloquea cualquier ejecución real).

- **`SandboxPolicy`**: estado mutable de la sesión. Mantiene grants,
  denials explícitos, modo, y un audit_callback para emitir eventos.

- **Coverage**: una grant cubre una capability solicitada si:
  - kind iguales y scope idéntico, **o**
  - read-fs/write-fs con scope path-prefix (ej. grant de
    `read-fs:~/Documents` cubre solicitudes a `read-fs:~/Documents/x.txt`),
    pero NUNCA con traversal (`..` resuelto se valida vs el grant),
  - network con grant `any` cubre cualquier hostname,
  - cualquier `sudo:*` queda **bloqueado** si existe `sudo:never` en
    `denied`. `sudo:never` no se concede; se "denies" para señalar la
    política.

Política de seguridad explícita:

- Las grants **expiran al cerrar la sesión** salvo que `persistent=True`
  (la persistencia entre sesiones la maneja una capa superior — este
  módulo sólo expone el flag).
- Los `denied` son **prevalecen** sobre cualquier grant — incluso si una
  capability fue grant antes, ponerla en denied bloquea futuras
  solicitudes.
- El `audit_callback` se invoca **dentro** de cada grant/revoke/deny/use,
  con la capability y el resultado. Es responsabilidad del caller no
  bloquear con I/O lento ahí (típicamente delega a un queue).
- Tiempos: el módulo no usa `time.time()` directamente; recibe
  `now_provider` inyectable para que los tests sean deterministas y
  para que un eventual reloj NTP-corrupto no rompa el sandbox.

Lo que NO hace este módulo:

- Pedir consentimiento al usuario (eso es UI, vive en `desktop/`).
- Persistir grants entre sesiones (eso lo hace una capa superior usando
  `~/.local/share/allai/sandbox-consents.jsonl`).
- Ejecutar bwrap o aplicar seccomp (sus módulos respectivos consultan
  esta policy).
- Cargar/guardar el estado a disco (es estado puro de la sesión).
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Final

from tools.base import CapabilityDeniedError, RiskLevel

# ─── Modos de operación ──────────────────────────────────────────────────────


class SandboxMode(str, Enum):
    """Tres modos operativos.

    - PARANOID: confirma cada acción, incluso `safe`. Capabilities mínimas.
    - NORMAL (default): confirma `confirm`/`dangerous`. Capabilities por
      sesión con scopes acotados.
    - DEMO: dry-run total. `assert_capability` siempre lanza para que el
      caller no ejecute nada real, pero se registra el intento en audit.
    """

    PARANOID = "paranoid"
    NORMAL = "normal"
    DEMO = "demo"


def mode_requires_confirmation(mode: SandboxMode, risk: RiskLevel) -> bool:
    """¿Este `mode` exige confirmación humana para una acción de `risk`?

    - PARANOID: True para cualquier riesgo.
    - NORMAL: True sólo para CONFIRM y DANGEROUS.
    - DEMO: True (no relevante — todas se bloquean igual antes de pedir).
    """
    if mode is SandboxMode.PARANOID:
        return True
    if mode is SandboxMode.DEMO:
        return True
    return risk is not RiskLevel.SAFE


# ─── Capability ──────────────────────────────────────────────────────────────


_KNOWN_KINDS: Final[frozenset[str]] = frozenset(
    {
        "read-fs",
        "write-fs",
        "network",
        "shell",
        "clipboard",
        "screen",
        "input",
        "app",
        "sudo",
    }
)
"""Tipos de capability reconocidos. El parser rechaza cualquier otro.

Cuando se agregue un kind nuevo, agregarlo aquí y documentar su semántica
de coverage en `Capability.covers`.
"""

_PATH_KINDS: Final[frozenset[str]] = frozenset({"read-fs", "write-fs"})
"""Kinds cuyo scope es un path filesystem, sujeto a normalización y
comparación por path-prefix."""


class CapabilityParseError(ValueError):
    """El string de capability no se pudo parsear."""


@dataclass(frozen=True, slots=True)
class Capability:
    """Permiso granular `(kind, scope)`.

    Ejemplos:
      - `Capability("read-fs", "~/Documents")`
      - `Capability("network", "api.openai.com")`
      - `Capability("shell", "read-only")`

    El scope es opaco al tipo en general; sólo `read-fs`/`write-fs` lo
    interpretan como path. La coincidencia exacta es siempre la regla
    base; las extensiones (path-prefix, network:any) están en `covers`.
    """

    kind: str
    scope: str

    def __post_init__(self) -> None:
        if self.kind not in _KNOWN_KINDS:
            raise CapabilityParseError(
                f"kind desconocido: {self.kind!r}. "
                f"Conocidos: {sorted(_KNOWN_KINDS)}"
            )
        if not self.scope:
            raise CapabilityParseError(
                f"scope vacío para {self.kind} — usa 'any' o un valor explícito"
            )

    @classmethod
    def parse(cls, raw: str) -> Capability:
        """Parsea `kind:scope`. Lanza `CapabilityParseError` si está mal."""
        if not isinstance(raw, str):
            raise CapabilityParseError(f"capability debe ser str, vino {type(raw)}")
        if ":" not in raw:
            raise CapabilityParseError(
                f"formato inválido {raw!r} — esperado 'kind:scope'"
            )
        kind, scope = raw.split(":", 1)
        kind = kind.strip()
        scope = scope.strip()
        return cls(kind=kind, scope=scope)

    def __str__(self) -> str:
        return f"{self.kind}:{self.scope}"

    def covers(self, requested: Capability) -> bool:
        """¿Esta capability concede lo que `requested` solicita?

        Reglas:
          - kinds distintos → False.
          - read-fs / write-fs: scope normalizado de la grant debe ser
            ancestro (o igual) al scope normalizado de la solicitud.
            La normalización resuelve `~`, `..`, links — sin red.
          - network: scope `any` cubre todo; otherwise igualdad exacta.
          - resto de kinds: igualdad exacta de scope.
        """
        if self.kind != requested.kind:
            return False
        if self.kind in _PATH_KINDS:
            return _path_covers(self.scope, requested.scope)
        if self.kind == "network":
            return self.scope == "any" or self.scope == requested.scope
        return self.scope == requested.scope


def _to_capability(value: Capability | str) -> Capability:
    """Convierte str o Capability a Capability."""
    if isinstance(value, Capability):
        return value
    return Capability.parse(value)


def _path_covers(grant_scope: str, requested_scope: str) -> bool:
    """¿`grant_scope` cubre `requested_scope` en sentido path-prefix?

    Pasos:
      1. Expandir `~` en ambos.
      2. Resolver a path absoluto (sin tocar disco; `Path` puro).
      3. La grant debe ser ancestro o igual al requested.

    Si alguno no se puede resolver (ej. caracteres raros), retorna False
    de forma defensiva — preferimos negar que conceder por error.
    """
    try:
        grant_path = _normalize_path(grant_scope)
        requested_path = _normalize_path(requested_scope)
    except (ValueError, OSError):
        return False
    try:
        return requested_path == grant_path or grant_path in requested_path.parents
    except ValueError:
        return False


def _normalize_path(raw: str) -> Path:
    """Expande `~`, fuerza absolute, normaliza separadores. No toca disco.

    No usamos `Path.resolve()` porque resuelve symlinks (toca disco) y
    en sandboxing queremos comparar el scope **declarado**, no el
    target del link. Si un atacante concede `~/Documents` y luego lo
    convierte en symlink a `/`, eso es un bug de la UI/del usuario, no
    nuestro — el sandbox bwrap aplica los binds sobre el path declarado.
    """
    expanded = os.path.expanduser(raw)
    p = Path(expanded)
    if not p.is_absolute():
        # Path relativo: lo anclamos al cwd para tener una representación
        # determinista. En la práctica las grants siempre vienen
        # absolutas o con `~`, así que esta rama es defensiva.
        p = Path.cwd() / p
    # `os.path.normpath` quita `..` y `.` sin tocar disco.
    return Path(os.path.normpath(str(p)))


# ─── Grant ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CapabilityGrant:
    """Concesión de una capability con metadatos para audit.

    `expires_at` `None` significa "fin de sesión" (la sesión decide
    cuándo cierra). `persistent=True` indica que la UI superior debe
    persistirla entre sesiones; este módulo sólo expone la flag.
    """

    capability: Capability
    granted_at: int
    granted_by: str = "user"
    """Quién originó la concesión: 'user', 'policy-default', 'system', etc."""
    expires_at: int | None = None
    persistent: bool = False
    note: str = ""
    """Texto libre para audit/UX."""


# ─── Audit ──────────────────────────────────────────────────────────────────


SandboxAuditEvent = str
"""Tipo del evento — usamos strings para flexibilidad. Eventos definidos:

- 'grant': capability concedida.
- 'revoke': grant explícitamente removida.
- 'deny': capability puesta en blocklist.
- 'use:allowed': capability solicitada y concedida (assert_capability OK).
- 'use:denied': capability solicitada y rechazada.
- 'use:expired': capability concedida pero expirada al momento de uso.
- 'mode:set': cambio de modo.
- 'expire:purge': barrido de grants expiradas.
"""

SandboxAuditCallback = Callable[[SandboxAuditEvent, Capability | None, str], None]
"""Firma del callback: `(event, capability_or_none, detail)`. El callback
NO debe levantar excepciones — si lo hace, las atrapamos para no
romper la operación que está en curso. Sí debe ser barato; si hace
I/O, conviene encolar y procesar fuera."""


# ─── Errores ─────────────────────────────────────────────────────────────────


class CapabilityNotGrantedError(CapabilityDeniedError):
    """La capability no fue solicitada al usuario / no fue concedida.

    Distinta de `CapabilityDeniedError` directa (que indica denial
    explícito o uso fuera de scope).
    """


class DemoModeBlockedError(CapabilityDeniedError):
    """Modo `demo` está activo: ninguna acción se ejecuta de verdad."""

    def __init__(self, capability: Capability) -> None:
        super().__init__(str(capability))
        self.capability = capability


# ─── Policy ──────────────────────────────────────────────────────────────────


def _default_now() -> int:
    return int(time.time())


@dataclass
class SandboxPolicy:
    """Estado de capabilities/modos para una sesión del agente.

    Inmutable conceptualmente entre operaciones de la sesión; los
    métodos `grant`/`revoke`/`deny`/`set_mode` mutan el estado y emiten
    eventos de audit.
    """

    mode: SandboxMode = SandboxMode.NORMAL
    grants: dict[Capability, CapabilityGrant] = field(default_factory=dict)
    denied: set[Capability] = field(default_factory=set)
    audit_callback: SandboxAuditCallback | None = None
    now_provider: Callable[[], int] = field(default=_default_now)

    # ─── Mode ────────────────────────────────────────────────────────────────

    def set_mode(self, mode: SandboxMode) -> None:
        old = self.mode
        self.mode = mode
        self._emit("mode:set", None, f"{old.value} -> {mode.value}")

    def requires_confirmation(self, risk: RiskLevel) -> bool:
        """Atajo: ¿el modo actual requiere confirmación humana para `risk`?"""
        return mode_requires_confirmation(self.mode, risk)

    # ─── Grant / Revoke / Deny ───────────────────────────────────────────────

    def grant(
        self,
        capability: Capability | str,
        *,
        granted_by: str = "user",
        expires_at: int | None = None,
        persistent: bool = False,
        note: str = "",
    ) -> CapabilityGrant:
        """Registra una grant.

        Lanza `CapabilityDeniedError` si la capability está en `denied`.
        Si ya existía una grant para la misma capability, la reemplaza
        (audit log captura la transición).
        """
        cap = _to_capability(capability)
        if cap in self.denied:
            self._emit("use:denied", cap, "grant rechazada — está en denied")
            raise CapabilityDeniedError(str(cap))
        grant = CapabilityGrant(
            capability=cap,
            granted_at=self.now_provider(),
            granted_by=granted_by,
            expires_at=expires_at,
            persistent=persistent,
            note=note,
        )
        self.grants[cap] = grant
        self._emit("grant", cap, f"by={granted_by} persistent={persistent}")
        return grant

    def revoke(self, capability: Capability | str) -> bool:
        """Remueve una grant. Devuelve True si existía."""
        cap = _to_capability(capability)
        existed = self.grants.pop(cap, None) is not None
        if existed:
            self._emit("revoke", cap, "")
        return existed

    def deny(self, capability: Capability | str) -> None:
        """Pone la capability en blocklist. Cualquier grant existente es
        removida."""
        cap = _to_capability(capability)
        self.denied.add(cap)
        self.grants.pop(cap, None)
        self._emit("deny", cap, "")

    # ─── Queries ─────────────────────────────────────────────────────────────

    def is_granted(self, capability: Capability | str) -> bool:
        """¿La capability está activamente concedida?

        Considera: denied prevalece, expiración, y coverage por grants
        más amplias (e.g. read-fs:~/Documents cubre read-fs:~/Documents/x).
        """
        cap = _to_capability(capability)
        if cap in self.denied or self._is_dangerous_sudo_blocked(cap):
            return False
        return self._find_covering_grant(cap) is not None

    def assert_capability(self, capability: Capability | str) -> CapabilityGrant:
        """Verifica que la capability está concedida; devuelve la grant
        que la cubre.

        Lanza:
          - `DemoModeBlockedError` si el modo es DEMO (incluso con grant).
          - `CapabilityDeniedError` si está en denied.
          - `CapabilityNotGrantedError` si no hay grant que la cubra.
        """
        cap = _to_capability(capability)
        if self.mode is SandboxMode.DEMO:
            self._emit("use:denied", cap, "demo-mode")
            raise DemoModeBlockedError(cap)
        if cap in self.denied or self._is_dangerous_sudo_blocked(cap):
            self._emit("use:denied", cap, "denied-explicit")
            raise CapabilityDeniedError(str(cap))
        grant = self._find_covering_grant(cap)
        if grant is None:
            # ¿Existía pero expiró?
            if self._has_expired_grant(cap):
                self._emit("use:expired", cap, "")
            else:
                self._emit("use:denied", cap, "not-granted")
            raise CapabilityNotGrantedError(str(cap))
        self._emit("use:allowed", cap, f"covered-by={grant.capability}")
        return grant

    def list_grants(self, *, include_expired: bool = False) -> list[CapabilityGrant]:
        """Devuelve grants activas (o todas si `include_expired=True`)."""
        now = self.now_provider()
        out: list[CapabilityGrant] = []
        for grant in self.grants.values():
            if not include_expired and _is_expired(grant, now):
                continue
            out.append(grant)
        return out

    def purge_expired(self) -> int:
        """Borra grants expiradas. Devuelve cuántas se removieron."""
        now = self.now_provider()
        expired = [cap for cap, grant in self.grants.items() if _is_expired(grant, now)]
        for cap in expired:
            del self.grants[cap]
        if expired:
            self._emit("expire:purge", None, f"count={len(expired)}")
        return len(expired)

    # ─── Internals ───────────────────────────────────────────────────────────

    def _find_covering_grant(self, requested: Capability) -> CapabilityGrant | None:
        """Encuentra una grant activa que cubra `requested`.

        Recorre todas las grants; con N grants pequeño (~decenas en una
        sesión típica) es OK. Si llegara a ser caliente, indexamos por
        kind.
        """
        now = self.now_provider()
        for grant in self.grants.values():
            if _is_expired(grant, now):
                continue
            if grant.capability.covers(requested):
                return grant
        return None

    def _has_expired_grant(self, requested: Capability) -> bool:
        """¿Había una grant que cubriría pero está expirada?"""
        now = self.now_provider()
        for grant in self.grants.values():
            if not _is_expired(grant, now):
                continue
            if grant.capability.covers(requested):
                return True
        return False

    def _is_dangerous_sudo_blocked(self, requested: Capability) -> bool:
        """`sudo:never` en `denied` bloquea cualquier `sudo:*`."""
        if requested.kind != "sudo":
            return False
        sentinel = Capability("sudo", "never")
        return sentinel in self.denied

    def _emit(
        self,
        event: SandboxAuditEvent,
        capability: Capability | None,
        detail: str,
    ) -> None:
        cb = self.audit_callback
        if cb is None:
            return
        try:
            cb(event, capability, detail)
        except Exception:  # noqa: BLE001 - audit callback no debe romper la operación
            # Conscientemente silenciamos errores del callback para no
            # interrumpir la operación principal. Si el callback debe
            # alertar de su propio fallo, lo hace por canales propios.
            pass


def _is_expired(grant: CapabilityGrant, now: int) -> bool:
    return grant.expires_at is not None and grant.expires_at <= now
