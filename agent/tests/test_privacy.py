"""Tests del detector de PII."""

from __future__ import annotations

from core.messages import ImageBlock, Message, TextBlock
from core.privacy import (
    PIIKind,
    detect_pii,
    detect_pii_in_blocks,
    detect_pii_in_messages,
)


def _kinds(matches: list) -> list[PIIKind]:
    return [m.kind for m in matches]


def test_detect_email() -> None:
    matches = detect_pii("contacto en juan@example.com por favor")
    assert PIIKind.EMAIL in _kinds(matches)


def test_detect_phone_with_country_code() -> None:
    matches = detect_pii("llámame al +57 300 123 4567")
    assert PIIKind.PHONE in _kinds(matches)


def test_phone_short_sequence_not_detected() -> None:
    """7 dígitos sueltos no son teléfono — evitamos falsos positivos."""
    matches = detect_pii("el código es 123 4567")
    assert PIIKind.PHONE not in _kinds(matches)


def test_detect_anthropic_api_key() -> None:
    text = "mi clave es sk-ant-api03-AbCdEf123456789012345678901234567890"
    matches = detect_pii(text)
    kinds = _kinds(matches)
    assert PIIKind.API_KEY in kinds
    # No expone la clave completa en el snippet
    assert all(len(m.snippet) < 30 for m in matches if m.kind is PIIKind.API_KEY)


def test_detect_aws_key() -> None:
    text = "AKIAIOSFODNN7EXAMPLE es la clave"
    assert PIIKind.API_KEY in _kinds(detect_pii(text))


def test_detect_credit_card_with_luhn() -> None:
    # 4111 1111 1111 1111 es un número de prueba que pasa Luhn
    text = "tarjeta 4111 1111 1111 1111"
    assert PIIKind.CREDIT_CARD in _kinds(detect_pii(text))


def test_credit_card_invalid_luhn_not_detected() -> None:
    text = "número 1234 5678 9012 3456"
    assert PIIKind.CREDIT_CARD not in _kinds(detect_pii(text))


def test_detect_password_field() -> None:
    text = "password: super-secreta-123"
    assert PIIKind.PASSWORD_FIELD in _kinds(detect_pii(text))


def test_detect_password_field_spanish() -> None:
    text = "contraseña: hola1234"
    assert PIIKind.PASSWORD_FIELD in _kinds(detect_pii(text))


def test_detect_private_key_block() -> None:
    text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQ..."
    assert PIIKind.PRIVATE_KEY in _kinds(detect_pii(text))


def test_detect_national_id_with_label() -> None:
    text = "mi cédula es CC 1234567890"
    assert PIIKind.NATIONAL_ID in _kinds(detect_pii(text))


def test_no_pii_in_plain_text() -> None:
    text = "qué clima hace hoy en Bogotá"
    assert detect_pii(text) == []


def test_detect_pii_in_blocks_skips_images() -> None:
    blocks = [TextBlock(text="email juan@example.com"), ImageBlock(data=b"\x00")]
    matches = detect_pii_in_blocks(blocks)
    assert PIIKind.EMAIL in _kinds(matches)


def test_detect_pii_in_messages_aggregates() -> None:
    messages = [
        Message(role="user", content=[TextBlock(text="hola")]),
        Message(role="assistant", content=[TextBlock(text="contáctame en x@y.com")]),
    ]
    assert PIIKind.EMAIL in _kinds(detect_pii_in_messages(messages))


def test_redaction_truncates_long_values() -> None:
    matches = detect_pii("mi email es muy-largo-correo@example.com")
    snippet = next(m.snippet for m in matches if m.kind is PIIKind.EMAIL)
    assert "***" in snippet
    assert "muy-largo" not in snippet
