"""Tests del router con providers ficticios.

Usamos providers de prueba para no depender de Claude/Ollama reales.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest

from core.errors import AuthenticationError, ProviderUnavailableError
from core.messages import (
    ChatRequest,
    ChatResponse,
    ComputerUseTool,
    ImageBlock,
    Message,
    MessageStop,
    StreamEvent,
    TextBlock,
    TextDelta,
    Usage,
)
from core.policy import CostBudget, RoutingMode, RoutingPolicy
from core.provider import ModelInfo, Provider, ProviderCapabilities
from core.router import NoProviderAvailableError, Router
from core.task_classifier import TaskHints


# ─── Fakes ──────────────────────────────────────────────────────────────────


@dataclass
class FakeProvider(Provider):
    name: str = "fake"
    is_local: bool = False
    available: bool = True
    models: list[ModelInfo] = field(default_factory=list)
    chat_responses: list[ChatResponse | Exception] = field(default_factory=list)
    chat_calls: list[ChatRequest] = field(default_factory=list)

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            name=self.name,
            supports_streaming=True,
            supports_tools=any(m.supports_tools for m in self.models),
            supports_vision=any(m.supports_vision for m in self.models),
            supports_computer_use=any(m.supports_computer_use for m in self.models),
            supports_prompt_caching=False,
            is_local=self.is_local,
            requires_network=not self.is_local,
            available_models=list(self.models),
        )

    def is_available(self) -> bool:
        return self.available

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.chat_calls.append(request)
        if not self.chat_responses:
            return ChatResponse(
                content=[TextBlock(text="ok")],
                stop_reason="end_turn",
                usage=Usage(),
                model=request.model or "fake-model",
            )
        nxt = self.chat_responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    def chat_stream(self, request: ChatRequest) -> Iterator[StreamEvent]:
        self.chat_calls.append(request)
        if self.chat_responses and isinstance(self.chat_responses[0], Exception):
            exc = self.chat_responses.pop(0)
            raise exc  # type: ignore[misc]
        yield TextDelta(text="ok")
        yield MessageStop(stop_reason="end_turn", usage=Usage())


def _claude(**overrides):  # type: ignore[no-untyped-def]
    base = FakeProvider(
        name="claude",
        is_local=False,
        models=[
            ModelInfo(
                id="claude-opus-4-7",
                context_window=200_000,
                max_output_tokens=32_000,
                supports_vision=True,
                supports_tools=True,
                supports_computer_use=True,
                supports_caching=True,
                cost_per_million_input=15.0,
                cost_per_million_output=75.0,
            ),
            ModelInfo(
                id="claude-haiku-4-5-20251001",
                context_window=200_000,
                max_output_tokens=8_000,
                supports_vision=True,
                supports_tools=True,
                supports_computer_use=False,
                supports_caching=True,
                cost_per_million_input=0.80,
                cost_per_million_output=4.0,
            ),
        ],
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def _ollama(**overrides):  # type: ignore[no-untyped-def]
    base = FakeProvider(
        name="ollama",
        is_local=True,
        models=[
            ModelInfo(
                id="qwen2.5vl:7b",
                context_window=32_768,
                max_output_tokens=4_096,
                supports_vision=True,
                supports_tools=False,
                supports_computer_use=False,
                supports_caching=False,
            ),
            ModelInfo(
                id="qwen2.5:7b",
                context_window=32_768,
                max_output_tokens=4_096,
                supports_vision=False,
                supports_tools=True,
                supports_computer_use=False,
                supports_caching=False,
            ),
        ],
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def _user(text: str) -> list[Message]:
    return [Message(role="user", content=[TextBlock(text=text)])]


# ─── Tests de routing puro ──────────────────────────────────────────────────


def test_router_requires_at_least_one_provider() -> None:
    with pytest.raises(ValueError):
        Router(providers=[])


def test_auto_plain_chat_prefers_local() -> None:
    router = Router([_claude(), _ollama()])
    decision = router.route(ChatRequest(messages=_user("hola")))
    assert decision.primary.provider.name == "ollama"
    assert "local" in decision.reason


def test_auto_plain_chat_falls_to_cloud_when_local_unavailable() -> None:
    router = Router([_claude(), _ollama(available=False)])
    decision = router.route(ChatRequest(messages=_user("hola")))
    assert decision.primary.provider.name == "claude"


def test_auto_computer_use_prefers_cloud_native() -> None:
    router = Router([_claude(), _ollama()])
    decision = router.route(
        ChatRequest(
            messages=_user("abre Firefox"),
            tools=[ComputerUseTool(display_width_px=1920, display_height_px=1080)],
        )
    )
    assert decision.primary.provider.name == "claude"
    assert decision.primary.model == "claude-opus-4-7"
    # Debe haber fallback local
    assert any(c.provider.name == "ollama" for c in decision.chain[1:])


def test_auto_computer_use_falls_to_local_when_cloud_unavailable() -> None:
    router = Router([_claude(available=False), _ollama()])
    decision = router.route(
        ChatRequest(
            messages=_user("abre Firefox"),
            tools=[ComputerUseTool(display_width_px=1920, display_height_px=1080)],
        )
    )
    assert decision.primary.provider.name == "ollama"
    # qwen2.5vl tiene visión, sirve para emular computer use
    assert decision.primary.model == "qwen2.5vl:7b"


def test_pii_forces_local_even_in_cloud_first() -> None:
    router = Router(
        [_claude(), _ollama()], policy=RoutingPolicy(mode=RoutingMode.CLOUD_FIRST)
    )
    decision = router.route(
        ChatRequest(messages=_user("mi email es test@example.com"))
    )
    assert decision.primary.provider.name == "ollama"
    assert "sensible" in decision.reason or "email" in decision.reason


def test_hint_private_forces_local() -> None:
    router = Router([_claude(), _ollama()], policy=RoutingPolicy.cloud_first())
    decision = router.route(
        ChatRequest(messages=_user("hola")), hints=TaskHints(private=True)
    )
    assert decision.primary.provider.name == "ollama"


def test_local_only_never_cloud() -> None:
    router = Router(
        [_claude(), _ollama()], policy=RoutingPolicy(mode=RoutingMode.LOCAL_ONLY)
    )
    decision = router.route(ChatRequest(messages=_user("hola")))
    assert all(c.provider.name == "ollama" for c in decision.chain)


def test_local_only_fails_when_local_unavailable() -> None:
    router = Router(
        [_claude(), _ollama(available=False)],
        policy=RoutingPolicy(mode=RoutingMode.LOCAL_ONLY),
    )
    with pytest.raises(NoProviderAvailableError):
        router.route(ChatRequest(messages=_user("hola")))


def test_cloud_only_fails_when_cloud_unavailable() -> None:
    router = Router(
        [_claude(available=False), _ollama()],
        policy=RoutingPolicy(mode=RoutingMode.CLOUD_ONLY),
    )
    with pytest.raises(NoProviderAvailableError):
        router.route(ChatRequest(messages=_user("hola")))


def test_budget_exhausted_forces_local() -> None:
    router = Router(
        [_claude(), _ollama()],
        policy=RoutingPolicy(
            mode=RoutingMode.CLOUD_FIRST,
            cost_budget=CostBudget(monthly_usd=10.0, spent_monthly_usd=11.0),
        ),
    )
    decision = router.route(ChatRequest(messages=_user("hola")))
    assert decision.primary.provider.name == "ollama"
    assert "presupuesto" in decision.reason.lower()


def test_vision_request_picks_vision_model_in_local() -> None:
    router = Router([_claude(), _ollama()], policy=RoutingPolicy.auto())
    req = ChatRequest(
        messages=[
            Message(role="user", content=[ImageBlock(data=b"\x89PNG")]),
        ]
    )
    decision = router.route(req)
    # plain vision: local primero (privacy by default), modelo con visión
    assert decision.primary.provider.name == "ollama"
    assert decision.primary.model == "qwen2.5vl:7b"


def test_preferred_model_used_when_fits() -> None:
    router = Router(
        [_claude(), _ollama()],
        policy=RoutingPolicy(
            mode=RoutingMode.CLOUD_FIRST,
            preferred_cloud_model="claude-haiku-4-5-20251001",
        ),
    )
    decision = router.route(ChatRequest(messages=_user("rápido")))
    assert decision.primary.model == "claude-haiku-4-5-20251001"


def test_preferred_model_skipped_when_lacks_capability() -> None:
    """Si pides Haiku para Computer Use, el router se rinde y elige otro."""
    router = Router(
        [_claude(), _ollama()],
        policy=RoutingPolicy(
            mode=RoutingMode.CLOUD_FIRST,
            preferred_cloud_model="claude-haiku-4-5-20251001",
        ),
    )
    decision = router.route(
        ChatRequest(
            messages=_user("abre Firefox"),
            tools=[ComputerUseTool(display_width_px=1, display_height_px=1)],
        )
    )
    assert decision.primary.model == "claude-opus-4-7"


# ─── Tests de ejecución con fallback ────────────────────────────────────────


def test_chat_returns_response_from_primary() -> None:
    router = Router([_claude(), _ollama()], policy=RoutingPolicy.cloud_first())
    response = router.chat(ChatRequest(messages=_user("hola")))
    assert response.text == "ok"


def test_chat_falls_back_when_primary_unavailable() -> None:
    claude = _claude()
    claude.chat_responses = [ProviderUnavailableError("offline", provider="claude")]
    router = Router([claude, _ollama()], policy=RoutingPolicy.cloud_first())
    response = router.chat(ChatRequest(messages=_user("hola")))
    assert response.text == "ok"


def test_chat_does_not_fallback_on_auth_error() -> None:
    claude = _claude()
    claude.chat_responses = [AuthenticationError("no key", provider="claude")]
    router = Router([claude, _ollama()], policy=RoutingPolicy.cloud_first())
    with pytest.raises(AuthenticationError):
        router.chat(ChatRequest(messages=_user("hola")))


def test_chat_raises_when_all_fail() -> None:
    claude = _claude()
    claude.chat_responses = [ProviderUnavailableError("a", provider="claude")]
    ollama = _ollama()
    ollama.chat_responses = [ProviderUnavailableError("b", provider="ollama")]
    router = Router([claude, ollama], policy=RoutingPolicy.cloud_first())
    with pytest.raises(NoProviderAvailableError):
        router.chat(ChatRequest(messages=_user("hola")))


def test_request_passed_to_provider_has_selected_model() -> None:
    """Para chat plano, cloud_first elige el modelo más barato que sirva (Haiku)."""
    claude = _claude()
    router = Router([claude, _ollama()], policy=RoutingPolicy.cloud_first())
    router.chat(ChatRequest(messages=_user("hola"), model=None))
    assert claude.chat_calls[0].model == "claude-haiku-4-5-20251001"


def test_computer_use_picks_capable_model() -> None:
    """Para Computer Use cloud_first debe elegir el modelo que lo soporta nativo."""
    claude = _claude()
    router = Router([claude, _ollama()], policy=RoutingPolicy.cloud_first())
    router.chat(
        ChatRequest(
            messages=_user("abre Firefox"),
            tools=[ComputerUseTool(display_width_px=1920, display_height_px=1080)],
        )
    )
    assert claude.chat_calls[0].model == "claude-opus-4-7"


def test_chat_stream_yields_until_message_stop() -> None:
    router = Router([_claude(), _ollama()], policy=RoutingPolicy.cloud_first())
    events = list(router.chat_stream(ChatRequest(messages=_user("hola"))))
    assert any(isinstance(e, TextDelta) for e in events)
    assert isinstance(events[-1], MessageStop)
