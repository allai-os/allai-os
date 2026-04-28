"""Errores de provider-agnostic."""

from __future__ import annotations


class ProviderError(Exception):
    """Base de errores de provider."""

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        status_code: int | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.__cause__ = cause


class ProviderUnavailableError(ProviderError):
    """El provider no está disponible (servicio caído, sin red, modelo no instalado)."""


class AuthenticationError(ProviderError):
    """Credenciales inválidas o ausentes."""


class RateLimitError(ProviderError):
    """Cuota excedida o rate limit."""

    def __init__(
        self,
        message: str,
        *,
        retry_after: float | None = None,
        provider: str | None = None,
    ) -> None:
        super().__init__(message, provider=provider, status_code=429)
        self.retry_after = retry_after


class InvalidRequestError(ProviderError):
    """La request al provider está mal formada."""
