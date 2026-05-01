"""Memoria del agente — almacenamiento local cifrado con Argon2id + SQLCipher.

Política de privacidad: la memoria nunca sale del equipo salvo opt-in
explícito del usuario. Los registros marcados como `sensitive` o
`untrusted` no se inyectan en requests cloud sin confirmación adicional.

Submódulos:
  - crypto: KDF, salt, AEAD sealed exports.
  - permissions: chmod 0700/0600 + validación.
  - store: SQLCipher (AES-256/HMAC-SHA512) — TODO.
  - audit: log append-only con hash-chain — TODO.
  - pii: filtro de información sensible.
  - injection_guard: detección de prompt injection.
  - embeddings: 100% local, nunca remoto — TODO.
  - retrieval: vector + BM25 sobre sqlite-fts5 — TODO.
  - session: short-term in-memory — TODO.
  - commands: parser de "recuerda/olvida/qué sabes" — TODO.
"""

from memory.audit import (
    AUDIT_HKDF_INFO,
    GENESIS_HMAC,
    AuditError,
    TamperedAuditError,
    append as audit_append,
    read_all as audit_read_all,
    verify as audit_verify,
)
from memory.crypto import (
    KEY_LENGTH,
    NONCE_LENGTH,
    SALT_LENGTH,
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
from memory.permissions import (
    DIR_MODE,
    FILE_MODE,
    InsecurePermissionsError,
    ensure_dir,
    ensure_file_perms,
    is_world_or_group_accessible,
    validate_dir_perms,
    validate_file_perms,
)
from memory.injection_guard import (
    InjectionBlockedError,
    InjectionPolicy,
    InjectionResult,
    assert_safe_for_injection,
    scan as injection_scan,
    wrap_for_injection,
)
from memory.pii import (
    CloudBlockedError,
    PIIFilterResult,
    assert_safe_for_cloud,
    is_sensitive,
    scan as pii_scan,
)
from memory.store import (
    SQLCipherUnavailableError,
    StoreError,
    delete_entry,
    get_entry,
    insert_entry,
    is_sqlcipher_available,
    list_entries,
    open_database,
    purge_expired,
    search_fts,
    transaction,
)

__all__ = [
    "AUDIT_HKDF_INFO",
    "DIR_MODE",
    "FILE_MODE",
    "GENESIS_HMAC",
    "KEY_LENGTH",
    "NONCE_LENGTH",
    "SALT_LENGTH",
    "AuditError",
    "CorruptedSaltError",
    "CryptoError",
    "InsecurePermissionsError",
    "InvalidPassphraseError",
    "SQLCipherUnavailableError",
    "StoreError",
    "TamperedAuditError",
    "TamperedDataError",
    "audit_append",
    "audit_read_all",
    "audit_verify",
    "delete_entry",
    "derive_key",
    "derive_subkey",
    "ensure_dir",
    "ensure_file_perms",
    "generate_salt",
    "get_entry",
    "insert_entry",
    "is_sqlcipher_available",
    "is_world_or_group_accessible",
    "key_to_sqlcipher_pragma",
    "list_entries",
    "load_salt",
    "open_database",
    "purge_expired",
    "search_fts",
    "seal",
    "store_salt",
    "transaction",
    "unseal",
    "validate_dir_perms",
    "validate_file_perms",
    # pii
    "CloudBlockedError",
    "PIIFilterResult",
    "assert_safe_for_cloud",
    "is_sensitive",
    "pii_scan",
    # injection_guard
    "InjectionBlockedError",
    "InjectionPolicy",
    "InjectionResult",
    "assert_safe_for_injection",
    "injection_scan",
    "wrap_for_injection",
]
