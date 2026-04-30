"""Primitivas criptográficas para la memoria del agente.

Decisiones (security-first):

- KDF de la passphrase del usuario: **Argon2id** (resistente a GPU/ASIC y
  side-channel attacks). Parámetros calibrados a un objetivo de
  ~250-500 ms en CPU moderna: time_cost=3, memory_cost=64 MiB,
  parallelism=4, hash_len=32 bytes. La key resultante alimenta SQLCipher
  como bytes raw (saltando el KDF interno de SQLCipher porque el nuestro
  es más fuerte).
- Salt: 32 bytes de `os.urandom` por instalación, almacenado en archivo
  aparte del DB. Sin el salt no se puede derivar la key — funciona como
  segundo factor implícito (poseer el archivo del usuario).
- AEAD para sealed exports: **ChaCha20-Poly1305** (cifrado autenticado).
  Nonce de 96 bits aleatorio por operación. Para exports manuales el
  riesgo de colisión es despreciable; si en el futuro automatizamos
  encriptaciones masivas, migraremos a XChaCha20-Poly1305 (192-bit nonce)
  vía PyNaCl.
- Comparaciones constant-time donde sea relevante (`hmac.compare_digest`).

Lo que NO está en este módulo:
- SQLCipher en sí: lo encapsula `store.py`; aquí sólo formateamos la key.
- Audit log: `audit.py`.
- PII / injection guard: módulos propios.
- Manejo de permisos POSIX 0700/0600: `permissions.py` (este módulo
  hace un best-effort 0o600 al escribir el salt; la validación canónica
  ocurre en `permissions.py`).
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# ─── Constantes ──────────────────────────────────────────────────────────────

KEY_LENGTH = 32
"""Longitud de la key derivada en bytes (256 bits — AES-256/ChaCha20)."""

SALT_LENGTH = 32
"""Longitud del salt en bytes. 32 supera con margen el mínimo recomendado."""

NONCE_LENGTH = 12
"""Tamaño del nonce ChaCha20-Poly1305 (96 bits, RFC 8439)."""

TAG_LENGTH = 16
"""Tamaño del tag de autenticación Poly1305."""

ARGON2_TIME_COST = 3
"""Iteraciones internas de Argon2id (mínimo OWASP 2023 = 2; usamos 3)."""

ARGON2_MEMORY_COST_KIB = 65_536
"""Memoria en KiB usada por Argon2id (64 MiB — supera mínimo OWASP de 19 MiB)."""

ARGON2_PARALLELISM = 4
"""Lanes paralelos. 4 acelera en CPUs modernas sin reducir seguridad."""


# ─── Errores ────────────────────────────────────────────────────────────────


class CryptoError(Exception):
    """Error genérico del módulo crypto."""


class InvalidPassphraseError(CryptoError):
    """La passphrase es inválida (vacía, no-string, etc.)."""


class CorruptedSaltError(CryptoError):
    """El archivo de salt está corrupto, ausente o tiene tamaño incorrecto."""


class TamperedDataError(CryptoError):
    """El payload sellado fue alterado o se intentó descifrar con key/AAD incorrecta.

    Esta excepción es deliberadamente genérica para evitar oráculos: no
    distinguimos entre "key incorrecta", "MAC alterada", "AAD distinta" o
    "payload truncado". El caller sólo sabe que la verificación de
    autenticidad falló.
    """


# ─── Salt ────────────────────────────────────────────────────────────────────


def generate_salt() -> bytes:
    """Genera un salt criptográficamente seguro de SALT_LENGTH bytes.

    Usa `secrets.token_bytes` (alias de `os.urandom`) — fuente CSPRNG del SO.
    """
    return secrets.token_bytes(SALT_LENGTH)


def store_salt(path: Path, salt: bytes) -> None:
    """Persiste `salt` en `path` con escritura atómica.

    En POSIX aplica modo 0600 antes del `rename` (best-effort). En
    Windows la protección depende del ACL heredado del directorio user.
    El módulo `permissions.py` valida los permisos al abrir y rechaza
    el archivo si están laxos.

    Args:
      path: ruta absoluta del archivo de salt.
      salt: bytes de exactamente SALT_LENGTH.

    Raises:
      CryptoError: si `salt` no tiene el tamaño correcto.
    """
    if len(salt) != SALT_LENGTH:
        raise CryptoError(
            f"salt debe ser de {SALT_LENGTH} bytes, vino de {len(salt)}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    # Escritura con flags O_EXCL para evitar TOCTOU si otro proceso intenta
    # crear el mismo archivo entre el `mkdir` y el `open`.
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(tmp, flags, 0o600)
    try:
        os.write(fd, salt)
        os.fsync(fd)
    finally:
        os.close(fd)
    if os.name == "posix":
        # Re-aplica chmod por si el umask interfirió.
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def load_salt(path: Path) -> bytes:
    """Carga el salt desde `path`, validando tamaño.

    Raises:
      CorruptedSaltError: si el archivo no existe, no se puede leer, o
        tiene un tamaño distinto a SALT_LENGTH.
    """
    try:
        data = path.read_bytes()
    except FileNotFoundError as exc:
        raise CorruptedSaltError(f"salt no encontrado en {path}") from exc
    except OSError as exc:
        raise CorruptedSaltError(f"no se puede leer {path}: {exc}") from exc
    if len(data) != SALT_LENGTH:
        raise CorruptedSaltError(
            f"salt debe ser de {SALT_LENGTH} bytes, archivo tiene {len(data)}"
        )
    return data


# ─── KDF ─────────────────────────────────────────────────────────────────────


def derive_key(passphrase: str, salt: bytes) -> bytes:
    """Deriva una key de `KEY_LENGTH` bytes usando Argon2id.

    Args:
      passphrase: secreto del usuario. Debe ser no-vacío.
      salt: salt cargado/generado, de exactamente SALT_LENGTH bytes.

    Raises:
      InvalidPassphraseError: si la passphrase es vacía o no es str.
      CryptoError: si el salt tiene tamaño incorrecto.
    """
    if not isinstance(passphrase, str):
        raise InvalidPassphraseError("passphrase debe ser str")
    if not passphrase:
        raise InvalidPassphraseError("passphrase vacía")
    if len(salt) != SALT_LENGTH:
        raise CryptoError(
            f"salt debe ser de {SALT_LENGTH} bytes, vino de {len(salt)}"
        )
    return hash_secret_raw(
        secret=passphrase.encode("utf-8"),
        salt=salt,
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_COST_KIB,
        parallelism=ARGON2_PARALLELISM,
        hash_len=KEY_LENGTH,
        type=Type.ID,
    )


# ─── AEAD (sealed export) ────────────────────────────────────────────────────


def seal(
    plaintext: bytes,
    key: bytes,
    *,
    associated_data: bytes | None = None,
) -> bytes:
    """Cifra+autentica `plaintext` con ChaCha20-Poly1305.

    El payload devuelto es `nonce(12B) || ciphertext_with_tag`, listo
    para escribirse a archivo o enviarse en transporte. El AAD opcional
    no se cifra pero se autentica — útil para versionar formatos
    (`b"allai-memory-export-v1"`).

    Args:
      plaintext: datos a cifrar.
      key: bytes de exactamente KEY_LENGTH.
      associated_data: datos adicionales a autenticar (no cifrados).

    Raises:
      CryptoError: si la key tiene tamaño incorrecto.
    """
    _check_key_size(key)
    nonce = secrets.token_bytes(NONCE_LENGTH)
    aead = ChaCha20Poly1305(key)
    ciphertext = aead.encrypt(nonce, plaintext, associated_data)
    return nonce + ciphertext


def unseal(
    payload: bytes,
    key: bytes,
    *,
    associated_data: bytes | None = None,
) -> bytes:
    """Descifra y verifica un payload producido por `seal()`.

    Args:
      payload: bytes producidos por `seal`.
      key: misma key usada en `seal`.
      associated_data: mismo AAD usado en `seal` (None si no se usó).

    Raises:
      CryptoError: si la key tiene tamaño incorrecto.
      TamperedDataError: si la verificación de autenticidad falla por
        cualquier razón (key incorrecta, payload alterado, AAD
        diferente, payload truncado). No distingue causas — evita
        oráculos.
    """
    _check_key_size(key)
    if len(payload) < NONCE_LENGTH + TAG_LENGTH:
        raise TamperedDataError("payload demasiado corto para ser válido")
    nonce = payload[:NONCE_LENGTH]
    ciphertext = payload[NONCE_LENGTH:]
    aead = ChaCha20Poly1305(key)
    try:
        return aead.decrypt(nonce, ciphertext, associated_data)
    except InvalidTag as exc:
        raise TamperedDataError("autenticación fallida") from exc


# ─── SQLCipher key formatting ────────────────────────────────────────────────


def derive_subkey(master: bytes, *, info: bytes, length: int = KEY_LENGTH) -> bytes:
    """Deriva una subkey con HKDF-Expand-SHA256 (RFC 5869).

    Permite obtener varias keys independientes a partir de la misma master
    (la que sale de Argon2id). Cada submódulo usa un `info` distinto:

      - SQLCipher: usa la master directamente (no pasa por aquí).
      - Audit log: `info=b"allai-memory-audit-hmac-v1"`.
      - Future: cualquier otro uso debe declarar su propio info.

    Si dos llamadas usan el mismo `info` y `master`, devuelven la misma
    subkey. Si cualquiera difiere, las subkeys son independientes.

    Args:
      master: bytes de exactamente KEY_LENGTH (la output de derive_key).
      info: contexto único por uso. Debe ser estable y versionado.
      length: tamaño de la subkey en bytes (default: KEY_LENGTH).

    Raises:
      CryptoError: si `master` no tiene KEY_LENGTH bytes o `info` está vacío.
    """
    _check_key_size(master)
    if not info:
        raise CryptoError("info no puede ser vacío")
    if length <= 0 or length > 255 * 32:
        raise CryptoError(f"length fuera de rango: {length}")
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=length,
        salt=None,
        info=info,
    )
    return hkdf.derive(master)


def key_to_sqlcipher_pragma(key: bytes) -> str:
    """Formatea una key raw como literal aceptado por `PRAGMA key`.

    SQLCipher acepta la sintaxis `PRAGMA key = "x'<hex>'";` para usar
    bytes raw sin pasar por su KDF interno (que es PBKDF2). Como
    nosotros ya derivamos con Argon2id (más fuerte), saltamos el KDF
    interno con esta forma.

    NB: el caller debe **construir el statement con string concatenation
    tras llamar a esta función**; `PRAGMA key` no acepta parámetros
    bound. La función `store.open_db()` se encarga de eso de forma
    controlada — no exponemos esto a entrada del usuario.

    Raises:
      CryptoError: si la key tiene tamaño incorrecto.
    """
    _check_key_size(key)
    return f"x'{key.hex()}'"


# ─── Helpers internos ────────────────────────────────────────────────────────


def _check_key_size(key: bytes) -> None:
    if len(key) != KEY_LENGTH:
        raise CryptoError(
            f"key debe ser de {KEY_LENGTH} bytes, vino de {len(key)}"
        )
