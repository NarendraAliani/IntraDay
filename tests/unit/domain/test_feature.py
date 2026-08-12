# tests/unit/domain/test_feature.py
#
# Unit tests for the FeatureValue contract (Checkpoint 5).
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe, Version

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")


def test_valid_feature_value_constructs() -> None:
    fv = FeatureValue(
        feature_name="ema_20",
        feature_version=Version(value="v1"),
        instrument_id=RELIANCE,
        timeframe=Timeframe.FIVE_MINUTE,
        timestamp=datetime(2026, 1, 1, 9, 20, tzinfo=UTC),
        value=Decimal("101.25"),
    )
    assert fv.feature_name == "ema_20"


def test_feature_value_rejects_empty_name() -> None:
    with pytest.raises(ValueError):
        FeatureValue(
            feature_name="  ",
            feature_version=Version(value="v1"),
            instrument_id=RELIANCE,
            timeframe=Timeframe.FIVE_MINUTE,
            timestamp=datetime(2026, 1, 1, 9, 20, tzinfo=UTC),
            value=Decimal("1"),
        )


def test_feature_value_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError):
        FeatureValue(
            feature_name="ema_20",
            feature_version=Version(value="v1"),
            instrument_id=RELIANCE,
            timeframe=Timeframe.FIVE_MINUTE,
            timestamp=datetime(2026, 1, 1, 9, 20),
            value=Decimal("1"),
        )


def test_feature_value_rejects_float_value() -> None:
    with pytest.raises(TypeError):
        FeatureValue(
            feature_name="ema_20",
            feature_version=Version(value="v1"),
            instrument_id=RELIANCE,
            timeframe=Timeframe.FIVE_MINUTE,
            timestamp=datetime(2026, 1, 1, 9, 20, tzinfo=UTC),
            value=1.5,  # type: ignore[arg-type]
        )
