"""Fernet encryption for broker credentials (Phase 10.2B-1).

Provides encrypt/decrypt helpers for broker API keys, secrets, and tokens.
All broker credentials stored in PostgreSQL are encrypted at rest using
Fernet symmetric encryption (AES-128-CBC + HMAC-SHA256).

Key derivation:
  TOKEN_ENCRYPTION_KEY is derived into a 32-byte Fernet key via
  PBKDF2-HMAC-SHA256 with 480,000 iterations and a fixed, non-secret
  derivation salt (_FIXED_SALT). The fixed salt is part of the algorithm,
  not a key-management parameter — it prevents rainbow-table attacks on
  the derivation itself. The derived Fernet key is deterministic: the same
  TOKEN_ENCRYPTION_KEY always produces the same Fernet instance.

Key rotation:
  Changing TOKEN_ENCRYPTION_KEY invalidates ALL previously encrypted
  ciphertext. Rotation requires: (1) set the new key, (2) re-encrypt
  every row in broker_connections and broker_tokens, (3) deploy. There
  is no automatic key rotation — TOKEN_ENCRYPTION_KEY is stable for the
  lifetime of the deployment.

Security properties:
  - Tokens are never logged, repr'd, or returned in error messages.
  - The Fernet instance is cached per process (key derivation is expensive).
  - TOKEN_ENCRYPTION_KEY must be set; empty string raises ValueError.
"""

from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

# Module-level cache for the Fernet instance (expensive to derive).
_fernet_instance: Fernet | None = None

# Fixed salt for key derivation. The TOKEN_ENCRYPTION_KEY is the secret;
# the salt prevents rainbow-table attacks on the derivation itself.
# This salt is NOT a secret and is NOT configurable — it is part of the
# algorithm, not a key-management parameter.
_FIXED_SALT = b"strike-nova-10.2b-credential-encryption-v1"


def get_fernet() -> Fernet:
    """Return the Fernet instance derived from TOKEN_ENCRYPTION_KEY.

    The key is derived via PBKDF2-HMAC-SHA256 with 480,000 iterations.
    The result is cached for the process lifetime.

    Raises
    ------
    ValueError
        If TOKEN_ENCRYPTION_KEY is empty or not set.
    """
    global _fernet_instance
    if _fernet_instance is not None:
        return _fernet_instance

    from app.config import settings

    key = getattr(settings, "TOKEN_ENCRYPTION_KEY", "")
    if not key:
        raise ValueError(
            "TOKEN_ENCRYPTION_KEY must be set for broker credential encryption. "
            "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )

    # Derive a 32-byte Fernet key from the encryption key using PBKDF2.
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_FIXED_SALT,
        iterations=480_000,
    )
    derived = kdf.derive(key.encode("utf-8"))
    fernet_key = base64.urlsafe_b64encode(derived)

    _fernet_instance = Fernet(fernet_key)
    return _fernet_instance


def encrypt(plaintext: str) -> str:
    """Encrypt a string value. Returns a Fernet token as a UTF-8 string.

    Parameters
    ----------
    plaintext : str
        The value to encrypt (e.g. an API key or access token).

    Returns
    -------
    str
        The encrypted value, safe for storage in a TEXT column.
    """
    fernet = get_fernet()
    return fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(encrypted: str) -> str:
    """Decrypt a Fernet token. Returns the original plaintext string.

    Parameters
    ----------
    encrypted : str
        The Fernet token to decrypt.

    Returns
    -------
    str
        The decrypted plaintext.

    Raises
    ------
    cryptography.fernet.InvalidToken
        If the token is corrupted, was encrypted with a different key,
        or is not a valid Fernet token.
    """
    fernet = get_fernet()
    return fernet.decrypt(encrypted.encode("utf-8")).decode("utf-8")
