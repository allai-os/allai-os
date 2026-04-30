"""Tests de GeminiProvider con mocks. Sin red real ni dep de google-genai."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from core.errors import (
    AuthenticationError,
    ProviderError,
    RateLimitError,
)
from core.messages import (
    ChatRequest,
    ComputerUseTool,
    ImageBlock,
    Message,
    TextBlock,
    Tool,
    ToolUseBlock,
)
from providers.gemini import GeminiProvider, _decode_response


def _fake_response(
    *,
    text_parts: list[str] | None = None,
    function_calls: list[dict[str, Any]] | None = None,
    finish_reason: str = "STOP",
    input_tokens: int = 100,
    output_tokens: int = 50,
    cache_read: int = 0,
) -> MagicMock:
    parts = []
    for t in text_parts or []:
        p = MagicMock()
        p.text = t
        p.function_call = None
        parts.append(p)
    for fc in function_calls or []:
        p = MagicMock()
        p.text = None
        function_call = MagicMock()
        function_call.name = fc["name"]
        function_call.args = fc.get("args", {})
        function_call.id = fc.get("id", "")
        p.function_call = function_call
        parts.append(p)

    content = MagicMock()
    content.parts = parts

    finish = MagicMock()
    finish.name = finish_reason

    candidate = MagicMock()
    candidate.content = content
    candidate.finish_reason = finish

    response = MagicMock()
    response.candidates = [candidate]
    response.usage_metadata = MagicMock(
        prompt_token_count=input_tokens,
        candidates_token_count=output_tokens,
        cached_content_token_count=cache_read,
    )
    return response


def test_capabilities_lists_models() -> None:
    provider = GeminiProvider(api_key="fake")
    caps = provider.capabilities()
    ids = [m.id for m in caps.available_models]
    assert "gemini-2.5-pro" in ids
    assert "gemini-2.5-flash" in ids
    assert "gemini-2.5-flash-lite" in ids
    assert any("computer-use" in i for i in ids)
    assert caps.is_local is False
    assert caps.requires_network is True
    assert caps.supports_computer_use is True
    assert caps.supports_vision is True


def test_is_available_with_key() -> None:
    assert GeminiProvider(api_key="fake").is_available() is True


def test_is_available_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert GeminiProvider().is_available() is False


def test_chat_returns_text() -> None:
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _fake_response(
        text_parts=["hola desde gemini"]
    )

    provider = GeminiProvider(client=fake_client, api_key="fake")
    response = provider.chat(
        ChatRequest(
            messages=[Message(role="user", content=[TextBlock(text="saluda")])],
            model="gemini-2.5-flash",
        )
    )
    assert response.text == "hola desde gemini"
    assert response.stop_reason == "end_turn"
    assert response.usage.input_tokens == 100
    assert response.usage.output_tokens == 50


def test_chat_returns_tool_use_when_function_call() -> None:
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _fake_response(
        function_calls=[
            {"name": "get_weather", "args": {"city": "Bogotá"}, "id": "fc_1"}
        ]
    )

    provider = GeminiProvider(client=fake_client, api_key="fake")
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
            model="gemini-2.5-flash",
        )
    )
    assert response.stop_reason == "tool_use"
    tool_uses = response.tool_uses
    assert len(tool_uses) == 1
    assert tool_uses[0].name == "get_weather"
    assert tool_uses[0].input == {"city": "Bogotá"}


def test_chat_routes_to_computer_use_model_when_tool_present() -> None:
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _fake_response(text_parts=["ok"])

    provider = GeminiProvider(
        client=fake_client,
        api_key="fake",
        computer_use_model="gemini-2.5-computer-use-preview-X",
    )
    provider.chat(
        ChatRequest(
            messages=[Message(role="user", content=[TextBlock(text="abre Firefox")])],
            tools=[ComputerUseTool(display_width_px=1920, display_height_px=1080)],
        )
    )
    args = fake_client.models.generate_content.call_args
    assert args.kwargs["model"] == "gemini-2.5-computer-use-preview-X"


def test_chat_explicit_model_overrides_default() -> None:
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _fake_response(text_parts=["ok"])
    provider = GeminiProvider(client=fake_client, api_key="fake")
    provider.chat(
        ChatRequest(
            messages=[Message(role="user", content=[TextBlock(text="hola")])],
            model="gemini-2.5-pro",
        )
    )
    assert fake_client.models.generate_content.call_args.kwargs["model"] == "gemini-2.5-pro"


def test_decode_max_tokens_finish_reason() -> None:
    response = _fake_response(text_parts=["truncado..."], finish_reason="MAX_TOKENS")
    decoded = _decode_response(response, "gemini-2.5-flash")
    assert decoded.stop_reason == "max_tokens"


def test_decode_safety_finish_maps_to_error() -> None:
    response = _fake_response(text_parts=[""], finish_reason="SAFETY")
    decoded = _decode_response(response, "gemini-2.5-flash")
    assert decoded.stop_reason == "error"


def test_chat_translates_authentication_error() -> None:
    fake_client = MagicMock()
    boom = Exception("API key invalid")
    fake_client.models.generate_content.side_effect = boom

    provider = GeminiProvider(client=fake_client, api_key="fake")
    with pytest.raises(AuthenticationError):
        provider.chat(
            ChatRequest(
                messages=[Message(role="user", content=[TextBlock(text="hola")])]
            )
        )


def test_chat_translates_rate_limit() -> None:
    fake_client = MagicMock()

    class _Boom(Exception):
        status_code = 429

    fake_client.models.generate_content.side_effect = _Boom("quota exceeded")

    provider = GeminiProvider(client=fake_client, api_key="fake")
    with pytest.raises(RateLimitError):
        provider.chat(
            ChatRequest(
                messages=[Message(role="user", content=[TextBlock(text="hola")])]
            )
        )


def test_chat_passes_system_instruction(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _fake_response(text_parts=["ok"])

    provider = GeminiProvider(client=fake_client, api_key="fake")
    provider.chat(
        ChatRequest(
            messages=[Message(role="user", content=[TextBlock(text="hola")])],
            system="Sé conciso.",
        )
    )
    config = fake_client.models.generate_content.call_args.kwargs.get("config")
    # No assertamos el shape exacto del config (depende del SDK), sólo que se pasó.
    assert config is not None


def test_chat_handles_image_block() -> None:
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _fake_response(text_parts=["veo"])
    provider = GeminiProvider(client=fake_client, api_key="fake")
    provider.chat(
        ChatRequest(
            messages=[
                Message(
                    role="user",
                    content=[TextBlock(text="qué ves"), ImageBlock(data=b"\x89PNG")],
                )
            ]
        )
    )
    contents = fake_client.models.generate_content.call_args.kwargs["contents"]
    # Verifica que el content tiene un único turno user con dos parts (text + image)
    assert len(contents) == 1


def test_chat_propagates_assistant_history() -> None:
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = _fake_response(text_parts=["ok"])
    provider = GeminiProvider(client=fake_client, api_key="fake")
    provider.chat(
        ChatRequest(
            messages=[
                Message(role="user", content=[TextBlock(text="hola")]),
                Message(
                    role="assistant",
                    content=[
                        ToolUseBlock(id="x", name="search", input={"q": "py"}),
                    ],
                ),
            ]
        )
    )
    contents = fake_client.models.generate_content.call_args.kwargs["contents"]
    assert len(contents) == 2


def test_chat_without_key_raises_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    provider = GeminiProvider()
    with pytest.raises(AuthenticationError):
        provider.chat(
            ChatRequest(
                messages=[Message(role="user", content=[TextBlock(text="hola")])]
            )
        )


def test_unknown_error_propagates_as_provider_error() -> None:
    fake_client = MagicMock()
    fake_client.models.generate_content.side_effect = RuntimeError("inesperado")

    provider = GeminiProvider(client=fake_client, api_key="fake")
    with pytest.raises(ProviderError):
        provider.chat(
            ChatRequest(
                messages=[Message(role="user", content=[TextBlock(text="hola")])]
            )
        )
