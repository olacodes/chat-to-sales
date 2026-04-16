"""
app/infra/crypto.py

Symmetric encryption utilities for sensitive credentials (e.g. access tokens).

Design
------
- Uses Fernet (AES-128-CBC + HMAC-SHA256) from the `cryptography` package,
  which ships as a transitive dependency of python-jose[cryptography].
- The secret key is read from ENV: ENCRYPTION_KEY.
  Generate a valid key once and store it securely:
      python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
- Both helpers raise ValueError on misconfiguration rather than silently
  returning garbage, so deployment misconfigurations surface immediately.
"""

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _get_fernet() -> Fernet:
    """Return a Fernet instance backed by the configured ENCRYPTION_KEY."""
    key = get_settings().ENCRYPTION_KEY
    if not key:
        raise ValueError(
            "ENCRYPTION_KEY is not configured. "
            'Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )
    try:
        return Fernet(key.encode())
    except Exception as exc:
        raise ValueError(
            "ENCRYPTION_KEY is not a valid Fernet key. "
            "Re-generate it with Fernet.generate_key()."
        ) from exc


def encrypt_token(token: str) -> str:
    """
    Encrypt a plaintext token and return a URL-safe base64-encoded ciphertext.

    The output is safe to store in a VARCHAR/TEXT column.
    """
    fernet = _get_fernet()
    return fernet.encrypt(token.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    """
    Decrypt a ciphertext produced by encrypt_token().

    Raises:
        ValueError: if the key is misconfigured or the token has been tampered with.
    """
    fernet = _get_fernet()
    try:
        return fernet.decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        # Do not log the ciphertext — it may be sensitive.
        logger.error(
            "Token decryption failed — possible key rotation or data corruption"
        )
        raise ValueError(
            "Failed to decrypt token: invalid key or corrupted ciphertext"
        ) from exc
