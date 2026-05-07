"""Generador de filtros seccomp BPF para procesos del agente.

Este módulo construye una representación pura de un filtro seccomp
(`SeccompFilter`) que el caller puede:

  - Inspeccionar / testear sin tocar `pyseccomp`.
  - Compilar a un `pyseccomp.SyscallFilter` real con `compile()` (Linux).
  - Exportar a BPF binario con `to_bpf_bytes()` para alimentar a
    `bwrap --seccomp <fd>`.

Política (security-first):

- **Whitelist, no blacklist**. Empezamos con `KILL_PROCESS` como acción
  default y agregamos sólo las ~80 syscalls que un proceso Python típico
  necesita. Una syscall no listada mata el proceso. Esto es más
  estricto que el seccomp típico de flatpak (que usa `EPERM` y deja
  que el proceso se reintente o degrade).

- **Default action `KILL_PROCESS`** (no `KILL_THREAD`, no `ERRNO`).
  Razón: un thread killed deja al resto del proceso en estado
  inconsistente; un `EPERM` puede ser interpretado por el atacante
  como "intenta otra cosa". Matar todo el proceso ante una syscall
  inesperada es la respuesta menos ambigua.

- **Network syscalls condicionales por capability**. Si la policy
  no tiene una grant `network:*`, las syscalls `socket`, `connect`,
  `bind`, etc. están fuera de la whitelist. Defensa en profundidad
  con `bwrap --unshare-all` (que ya bloquea network namespace).

- **Sin `ptrace`, `bpf`, `kexec_load`, `init_module`, `delete_module`,
  `mount`, `umount2`, `pivot_root`, `swapon`/`swapoff`, `reboot`,
  `clock_settime`, `settimeofday`** — todas peligrosas y nunca
  necesarias para el agente. NO se incluyen ni siquiera con grant.

- **`execve` permitido** (Python lo necesita para subprocess.run con
  shell tools). El containment del path lo hace `bwrap` con sus
  binds; aquí no filtramos por path porque seccomp no inspecciona
  strings de userspace de forma segura.

- **`ioctl` permitido sin filtrar argumentos** por ahora. TODO:
  filtrar `TCGETS`/`TCSETS` y bloquear `KDSETMODE`, `TIOCSTI` (que
  permite escribir al TTY de otros procesos). Esto requiere
  `seccomp_rule_add_array` con argumentos y se deja para una
  iteración futura documentada en threat-model.md.

Lo que NO hace este módulo:

- No carga pyseccomp eagerly — sólo cuando `compile()` se llama. Esto
  permite que el resto del proyecto importe el módulo en Windows.
- No ejecuta el filtro. El caller pasa el output a bwrap o lo aplica
  con `seccomp_load()` desde Python (no recomendado — bwrap lo hace
  antes del execve del comando, justo como queremos).
- No filtra por arquitectura más allá de la nativa. Si la imagen
  futura corre x86_64 + aarch64, ampliamos.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Final

from sandbox.policy import SandboxMode, SandboxPolicy

# ─── Constantes ─────────────────────────────────────────────────────────────


# Acciones seccomp soportadas. La acción default del filtro debe ser
# una de estas. `KILL_PROCESS` es la más estricta y la que usamos
# por default para syscalls fuera de la whitelist.
SECCOMP_ACTION_KILL_PROCESS: Final[str] = "KILL_PROCESS"
SECCOMP_ACTION_KILL_THREAD: Final[str] = "KILL_THREAD"
SECCOMP_ACTION_ERRNO: Final[str] = "ERRNO"
SECCOMP_ACTION_TRAP: Final[str] = "TRAP"
SECCOMP_ACTION_LOG: Final[str] = "LOG"
SECCOMP_ACTION_ALLOW: Final[str] = "ALLOW"

_VALID_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        SECCOMP_ACTION_KILL_PROCESS,
        SECCOMP_ACTION_KILL_THREAD,
        SECCOMP_ACTION_ERRNO,
        SECCOMP_ACTION_TRAP,
        SECCOMP_ACTION_LOG,
        SECCOMP_ACTION_ALLOW,
    }
)

ARCH_NATIVE: Final[str] = "native"
ARCH_X86_64: Final[str] = "x86_64"
ARCH_AARCH64: Final[str] = "aarch64"

_SUPPORTED_ARCHS: Final[frozenset[str]] = frozenset(
    {ARCH_NATIVE, ARCH_X86_64, ARCH_AARCH64}
)


# Whitelist mínima para procesos Python típicos. Cubre I/O, memoria,
# threads, signals, time, identity. Excluye explícitamente network y
# ejecuciones privilegiadas — esas se gating por capability.
#
# La lista se mantiene **ordenada y deduplicada** para que dos llamadas
# con el mismo input produzcan el mismo SeccompFilter (importante para
# audit logging y reproducibilidad).
DEFAULT_BASE_SYSCALLS: Final[frozenset[str]] = frozenset(
    {
        # I/O básico
        "read",
        "write",
        "readv",
        "writev",
        "pread64",
        "pwrite64",
        "open",
        "openat",
        "openat2",
        "close",
        "close_range",
        "lseek",
        "fstat",
        "stat",
        "lstat",
        "newfstatat",
        "statx",
        "fcntl",
        "fadvise64",
        "fdatasync",
        "fsync",
        "ftruncate",
        "truncate",
        "readlink",
        "readlinkat",
        "access",
        "faccessat",
        "faccessat2",
        # Memoria
        "mmap",
        "munmap",
        "mprotect",
        "brk",
        "madvise",
        "mremap",
        "mlock",
        "munlock",
        # Procesos / threads
        "clone",
        "clone3",
        "fork",
        "vfork",
        "execve",
        "execveat",
        "exit",
        "exit_group",
        "wait4",
        "waitid",
        "kill",
        "tkill",
        "tgkill",
        "getpid",
        "getppid",
        "gettid",
        "set_tid_address",
        "set_robust_list",
        "get_robust_list",
        # Scheduling
        "sched_yield",
        "sched_getaffinity",
        "sched_setaffinity",
        "sched_getparam",
        "sched_getscheduler",
        # Tiempo
        "clock_gettime",
        "clock_getres",
        "clock_nanosleep",
        "gettimeofday",
        "nanosleep",
        "time",
        # Filesystem ops
        "getcwd",
        "chdir",
        "fchdir",
        "mkdir",
        "mkdirat",
        "rmdir",
        "rename",
        "renameat",
        "renameat2",
        "unlink",
        "unlinkat",
        "link",
        "linkat",
        "symlink",
        "symlinkat",
        "getdents",
        "getdents64",
        "umask",
        "chmod",
        "fchmod",
        "fchmodat",
        # Pipes / redirección
        "pipe",
        "pipe2",
        "dup",
        "dup2",
        "dup3",
        # Polling / eventfd
        "poll",
        "ppoll",
        "select",
        "pselect6",
        "epoll_create",
        "epoll_create1",
        "epoll_ctl",
        "epoll_wait",
        "epoll_pwait",
        "eventfd",
        "eventfd2",
        "signalfd",
        "signalfd4",
        # Signals
        "rt_sigaction",
        "rt_sigprocmask",
        "rt_sigreturn",
        "rt_sigtimedwait",
        "rt_sigsuspend",
        "rt_sigpending",
        "rt_sigqueueinfo",
        "rt_tgsigqueueinfo",
        "sigaltstack",
        # Random
        "getrandom",
        # Identity
        "getuid",
        "geteuid",
        "getgid",
        "getegid",
        "getgroups",
        "getresuid",
        "getresgid",
        "getsid",
        "getpgid",
        "getpgrp",
        # Misc seguros
        "prctl",
        "arch_prctl",
        "uname",
        "sysinfo",
        "getrlimit",
        "prlimit64",
        "ioctl",  # TODO: filter args (TCGETS ok, TIOCSTI bloquear)
        "memfd_create",
    }
)


# Syscalls relacionadas con red. Sólo se incluyen si la policy tiene
# una grant `network:*` activa.
NETWORK_SYSCALLS: Final[frozenset[str]] = frozenset(
    {
        "socket",
        "socketpair",
        "connect",
        "bind",
        "listen",
        "accept",
        "accept4",
        "shutdown",
        "sendto",
        "sendmsg",
        "sendmmsg",
        "recvfrom",
        "recvmsg",
        "recvmmsg",
        "getsockname",
        "getpeername",
        "getsockopt",
        "setsockopt",
    }
)


# Syscalls **siempre** prohibidas — no entran a la whitelist ni con
# capabilities concedidas. Listadas para documentar intent y para
# verificación en tests.
ALWAYS_DENIED_SYSCALLS: Final[frozenset[str]] = frozenset(
    {
        # Privilege escalation / kernel manipulation
        "ptrace",
        "process_vm_readv",
        "process_vm_writev",
        "kcmp",
        "bpf",
        "kexec_load",
        "kexec_file_load",
        "init_module",
        "finit_module",
        "delete_module",
        "create_module",
        "query_module",
        # Mount / namespace manipulation que no quiero permitir
        # incluso dentro del namespace
        "mount",
        "umount",
        "umount2",
        "pivot_root",
        "chroot",
        "swapon",
        "swapoff",
        # Tiempo del sistema
        "settimeofday",
        "clock_settime",
        "clock_adjtime",
        "adjtimex",
        # Hardware / boot
        "reboot",
        "iopl",
        "ioperm",
        "vhangup",
        # Debugging / tracing avanzado
        "perf_event_open",
        "uselib",
        # Quotas / accounting
        "quotactl",
        "acct",
        # Module/key management
        "add_key",
        "request_key",
        "keyctl",
        # Personality changes (puede deshabilitar ASLR)
        "personality",
        # Capabilities
        "capset",
    }
)


# ─── Errores ────────────────────────────────────────────────────────────────


class SeccompError(Exception):
    """Error general del módulo seccomp."""


class SeccompUnavailableError(SeccompError):
    """`pyseccomp` no está instalado o no es importable.

    Esperado en Windows / macOS / sistemas sin libseccomp. Los tests
    usan import gates idénticos al patrón de sqlcipher3.
    """


# ─── Profile ────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SeccompProfile:
    """Configuración base del filtro seccomp.

    `whitelist` es el set de syscalls permitidas BASE — antes de que
    `build_filter` añada las condicionales por capability. La acción
    default es lo que ocurre cuando una syscall no listada es invocada.

    `arch` es la arquitectura objetivo. `native` resuelve a la del
    host en `compile()`. Para cross-compile (raro en allAI), se puede
    forzar `x86_64` o `aarch64`.
    """

    base_whitelist: frozenset[str] = field(default_factory=lambda: DEFAULT_BASE_SYSCALLS)
    default_action: str = SECCOMP_ACTION_KILL_PROCESS
    arch: str = ARCH_NATIVE

    def __post_init__(self) -> None:
        if self.default_action not in _VALID_ACTIONS:
            raise SeccompError(
                f"default_action inválido: {self.default_action!r}. "
                f"Válidos: {sorted(_VALID_ACTIONS)}"
            )
        if self.arch not in _SUPPORTED_ARCHS:
            raise SeccompError(
                f"arch no soportada: {self.arch!r}. Soportadas: {sorted(_SUPPORTED_ARCHS)}"
            )
        # No permitimos solapamiento con ALWAYS_DENIED — proteger contra
        # un bug futuro que añada accidentalmente una syscall peligrosa
        # a la whitelist.
        overlap = self.base_whitelist & ALWAYS_DENIED_SYSCALLS
        if overlap:
            raise SeccompError(
                f"base_whitelist incluye syscalls always-denied: {sorted(overlap)}"
            )

    @classmethod
    def default(cls) -> "SeccompProfile":
        """Profile estándar para modo `normal`."""
        return cls()

    @classmethod
    def paranoid(cls) -> "SeccompProfile":
        """Profile más estricto: quita syscalls que el agente típico no
        usa pero que podrían facilitar exploits.
        """
        # Quita kill, tkill, tgkill (un proceso paranoid no envía señales
        # arbitrarias), execve/execveat (no debería re-exec si está bien
        # confinado), set/get scheduler.
        more_strict = DEFAULT_BASE_SYSCALLS - {
            "kill",
            "tkill",
            "tgkill",
            "execve",
            "execveat",
            "sched_setaffinity",
            "sched_setparam",
            "sched_setscheduler",
            "personality",
        }
        return cls(base_whitelist=frozenset(more_strict))


# ─── Filter (representación pura) ───────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SeccompFilter:
    """Representación inmutable del filtro seccomp generado.

    Es 100% inspectable sin pyseccomp — ideal para tests y audit logs.
    `compile()` produce un objeto `pyseccomp.SyscallFilter` real
    (Linux). `to_bpf_bytes()` exporta el programa BPF para
    `bwrap --seccomp <fd>` o uso similar.

    `allowed_syscalls` está ordenado lexicográficamente para
    determinismo: dos llamadas a `build_filter` con la misma policy
    producen el mismo filtro byte-por-byte (modulo cambios de
    arquitectura).
    """

    allowed_syscalls: tuple[str, ...]
    default_action: str
    arch: str

    def compile(self) -> Any:
        """Compila a `pyseccomp.SyscallFilter`. Lanza si no está disponible.

        En Linux con `pyseccomp` instalado:
          1. Crea SyscallFilter con default_action.
          2. Añade ALLOW para cada syscall en allowed_syscalls.
          3. Devuelve el filter listo para load() o export_pfc()/export_bpf().

        Raises:
          SeccompUnavailableError: pyseccomp no instalado.
          SeccompError: alguna syscall no se reconoce en la libseccomp local.
        """
        seccomp = _import_pyseccomp()
        action_const = _resolve_action_constant(seccomp, self.default_action)
        try:
            f = seccomp.SyscallFilter(action_const)
        except Exception as exc:  # noqa: BLE001 - traducimos a nuestra jerarquía
            raise SeccompError(f"no se pudo crear SyscallFilter: {exc}") from exc

        if self.arch != ARCH_NATIVE:
            try:
                arch_const = _resolve_arch_constant(seccomp, self.arch)
                f.add_arch(arch_const)
            except Exception as exc:  # noqa: BLE001
                raise SeccompError(
                    f"arch {self.arch!r} no soportada por pyseccomp local: {exc}"
                ) from exc

        allow_const = _resolve_action_constant(seccomp, SECCOMP_ACTION_ALLOW)
        for syscall in self.allowed_syscalls:
            try:
                f.add_rule(allow_const, syscall)
            except Exception as exc:  # noqa: BLE001
                raise SeccompError(
                    f"syscall {syscall!r} no reconocida por libseccomp: {exc}"
                ) from exc
        return f

    def to_bpf_bytes(self) -> bytes:
        """Exporta el programa BPF como bytes (Linux con pyseccomp).

        Útil para escribir a un fd y pasarlo a `bwrap --seccomp <fd>`.
        Lanza `SeccompUnavailableError` si pyseccomp no está.
        """
        compiled = self.compile()
        # pyseccomp expone `export_bpf(file)` que escribe a un file-like.
        import io

        buf = io.BytesIO()
        compiled.export_bpf(buf)
        return buf.getvalue()


# ─── Constructor principal ──────────────────────────────────────────────────


def build_filter(
    policy: SandboxPolicy,
    *,
    profile: SeccompProfile | None = None,
) -> SeccompFilter:
    """Construye un `SeccompFilter` para la `policy` actual.

    Pasos:
      1. Resuelve profile (explícito > derivado del modo).
      2. Toma la base whitelist del profile.
      3. Añade NETWORK_SYSCALLS si la policy tiene grant network:* y
         el modo no es DEMO.
      4. Aplica el invariante de que ninguna syscall ALWAYS_DENIED
         entre por error (sanity check).

    El resultado es un `SeccompFilter` con allowed_syscalls ordenadas
    para determinismo.
    """
    chosen = profile or _profile_for_mode(policy.mode)

    allowed: set[str] = set(chosen.base_whitelist)

    if policy.mode is not SandboxMode.DEMO and _has_network_grant(policy):
        allowed.update(NETWORK_SYSCALLS)

    # Sanity: nunca dejes pasar always-denied, aunque la lógica anterior
    # debería haberlo evitado.
    allowed -= ALWAYS_DENIED_SYSCALLS

    return SeccompFilter(
        allowed_syscalls=tuple(sorted(allowed)),
        default_action=chosen.default_action,
        arch=chosen.arch,
    )


# ─── Disponibilidad ─────────────────────────────────────────────────────────


def is_seccomp_available() -> bool:
    """True si `pyseccomp` se puede importar en este entorno.

    En Windows/macOS sin libseccomp, retorna False sin levantar.
    """
    if os.name != "posix":
        return False
    try:
        _import_pyseccomp()
    except SeccompUnavailableError:
        return False
    return True


# ─── Internals ──────────────────────────────────────────────────────────────


def _import_pyseccomp() -> Any:
    """Import perezoso de `pyseccomp`.

    Lo hacemos lazy para que el módulo cargue en Windows / sistemas sin
    libseccomp — los tests unitarios de la representación pura no lo
    necesitan.
    """
    try:
        import pyseccomp  # type: ignore[import-not-found]
    except ImportError as exc:
        raise SeccompUnavailableError(
            "pyseccomp no está disponible. En Linux: "
            "`pip install pyseccomp` (requiere libseccomp-dev). "
            "En Windows/macOS los tests unitarios usan la representación "
            "pura sin compilar."
        ) from exc
    return pyseccomp


def _profile_for_mode(mode: SandboxMode) -> SeccompProfile:
    if mode is SandboxMode.PARANOID:
        return SeccompProfile.paranoid()
    if mode is SandboxMode.DEMO:
        # Demo dry-run: igual generamos un filtro, pero no se ejecutará.
        # Usamos paranoid como caja extra de defensa por si alguien
        # decide ejecutar el comando demo aún así.
        return SeccompProfile.paranoid()
    return SeccompProfile.default()


def _has_network_grant(policy: SandboxPolicy) -> bool:
    return any(g.capability.kind == "network" for g in policy.list_grants())


def _resolve_action_constant(seccomp: Any, name: str) -> Any:
    """Mapea nuestro string de acción al símbolo de pyseccomp."""
    mapping = {
        SECCOMP_ACTION_KILL_PROCESS: "KILL_PROCESS",
        SECCOMP_ACTION_KILL_THREAD: "KILL",
        SECCOMP_ACTION_ERRNO: "ERRNO",
        SECCOMP_ACTION_TRAP: "TRAP",
        SECCOMP_ACTION_LOG: "LOG",
        SECCOMP_ACTION_ALLOW: "ALLOW",
    }
    attr = mapping[name]
    return getattr(seccomp, attr)


def _resolve_arch_constant(seccomp: Any, arch: str) -> Any:
    """Mapea nuestra arch al símbolo de pyseccomp.Arch."""
    mapping = {
        ARCH_X86_64: "X86_64",
        ARCH_AARCH64: "AARCH64",
    }
    attr_name = mapping[arch]
    arch_module = getattr(seccomp, "Arch", None) or seccomp
    return getattr(arch_module, attr_name)
