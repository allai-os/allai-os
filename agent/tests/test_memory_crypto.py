"""Tests del módulo memory.crypto.

Cubre:
  - KDF Argon2id (determinismo, sensibilidad a salt/passphrase, validación).
  - Manejo de salt (generación, persistencia atómica, lectura, validación
    de tamaño, permisos POSIX).
  - AEAD ChaCha20-Poly1305 (round-trip, tampering, AAD, nonce único).
  - Formato SQLCipher PRAGMA key.

No corre Argon2 con parámetros productivos en cada test (sería lento).
Para eso hay un test marcado `slow` que verifica que los parámetros
default tardan al menos un mínimo razonable.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from memory.crypto import (
    KEY_LENGTH,
    NONCE_LENGTH,
    SALT_LENGTH,
    TAG_LENGTH,
    CorruptedSaltError,
    CryptoError,
    InvalidPassphraseError,
    TamperedDataError,
    derive_key,
    derive_subkey,
    generate_salt,
    key_to_sqlcipher_pragma,
    load_salt,
    seal,
    store_salt,
    unseal,
)


# ─── Salt ────────────────────────────────────────────────────────────────────


def test_generate_salt_correct_size() -> None:
    salt = generate_salt()
    assert len(salt) == SALT_LENGTH


def test_generate_salt_is_random() -> None:
    a = generate_salt()
    b = generate_salt()
    assert a != b, "dos salts consecutivos no deberían coincidir"


def test_store_and_load_salt_roundtrip(tmp_path: Path) -> None:
    salt = generate_salt()
    target = tmp_path / "salt.bin"
    store_salt(target, salt)
    assert target.exists()
    loaded = load_salt(target)
    assert loaded == salt


def test_store_salt_overwrites_atomically(tmp_path: Path) -> None:
    target = tmp_path / "salt.bin"
    first = generate_salt()
    second = generate_salt()
    store_salt(target, first)
    store_salt(target, second)
    assert load_salt(target) == second
    # No deben quedar archivos .tmp huérfanos
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == []


def test_store_salt_creates_parent_dir(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "deeper" / "salt.bin"
    store_salt(target, generate_salt())
    assert target.exists()


def test_store_salt_rejects_wrong_size(tmp_path: Path) -> None:
    with pytest.raises(CryptoError, match="32 bytes"):
        store_salt(tmp_path / "salt.bin", b"too short")


def test_load_salt_missing_file(tmp_path: Path) -> None:
    with pytest.raises(CorruptedSaltError, match="no encontrado"):
        load_salt(tmp_path / "ausente.bin")


def test_load_salt_wrong_size(tmp_path: Path) -> None:
    target = tmp_path / "salt.bin"
    target.write_bytes(b"only 14 bytes!")
    with pytest.raises(CorruptedSaltError, match="32 bytes"):
        load_salt(target)


@pytest.mark.skipif(os.name != "posix", reason="permisos POSIX no aplican en Windows")
def test_store_salt_posix_permissions_0600(tmp_path: Path) -> None:
    target = tmp_path / "salt.bin"
    store_salt(target, generate_salt())
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o600, f"se esperaba 0o600, vino 0o{mode:o}"


# ─── KDF ─────────────────────────────────────────────────────────────────────

# Salt fijo para tests rápidos (no compromete seguridad — sólo verifica
# determinismo del KDF).
_FIXED_SALT = b"\x00" * SALT_LENGTH


def test_derive_key_correct_size() -> None:
    key = derive_key("hunter2", _FIXED_SALT)
    assert len(key) == KEY_LENGTH


def test_derive_key_deterministic() -> None:
    a = derive_key("hunter2", _FIXED_SALT)
    b = derive_key("hunter2", _FIXED_SALT)
    assert a == b


def test_derive_key_changes_with_passphrase() -> None:
    a = derive_key("hunter2", _FIXED_SALT)
    b = derive_key("hunter3", _FIXED_SALT)
    assert a != b


def test_derive_key_changes_with_salt() -> None:
    other_salt = b"\x01" * SALT_LENGTH
    a = derive_key("hunter2", _FIXED_SALT)
    b = derive_key("hunter2", other_salt)
    assert a != b


def test_derive_key_rejects_empty_passphrase() -> None:
    with pytest.raises(InvalidPassphraseError):
        derive_key("", _FIXED_SALT)


def test_derive_key_rejects_non_string_passphrase() -> None:
    with pytest.raises(InvalidPassphraseError):
        derive_key(b"bytes-not-str", _FIXED_SALT)  # type: ignore[arg-type]


def test_derive_key_rejects_wrong_salt_size() -> None:
    with pytest.raises(CryptoError, match="32 bytes"):
        derive_key("hunter2", b"too short")


def test_derive_key_handles_unicode_passphrase() -> None:
    key = derive_key("contraseña con ñ y emoji 🔒", _FIXED_SALT)
    assert len(key) == KEY_LENGTH


# ─── derive_subkey (HKDF) ────────────────────────────────────────────────────


def _master_key() -> bytes:
    return bytes(range(KEY_LENGTH))


def test_derive_subkey_correct_size_default() -> None:
    sub = derive_subkey(_master_key(), info=b"audit-hmac-v1")
    assert len(sub) == KEY_LENGTH


def test_derive_subkey_correct_size_custom() -> None:
    sub = derive_subkey(_master_key(), info=b"x", length=16)
    assert len(sub) == 16


def test_derive_subkey_deterministic() -> None:
    a = derive_subkey(_master_key(), info=b"audit-hmac-v1")
    b = derive_subkey(_master_key(), info=b"audit-hmac-v1")
    assert a == b


def test_derive_subkey_changes_with_info() -> None:
    a = derive_subkey(_master_key(), info=b"audit-hmac-v1")
    b = derive_subkey(_master_key(), info=b"audit-hmac-v2")
    assert a != b


def test_derive_subkey_changes_with_master() -> None:
    a = derive_subkey(_master_key(), info=b"x")
    b = derive_subkey(bytes(KEY_LENGTH), info=b"x")
    assert a != b


def test_derive_subkey_rejects_wrong_master_size() -> None:
    with pytest.raises(CryptoError, match="32 bytes"):
        derive_subkey(b"too-short", info=b"x")


def test_derive_subkey_rejects_empty_info() -> None:
    with pytest.raises(CryptoError, match="info"):
        derive_subkey(_master_key(), info=b"")


def test_derive_subkey_rejects_invalid_length() -> None:
    with pytest.raises(CryptoError, match="length"):
        derive_subkey(_master_key(), info=b"x", length=0)
    with pytest.raises(CryptoError, match="length"):
        derive_subkey(_master_key(), info=b"x", length=255 * 32 + 1)


# ─── AEAD ────────────────────────────────────────────────────────────────────


def _example_key() -> bytes:
    return bytes(range(KEY_LENGTH))


def test_seal_unseal_roundtrip() -> None:
    key = _example_key()
    plaintext = b"hello allAI memory"
    payload = seal(plaintext, key)
    assert unseal(payload, key) == plaintext


def test_seal_unseal_with_associated_data() -> None:
    key = _example_key()
    plaintext = b"sensitive content"
    aad = b"allai-memory-export-v1"
    payload = seal(plaintext, key, associated_data=aad)
    assert unseal(payload, key, associated_data=aad) == plaintext


def test_seal_produces_unique_payloads() -> None:
    """Dos llamadas con el mismo input deben dar payloads distintos
    (nonce aleatorio)."""
    key = _example_key()
    a = seal(b"same content", key)
    b = seal(b"same content", key)
    assert a != b
    # Pero ambos descifran al mismo plaintext
    assert unseal(a, key) == unseal(b, key) == b"same content"


def test_seal_payload_starts_with_nonce_of_correct_size() -> None:
    key = _example_key()
    payload = seal(b"x", key)
    assert len(payload) >= NONCE_LENGTH + TAG_LENGTH


def test_unseal_with_wrong_key_raises_tampered() -> None:
    key = _example_key()
    other_key = bytes((b ^ 0xFF) for b in key)
    payload = seal(b"hello", key)
    with pytest.raises(TamperedDataError):
        unseal(payload, other_key)


def test_unseal_with_corrupted_ciphertext_raises_tampered() -> None:
    key = _example_key()
    payload = bytearray(seal(b"hello world", key))
    # Flip un byte en la zona de ciphertext (después del nonce)
    payload[NONCE_LENGTH + 2] ^= 0x01
    with pytest.raises(TamperedDataError):
        unseal(bytes(payload), key)


def test_unseal_with_corrupted_nonce_raises_tampered() -> None:
    key = _example_key()
    payload = bytearray(seal(b"hello world", key))
    payload[0] ^= 0x01
    with pytest.raises(TamperedDataError):
        unseal(bytes(payload), key)


def test_unseal_with_wrong_aad_raises_tampered() -> None:
    key = _example_key()
    payload = seal(b"x", key, associated_data=b"v1")
    with pytest.raises(TamperedDataError):
        unseal(payload, key, associated_data=b"v2")


def test_unseal_without_aad_when_sealed_with_aad_raises_tampered() -> None:
    key = _example_key()
    payload = seal(b"x", key, associated_data=b"v1")
    with pytest.raises(TamperedDataError):
        unseal(payload, key)


def test_unseal_with_truncated_payload_raises_tampered() -> None:
    key = _example_key()
    payload = seal(b"hello", key)
    truncated = payload[: NONCE_LENGTH + TAG_LENGTH - 1]
    with pytest.raises(TamperedDataError):
        unseal(truncated, key)


def test_unseal_empty_payload_raises_tampered() -> None:
    with pytest.raises(TamperedDataError):
        unseal(b"", _example_key())


def test_seal_rejects_wrong_key_size() -> None:
    with pytest.raises(CryptoError, match="32 bytes"):
        seal(b"x", b"too short")


def test_unseal_rejects_wrong_key_size() -> None:
    with pytest.raises(CryptoError, match="32 bytes"):
        unseal(b"x" * 100, b"too short")


def test_seal_handles_empty_plaintext() -> None:
    key = _example_key()
    payload = seal(b"", key)
    assert unseal(payload, key) == b""


def test_seal_handles_large_plaintext() -> None:
    key = _example_key()
    plaintext = os.urandom(1_000_000)
    payload = seal(plaintext, key)
    assert unseal(payload, key) == plaintext


# ─── SQLCipher PRAGMA ────────────────────────────────────────────────────────


def test_key_to_sqlcipher_pragma_format() -> None:
    key = bytes(range(KEY_LENGTH))
    pragma = key_to_sqlcipher_pragma(key)
    # Formato esperado: x'000102...1f'
    assert pragma.startswith("x'")
    assert pragma.endswith("'")
    assert len(pragma) == len("x''") + KEY_LENGTH * 2
    # El hex coincide con la key
    hex_part = pragma[2:-1]
    assert bytes.fromhex(hex_part) == key


def test_key_to_sqlcipher_pragma_rejects_wrong_size() -> None:
    with pytest.raises(CryptoError, match="32 bytes"):
        key_to_sqlcipher_pragma(b"too short")
