"""Detección heurística de información personal identificable (PII).

Esta es una primera línea de defensa para forzar enrutamiento local cuando
el contenido del usuario huele sensible. **No reemplaza** el sistema de
permisos ni la decisión consciente del usuario; es un default seguro.

Las heurísticas son intencionalmente conservadoras: preferimos un falso
positivo (mantener algo en local) que un falso negativo (filtrar a cloud
algo sensible).

Ver `docs/AI_ETHICS.md` (privacidad como default).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from core.messages import ContentBlock, Message, TextBlock


class PIIKind(str, Enum):
    EMAIL = "email"
    PHONE = "phone"
    CREDIT_CARD = "credit_card"
    NATIONAL_ID = "national_id"  # SSN, DNI, etc.
    API_KEY = "api_key"
    PRIVATE_KEY = "private_key"
    PASSWORD_FIELD = "password_field"


@dataclass(frozen=True, slots=True)
class PIIMatch:
    kind: PIIKind
    snippet: str
    """Extracto recortado para no repetir el dato sensible completo en logs."""


_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
# Teléfonos: secuencias largas con + opcional, espacios/guiones/paréntesis.
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)(?!\d)"
)
# Números de tarjeta de 13-19 dígitos con separadores opcionales.
_CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
# Claves API conocidas: Anthropic, OpenAI, AWS, etc.
_API_KEY_RE = re.compile(
    r"\b(?:sk-(?:ant-)?[A-Za-z0-9_\-]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}|"
    r"xox[baprs]-[A-Za-z0-9-]{10,})\b"
)
# Bloques de claves privadas en PEM.
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED |PRIVATE )?PRIVATE KEY-----"
)
# Palabras clave que indican credencial.
_PASSWORD_RE = re.compile(
    r"(?i)\b(?:password|passwd|pwd|contraseña|clave|secret)\s*[:=]\s*\S+"
)
# IDs nacionales aproximados (cédula, NIT, DNI, RUT, SSN). Aceptamos 7-11 dígitos
# con etiqueta delante para reducir falsos positivos sobre cualquier número.
_NATIONAL_ID_RE = re.compile(
    r"(?i)\b(?:cc|cedula|cédula|dni|nit|rut|ssn|passport|pasaporte)[\s#:.-]*"
    r"([A-Z0-9]{6,12})\b"
)


def _luhn(number: str) -> bool:
    """Verificación Luhn para reducir falsos positivos en tarjetas."""
    digits = [int(c) for c in number if c.isdigit()]
    if len(digits) < 13:
        return False
    checksum = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def _redact(text: str) -> str:
    """Recorta a 8 chars + ... para no replicar el dato en logs."""
    text = text.strip()
    if len(text) <= 8:
        return text[:4] + "***"
    return text[:4] + "***" + text[-2:]


def detect_pii(text: str) -> list[PIIMatch]:
    """Detecta PII en un texto. Devuelve match list ordenada por aparición.

    Diseño: queremos detectar "lo que importa" sin filtrar el contenido a
    los logs. Cada match guarda un snippet recortado.
    """
    matches: list[tuple[int, PIIMatch]] = []

    for m in _PRIVATE_KEY_RE.finditer(text):
        matches.append(
            (m.start(), PIIMatch(kind=PIIKind.PRIVATE_KEY, snippet="<PEM block>"))
        )

    for m in _API_KEY_RE.finditer(text):
        matches.append(
            (m.start(), PIIMatch(kind=PIIKind.API_KEY, snippet=_redact(m.group(0))))
        )

    for m in _PASSWORD_RE.finditer(text):
        matches.append(
            (
                m.start(),
                PIIMatch(kind=PIIKind.PASSWORD_FIELD, snippet=_redact(m.group(0))),
            )
        )

    for m in _EMAIL_RE.finditer(text):
        matches.append(
            (m.start(), PIIMatch(kind=PIIKind.EMAIL, snippet=_redact(m.group(0))))
        )

    for m in _CARD_RE.finditer(text):
        if _luhn(m.group(0)):
            matches.append(
                (
                    m.start(),
                    PIIMatch(kind=PIIKind.CREDIT_CARD, snippet=_redact(m.group(0))),
                )
            )

    for m in _NATIONAL_ID_RE.finditer(text):
        matches.append(
            (m.start(), PIIMatch(kind=PIIKind.NATIONAL_ID, snippet=_redact(m.group(0))))
        )

    for m in _PHONE_RE.finditer(text):
        digits = sum(1 for c in m.group(0) if c.isdigit())
        if 8 <= digits <= 15:
            matches.append(
                (m.start(), PIIMatch(kind=PIIKind.PHONE, snippet=_redact(m.group(0))))
            )

    matches.sort(key=lambda pair: pair[0])
    return [match for _, match in matches]


def detect_pii_in_blocks(blocks: list[ContentBlock]) -> list[PIIMatch]:
    found: list[PIIMatch] = []
    for block in blocks:
        if isinstance(block, TextBlock):
            found.extend(detect_pii(block.text))
    return found


def detect_pii_in_messages(messages: list[Message]) -> list[PIIMatch]:
    found: list[PIIMatch] = []
    for msg in messages:
        found.extend(detect_pii_in_blocks(msg.content))
    return found
