# Agent core (Python)

Cerebro de allAI OS: capa de proveedores, router híbrido, registro de herramientas, memoria, voz.

## Estado

- `core/` — interfaces y tipos provider-agnostic ✅ (L.1)
- `providers/claude.py` — implementación con anthropic SDK ✅ (L.1)
- `providers/ollama.py` — implementación local ✅ (L.1)
- `core/router.py` — router híbrido ⏳ (L.2)
- `tools/` — registro de tools ⏳ (L.3)
- `memory/` — memoria cifrada ⏳ (L.4)
- `voice/` — STT/TTS ⏳ (L.5)
- `sandbox/` — bubblewrap wrapper ⏳ (Launch)
- `permissions/` — capability system ⏳ (Launch)
- `prototype/` — prototipo desechable de viabilidad ✅ (A.5)

## Setup local

```bash
# Desde agent/
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Tests

```bash
# Sin red
pytest -m "not integration"

# Todos (requiere ANTHROPIC_API_KEY y/o ollama corriendo)
pytest

# Lint y type-check
ruff check .
ruff format --check .
mypy .
```

## Uso programático

```python
from core import ChatRequest, Message, TextBlock
from providers import ClaudeProvider, OllamaProvider

# Claude (cloud, requiere ANTHROPIC_API_KEY)
provider = ClaudeProvider()
response = provider.chat(ChatRequest(
    messages=[Message(role="user", content=[TextBlock(text="hola")])],
    system="Eres un asistente útil.",
))
print(response.text)

# Ollama (local, requiere ollama corriendo)
provider = OllamaProvider()
if provider.is_available():
    response = provider.chat(ChatRequest(
        messages=[Message(role="user", content=[TextBlock(text="hola")])],
        model="qwen2.5:7b",
    ))
    print(response.text)
```

## Decisiones de diseño

Esta capa implementa lo decidido en:

- [ADR-001](../docs/adr/0001-lenguaje-agente-core.md) — Python para el agente
- [ADR-006](../docs/adr/0006-modelo-permisos.md) — interfaces que el sistema de permisos puede observar

La interfaz `Provider` aísla los detalles de cada SDK. El router (L.2) elige
provider en cada request y la lógica de tools (L.3) trabaja sobre los tipos
agnósticos definidos en `core/messages.py`.
