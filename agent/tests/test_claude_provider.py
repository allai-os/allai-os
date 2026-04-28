"""Tests de ClaudeProvider con mocks. Sin red real."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from core.errors import AuthenticationError, InvalidRequestError
from core.messages import (
    ChatRequest,
    ComputerUseTool,
    ImageBlock,
    Message,
    TextBlock,
    Tool,
    ToolResultBlock,
    ToolUseBlock,
)
from providers.claude import (
    COMPUTER_USE_BETA,
    COMPUTER_USE_TOOL_TYPE,
    ClaudeProvider,
    _encode_block,
    _encode_message,
)


def _fake_message(
    *,
    text_parts: list[str] | None = None,
    tool_uses: list[dict[str, Any]] | None = None,
    stop_reason: str = "end_turn",
    input_tokens: int = 100,
    output_tokens: int = 50,
    cache_read: int = 0,
    cache_write: int = 0,
    model: str = "claude-opus-4-7",
) -> MagicMock:
    contents = []
    for t in text_parts or []:
        block = MagicMock()
        block.type = "text"
        block.text = t
        contents.append(block)
    for tu in tool_uses or []:
        block = MagicMock()
        block.type = "tool_use"
        block.id = tu["id"]
        block.name = tu["name"]
        block.input = tu["input"]
        contents.append(block)

    msg = MagicMock()
    msg.content = contents
    msg.stop_reason = stop_reason
    msg.model = model
    msg.usage.input_tokens = input_tokens
    msg.usage.output_tokens = output_tokens
    msg.usage.cache_read_input_tokens = cache_read
    msg.usage.cache_creation_input_tokens = cache_write
    return msg


def test_capabilities_lists_three_models() -> None:
    provider = ClaudeProvider(api_key="sk-fake")
    caps = provider.capabilities()
    ids = [m.id for m in caps.available_models]
    assert "claude-opus-4-7" in ids
    assert "claude-sonnet-4-6" in ids
    assert "claude-haiku-4-5-20251001" in ids
    assert caps.is_local is False
    assert caps.requires_network is True
    assert caps.supports_prompt_caching is True


def test_is_available_with_key() -> None:
    assert ClaudeProvider(api_key="sk-fake").is_available() is True


def test_is_available_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert ClaudeProvider().is_available() is False


def test_chat_translates_response_blocks() -> None:
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_message(
        text_parts=["hola"],
        tool_uses=[{"id": "tu_1", "name": "get_weather", "input": {"city": "Bogotá"}}],
        stop_reason="tool_use",
    )

    provider = ClaudeProvider(client=fake_client, api_key="sk-fake")
    response = provider.chat(
        ChatRequest(
            messages=[Message(role="user", content=[TextBlock(text="clima en Bogotá")])],
        )
    )

    assert response.text == "hola"
    assert len(response.tool_uses) == 1
    assert response.tool_uses[0].name == "get_weather"
    assert response.tool_uses[0].input == {"city": "Bogotá"}
    assert response.stop_reason == "tool_use"
    assert response.usage.input_tokens == 100
    assert response.usage.output_tokens == 50


def test_chat_passes_system_with_cache_control() -> None:
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_message(text_parts=["ok"])

    provider = ClaudeProvider(client=fake_client, api_key="sk-fake")
    provider.chat(
        ChatRequest(
            messages=[Message(role="user", content=[TextBlock(text="hola")])],
            system="Eres un asistente útil.",
        )
    )

    args = fake_client.messages.create.call_args
    system = args.kwargs["system"]
    assert isinstance(system, list)
    assert system[0]["type"] == "text"
    assert system[0]["text"] == "Eres un asistente útil."
    assert system[0]["cache_control"] == {"type": "ephemeral"}


def test_chat_disabled_caching() -> None:
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_message(text_parts=["ok"])

    provider = ClaudeProvider(
        client=fake_client, api_key="sk-fake", enable_prompt_caching=False
    )
    provider.chat(
        ChatRequest(
            messages=[Message(role="user", content=[TextBlock(text="hola")])],
            system="x",
        )
    )

    system = fake_client.messages.create.call_args.kwargs["system"]
    assert "cache_control" not in system[0]


def test_chat_caches_last_tool_definition() -> None:
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_message(text_parts=["ok"])

    provider = ClaudeProvider(client=fake_client, api_key="sk-fake")
    provider.chat(
        ChatRequest(
            messages=[Message(role="user", content=[TextBlock(text="hola")])],
            tools=[
                Tool(name="a", description="x", input_schema={"type": "object"}),
                Tool(name="b", description="y", input_schema={"type": "object"}),
            ],
        )
    )

    tools = fake_client.messages.create.call_args.kwargs["tools"]
    assert "cache_control" not in tools[0]
    assert tools[1]["cache_control"] == {"type": "ephemeral"}


def test_chat_with_computer_use_adds_beta() -> None:
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_message(text_parts=["ok"])

    provider = ClaudeProvider(client=fake_client, api_key="sk-fake")
    provider.chat(
        ChatRequest(
            messages=[Message(role="user", content=[TextBlock(text="abre Firefox")])],
            tools=[ComputerUseTool(display_width_px=1920, display_height_px=1080)],
        )
    )

    kwargs = fake_client.messages.create.call_args.kwargs
    assert COMPUTER_USE_BETA in kwargs["betas"]
    tool = kwargs["tools"][0]
    assert tool["type"] == COMPUTER_USE_TOOL_TYPE
    assert tool["display_width_px"] == 1920


def test_system_role_in_messages_raises() -> None:
    with pytest.raises(InvalidRequestError):
        _encode_message(
            Message(role="system", content=[TextBlock(text="no debe ir aquí")])
        )


def test_encode_image_block_to_base64() -> None:
    encoded = _encode_block(ImageBlock(data=b"\x89PNG", mime="image/png"))
    assert encoded["type"] == "image"
    assert encoded["source"]["type"] == "base64"
    assert encoded["source"]["media_type"] == "image/png"


def test_encode_tool_use_block() -> None:
    encoded = _encode_block(
        ToolUseBlock(id="tu_1", name="x", input={"a": 1})
    )
    assert encoded == {"type": "tool_use", "id": "tu_1", "name": "x", "input": {"a": 1}}


def test_encode_tool_result_string() -> None:
    encoded = _encode_block(ToolResultBlock(tool_use_id="tu_1", content="ok"))
    assert encoded["content"] == "ok"
    assert encoded["is_error"] is False


def test_encode_tool_result_with_blocks() -> None:
    encoded = _encode_block(
        ToolResultBlock(
            tool_use_id="tu_1",
            content=[TextBlock(text="aquí"), ImageBlock(data=b"\x00")],
        )
    )
    assert isinstance(encoded["content"], list)
    assert encoded["content"][0]["type"] == "text"
    assert encoded["content"][1]["type"] == "image"


def test_chat_without_key_raises_auth() -> None:
    provider = ClaudeProvider(api_key=None)
    with pytest.raises(AuthenticationError):
        provider.chat(
            ChatRequest(
                messages=[Message(role="user", content=[TextBlock(text="hola")])]
            )
        )
