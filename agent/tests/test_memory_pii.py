"""Tests de memory.pii — filtro de PII para entradas de memoria."""

from __future__ import annotations

import pytest

from core.privacy import PIIKind
from memory.pii import CloudBlockedError, PIIFilterResult, assert_safe_for_cloud, is_sensitive, scan


def test_scan_clean_text_returns_not_sensitive() -> None:
    result = scan("el cielo es azul y el mar también")
    assert isinstance(result, PIIFilterResult)
    assert result.sensitive is False
    assert result.kinds == []
    assert result.matches == []


def test_scan_email_marks_sensitive() -> None:
    result = scan("escríbeme a juan@example.com")
    assert result.sensitive is True
    assert PIIKind.EMAIL in result.kinds


def test_scan_api_key_marks_sensitive() -> None:
    result = scan("mi key es sk-ant-api03-XXXXXXXXXXXXXXXXXXXX")
    assert result.sensitive is True
    assert PIIKind.API_KEY in result.kinds


def test_scan_credit_card_marks_sensitive() -> None:
    # Número Luhn-válido de prueba: 4532015112830366
    result = scan("paga con 4532015112830366")
    assert result.sensitive is True
    assert PIIKind.CREDIT_CARD in result.kinds


def test_scan_phone_marks_sensitive() -> None:
    result = scan("llámame al +57 300 123 4567")
    assert result.sensitive is True
    assert PIIKind.PHONE in result.kinds


def test_scan_password_field_marks_sensitive() -> None:
    result = scan("password: supersecret123")
    assert result.sensitive is True
    assert PIIKind.PASSWORD_FIELD in result.kinds


def test_scan_multiple_pii_returns_all_kinds() -> None:
    result = scan("email: a@b.com y password: abc123")
    assert result.sensitive is True
    assert PIIKind.EMAIL in result.kinds
    assert PIIKind.PASSWORD_FIELD in result.kinds


def test_scan_summary_clean() -> None:
    assert scan("texto limpio").summary == "clean"


def test_scan_summary_sensitive_contains_kind() -> None:
    result = scan("user@host.com")
    assert "email" in result.summary
    assert "sensitive" in result.summary


def test_is_sensitive_true_for_email() -> None:
    assert is_sensitive("contacto: foo@bar.org") is True


def test_is_sensitive_false_for_clean() -> None:
    assert is_sensitive("hola mundo") is False


def test_assert_safe_for_cloud_passes_clean_text() -> None:
    assert_safe_for_cloud("el tiempo es bueno hoy")  # no debe lanzar


def test_assert_safe_for_cloud_blocks_sensitive() -> None:
    with pytest.raises(CloudBlockedError):
        assert_safe_for_cloud("mi correo es foo@bar.com")


def test_assert_safe_for_cloud_allow_cloud_overrides_block() -> None:
    # Con allow_cloud=True, incluso datos sensibles pasan
    assert_safe_for_cloud("foo@bar.com", allow_cloud=True)  # no debe lanzar


def test_assert_safe_for_cloud_error_message_contains_summary() -> None:
    with pytest.raises(CloudBlockedError, match="email"):
        assert_safe_for_cloud("contacto: user@example.com")


def test_assert_safe_for_cloud_error_lists_snippets() -> None:
    with pytest.raises(CloudBlockedError, match="allow_cloud"):
        assert_safe_for_cloud("token sk-ant-api03-FAKEKEY1234567890XX")
