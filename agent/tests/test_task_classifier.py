"""Tests del clasificador de tareas."""

from __future__ import annotations

from core.messages import (
    ChatRequest,
    ComputerUseTool,
    ImageBlock,
    Message,
    TextBlock,
    Tool,
    ToolUseBlock,
)
from core.task_classifier import TaskKind, classify


def _req(messages, tools=None):  # type: ignore[no-untyped-def]
    return ChatRequest(messages=messages, tools=tools or [])


def test_plain_chat() -> None:
    req = _req([Message(role="user", content=[TextBlock(text="hola")])])
    profile = classify(req)
    assert profile.kind is TaskKind.PLAIN_CHAT
    assert not profile.needs_vision
    assert not profile.needs_tools
    assert not profile.needs_computer_use


def test_vision_via_image_block() -> None:
    req = _req(
        [
            Message(
                role="user",
                content=[TextBlock(text="qué ves"), ImageBlock(data=b"\x89PNG")],
            )
        ]
    )
    profile = classify(req)
    assert profile.kind is TaskKind.VISION
    assert profile.needs_vision is True
    assert profile.has_images is True


def test_computer_use_tool() -> None:
    req = _req(
        [Message(role="user", content=[TextBlock(text="abre Firefox")])],
        tools=[ComputerUseTool(display_width_px=1920, display_height_px=1080)],
    )
    profile = classify(req)
    assert profile.kind is TaskKind.COMPUTER_USE
    assert profile.needs_computer_use is True


def test_tool_chain() -> None:
    req = _req(
        [Message(role="user", content=[TextBlock(text="clima")])],
        tools=[Tool(name="get_weather", description="x", input_schema={})],
    )
    profile = classify(req)
    assert profile.kind is TaskKind.TOOL_CHAIN
    assert profile.needs_tools is True


def test_tool_chain_via_history() -> None:
    """Aunque la request no traiga tools nuevos, si en history hay tool_use,
    el provider debe soportarlos."""
    req = _req(
        [
            Message(role="user", content=[TextBlock(text="hola")]),
            Message(
                role="assistant",
                content=[
                    TextBlock(text="voy a usar"),
                    ToolUseBlock(id="tu_1", name="x", input={}),
                ],
            ),
        ]
    )
    profile = classify(req)
    assert profile.kind is TaskKind.TOOL_CHAIN
    assert profile.has_tool_uses_in_history is True


def test_computer_use_takes_precedence_over_vision() -> None:
    req = _req(
        [Message(role="user", content=[ImageBlock(data=b"\x00")])],
        tools=[ComputerUseTool(display_width_px=1, display_height_px=1)],
    )
    profile = classify(req)
    assert profile.kind is TaskKind.COMPUTER_USE
    assert profile.has_images is True
