"""Filtro de PII para entradas de memoria.

Envuelve `core.privacy` y añade la política del store:
- Determinar si una entrada debe marcarse `sensitive=True`.
- Bloquear inyección a cloud de entradas sensibles sin opt-in explícito.
- Exponer snippets redactados para logs (nunca el dato completo).

Decisión de diseño: preferimos falsos positivos. Si hay duda, la entrada
queda marcada sensible y se procesa sólo local.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.privacy import PIIKind, PIIMatch, detect_pii


class CloudBlockedError(Exception):
    """Se intentó inyectar a cloud un fragmento con PII sin opt-in."""


@dataclass(frozen=True, slots=True)
class PIIFilterResult:
    sensitive: bool
    kinds: list[PIIKind] = field(default_factory=list)
    matches: list[PIIMatch] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if not self.sensitive:
            return "clean"
        names = ", ".join(sorted({k.value for k in self.kinds}))
        return f"sensitive [{names}]"


def scan(text: str) -> PIIFilterResult:
    """Escanea `text` y devuelve un resultado con flag sensitive y detalle."""
    matches = detect_pii(text)
    if not matches:
        return PIIFilterResult(sensitive=False)
    kinds = [m.kind for m in matches]
    return PIIFilterResult(sensitive=True, kinds=kinds, matches=matches)


def is_sensitive(text: str) -> bool:
    """Atajo booleano: True si el texto contiene PII reconocida."""
    return bool(detect_pii(text))


def assert_safe_for_cloud(text: str, *, allow_cloud: bool = False) -> None:
    """Lanza CloudBlockedError si el texto es sensible y allow_cloud es False.

    Uso típico antes de inyectar memoria en un request cloud:

        assert_safe_for_cloud(entry.content, allow_cloud=user_opted_in)
    """
    if allow_cloud:
        return
    result = scan(text)
    if result.sensitive:
        snippets = [m.snippet for m in result.matches[:3]]
        raise CloudBlockedError(
            f"Entrada sensible bloqueada para cloud ({result.summary}). "
            f"Fragmentos: {snippets}. Pasa allow_cloud=True para anular."
        )
