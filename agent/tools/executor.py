"""Dispatcher de tool calls.

El agente recibe un `ToolUseBlock` del modelo, y este executor:

1. Resuelve la definición en el registro.
2. Pide capabilities ausentes al checker (que en producción habla con la UI
   de allAI; en tests es un stub).
3. Aplica el gate de riesgo: SAFE pasa, CONFIRM pide ok la primera vez,
   DANGEROUS pide ok siempre.
4. Valida entrada contra el JSON schema (validación mínima — el modelo
   suele cumplir, pero defensivo).
5. Ejecuta el tool, captura tiempo, errores y resultado.
6. Devuelve un `ToolResult` listo para inyectarse al modelo como `ToolResultBlock`.

La fase Launch enchufa los protocolos `ConfirmationProtocol` y
`CapabilityCheckerProtocol` a la UI real. Esta capa los recibe inyectados.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Protocol

from core.messages import ToolResultBlock, ToolUseBlock
from tools.base import (
    CapabilityDeniedError,
    ConfirmationDeniedError,
    RiskLevel,
    ToolDefinition,
    ToolError,
    ToolResult,
    ToolValidationError,
)
from tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


# ─── Protocols inyectables ──────────────────────────────────────────────────


class ConfirmationProtocol(Protocol):
    """Decide si una acción se ejecuta cuando el riesgo lo exige."""

    def confirm(
        self,
        *,
        tool_name: str,
        input: dict[str, Any],
        risk: RiskLevel,
        description: str,
    ) -> bool: ...


class CapabilityCheckerProtocol(Protocol):
    """Verifica y solicita capabilities."""

    def has(self, capability: str) -> bool: ...
    def request(self, capability: str) -> bool: ...


# ─── Implementaciones de prueba/dev ─────────────────────────────────────────


class AlwaysConfirm:
    """Útil para tests y desarrollo. NO usar en producción."""

    def confirm(self, **kwargs: Any) -> bool:  # noqa: ARG002
        return True


class NeverConfirm:
    """Para auditorías y modo paranoid."""

    def confirm(self, **kwargs: Any) -> bool:  # noqa: ARG002
        return False


class AllCapabilitiesGranted:
    def has(self, capability: str) -> bool:  # noqa: ARG002
        return True

    def request(self, capability: str) -> bool:  # noqa: ARG002
        return True


class NoCapabilities:
    def has(self, capability: str) -> bool:  # noqa: ARG002
        return False

    def request(self, capability: str) -> bool:  # noqa: ARG002
        return False


# ─── Modos de comportamiento de gate ────────────────────────────────────────


class GatePolicy:
    """Política para cuándo activar el gate de confirmación.

    `confirm_first_use_only`: pedir confirm sólo la primera vez por tool.
    `always_ask`: pedir confirm en cada uso (modo paranoid).
    `trust_safe_and_confirm_after_first`: SAFE pasa siempre, CONFIRM pide
    sólo la primera vez, DANGEROUS siempre. Default sensato.
    """

    def __init__(self, *, mode: str = "trust_after_first") -> None:
        self.mode = mode
        self._confirmed: set[str] = set()

    def needs_confirmation(self, tool_name: str, risk: RiskLevel) -> bool:
        if risk is RiskLevel.SAFE:
            return False
        if risk is RiskLevel.DANGEROUS:
            # Reglas absolutas: no se desactivan nunca.
            return True
        # CONFIRM
        if self.mode == "always_ask":
            return True
        if self.mode == "trust_after_first":
            return tool_name not in self._confirmed
        # mode 'never' — no recomendado.
        return False

    def remember_confirmed(self, tool_name: str) -> None:
        self._confirmed.add(tool_name)


# ─── Executor ───────────────────────────────────────────────────────────────


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        confirmer: ConfirmationProtocol | None = None,
        capabilities: CapabilityCheckerProtocol | None = None,
        gate_policy: GatePolicy | None = None,
    ) -> None:
        self._registry = registry
        self._confirmer = confirmer or AlwaysConfirm()
        self._caps = capabilities or AllCapabilitiesGranted()
        self._gate = gate_policy or GatePolicy()

    def execute(self, tool_use: ToolUseBlock) -> ToolResult:
        """Ejecuta un tool. Devuelve `ToolResult` con `is_error=True` ante fallos."""
        started = time.monotonic()
        try:
            definition = self._registry.get(tool_use.name)
            self._check_capabilities(definition)
            self._maybe_confirm(definition, tool_use.input)
            _validate_input(definition, tool_use.input)
            result = definition.executor(**tool_use.input)
            duration_ms = (time.monotonic() - started) * 1000
            return ToolResult(
                output=result.output,
                images=result.images,
                structured=result.structured,
                is_error=result.is_error,
                duration_ms=duration_ms,
            )
        except ToolError as exc:
            duration_ms = (time.monotonic() - started) * 1000
            logger.warning("tool %s falló: %s", tool_use.name, exc)
            return ToolResult(
                output=f"{type(exc).__name__}: {exc}",
                is_error=True,
                duration_ms=duration_ms,
            )
        except Exception as exc:  # noqa: BLE001 - última red, no propagamos al modelo
            duration_ms = (time.monotonic() - started) * 1000
            logger.exception("tool %s lanzó excepción inesperada", tool_use.name)
            return ToolResult(
                output=f"{type(exc).__name__}: {exc}",
                is_error=True,
                duration_ms=duration_ms,
            )

    def execute_to_block(self, tool_use: ToolUseBlock) -> ToolResultBlock:
        """Ejecuta y empaqueta como `ToolResultBlock` para inyectar al modelo."""
        result = self.execute(tool_use)
        blocks = result.to_blocks()
        if not blocks:
            content: str | list[Any] = "ok"
        elif len(blocks) == 1 and hasattr(blocks[0], "text"):
            content = blocks[0].text  # type: ignore[union-attr]
        else:
            content = blocks
        return ToolResultBlock(
            tool_use_id=tool_use.id, content=content, is_error=result.is_error
        )

    # ─── Internals ──────────────────────────────────────────────────────────

    def _check_capabilities(self, definition: ToolDefinition) -> None:
        for cap in definition.capabilities_required:
            if self._caps.has(cap):
                continue
            if not self._caps.request(cap):
                raise CapabilityDeniedError(cap)

    def _maybe_confirm(
        self, definition: ToolDefinition, payload: dict[str, Any]
    ) -> None:
        if not self._gate.needs_confirmation(definition.name, definition.risk):
            return
        ok = self._confirmer.confirm(
            tool_name=definition.name,
            input=payload,
            risk=definition.risk,
            description=definition.description,
        )
        if not ok:
            raise ConfirmationDeniedError(definition.name, definition.risk)
        self._gate.remember_confirmed(definition.name)


# ─── Validación de input ────────────────────────────────────────────────────


def _validate_input(definition: ToolDefinition, payload: dict[str, Any]) -> None:
    """Validación mínima contra `input_schema`.

    No usamos jsonschema (dep extra) — chequeamos required + type básico.
    """
    schema = definition.input_schema or {}
    required = schema.get("required") or []
    properties = schema.get("properties") or {}

    for prop in required:
        if prop not in payload:
            raise ToolValidationError(
                f"falta argumento requerido '{prop}' en {definition.name}"
            )

    type_map: dict[str, type | tuple[type, ...]] = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    for key, value in payload.items():
        prop_schema = properties.get(key)
        if not prop_schema:
            continue
        expected = prop_schema.get("type")
        if expected and expected in type_map:
            if not isinstance(value, type_map[expected]):
                raise ToolValidationError(
                    f"argumento '{key}' debe ser {expected} en {definition.name}"
                )
