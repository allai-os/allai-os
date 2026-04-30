"""Tests de memory.permissions.

En POSIX validamos chmod 0700/0600 estrictos. En Windows confiamos en el
ACL NTFS y los tests POSIX están marcados con `skipif`.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from memory.permissions import (
    DIR_MODE,
    FILE_MODE,
    InsecurePermissionsError,
    ensure_dir,
    ensure_file_perms,
    is_world_or_group_accessible,
    validate_dir_perms,
    validate_file_perms,
)


_POSIX_ONLY = pytest.mark.skipif(
    os.name != "posix", reason="permisos POSIX no aplican en Windows"
)


# ─── ensure_dir ──────────────────────────────────────────────────────────────


def test_ensure_dir_creates_path(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "deep" / "memory"
    ensure_dir(target)
    assert target.is_dir()


def test_ensure_dir_is_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "memory"
    ensure_dir(target)
    ensure_dir(target)  # no debe lanzar
    assert target.is_dir()


@_POSIX_ONLY
def test_ensure_dir_applies_0700(tmp_path: Path) -> None:
    target = tmp_path / "memory"
    ensure_dir(target)
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == DIR_MODE


@_POSIX_ONLY
def test_ensure_dir_corrects_lax_perms(tmp_path: Path) -> None:
    target = tmp_path / "memory"
    target.mkdir()
    os.chmod(target, 0o755)  # too lax
    ensure_dir(target)
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == DIR_MODE


# ─── ensure_file_perms ───────────────────────────────────────────────────────


def test_ensure_file_perms_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        ensure_file_perms(tmp_path / "ghost.txt")


@_POSIX_ONLY
def test_ensure_file_perms_applies_0600(tmp_path: Path) -> None:
    target = tmp_path / "secret.bin"
    target.write_bytes(b"x")
    os.chmod(target, 0o644)
    ensure_file_perms(target)
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == FILE_MODE


# ─── validate_dir_perms ──────────────────────────────────────────────────────


def test_validate_dir_perms_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        validate_dir_perms(tmp_path / "ghost")


def test_validate_dir_perms_not_a_directory(tmp_path: Path) -> None:
    f = tmp_path / "file.txt"
    f.write_text("x")
    with pytest.raises(InsecurePermissionsError, match="no es un directorio"):
        validate_dir_perms(f)


@_POSIX_ONLY
def test_validate_dir_perms_accepts_0700(tmp_path: Path) -> None:
    target = tmp_path / "memory"
    target.mkdir()
    os.chmod(target, 0o700)
    validate_dir_perms(target)  # no debe lanzar


@_POSIX_ONLY
@pytest.mark.parametrize("bad_mode", [0o755, 0o775, 0o777, 0o710, 0o701])
def test_validate_dir_perms_rejects_lax(tmp_path: Path, bad_mode: int) -> None:
    target = tmp_path / "memory"
    target.mkdir()
    os.chmod(target, bad_mode)
    with pytest.raises(InsecurePermissionsError):
        validate_dir_perms(target)


# ─── validate_file_perms ─────────────────────────────────────────────────────


def test_validate_file_perms_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        validate_file_perms(tmp_path / "ghost.bin")


def test_validate_file_perms_not_a_regular_file(tmp_path: Path) -> None:
    d = tmp_path / "dir"
    d.mkdir()
    with pytest.raises(InsecurePermissionsError, match="archivo regular"):
        validate_file_perms(d)


@_POSIX_ONLY
def test_validate_file_perms_accepts_0600(tmp_path: Path) -> None:
    target = tmp_path / "secret.bin"
    target.write_bytes(b"x")
    os.chmod(target, 0o600)
    validate_file_perms(target)  # no debe lanzar


@_POSIX_ONLY
@pytest.mark.parametrize("bad_mode", [0o644, 0o664, 0o666, 0o604, 0o640])
def test_validate_file_perms_rejects_lax(tmp_path: Path, bad_mode: int) -> None:
    target = tmp_path / "secret.bin"
    target.write_bytes(b"x")
    os.chmod(target, bad_mode)
    with pytest.raises(InsecurePermissionsError):
        validate_file_perms(target)


# ─── is_world_or_group_accessible ────────────────────────────────────────────


@_POSIX_ONLY
def test_world_or_group_accessible_true_for_lax(tmp_path: Path) -> None:
    target = tmp_path / "loose.bin"
    target.write_bytes(b"x")
    os.chmod(target, 0o644)
    assert is_world_or_group_accessible(target) is True


@_POSIX_ONLY
def test_world_or_group_accessible_false_for_strict(tmp_path: Path) -> None:
    target = tmp_path / "strict.bin"
    target.write_bytes(b"x")
    os.chmod(target, 0o600)
    assert is_world_or_group_accessible(target) is False


def test_world_or_group_accessible_returns_false_in_windows_or_missing(
    tmp_path: Path,
) -> None:
    """En Windows o si el archivo no existe, retorna False."""
    assert is_world_or_group_accessible(tmp_path / "no-existe") is False
