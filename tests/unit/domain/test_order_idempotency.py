# tests/unit/domain/test_order_idempotency.py
#
# Checkpoint 34 Part 6/18: idempotency/correlation chain contract.
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from intraday.domain.order.idempotency import (
    DuplicateOrderSubmissionError,
    IdempotencyMapping,
    derive_correlation_id,
)

NOW = datetime(2026, 1, 1, 9, 20, tzinfo=UTC)


def test_derive_correlation_id_is_deterministic() -> None:
    assert derive_correlation_id("abc-123") == derive_correlation_id("abc-123")


def test_derive_correlation_id_truncates_to_30_chars() -> None:
    long_key = "x" * 50
    correlation_id = derive_correlation_id(long_key)
    assert len(correlation_id) == 30


def test_derive_correlation_id_rejects_empty() -> None:
    with pytest.raises(ValueError):
        derive_correlation_id("   ")


def test_idempotency_mapping_requires_utc_timestamp() -> None:
    with pytest.raises(ValueError):
        IdempotencyMapping(
            idempotency_key="k1",
            correlation_id="c1",
            broker_order_id=None,
            order_id="ord-1",
            recorded_at=datetime(2026, 1, 1, 9, 20),  # naive
        )


def test_idempotency_mapping_rejects_empty_key() -> None:
    with pytest.raises(ValueError, match="idempotency_key"):
        IdempotencyMapping(
            idempotency_key="",
            correlation_id="c1",
            broker_order_id=None,
            order_id="ord-1",
            recorded_at=NOW,
        )


def test_duplicate_order_submission_error_carries_original_order_id() -> None:
    error = DuplicateOrderSubmissionError("idem-1", "ord-1")
    assert error.idempotency_key == "idem-1"
    assert error.existing_order_id == "ord-1"
    assert "ord-1" in str(error)
