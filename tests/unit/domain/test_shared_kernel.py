# tests/unit/domain/test_shared_kernel.py
#
# Unit tests for the shared-kernel primitives (Checkpoint 5). Pure Python
# — no Django, database, Redis, broker, or network access, per Checkpoint
# 5 Section 25.
from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from intraday.domain.shared_kernel.contracts import Price, Quantity, Version, ensure_utc


def test_version_requires_non_empty_value() -> None:
    with pytest.raises(ValueError):
        Version(value="   ")


def test_version_is_immutable() -> None:
    version = Version(value="v1")
    with pytest.raises(FrozenInstanceError):
        version.value = "v2"  # type: ignore[misc]


def test_price_rejects_float() -> None:
    with pytest.raises(TypeError):
        Price(amount=1.5)  # type: ignore[arg-type]


def test_price_rejects_negative() -> None:
    with pytest.raises(ValueError):
        Price(amount=Decimal("-1"))


def test_quantity_rejects_zero_or_negative() -> None:
    with pytest.raises(ValueError):
        Quantity(amount=Decimal("0"))


def test_ensure_utc_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError):
        ensure_utc(datetime(2026, 1, 1, 9, 15))


def test_ensure_utc_rejects_non_utc_offset() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    with pytest.raises(ValueError):
        ensure_utc(datetime(2026, 1, 1, 9, 15, tzinfo=ist))


def test_ensure_utc_accepts_utc_datetime() -> None:
    value = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    assert ensure_utc(value) is value


@given(st.decimals(min_value="0.01", max_value="1000000", places=2, allow_nan=False))
def test_price_accepts_any_positive_decimal(amount: Decimal) -> None:
    assert Price(amount=amount).amount == amount


@given(st.decimals(max_value="0", allow_nan=False, allow_infinity=False))
def test_price_rejects_any_negative_decimal(amount: Decimal) -> None:
    if amount < 0:
        with pytest.raises(ValueError):
            Price(amount=amount)
