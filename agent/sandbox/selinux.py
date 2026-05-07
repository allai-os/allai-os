"""Wrapper Python para interactuar con SELinux desde el agente.

La policy en sí vive en `distro/selinux/allai.te` (Type Enforcement) y
se compila/carga sólo en Fedora/RHEL con `selinux-policy-devel`. Este
módulo Python:

  - Detecta si SELinux está disponible y en qué modo
    (`is_selinux_available`, `current_mode`).
  - Verifica que el módulo `allai` esté cargado
    (`is_allai_module_loaded`).
  - Provee un parser/validator de **contextos SELinux** como strings
    (`SELinuxContext`) — es lo que se ve en `ls -Z`. 100% testeable
    sin libselinux.
  - Permite consultar el contexto del proceso actual
    (`current_process_context`).
  - Detecta denials recientes en `/var/log/audit/audit.log`
    (`recent_denials_for_domain`) — útil para mostrar en Activity
    Center cuando el sandbox bloquea algo.

Diseño (security-first):

- **Lazy import** de `selinux` (binding de libselinux). En Windows /
  macOS el módulo Python carga sin error y las funciones que requieren
  libselinux levantan `SELinuxUnavailableError` al invocarse.
- **Fail-soft con warning**: si SELinux no está activo o el módulo no
  cargado, el agente NO se detiene — registra warning y continúa con
  bwrap+seccomp. Es defensa en profundidad: SELinux es la tercera
  capa, no la primera.
- **No carga ni descarga policies** desde Python. Eso lo hace el
  paquete RPM al instalarse, vía `semodule`. Cargar policies desde
  un proceso del usuario sería un anti-pattern de seguridad.
- **Parsing puro de contextos**: `SELinuxContext.parse` valida sin
  side effects; los tests cubren formatos válidos y inválidos.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

# ─── Constantes ─────────────────────────────────────────────────────────────


SELINUX_MODE_DISABLED: Final[str] = "disabled"
SELINUX_MODE_PERMISSIVE: Final[str] = "permissive"
SELINUX_MODE_ENFORCING: Final[str] = "enforcing"

ALLAI_MODULE_NAME: Final[str] = "allai"
ALLAI_DAEMON_TYPE: Final[str] = "allai_t"
ALLAI_SANDBOXED_TYPE: Final[str] = "allai_sandboxed_t"
ALLAI_DATA_TYPE: Final[str] = "allai_data_t"
ALLAI_CONFIG_TYPE: Final[str] = "allai_config_t"

DEFAULT_AUDIT_LOG: Final[str] = "/var/log/audit/audit.log"


# ─── Errores ────────────────────────────────────────────────────────────────


class SELinuxError(Exception):
    """Error general del wrapper SELinux."""


class SELinuxUnavailableError(SELinuxError):
    """SELinux no está disponible en este sistema (Windows/macOS o
    libselinux ausente).
    """


class SELinuxContextError(SELinuxError):
    """Error parseando o validando un contexto SELinux."""


# ─── SELinuxContext ─────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SELinuxContext:
    """Contexto SELinux: `<user>:<role>:<type>:<sensitivity>[:categories]`.

    Ejemplos:
      - `system_u:system_r:allai_t:s0`
      - `unconfined_u:object_r:allai_data_t:s0`
      - `staff_u:staff_r:staff_t:s0-s0:c0.c1023` (con categorías MLS)

    El parser acepta los formatos comunes de Fedora targeted policy.
    Categorías opcionales (último campo si tiene `:c<N>`).
    """

    user: str
    role: str
    type_: str
    sensitivity: str
    categories: str | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("user", self.user),
            ("role", self.role),
            ("type_", self.type_),
            ("sensitivity", self.sensitivity),
        ):
            if not value or not isinstance(value, str):
                raise SELinuxContextError(
                    f"campo {field_name} vacío o no es string: {value!r}"
                )
            if ":" in value:
                raise SELinuxContextError(
                    f"campo {field_name} no debe contener ':' (vino {value!r})"
                )

    @classmethod
    def parse(cls, raw: str) -> "SELinuxContext":
        """Parsea un string como `<user>:<role>:<type>:<level>[:<cats>]`.

        Lanza `SELinuxContextError` si el formato es inválido.
        """
        if not isinstance(raw, str):
            raise SELinuxContextError(
                f"contexto debe ser str, vino {type(raw).__name__}"
            )
        if not raw:
            raise SELinuxContextError("contexto vacío")
        parts = raw.split(":")
        if len(parts) < 4:
            raise SELinuxContextError(
                f"contexto necesita al menos 4 campos (user:role:type:level), "
                f"vino {len(parts)}: {raw!r}"
            )
        if len(parts) > 5:
            # En Fedora targeted con MLS los campos sensitivity y
            # categories pueden venir como `s0-s0:c0.c1023` que tiene
            # un `:` interno — lo recomponemos.
            sensitivity = parts[3]
            categories = ":".join(parts[4:])
        elif len(parts) == 5:
            sensitivity = parts[3]
            categories = parts[4]
        else:
            sensitivity = parts[3]
            categories = None
        return cls(
            user=parts[0],
            role=parts[1],
            type_=parts[2],
            sensitivity=sensitivity,
            categories=categories,
        )

    def __str__(self) -> str:
        base = f"{self.user}:{self.role}:{self.type_}:{self.sensitivity}"
        if self.categories:
            return f"{base}:{self.categories}"
        return base

    def is_allai_domain(self) -> bool:
        """¿Este contexto corresponde a uno de los dominios allAI?"""
        return self.type_ in {ALLAI_DAEMON_TYPE, ALLAI_SANDBOXED_TYPE}


# ─── Disponibilidad ─────────────────────────────────────────────────────────


def is_selinux_available() -> bool:
    """True si libselinux está disponible y el sistema reporta SELinux
    habilitado.

    En Windows/macOS retorna False sin levantar.
    """
    if os.name != "posix":
        return False
    try:
        selinux = _import_selinux()
    except SELinuxUnavailableError:
        return False
    try:
        return bool(selinux.is_selinux_enabled())
    except Exception:  # noqa: BLE001 - si la llamada falla, asumimos no disponible
        return False


def current_mode() -> str:
    """Devuelve `enforcing`, `permissive`, o `disabled`.

    Raises:
      SELinuxUnavailableError: si libselinux no está.
    """
    selinux = _import_selinux()
    if not selinux.is_selinux_enabled():
        return SELINUX_MODE_DISABLED
    is_enforcing = selinux.security_getenforce()
    return SELINUX_MODE_ENFORCING if is_enforcing == 1 else SELINUX_MODE_PERMISSIVE


def is_allai_module_loaded() -> bool:
    """¿El módulo `allai` está cargado en SELinux?

    Usa `semodule -l` y busca el nombre. Si `semodule` no está en PATH
    o falla, retorna False.

    En sistemas sin SELinux retorna False sin levantar.
    """
    if not is_selinux_available():
        return False
    try:
        result = subprocess.run(
            ["semodule", "-l"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    return any(
        line.split()[0] == ALLAI_MODULE_NAME
        for line in result.stdout.splitlines()
        if line.strip()
    )


def current_process_context() -> SELinuxContext:
    """Contexto SELinux del proceso actual.

    Raises:
      SELinuxUnavailableError: si libselinux no está.
      SELinuxError: si la consulta falla.
    """
    selinux = _import_selinux()
    try:
        rc, ctx = selinux.getcon()
    except Exception as exc:  # noqa: BLE001
        raise SELinuxError(f"getcon() falló: {exc}") from exc
    if rc != 0 or not ctx:
        raise SELinuxError(f"getcon() retornó rc={rc} ctx={ctx!r}")
    return SELinuxContext.parse(ctx)


# ─── Audit log queries ──────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AVCDenial:
    """Una denegación AVC (Access Vector Cache) del kernel SELinux.

    Campos típicos extraídos de la línea de audit:
      - timestamp: epoch del evento.
      - source_context: contexto del proceso que intentó la operación.
      - target_context: contexto del objeto sobre el que intentó.
      - target_class: clase del objeto (file, dir, socket, ...).
      - permissions: lista de permisos denegados.
      - raw: línea original para debugging.
    """

    timestamp: float
    source_context: str
    target_context: str
    target_class: str
    permissions: tuple[str, ...]
    raw: str


def parse_avc_line(line: str) -> AVCDenial | None:
    """Parsea una línea de `audit.log` con un AVC denial.

    Devuelve `AVCDenial` si la línea es un AVC, `None` si no es uno
    reconocible. No levanta — fallar parseando una línea no debe
    detener al lector de logs.
    """
    if "type=AVC" not in line and "AVC " not in line:
        return None
    if " denied " not in line and " denied=" not in line:
        # Sólo nos interesan denials, no granted (que también pueden
        # aparecer si se activa auditallow).
        return None

    timestamp = _extract_field(line, "msg=audit(")
    if timestamp is not None:
        timestamp = timestamp.split(":", 1)[0]
        try:
            ts_value = float(timestamp)
        except ValueError:
            ts_value = 0.0
    else:
        ts_value = 0.0

    source = _extract_field(line, "scontext=") or ""
    target = _extract_field(line, "tcontext=") or ""
    tclass = _extract_field(line, "tclass=") or ""

    perms_raw = _extract_braced(line, "{") or ""
    perms = tuple(p for p in perms_raw.split() if p) if perms_raw else ()

    return AVCDenial(
        timestamp=ts_value,
        source_context=source,
        target_context=target,
        target_class=tclass,
        permissions=perms,
        raw=line.rstrip("\n"),
    )


def recent_denials_for_domain(
    domain_type: str = ALLAI_DAEMON_TYPE,
    *,
    log_path: Path = Path(DEFAULT_AUDIT_LOG),
    limit: int = 50,
) -> list[AVCDenial]:
    """Devuelve los AVC denials recientes que involucran a `domain_type`
    (en source o target context).

    Lectura: secuencial del archivo. Para audit logs grandes (>10 MB)
    el caller puede preferir `ausearch` directamente. Aquí mantenemos
    el código simple y portable.

    Si el log no existe o no es legible (necesitas permisos para leer
    `/var/log/audit/audit.log`), retorna lista vacía sin levantar.
    """
    if not log_path.exists():
        return []
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError):
        return []

    denials: list[AVCDenial] = []
    for line in text.splitlines():
        denial = parse_avc_line(line)
        if denial is None:
            continue
        if domain_type in denial.source_context or domain_type in denial.target_context:
            denials.append(denial)
    # Más recientes primero (audit.log es append-only ordenado por tiempo)
    denials.reverse()
    return denials[:limit]


# ─── Internals ──────────────────────────────────────────────────────────────


def _import_selinux() -> Any:
    """Import perezoso del binding `selinux`. En sistemas sin
    libselinux (Windows/macOS, o Linux sin paquete), levanta."""
    if os.name != "posix":
        raise SELinuxUnavailableError(
            "SELinux no está disponible fuera de Linux. "
            "El módulo Python carga, pero queries en runtime fallan."
        )
    try:
        import selinux  # type: ignore[import-not-found]
    except ImportError as exc:
        raise SELinuxUnavailableError(
            "libselinux Python binding no instalado. "
            "Fedora/RHEL: `sudo dnf install python3-libselinux`."
        ) from exc
    return selinux


def _extract_field(line: str, prefix: str) -> str | None:
    """Extrae el valor que sigue a `prefix=` hasta el siguiente espacio
    o final de línea. Si no encuentra `prefix`, retorna None.
    """
    idx = line.find(prefix)
    if idx == -1:
        return None
    start = idx + len(prefix)
    end = line.find(" ", start)
    if end == -1:
        end = len(line)
    value = line[start:end]
    # Algunos fields vienen con quotes; los quitamos.
    return value.strip('"')


def _extract_braced(line: str, open_brace: str) -> str | None:
    """Extrae el contenido entre `{` y `}` para listas de permisos.

    Por ejemplo, en `denied  { read write } for ...` retorna
    `"read write"`.
    """
    idx = line.find(open_brace)
    if idx == -1:
        return None
    end = line.find("}", idx + 1)
    if end == -1:
        return None
    return line[idx + 1 : end].strip()
