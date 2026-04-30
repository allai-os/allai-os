"""Validación y aplicación de permisos POSIX para archivos de memoria.

La política es estricta:
  - Directorios de memoria: 0700 (sólo el dueño puede leer/escribir/listar).
  - Archivos de memoria (DB, salt, audit log): 0600 (sólo el dueño).

Si al ABRIR un archivo detectamos permisos laxos (group/other con cualquier
bit), `validate_file_perms` lanza `InsecurePermissionsError` y refusamos
operar. Esto previene que un atacante con acceso al sistema multiusuario
modifique los archivos sin que lo notemos, y obliga al usuario a corregir
permisos antes de que la memoria se exponga.

En Windows POSIX modes no aplican: la protección viene del ACL NTFS
heredado del directorio del usuario. En esa plataforma:
  - `ensure_*` aplica `os.chmod` best-effort (sólo afecta el bit
    read-only en Windows) pero no lanza si falla.
  - `validate_*` retorna sin error (confiamos en el ACL del SO). Esto
    es una concesión documentada: el modelo de amenaza primario es
    Linux Fedora; soporte Windows es secundario.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

DIR_MODE = 0o700
"""Modo POSIX para directorios de memoria — sólo dueño rwx."""

FILE_MODE = 0o600
"""Modo POSIX para archivos de memoria — sólo dueño rw."""

_POSIX_FORBIDDEN_BITS = (
    stat.S_IRWXG  # group rwx
    | stat.S_IRWXO  # other rwx
)
"""Cualquier bit de group u other prendido es motivo de rechazo."""


class InsecurePermissionsError(OSError):
    """Los permisos de un archivo/directorio de memoria son demasiado laxos."""


# ─── Aplicación de permisos ──────────────────────────────────────────────────


def ensure_dir(path: Path, *, mode: int = DIR_MODE) -> None:
    """Crea `path` (incluyendo padres) y aplica `mode` en POSIX.

    Idempotente — si ya existe, sólo re-aplica el modo (en POSIX).
    """
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        os.chmod(path, mode)


def ensure_file_perms(path: Path, *, mode: int = FILE_MODE) -> None:
    """Aplica `mode` al archivo existente.

    Raises:
      FileNotFoundError: si `path` no existe.
    """
    if not path.exists():
        raise FileNotFoundError(f"no existe: {path}")
    if os.name == "posix":
        os.chmod(path, mode)


# ─── Validación ──────────────────────────────────────────────────────────────


def validate_dir_perms(path: Path, *, expected: int = DIR_MODE) -> None:
    """Lanza `InsecurePermissionsError` si los permisos del dir son laxos.

    En Windows retorna sin error (la protección depende del ACL NTFS).
    """
    _validate_perms(path, expected, kind="directorio", must_be_dir=True)


def validate_file_perms(path: Path, *, expected: int = FILE_MODE) -> None:
    """Lanza `InsecurePermissionsError` si los permisos del archivo son laxos."""
    _validate_perms(path, expected, kind="archivo", must_be_dir=False)


def is_world_or_group_accessible(path: Path) -> bool:
    """True si group u other tiene cualquier bit prendido (POSIX).

    En Windows retorna False (no aplicable).
    """
    if os.name != "posix":
        return False
    if not path.exists():
        return False
    mode = stat.S_IMODE(path.stat().st_mode)
    return bool(mode & _POSIX_FORBIDDEN_BITS)


# ─── Helpers internos ────────────────────────────────────────────────────────


def _validate_perms(
    path: Path,
    expected: int,
    *,
    kind: str,
    must_be_dir: bool,
) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{kind} no existe: {path}")
    if must_be_dir and not path.is_dir():
        raise InsecurePermissionsError(f"{path} no es un directorio")
    if not must_be_dir and not path.is_file():
        raise InsecurePermissionsError(f"{path} no es un archivo regular")

    if os.name != "posix":
        return  # Windows: depende del ACL del SO, no validamos aquí.

    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & _POSIX_FORBIDDEN_BITS:
        raise InsecurePermissionsError(
            f"{kind} {path} tiene permisos laxos: 0o{mode:o} "
            f"(esperado 0o{expected:o}). Corrige con: chmod {expected:o} {path}"
        )
    # También rechazamos cualquier bit del dueño que exceda lo esperado
    # (defensivo — actualmente DIR_MODE/FILE_MODE no incluyen 'x' en archivos
    # ni nada raro).
    if mode & ~expected & ~_POSIX_FORBIDDEN_BITS:
        raise InsecurePermissionsError(
            f"{kind} {path} tiene permisos inesperados: 0o{mode:o} "
            f"(esperado 0o{expected:o})"
        )
