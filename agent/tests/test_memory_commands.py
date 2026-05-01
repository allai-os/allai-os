"""Tests de memory.commands — parser de comandos en lenguaje natural."""

from __future__ import annotations

from memory.commands import (
    ClearCommand,
    CommandKind,
    ExportCommand,
    ForgetCommand,
    QueryCommand,
    RememberCommand,
    is_memory_command,
    parse,
)


# ─── RememberCommand ──────────────────────────────────────────────────────────

def test_remember_spanish_basic() -> None:
    cmd = parse("recuerda que mi nombre es Juan")
    assert isinstance(cmd, RememberCommand)
    assert "Juan" in cmd.content


def test_remember_spanish_without_que() -> None:
    cmd = parse("recuerda mi número favorito es 7")
    assert isinstance(cmd, RememberCommand)
    assert "7" in cmd.content


def test_remember_spanish_guarda() -> None:
    cmd = parse("guarda que uso Fedora")
    assert isinstance(cmd, RememberCommand)
    assert "Fedora" in cmd.content


def test_remember_spanish_anota() -> None:
    cmd = parse("anota que el proyecto se llama allAI OS")
    assert isinstance(cmd, RememberCommand)
    assert "allAI OS" in cmd.content


def test_remember_spanish_nota() -> None:
    cmd = parse("nota: el usuario prefiere Python")
    assert isinstance(cmd, RememberCommand)
    assert "Python" in cmd.content


def test_remember_english_basic() -> None:
    cmd = parse("remember that my name is Juan")
    assert isinstance(cmd, RememberCommand)
    assert "Juan" in cmd.content


def test_remember_english_without_that() -> None:
    cmd = parse("remember I use Linux")
    assert isinstance(cmd, RememberCommand)
    assert "Linux" in cmd.content


def test_remember_english_keep_in_mind() -> None:
    cmd = parse("keep in mind that I prefer dark mode")
    assert isinstance(cmd, RememberCommand)
    assert "dark mode" in cmd.content


def test_remember_english_note() -> None:
    cmd = parse("note: user prefers vim")
    assert isinstance(cmd, RememberCommand)


def test_remember_kind_is_remember() -> None:
    cmd = parse("recuerda que uso neovim")
    assert cmd is not None
    assert cmd.kind == CommandKind.REMEMBER


# ─── ForgetCommand ────────────────────────────────────────────────────────────

def test_forget_spanish_basic() -> None:
    cmd = parse("olvida mi dirección")
    assert isinstance(cmd, ForgetCommand)
    assert "dirección" in cmd.topic


def test_forget_spanish_borra() -> None:
    cmd = parse("borra mi email de tu memoria")
    assert isinstance(cmd, ForgetCommand)
    assert "email" in cmd.topic


def test_forget_english_basic() -> None:
    cmd = parse("forget my phone number")
    assert isinstance(cmd, ForgetCommand)
    assert "phone number" in cmd.topic


def test_forget_english_delete() -> None:
    cmd = parse("delete from memory my address")
    assert isinstance(cmd, ForgetCommand)


def test_forget_kind_is_forget() -> None:
    cmd = parse("olvida mi nombre")
    assert cmd is not None
    assert cmd.kind == CommandKind.FORGET


# ─── QueryCommand ─────────────────────────────────────────────────────────────

def test_query_spanish_basic() -> None:
    cmd = parse("qué sabes de mí")
    assert isinstance(cmd, QueryCommand)


def test_query_spanish_recuerdas() -> None:
    cmd = parse("qué recuerdas de Python")
    assert isinstance(cmd, QueryCommand)


def test_query_spanish_muestra() -> None:
    cmd = parse("muéstrame la memoria")
    assert isinstance(cmd, QueryCommand)


def test_query_spanish_lista() -> None:
    cmd = parse("lista la memoria")
    assert isinstance(cmd, QueryCommand)


def test_query_english_basic() -> None:
    cmd = parse("what do you know about me")
    assert isinstance(cmd, QueryCommand)


def test_query_english_show() -> None:
    cmd = parse("show me your memory")
    assert isinstance(cmd, QueryCommand)


def test_query_english_list() -> None:
    cmd = parse("list my memories")
    assert isinstance(cmd, QueryCommand)


def test_query_kind_is_query() -> None:
    cmd = parse("qué sabes de mí")
    assert cmd is not None
    assert cmd.kind == CommandKind.QUERY


# ─── ExportCommand ────────────────────────────────────────────────────────────

def test_export_spanish() -> None:
    cmd = parse("exportar la memoria")
    assert isinstance(cmd, ExportCommand)
    assert cmd.kind == CommandKind.EXPORT


def test_export_english() -> None:
    cmd = parse("export my memory")
    assert isinstance(cmd, ExportCommand)


# ─── ClearCommand ─────────────────────────────────────────────────────────────

def test_clear_spanish() -> None:
    cmd = parse("borra la memoria")
    assert isinstance(cmd, ClearCommand)
    assert cmd.kind == CommandKind.CLEAR


def test_clear_spanish_limpia() -> None:
    cmd = parse("limpia la memoria")
    assert isinstance(cmd, ClearCommand)


def test_clear_english() -> None:
    cmd = parse("clear all my memory")
    assert isinstance(cmd, ClearCommand)


def test_clear_english_wipe() -> None:
    cmd = parse("wipe my memories")
    assert isinstance(cmd, ClearCommand)


# ─── Sin comando ──────────────────────────────────────────────────────────────

def test_no_command_returns_none() -> None:
    assert parse("hola, ¿cómo estás?") is None


def test_no_command_question() -> None:
    assert parse("qué hora es?") is None


def test_no_command_empty() -> None:
    assert parse("") is None


def test_no_command_whitespace() -> None:
    assert parse("   ") is None


# ─── is_memory_command() ──────────────────────────────────────────────────────

def test_is_memory_command_true() -> None:
    assert is_memory_command("recuerda que uso Python") is True


def test_is_memory_command_false() -> None:
    assert is_memory_command("abre Firefox") is False
