"""Tests del filtro destructivo de shell.run."""

from __future__ import annotations

import pytest

from tools.shell import _looks_destructive


@pytest.mark.parametrize(
    "cmd",
    [
        "rm -rf /",
        "rm -rf ~",
        "rm -fR /tmp",
        "sudo apt update",
        "git push --force",
        "git push -f origin main",
        "git reset --hard",
        "mkfs.ext4 /dev/sda1",
        "dd if=/dev/zero of=/dev/sda",
        "shutdown -h now",
        "reboot",
        ":(){ :|:& };:",
        "echo bad > /dev/sda",
    ],
)
def test_destructive_patterns_detected(cmd: str) -> None:
    assert _looks_destructive(cmd) is not None


@pytest.mark.parametrize(
    "cmd",
    [
        "ls -la",
        "echo hola",
        "git status",
        "git log --oneline -5",
        "python -c 'print(1)'",
        "cat /etc/os-release",
        "rm somefile.txt",  # rm sin -rf no es destructivo
    ],
)
def test_safe_commands_pass(cmd: str) -> None:
    assert _looks_destructive(cmd) is None
