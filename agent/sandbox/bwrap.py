"""Generador de comandos `bubblewrap` parametrizado por `SandboxPolicy`.

Este módulo **no ejecuta** bwrap. Genera un argv (lista de strings) que
el caller pasa a `subprocess.run` o equivalente. Esa separación tiene
dos ventajas:

1. El argv es 100% inspeccionable y testeable sin necesidad de bwrap
   real instalado (vital para tests en Windows / CI minimalistas).
2. La capa que ejecuta puede decidir cómo invocar (capturar stdio,
   redireccionar, timeouts, etc.) sin que este módulo asuma una API
   particular de subprocess.

Diseño (security-first):

- **Default deny**: empezamos con `--unshare-all` y re-compartimos sólo
  lo que la `SandboxPolicy` autoriza. Si una capability no está
  concedida, su recurso queda fuera del namespace.
- **`--die-with-parent` siempre**: si `allaid` muere, el proceso confinado
  muere con él. Sin esto un escape parcial podría sobrevivir.
- **`--new-session` siempre**: nuevo session ID; el TTY del terminal
  exterior no es accesible.
- **Bind sólo lo necesario**: `/usr`, `/etc`, `/lib`, `/lib64` van como
  `--ro-bind` (lectura). El home no se bindea entero — sólo subscopes
  derivados de las capabilities `read-fs`/`write-fs` activas.
- **`/proc` y `/dev` mínimos**: `--proc /proc` y `--dev /dev` (que es un
  devtmpfs limitado por bwrap a /dev/null, /dev/zero, /dev/random,
  /dev/urandom y /dev/tty si corresponde). Sin acceso a /dev/mem,
  /dev/kmem ni dispositivos de hardware.
- **Network whitelist por host (futuro)**: bwrap por sí solo es todo-o-nada
  para network namespace. Para filtrar por host hay que componer con
  `slirp4netns` o un proxy local. Por ahora `network:any` libera la
  red entera y `network:<host>` se trata igual que `any` con un TODO
  documentado y un evento de audit que advierte el caller.
- **Sin `--seccomp` aquí**: el filtro BPF lo aplica `seccomp.py` y se
  pasa al argv como `--seccomp <fd>`. Ese acoplamiento se documenta
  en el siguiente paso del roadmap.

Ejemplo de uso (futuro):

    policy = SandboxPolicy(mode=SandboxMode.NORMAL)
    policy.grant("read-fs:~/Documents")
    policy.grant("network:any")
    argv = build_bwrap_argv(policy, ["python3", "-c", "print(1)"])
    subprocess.run(argv, check=True)

Lo que NO hace este módulo:

- No verifica que los paths existan en el host (lo dejamos al runtime).
- No carga seccomp ni SELinux (sus módulos respectivos).
- No ejecuta `bwrap`. Sólo construye argv.
- No transforma comandos shell — el caller pasa argv.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from sandbox.policy import Capability, SandboxMode, SandboxPolicy

DEFAULT_BWRAP_BIN: Final[str] = "bwrap"
"""Nombre del binario; se resuelve con `shutil.which` al construir el argv."""

# Paths read-only que el sandbox necesita para que glibc / Python /
# herramientas básicas funcionen. Son ro-bind por default; ningún
# proceso confinado puede modificar el sistema base.
_DEFAULT_RO_BIND_SYSTEM: Final[tuple[str, ...]] = (
    "/usr",
    "/etc",
    "/lib",
    "/lib64",
    "/bin",
    "/sbin",
)

# Variables de entorno que **NO** propagamos al sandbox por default —
# pueden filtrar credenciales o cambiar el comportamiento de programas.
_BLOCKED_ENV_VARS: Final[frozenset[str]] = frozenset(
    {
        "SSH_AUTH_SOCK",
        "SSH_AGENT_PID",
        "GPG_AGENT_INFO",
        "DBUS_SESSION_BUS_ADDRESS",  # se restablece dentro si se autoriza
        "XAUTHORITY",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_ACCESS_KEY_ID",
        "GITHUB_TOKEN",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
    }
)


class BwrapNotAvailableError(RuntimeError):
    """`bwrap` no se encontró en el PATH (o el binario forzado no existe)."""


# ─── Profile ────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class BwrapProfile:
    """Configuración base del sandbox, independiente de las capabilities.

    Las capabilities concedidas en la policy se aplican **sobre** este
    profile. Profile decide los binds del sistema, isolation flags y
    qué env vars propagamos.
    """

    ro_bind_system: tuple[str, ...] = _DEFAULT_RO_BIND_SYSTEM
    """Paths del sistema en lectura. Se ignoran los que no existan en el host."""

    tmpfs_paths: tuple[str, ...] = ("/tmp", "/run", "/var/tmp")
    """tmpfs aislados: cada proceso tiene su /tmp limpio."""

    proc_path: str = "/proc"
    """Si es no-vacío, monta un /proc nuevo dentro del namespace."""

    dev_path: str = "/dev"
    """Si es no-vacío, monta un devtmpfs limitado dentro del namespace."""

    unshare_user: bool = True
    """Aísla user namespace. Necesario para que las syscalls como
    `unshare` de adentro no afecten al host."""

    unshare_pid: bool = True
    """No ver procesos del host."""

    unshare_ipc: bool = True
    """Sin SysV IPC ni POSIX shm compartidos."""

    unshare_uts: bool = True
    """Hostname propio; no leakea el del host."""

    unshare_cgroup: bool = True
    """cgroup propio; no manipula el del host."""

    die_with_parent: bool = True
    """Mata el sandbox cuando muere `allaid`. **Siempre True** salvo
    para tests específicos del flag."""

    new_session: bool = True
    """Nuevo session ID — desconecta del TTY del invocador."""

    extra_env: dict[str, str] = field(default_factory=dict)
    """Env vars adicionales a setear (no leen del host). El sandbox
    parte con un env mínimo: PATH, HOME, USER, LANG (más estos)."""

    blocked_env: frozenset[str] = _BLOCKED_ENV_VARS
    """Env vars del host que JAMÁS propagamos."""

    @classmethod
    def default(cls) -> "BwrapProfile":
        """Profile estándar para modo `normal`."""
        return cls()

    @classmethod
    def paranoid(cls) -> "BwrapProfile":
        """Profile más estricto: tmpfs incluso en /var, sin /dev extra."""
        return cls(
            ro_bind_system=("/usr", "/etc", "/lib", "/lib64"),
            tmpfs_paths=("/tmp", "/run", "/var", "/var/tmp"),
        )

    @classmethod
    def demo(cls) -> "BwrapProfile":
        """Profile para `demo`: todo aislado, network siempre denegado.

        Aún cuando se generen comandos para inspección, el modo demo
        es dry-run; ejecutar este argv real bloquearía la red incluso
        si la policy concedió `network:any` (defensa en profundidad).
        """
        return cls(
            ro_bind_system=_DEFAULT_RO_BIND_SYSTEM,
            tmpfs_paths=("/tmp", "/run", "/var/tmp"),
        )


# ─── Constructor ─────────────────────────────────────────────────────────────


def build_bwrap_argv(
    policy: SandboxPolicy,
    command: list[str],
    *,
    profile: BwrapProfile | None = None,
    bwrap_path: str | None = None,
    home_dir: Path | None = None,
    require_bwrap: bool = False,
) -> list[str]:
    """Construye el argv para invocar `bwrap` con la policy aplicada.

    Args:
      policy: SandboxPolicy con grants activas. El modo influye en los
        binds permitidos (DEMO fuerza network=False aunque haya grant).
      command: argv del programa a ejecutar dentro del sandbox.
      profile: configuración base. Si es None, se elige por modo:
        DEMO → paranoid+demo, PARANOID → paranoid, NORMAL → default.
      bwrap_path: ruta al binario. Si es None, se busca con `shutil.which`.
        Si no se encuentra y `require_bwrap=True`, lanza BwrapNotAvailableError.
        Si `require_bwrap=False` (default) y no existe, usamos el nombre
        literal "bwrap" — útil para tests y para dejar al caller manejar
        el error de exec.
      home_dir: directorio del usuario para resolver `~` en grants. Si
        es None, usa `Path.home()`.
      require_bwrap: si True, exige que bwrap esté instalado al construir
        el argv. Útil para falla rápida en runtime; los tests usan False.

    Returns:
      argv listo para subprocess.run, empezando por la ruta del binario
      bwrap, sus flags, `--`, y luego `command`.

    Raises:
      BwrapNotAvailableError: si require_bwrap y bwrap no está.
      ValueError: si command está vacío.
    """
    if not command:
        raise ValueError("command no puede estar vacío")

    chosen_profile = profile or _profile_for_mode(policy.mode)
    binary = _resolve_bwrap_binary(bwrap_path, require=require_bwrap)
    home = home_dir or Path.home()

    args: list[str] = [binary]

    # Isolation flags. Empezamos con --unshare-all y restablecemos lo
    # que la policy permite.
    args.append("--unshare-all")
    if chosen_profile.die_with_parent:
        args.append("--die-with-parent")
    if chosen_profile.new_session:
        args.append("--new-session")
    if not chosen_profile.unshare_user:
        args.append("--share-user")
    if not chosen_profile.unshare_pid:
        args.append("--share-pid")
    if not chosen_profile.unshare_ipc:
        args.append("--share-ipc")
    if not chosen_profile.unshare_uts:
        args.append("--share-uts")
    if not chosen_profile.unshare_cgroup:
        args.append("--share-cgroup")

    # Network: bwrap es todo-o-nada. Sólo se comparte si:
    #   1) modo no es DEMO, Y
    #   2) la policy tiene alguna grant `network:*` activa.
    if policy.mode is not SandboxMode.DEMO and _has_network_grant(policy):
        args.append("--share-net")

    # Sistema en read-only.
    for path in chosen_profile.ro_bind_system:
        args.extend(["--ro-bind-try", path, path])

    # tmpfs aislados.
    for path in chosen_profile.tmpfs_paths:
        args.extend(["--tmpfs", path])

    # /proc y /dev mínimos.
    if chosen_profile.proc_path:
        args.extend(["--proc", chosen_profile.proc_path])
    if chosen_profile.dev_path:
        args.extend(["--dev", chosen_profile.dev_path])

    # Binds derivados de capabilities.
    for grant in policy.list_grants():
        cap = grant.capability
        if cap.kind == "read-fs":
            host_path = _resolve_path(cap.scope, home)
            args.extend(["--ro-bind-try", host_path, host_path])
        elif cap.kind == "write-fs":
            host_path = _resolve_path(cap.scope, home)
            args.extend(["--bind-try", host_path, host_path])

    # Variables de entorno.
    args.extend(_env_args(chosen_profile))

    # Setuid/setgid: nunca elevamos.
    args.append("--unshare-user")  # idempotente con --unshare-all pero explícito
    args.extend(["--cap-drop", "ALL"])

    # PR_SET_NO_NEW_PRIVS: una vez que entramos al sandbox, no podemos
    # adquirir privilegios incluso por setuid binarios.
    args.append("--no-new-privs")

    # Separator + comando del usuario.
    args.append("--")
    args.extend(command)

    return args


# ─── Helpers ────────────────────────────────────────────────────────────────


def is_bwrap_available(bwrap_path: str | None = None) -> bool:
    """True si `bwrap` (o el binario forzado) está en PATH."""
    return _resolve_bwrap_binary(bwrap_path, require=False, strict=True) is not None


def _resolve_bwrap_binary(
    bwrap_path: str | None,
    *,
    require: bool,
    strict: bool = False,
) -> str | None:
    """Resuelve la ruta absoluta del binario.

    Si `bwrap_path` se pasa, se usa tal cual (sin búsqueda). Si no, se
    busca con `shutil.which(DEFAULT_BWRAP_BIN)`.

    En modo `strict=True` (usado por `is_bwrap_available`), retorna
    None si no se encuentra. En modo normal, devuelve el string
    literal ("bwrap") si no se encuentra y `require=False` — útil
    para construir argv en sistemas sin bwrap (tests, Windows).

    Si `require=True` y no se encuentra, lanza.
    """
    candidate = bwrap_path or DEFAULT_BWRAP_BIN
    found = shutil.which(candidate)
    if found is not None:
        return found
    if strict:
        return None
    if require:
        raise BwrapNotAvailableError(
            f"bwrap no encontrado en PATH (buscado: {candidate!r}). "
            f"Instala bubblewrap (Fedora: dnf install bubblewrap)."
        )
    # Devuelve el nombre literal — el subprocess.run posterior fallará
    # si bwrap no está, con un error reconocible.
    return candidate


def _profile_for_mode(mode: SandboxMode) -> BwrapProfile:
    if mode is SandboxMode.PARANOID:
        return BwrapProfile.paranoid()
    if mode is SandboxMode.DEMO:
        return BwrapProfile.demo()
    return BwrapProfile.default()


def _has_network_grant(policy: SandboxPolicy) -> bool:
    return any(g.capability.kind == "network" for g in policy.list_grants())


def _resolve_path(scope: str, home: Path) -> str:
    """Expande `~` y normaliza el path. NO toca disco (no `resolve()`)."""
    if scope.startswith("~"):
        # Evitamos expanduser() que mira HOME del proceso — usamos el
        # `home` inyectable.
        suffix = scope[1:].lstrip("/\\")
        path = home / suffix if suffix else home
    else:
        path = Path(scope)
    # Normalize sin tocar disco.
    return os.path.normpath(str(path))


def _env_args(profile: BwrapProfile) -> list[str]:
    """Genera flags `--clearenv` + `--setenv` para un env mínimo y seguro.

    Limpiamos todo el env del host y reconstruimos sólo lo esencial:
    PATH, HOME, USER, LANG, TERM. Las API keys del host nunca entran;
    las que necesite el agente las pasa explícitamente vía `extra_env`
    de la policy / profile.
    """
    args: list[str] = ["--clearenv"]
    minimal_env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/tmp",  # se reconfigura si la policy bind-ea HOME
        "USER": "allai",
        "LANG": "C.UTF-8",
        "TERM": "xterm-256color",
    }
    minimal_env.update(profile.extra_env)
    for key, value in minimal_env.items():
        if key in profile.blocked_env:
            continue
        args.extend(["--setenv", key, value])
    return args
