"""Tests de la capa de tipos de mensajes."""

from __future__ import annotations

from core.messages import (
    ChatResponse,
    ImageBlock,
    Message,
    StopReason,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    Usage,
)


def test_text_block_defaults() -> None:
    block = TextBlock(text="hola")
    assert block.text == "hola"
    assert block.cache is False


def test_text_block_cache_flag() -> None:
    block = TextBlock(text="cachear esto", cache=True)
    assert block.cache is True


def test_image_block_defaults_to_png() -> None:
    block = ImageBlock(data=b"\x89PNG...")
    assert block.mime == "image/png"


def test_message_immutable() -> None:
    msg = Message(role="user", content=[TextBlock(text="hola")])
    assert msg.role == "user"
    assert len(msg.content) == 1


def test_tool_result_with_string() -> None:
    result = ToolResultBlock(tool_use_id="tu_1", content="ok")
    assert result.is_error is False
    assert result.content == "ok"


def test_tool_result_with_blocks() -> None:
    result = ToolResultBlock(
        tool_use_id="tu_2",
        content=[TextBlock(text="aquí está"), ImageBlock(data=b"\x00")],
    )
    assert isinstance(result.content, list)
    assert len(result.content) == 2


def test_chat_response_text_concatenates() -> None:
    response = ChatResponse(
        content=[TextBlock(text="hola"), TextBlock(text="mundo")],
        stop_reason="end_turn",
        usage=Usage(input_tokens=10, output_tokens=5),
        model="claude-opus-4-7",
    )
    assert response.text == "hola\nmundo"


def test_chat_response_tool_uses_filters() -> None:
    response = ChatResponse(
        content=[
            TextBlock(text="voy a usar un tool"),
            ToolUseBlock(id="tu_1", name="get_weather", input={"city": "Bogotá"}),
        ],
        stop_reason="tool_use",
        usage=Usage(),
        model="claude-opus-4-7",
    )
    tools = response.tool_uses
    assert len(tools) == 1
    assert tools[0].name == "get_weather"


def test_usage_total() -> None:
    usage = Usage(input_tokens=100, output_tokens=50, cache_read_tokens=200)
    assert usage.total_tokens == 350


def test_stop_reason_typed() -> None:
    valid: StopReason = "tool_use"
    assert valid == "tool_use"
