"""Tests del ToolExecutor: gates de capability, confirmación y validación."""

from __future__ import annotations

from typing import Any

import pytest

from core.messages import ToolUseBlock
from tools.base import RiskLevel, ToolDefinition, ToolResult
from tools.executor import (
    AllCapabilitiesGranted,
    AlwaysConfirm,
    GatePolicy,
    NeverConfirm,
    NoCapabilities,
    ToolExecutor,
)
from tools.registry import ToolRegistry


def _make_definition(
    *,
    risk: RiskLevel = RiskLevel.SAFE,
    capabilities: list[str] | None = None,
    schema: dict[str, Any] | None = None,
    raises: Exception | None = None,
):
    calls: list[dict[str, Any]] = []

    def executor(**kwargs: Any) -> ToolResult:
        calls.append(kwargs)
        if raises is not None:
            raise raises
        return ToolResult(output="executed")

    definition = ToolDefinition(
        name="t",
        description="stub",
        input_schema=schema or {"type": "object", "properties": {}, "required": []},
        risk=risk,
        executor=executor,
        capabilities_required=capabilities or [],
    )
    return definition, calls


def _executor_with(
    definition: ToolDefinition,
    *,
    confirmer: Any = None,
    capabilities: Any = None,
    gate: GatePolicy | None = None,
) -> ToolExecutor:
    registry = ToolRegistry()
    registry.register(definition)
    return ToolExecutor(
        registry,
        confirmer=confirmer or AlwaysConfirm(),
        capabilities=capabilities or AllCapabilitiesGranted(),
        gate_policy=gate or GatePolicy(),
    )


def test_safe_tool_runs_without_confirmation() -> None:
    definition, calls = _make_definition(risk=RiskLevel.SAFE)
    executor = _executor_with(
        definition,
        confirmer=NeverConfirm(),  # nunca debería llamarse
    )
    result = executor.execute(ToolUseBlock(id="x", name="t", input={}))
    assert result.is_error is False
    assert calls == [{}]


def test_dangerous_tool_blocked_by_never_confirm() -> None:
    definition, calls = _make_definition(risk=RiskLevel.DANGEROUS)
    executor = _executor_with(definition, confirmer=NeverConfirm())
    result = executor.execute(ToolUseBlock(id="x", name="t", input={}))
    assert result.is_error is True
    assert "denegó" in result.output
    assert calls == []


def test_dangerous_tool_passes_with_always_confirm() -> None:
    definition, calls = _make_definition(risk=RiskLevel.DANGEROUS)
    executor = _executor_with(definition, confirmer=AlwaysConfirm())
    result = executor.execute(ToolUseBlock(id="x", name="t", input={}))
    assert result.is_error is False
    assert calls == [{}]


def test_confirm_tool_asks_only_first_time_by_default() -> None:
    class CountingConfirmer:
        def __init__(self) -> None:
            self.calls = 0

        def confirm(self, **kwargs: Any) -> bool:  # noqa: ARG002
            self.calls += 1
            return True

    confirmer = CountingConfirmer()
    definition, _ = _make_definition(risk=RiskLevel.CONFIRM)
    executor = _executor_with(definition, confirmer=confirmer)
    executor.execute(ToolUseBlock(id="1", name="t", input={}))
    executor.execute(ToolUseBlock(id="2", name="t", input={}))
    executor.execute(ToolUseBlock(id="3", name="t", input={}))
    assert confirmer.calls == 1


def test_dangerous_tool_asks_every_time() -> None:
    class CountingConfirmer:
        def __init__(self) -> None:
            self.calls = 0

        def confirm(self, **kwargs: Any) -> bool:  # noqa: ARG002
            self.calls += 1
            return True

    confirmer = CountingConfirmer()
    definition, _ = _make_definition(risk=RiskLevel.DANGEROUS)
    executor = _executor_with(definition, confirmer=confirmer)
    executor.execute(ToolUseBlock(id="1", name="t", input={}))
    executor.execute(ToolUseBlock(id="2", name="t", input={}))
    assert confirmer.calls == 2


def test_capability_denied_blocks_execution() -> None:
    definition, calls = _make_definition(
        risk=RiskLevel.SAFE, capabilities=["read-fs:~"]
    )
    executor = _executor_with(definition, capabilities=NoCapabilities())
    result = executor.execute(ToolUseBlock(id="x", name="t", input={}))
    assert result.is_error is True
    assert "capability denegada" in result.output
    assert calls == []


def test_input_validation_required_field() -> None:
    schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }
    definition, calls = _make_definition(schema=schema)
    executor = _executor_with(definition)
    result = executor.execute(ToolUseBlock(id="x", name="t", input={}))
    assert result.is_error is True
    assert "path" in result.output
    assert calls == []


def test_input_validation_type() -> None:
    schema = {
        "type": "object",
        "properties": {"n": {"type": "integer"}},
        "required": ["n"],
    }
    definition, _ = _make_definition(schema=schema)
    executor = _executor_with(definition)
    result = executor.execute(ToolUseBlock(id="x", name="t", input={"n": "abc"}))
    assert result.is_error is True


def test_executor_catches_unexpected_exception() -> None:
    definition, _ = _make_definition(raises=ValueError("boom"))
    executor = _executor_with(definition)
    result = executor.execute(ToolUseBlock(id="x", name="t", input={}))
    assert result.is_error is True
    assert "boom" in result.output


def test_executor_records_duration() -> None:
    definition, _ = _make_definition()
    executor = _executor_with(definition)
    result = executor.execute(ToolUseBlock(id="x", name="t", input={}))
    assert result.duration_ms >= 0.0


def test_execute_to_block_returns_tool_result_block() -> None:
    definition, _ = _make_definition()
    executor = _executor_with(definition)
    block = executor.execute_to_block(ToolUseBlock(id="x", name="t", input={}))
    assert block.tool_use_id == "x"
    assert block.is_error is False
    assert block.content == "executed"


def test_unknown_tool_returns_error() -> None:
    registry = ToolRegistry()
    executor = ToolExecutor(registry)
    result = executor.execute(ToolUseBlock(id="x", name="missing", input={}))
    assert result.is_error is True
    assert "desconocido" in result.output


def test_gate_policy_always_ask_calls_each_time() -> None:
    class CountingConfirmer:
        def __init__(self) -> None:
            self.calls = 0

        def confirm(self, **kwargs: Any) -> bool:  # noqa: ARG002
            self.calls += 1
            return True

    confirmer = CountingConfirmer()
    definition, _ = _make_definition(risk=RiskLevel.CONFIRM)
    executor = _executor_with(
        definition, confirmer=confirmer, gate=GatePolicy(mode="always_ask")
    )
    executor.execute(ToolUseBlock(id="1", name="t", input={}))
    executor.execute(ToolUseBlock(id="2", name="t", input={}))
    assert confirmer.calls == 2
