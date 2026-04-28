"""Tests de OllamaProvider con mocks."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from core.messages import (
    ChatRequest,
    ComputerUseTool,
    Message,
    TextBlock,
    Tool,
)
from providers.ollama import (
    OllamaProvider,
    _try_parse_emulated_tool,
)


def _fake_list(models: list[str]) -> dict[str, Any]:
    return {"models": [{"name": m, "details": {"family": "qwen"}} for m in models]}


def _fake_chat_response(
    *,
    content: str = "",
    tool_calls: list[dict[str, Any]] | None = None,
    prompt_tokens: int = 50,
    eval_tokens: int = 25,
) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {
        "message": msg,
        "prompt_eval_count": prompt_tokens,
        "eval_count": eval_tokens,
        "done": True,
    }


def test_capabilities_when_unavailable() -> None:
    fake = MagicMock()
    fake.list.side_effect = ConnectionError("ollama no está corriendo")
    provider = OllamaProvider(client=fake)
    caps = provider.capabilities()
    assert caps.is_local is True
    assert caps.requires_network is False
    assert caps.available_models == []


def test_capabilities_marks_vision_models() -> None:
    fake = MagicMock()
    fake.list.return_value = _fake_list(["qwen2.5vl:7b", "llama3.2:3b"])
    provider = OllamaProvider(client=fake)
    caps = provider.capabilities()
    by_id = {m.id: m for m in caps.available_models}
    assert by_id["qwen2.5vl:7b"].supports_vision is True
    assert by_id["llama3.2:3b"].supports_vision is False


def test_capabilities_marks_native_tools() -> None:
    fake = MagicMock()
    fake.list.return_value = _fake_list(["qwen2.5:7b", "phi3:3b"])
    provider = OllamaProvider(client=fake)
    caps = provider.capabilities()
    by_id = {m.id: m for m in caps.available_models}
    assert by_id["qwen2.5:7b"].supports_tools is True
    # phi3 no está en _NATIVE_TOOLS_MARKERS
    assert by_id["phi3:3b"].supports_tools is False


def test_chat_simple_text() -> None:
    fake = MagicMock()
    fake.list.return_value = _fake_list(["qwen2.5:7b"])
    fake.chat.return_value = _fake_chat_response(content="hola mundo")
    provider = OllamaProvider(client=fake, default_model="qwen2.5:7b")

    response = provider.chat(
        ChatRequest(
            messages=[Message(role="user", content=[TextBlock(text="saluda")])],
        )
    )
    assert response.text == "hola mundo"
    assert response.stop_reason == "end_turn"
    assert response.usage.input_tokens == 50
    assert response.usage.output_tokens == 25


def test_chat_native_tool_call_decoded() -> None:
    fake = MagicMock()
    fake.list.return_value = _fake_list(["qwen2.5:7b"])
    fake.chat.return_value = _fake_chat_response(
        tool_calls=[
            {
                "function": {
                    "name": "get_weather",
                    "arguments": {"city": "Bogotá"},
                }
            }
        ]
    )
    provider = OllamaProvider(client=fake, default_model="qwen2.5:7b")

    response = provider.chat(
        ChatRequest(
            messages=[Message(role="user", content=[TextBlock(text="clima")])],
            tools=[
                Tool(
                    name="get_weather",
                    description="...",
                    input_schema={"type": "object"},
                )
            ],
        )
    )
    assert response.stop_reason == "tool_use"
    assert len(response.tool_uses) == 1
    assert response.tool_uses[0].name == "get_weather"
    assert response.tool_uses[0].input == {"city": "Bogotá"}


def test_chat_emulated_tool_via_json_text() -> None:
    fake = MagicMock()
    fake.list.return_value = _fake_list(["phi3:3b"])  # no tiene tools nativos
    fake.chat.return_value = _fake_chat_response(
        content='{"tool": "get_weather", "input": {"city": "Lima"}}'
    )
    provider = OllamaProvider(client=fake, default_model="phi3:3b")

    response = provider.chat(
        ChatRequest(
            messages=[Message(role="user", content=[TextBlock(text="clima")])],
            tools=[
                Tool(
                    name="get_weather",
                    description="...",
                    input_schema={"type": "object"},
                )
            ],
        )
    )
    assert response.stop_reason == "tool_use"
    assert len(response.tool_uses) == 1
    assert response.tool_uses[0].name == "get_weather"
    assert response.tool_uses[0].input == {"city": "Lima"}


def test_chat_computer_use_appends_emulation_system() -> None:
    fake = MagicMock()
    fake.list.return_value = _fake_list(["qwen2.5vl:7b"])
    fake.chat.return_value = _fake_chat_response(content="entendido")
    provider = OllamaProvider(client=fake, default_model="qwen2.5vl:7b")

    provider.chat(
        ChatRequest(
            messages=[Message(role="user", content=[TextBlock(text="abre Firefox")])],
            tools=[ComputerUseTool(display_width_px=1920, display_height_px=1080)],
        )
    )

    sent_messages = fake.chat.call_args.kwargs["messages"]
    assert sent_messages[0]["role"] == "system"
    assert "1920" in sent_messages[0]["content"]
    assert "1080" in sent_messages[0]["content"]


def test_try_parse_emulated_tool_direct_json() -> None:
    block = _try_parse_emulated_tool('{"tool": "x", "input": {"a": 1}}')
    assert block is not None
    assert block.name == "x"
    assert block.input == {"a": 1}


def test_try_parse_emulated_tool_embedded_json() -> None:
    text = 'Voy a usar la herramienta: {"tool": "x", "input": {}}'
    block = _try_parse_emulated_tool(text)
    assert block is not None
    assert block.name == "x"


def test_try_parse_emulated_tool_no_json_returns_none() -> None:
    assert _try_parse_emulated_tool("solo texto sin json") is None


def test_try_parse_emulated_tool_invalid_json_returns_none() -> None:
    assert _try_parse_emulated_tool('{"tool": "x", input broken') is None
