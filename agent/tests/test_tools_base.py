"""Tests de los tipos base."""

from __future__ import annotations

from tools.base import RiskLevel, ToolResult


def test_risk_level_values() -> None:
    assert RiskLevel.SAFE.value == "safe"
    assert RiskLevel.CONFIRM.value == "confirm"
    assert RiskLevel.DANGEROUS.value == "dangerous"


def test_tool_result_to_blocks_text_only() -> None:
    result = ToolResult(output="hola")
    blocks = result.to_blocks()
    assert len(blocks) == 1
    assert blocks[0].text == "hola"  # type: ignore[union-attr]


def test_tool_result_to_blocks_with_images() -> None:
    result = ToolResult(output="screenshot", images=[b"\x89PNG"])
    blocks = result.to_blocks()
    assert len(blocks) == 2


def test_tool_result_to_blocks_empty_when_no_output() -> None:
    result = ToolResult()
    assert result.to_blocks() == []


def test_tool_result_defaults() -> None:
    result = ToolResult()
    assert result.is_error is False
    assert result.images == []
    assert result.structured is None
