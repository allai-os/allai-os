"""Implementaciones concretas de `Provider`."""

from providers.claude import ClaudeProvider
from providers.ollama import OllamaProvider

__all__ = ["ClaudeProvider", "OllamaProvider"]
