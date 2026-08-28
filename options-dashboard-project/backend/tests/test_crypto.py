"""Tests for Phase 10.2B-1 encryption module (app.crypto).

Verifies Fernet encrypt/decrypt round-trip, key derivation,
error handling, and process-lifetime caching.
"""

import pytest
from cryptography.fernet import InvalidToken

from app.crypto import encrypt, decrypt, get_fernet


class TestFernetKeyDerivation:
    """Verify get_fernet() derives a valid Fernet instance."""

    def test_returns_fernet_instance(self):
        """get_fernet() must return a Fernet object."""
        from cryptography.fernet import Fernet
        assert isinstance(get_fernet(), Fernet)

    def test_caches_instance(self):
        """get_fernet() must return the same instance on repeated calls."""
        a = get_fernet()
        b = get_fernet()
        assert a is b

    def test_missing_key_raises(self):
        """get_fernet() must raise ValueError when TOKEN_ENCRYPTION_KEY is empty."""
        import app.crypto as crypto_mod
        import app.config as config_mod

        # Save original
        orig_key = getattr(config_mod.settings, "TOKEN_ENCRYPTION_KEY", "")
        orig_fernet = crypto_mod._fernet_instance
        try:
            config_mod.settings.TOKEN_ENCRYPTION_KEY = ""
            crypto_mod._fernet_instance = None  # Reset cache
            with pytest.raises(ValueError, match="TOKEN_ENCRYPTION_KEY must be set"):
                get_fernet()
        finally:
            config_mod.settings.TOKEN_ENCRYPTION_KEY = orig_key
            crypto_mod._fernet_instance = orig_fernet


class TestEncryptDecrypt:
    """Verify encrypt/decrypt round-trip."""

    def test_round_trip(self):
        """Encrypted value must decrypt to original plaintext."""
        plaintext = "sk-test-api-key-12345"
        encrypted = encrypt(plaintext)
        assert decrypt(encrypted) == plaintext

    def test_empty_string(self):
        """Empty strings must encrypt/decrypt correctly."""
        assert decrypt(encrypt("")) == ""

    def test_unicode(self):
        """Unicode strings must encrypt/decrypt correctly."""
        plaintext = "user@example.com — test"
        assert decrypt(encrypt(plaintext)) == plaintext

    def test_long_string(self):
        """Long strings (e.g. JWTs) must encrypt/decrypt correctly."""
        plaintext = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9." + "x" * 500
        assert decrypt(encrypt(plaintext)) == plaintext

    def test_produces_different_ciphertext(self):
        """Same plaintext must produce different ciphertext (random IV)."""
        plaintext = "same-key"
        a = encrypt(plaintext)
        b = encrypt(plaintext)
        assert a != b  # Fernet uses random IV
        # But both must decrypt to the same value
        assert decrypt(a) == decrypt(b) == plaintext

    def test_decrypt_wrong_key_raises(self):
        """Decrypting with a different key must raise InvalidToken."""
        import app.crypto as crypto_mod
        import app.config as config_mod

        orig_key = getattr(config_mod.settings, "TOKEN_ENCRYPTION_KEY", "")
        orig_fernet = crypto_mod._fernet_instance
        try:
            # Encrypt with current key
            encrypted = encrypt("secret-value")

            # Switch to different key
            config_mod.settings.TOKEN_ENCRYPTION_KEY = "completely-different-key-xyz"
            crypto_mod._fernet_instance = None  # Reset cache

            with pytest.raises(InvalidToken):
                decrypt(encrypted)
        finally:
            config_mod.settings.TOKEN_ENCRYPTION_KEY = orig_key
            crypto_mod._fernet_instance = orig_fernet

    def test_decrypt_corrupted_data_raises(self):
        """Decrypting corrupted ciphertext must raise InvalidToken."""
        with pytest.raises(InvalidToken):
            decrypt("not-a-valid-fernet-token")

    def test_decrypt_empty_string_raises(self):
        """Decrypting empty string must raise InvalidToken."""
        with pytest.raises(InvalidToken):
            decrypt("")


class TestCredentialEncryption:
    """Verify encryption works for realistic broker credential values."""

    def test_upstox_api_key(self):
        """Upstox API key format must encrypt/decrypt correctly."""
        key = "615b1297-d443-3b39-ba19-1927fbcdddc7"
        assert decrypt(encrypt(key)) == key

    def test_upstox_api_secret(self):
        """Upstox API secret format must encrypt/decrypt correctly."""
        secret = "abc123def456ghi789"
        assert decrypt(encrypt(secret)) == secret

    def test_fyers_app_id(self):
        """FYERS App ID format must encrypt/decrypt correctly."""
        app_id = "SPXXXXE7-100"
        assert decrypt(encrypt(app_id)) == app_id

    def test_fyers_secret_id(self):
        """FYERS Secret ID format must encrypt/decrypt correctly."""
        secret = "a1b2c3d4e5f6g7h8i9j0"
        assert decrypt(encrypt(secret)) == secret

    def test_analytics_token(self):
        """Upstox Analytics Token (long JWT-like string) must work."""
        token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9." + "x" * 200
        assert decrypt(encrypt(token)) == token

    def test_access_token(self):
        """OAuth access token must encrypt/decrypt correctly."""
        token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test"
        assert decrypt(encrypt(token)) == token

    def test_refresh_token(self):
        """FYERS refresh token must encrypt/decrypt correctly."""
        token = "eyJhbGciOiJIUzI1NiJ9.refresh_token_data_here"
        assert decrypt(encrypt(token)) == token
