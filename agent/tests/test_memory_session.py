"""Tests de memory.session — short-term in-memory store."""

from __future__ import annotations

import threading

import pytest

from memory.session import SessionMemory, SessionEntry


def test_add_returns_entry() -> None:
    s = SessionMemory()
    e = s.add("el usuario se llama Juan")
    assert isinstance(e, SessionEntry)
    assert e.content == "el usuario se llama Juan"
    assert e.kind == "fact"


def test_add_default_kind_is_fact() -> None:
    s = SessionMemory()
    e = s.add("algo")
    assert e.kind == "fact"


def test_add_explicit_kind() -> None:
    s = SessionMemory()
    e = s.add("hola", kind="message")
    assert e.kind == "message"


def test_add_strips_whitespace() -> None:
    s = SessionMemory()
    e = s.add("  dato  ")
    assert e.content == "dato"


def test_add_empty_raises() -> None:
    s = SessionMemory()
    with pytest.raises(ValueError):
        s.add("")


def test_add_whitespace_only_raises() -> None:
    s = SessionMemory()
    with pytest.raises(ValueError):
        s.add("   ")


def test_add_detects_pii_automatically() -> None:
    s = SessionMemory()
    e = s.add("mi correo es foo@example.com")
    assert e.sensitive is True


def test_add_clean_text_not_sensitive() -> None:
    s = SessionMemory()
    e = s.add("el tiempo estará soleado")
    assert e.sensitive is False


def test_add_sensitive_override() -> None:
    # El caller puede forzar sensitive=True sin PII
    s = SessionMemory()
    e = s.add("dato secreto", sensitive=True)
    assert e.sensitive is True


def test_size_increments() -> None:
    s = SessionMemory()
    assert s.size == 0
    s.add("a")
    s.add("b")
    assert s.size == 2


def test_max_entries_sliding_window() -> None:
    s = SessionMemory(max_entries=3)
    for i in range(5):
        s.add(f"entrada {i}")
    assert s.size == 3
    contents = [e.content for e in s.all()]
    assert contents == ["entrada 2", "entrada 3", "entrada 4"]


def test_max_entries_one_is_valid() -> None:
    s = SessionMemory(max_entries=1)
    s.add("a")
    s.add("b")
    assert s.size == 1
    assert s.all()[0].content == "b"


def test_max_entries_zero_raises() -> None:
    with pytest.raises(ValueError):
        SessionMemory(max_entries=0)


def test_all_returns_copy() -> None:
    s = SessionMemory()
    s.add("x")
    result = s.all()
    result.clear()
    assert s.size == 1  # la lista interna no se vio afectada


def test_all_exclude_sensitive() -> None:
    s = SessionMemory()
    s.add("dato limpio")
    s.add("mi email es a@b.com")
    clean = s.all(include_sensitive=False)
    assert len(clean) == 1
    assert clean[0].content == "dato limpio"


def test_recent_returns_last_n() -> None:
    s = SessionMemory()
    for i in range(10):
        s.add(f"e{i}")
    recent = s.recent(3)
    assert [e.content for e in recent] == ["e7", "e8", "e9"]


def test_by_kind_filters_correctly() -> None:
    s = SessionMemory()
    s.add("hecho", kind="fact")
    s.add("mensaje", kind="message")
    s.add("observación", kind="observation")
    facts = s.by_kind("fact")
    assert len(facts) == 1
    assert facts[0].content == "hecho"


def test_search_finds_substring() -> None:
    s = SessionMemory()
    s.add("el usuario prefiere Python")
    s.add("el usuario usa Linux")
    results = s.search("Python")
    assert len(results) == 1
    assert "Python" in results[0].content


def test_search_case_insensitive() -> None:
    s = SessionMemory()
    s.add("El Usuario Usa GNOME")
    assert len(s.search("gnome")) == 1


def test_search_excludes_sensitive_by_default_when_asked() -> None:
    s = SessionMemory()
    s.add("clave: password: supersecret123")
    s.add("dato limpio con password keyword check", sensitive=False)
    results = s.search("password", include_sensitive=False)
    # Solo la entrada forzada no-sensitive
    assert all(not e.sensitive for e in results)


def test_clear_removes_all() -> None:
    s = SessionMemory()
    s.add("a")
    s.add("b")
    count = s.clear()
    assert count == 2
    assert s.size == 0


def test_context_snippet_empty_session() -> None:
    s = SessionMemory()
    assert s.context_snippet() == ""


def test_context_snippet_format() -> None:
    s = SessionMemory()
    s.add("el usuario es Juan", kind="fact")
    snippet = s.context_snippet()
    assert "[fact]" in snippet
    assert "el usuario es Juan" in snippet


def test_context_snippet_excludes_sensitive_by_default() -> None:
    s = SessionMemory()
    s.add("dato limpio")
    s.add("foo@bar.com en el texto")  # detectado como sensible
    snippet = s.context_snippet(allow_sensitive=False)
    assert "foo@bar.com" not in snippet


def test_thread_safety() -> None:
    s = SessionMemory(max_entries=200)
    errors: list[Exception] = []

    def worker(n: int) -> None:
        try:
            for i in range(20):
                s.add(f"thread {n} entry {i}")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert s.size <= 200
