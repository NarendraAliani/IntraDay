# tests/unit/infrastructure/persistence/test_encryption.py
#
# Checkpoint 22: encryption-at-rest round-trip and tamper-detection
# coverage for infrastructure/persistence/encryption.py. Uses only
# obviously-fake placeholder secrets, never anything resembling a real
# credential.
from __future__ import annotations

import pytest

from intraday.infrastructure.persistence.encryption import (
    DecryptionError,
    decrypt_value,
    encrypt_value,
)


def test_encrypt_then_decrypt_round_trips() -> None:
    plaintext = "fake-secret-value-not-real"  # noqa: S105

    ciphertext = encrypt_value(plaintext)
    decrypted = decrypt_value(ciphertext)

    assert decrypted == plaintext


def test_ciphertext_never_contains_the_plaintext() -> None:
    plaintext = "fake-super-secret-token-xyz"  # noqa: S105

    ciphertext = encrypt_value(plaintext)

    assert plaintext.encode("utf-8") not in ciphertext


def test_two_encryptions_of_the_same_value_differ() -> None:
    """Fernet includes a random IV per call - proves this isn't a
    deterministic/ECB-style scheme that would leak equality between two
    stored secrets."""
    plaintext = "fake-secret-value-not-real"  # noqa: S105

    first = encrypt_value(plaintext)
    second = encrypt_value(plaintext)

    assert first != second
    assert decrypt_value(first) == decrypt_value(second) == plaintext


def test_corrupted_ciphertext_raises_decryption_error() -> None:
    ciphertext = encrypt_value("fake-secret-value-not-real")
    corrupted = ciphertext[:-4] + b"0000"

    with pytest.raises(DecryptionError) as exc_info:
        decrypt_value(corrupted)

    # The error message must never leak ciphertext or key material.
    assert corrupted not in str(exc_info.value).encode("utf-8", errors="ignore")
