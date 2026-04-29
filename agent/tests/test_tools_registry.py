"""Tests del ToolRegistry."""

from __future__ import annotations

import pytest

from tools.base import RiskLevel, ToolDefinition, ToolNotFoundError, ToolResult
from tools.registry import ToolRegistry


def _stub(**kwargs):  # type: ignore[no-untyped-def, ARG001]
    return ToolResult(output="ok")


def _def(name: str, risk: RiskLevel = RiskLevel.SAFE, category: str = "misc") -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"stub {name}",
        input_schema={"type": "object", "properties": {}, "required": []},
        risk=risk,
        executor=_stub,
        category=category,
    )


def test_register_and_get() -> None:
    r = ToolRegistry()
    r.register(_def("a"))
    assert r.has("a")
    assert r.get("a").name == "a"


def test_register_duplicate_raises() -> None:
    r = ToolRegistry()
    r.register(_def("a"))
    with pytest.raises(ValueError, match="ya registrado"):
        r.register(_def("a"))


def test_replace_overrides() -> None:
    r = ToolRegistry()
    r.register(_def("a"))
    r.replace(_def("a", risk=RiskLevel.DANGEROUS))
    assert r.get("a").risk is RiskLevel.DANGEROUS


def test_get_missing_raises() -> None:
    r = ToolRegistry()
    with pytest.raises(ToolNotFoundError):
        r.get("nope")


def test_names_sorted() -> None:
    r = ToolRegistry()
    for n in ["c", "a", "b"]:
        r.register(_def(n))
    assert r.names() == ["a", "b", "c"]


def test_by_risk_filters() -> None:
    r = ToolRegistry()
    r.register(_def("a", risk=RiskLevel.SAFE))
    r.register(_def("b", risk=RiskLevel.DANGEROUS))
    r.register(_def("c", risk=RiskLevel.CONFIRM))

    safes = r.by_risk(RiskLevel.SAFE)
    assert [t.name for t in safes] == ["a"]

    risky = r.by_risk(RiskLevel.CONFIRM, RiskLevel.DANGEROUS)
    assert {t.name for t in risky} == {"b", "c"}


def test_by_category_filters() -> None:
    r = ToolRegistry()
    r.register(_def("a", category="screen"))
    r.register(_def("b", category="input"))
    assert [t.name for t in r.by_category("screen")] == ["a"]


def test_to_provider_tools() -> None:
    r = ToolRegistry()
    r.register(_def("a"))
    r.register(_def("b"))
    tools = r.to_provider_tools()
    assert len(tools) == 2
    assert {t.name for t in tools} == {"a", "b"}


def test_to_provider_tools_filtered() -> None:
    r = ToolRegistry()
    r.register(_def("a"))
    r.register(_def("b"))
    tools = r.to_provider_tools(only=["a"])
    assert len(tools) == 1
    assert tools[0].name == "a"


def test_unregister_and_clear() -> None:
    r = ToolRegistry()
    r.register(_def("a"))
    r.unregister("a")
    assert not r.has("a")
    r.register(_def("b"))
    r.clear()
    assert len(r) == 0
