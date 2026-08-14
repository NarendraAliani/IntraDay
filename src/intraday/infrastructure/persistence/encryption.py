# File: src/intraday/infrastructure/persistence/encryption.py
#
# Checkpoint 22: application-level encryption at rest for operational
# provider credentials (Dhan access token, Telegram bot token, Discord
# webhook URL). Uses `cryptography`'s `Fernet` (AES-128-CBC + HMAC,
# authenticated symmetric encryption) - a well-audited standard-library-
# adjacent primitive, not a hand-rolled cipher.
#
# Key precedence (documented, not silently guessed):
#   1. `SETTINGS_ENCRYPTION_KEY` env var (a real Fernet key, generated via
#      `Fernet.generate_key()`) - the correct value for any non-development
#      use.
#   2. A key deterministically derived from `DJANGO_SECRET_KEY` via
#      SHA-256 - a DEVELOPMENT-ONLY fallback, exactly mirroring
#      `settings/development.py`'s own existing SECRET_KEY placeholder-
#      fallback pattern (Checkpoint 4). Never used in production - see
#      `settings/production.py`'s own equivalent refusal-to-boot pattern
#      for SECRET_KEY; the same reasoning applies here (documented in
#      docs/architecture/PROVIDER_CONNECTIVITY_ARCHITECTURE.md).
#
# This module never logs, prints, or otherwise surfaces a key or a
# decrypted value - callers are responsible for that discipline at their
# own boundary (see infrastructure/api/settings_views.py's masking).
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


class DecryptionError(ValueError):
    """Raised when a stored encrypted value cannot be decrypted with the
    currently configured key - e.g. `SETTINGS_ENCRYPTION_KEY` was
    rotated without re-encrypting existing rows. Never includes the
    ciphertext or any derived key material in its message."""


def _resolve_key() -> bytes:
    raw_key = getattr(settings, "SETTINGS_ENCRYPTION_KEY", "") or ""
    if raw_key:
        return raw_key.encode("utf-8")
    # Development-only fallback - deterministic, so encrypted values
    # remain decryptable across restarts without requiring every
    # developer to generate and manage a real key locally.
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_value(plaintext: str) -> bytes:
    """Encrypts `plaintext` for storage. Returns raw bytes suitable for a
    `BinaryField`. Never called with an empty string by convention -
    callers store `None`/no row for "not configured" rather than
    encrypting an empty value."""
    fernet = Fernet(_resolve_key())
    return fernet.encrypt(plaintext.encode("utf-8"))


def decrypt_value(ciphertext: bytes) -> str:
    """Decrypts a value previously produced by `encrypt_value`. Raises
    `DecryptionError` (never leaks the ciphertext or key) if the value
    cannot be decrypted with the currently configured key."""
    fernet = Fernet(_resolve_key())
    try:
        return fernet.decrypt(bytes(ciphertext)).decode("utf-8")
    except InvalidToken as exc:
        raise DecryptionError(
            "stored value could not be decrypted with the current encryption key"
        ) from exc
