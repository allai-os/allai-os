"""Tests de los tools de filesystem (no requieren display ni red)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.fs import (
    _fs_delete,
    _fs_glob,
    _fs_list,
    _fs_read,
    _fs_write,
)


def test_fs_write_then_read(tmp_path: Path) -> None:
    target = tmp_path / "hello.txt"
    write = _fs_write(str(target), "hola allAI")
    assert not write.is_error
    assert target.read_text() == "hola allAI"

    read = _fs_read(str(target))
    assert not read.is_error
    assert "hola allAI" in read.output


def test_fs_write_creates_parent_dirs(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "sub" / "file.txt"
    result = _fs_write(str(target), "x")
    assert not result.is_error
    assert target.exists()


def test_fs_write_append(tmp_path: Path) -> None:
    target = tmp_path / "a.txt"
    _fs_write(str(target), "hola ")
    _fs_write(str(target), "mundo", append=True)
    assert target.read_text() == "hola mundo"


def test_fs_read_truncates_large_file(tmp_path: Path) -> None:
    target = tmp_path / "big.txt"
    target.write_text("a" * 100)
    result = _fs_read(str(target), max_bytes=10)
    assert "[truncado" in result.output
    assert result.structured is not None
    assert result.structured["truncated"] is True


def test_fs_read_binary(tmp_path: Path) -> None:
    target = tmp_path / "blob.bin"
    target.write_bytes(b"\x89PNG\x00\x01\xff")
    result = _fs_read(str(target))
    assert result.structured is not None
    assert result.structured["binary"] is True


def test_fs_read_missing(tmp_path: Path) -> None:
    result = _fs_read(str(tmp_path / "nope.txt"))
    assert result.is_error
    assert "no existe" in result.output


def test_fs_list_directory(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "b").mkdir()

    result = _fs_list(str(tmp_path))
    assert not result.is_error
    assert result.structured is not None
    names = {e["name"] for e in result.structured["entries"]}
    assert names == {"a.txt", "b"}


def test_fs_list_not_a_directory(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("x")
    result = _fs_list(str(target))
    assert result.is_error


def test_fs_glob(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("")
    (tmp_path / "b.py").write_text("")
    (tmp_path / "c.txt").write_text("")
    result = _fs_glob("*.py", str(tmp_path))
    assert not result.is_error
    assert result.structured is not None
    assert result.structured["count"] == 2


def test_fs_delete_file(tmp_path: Path) -> None:
    target = tmp_path / "trash.txt"
    target.write_text("x")
    result = _fs_delete(str(target))
    assert not result.is_error
    assert not target.exists()


def test_fs_delete_directory_refuses(tmp_path: Path) -> None:
    target = tmp_path / "dir"
    target.mkdir()
    result = _fs_delete(str(target))
    assert result.is_error
    assert target.exists()


@pytest.mark.parametrize(
    ("path",),
    [("~/notexists",), ("/nonexistent/whatever",)],
)
def test_fs_read_handles_nonexistent(path: str) -> None:
    result = _fs_read(path)
    assert result.is_error
