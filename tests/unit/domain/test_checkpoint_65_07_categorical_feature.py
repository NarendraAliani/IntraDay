# tests/unit/domain/test_checkpoint_65_07_categorical_feature.py
#
# Checkpoint 65.07 - CATEGORICAL FEATURE CONTRACT EXTENSION. Targeted,
# reduced test set per the checkpoint directive's Part O (no full
# platform regression). Covers exactly the contracts this checkpoint
# touched: `FeatureValue` (unchanged), `CategoricalFeatureValue` (new
# sibling type), `AnyFeatureValue` union, `FieldDataType.CATEGORICAL`
# (registry), and `FeatureSeriesComputer`'s widened dispatcher typing
# (coordinator). No market_regime feature exists - none of these tests
# reference BULL/BEAR/SIDEWAYS/TRANSITION or any concrete business
# category.
from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from intraday.domain.feature.contracts import (
    AnyFeatureValue,
    CategoricalFeatureValue,
    FeatureValue,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe, Version
from intraday.signal_intelligence.feature_engine.field_registry import (
    FieldAvailability,
    FieldCategory,
    FieldDataType,
    FieldDefinition,
)

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
TS = datetime(2026, 1, 1, 9, 20, tzinfo=UTC)


def _categorical(category: str = "TEST_CATEGORY_A") -> CategoricalFeatureValue:
    return CategoricalFeatureValue(
        feature_name="test_categorical_field",
        feature_version=Version(value="v1"),
        instrument_id=RELIANCE,
        timeframe=Timeframe.FIVE_MINUTE,
        timestamp=TS,
        category=category,
    )


def _numeric(value: Decimal = Decimal("1.5")) -> FeatureValue:
    return FeatureValue(
        feature_name="ema_20",
        feature_version=Version(value="v1"),
        instrument_id=RELIANCE,
        timeframe=Timeframe.FIVE_MINUTE,
        timestamp=TS,
        value=value,
    )


# ---------------------------------------------------------------------------
# Numeric FeatureValue remains Decimal-only and unaffected (Part P).
# ---------------------------------------------------------------------------


def test_numeric_feature_value_still_requires_decimal() -> None:
    with pytest.raises(TypeError):
        FeatureValue(
            feature_name="ema_20",
            feature_version=Version(value="v1"),
            instrument_id=RELIANCE,
            timeframe=Timeframe.FIVE_MINUTE,
            timestamp=TS,
            value=1.5,  # type: ignore[arg-type]
        )


def test_numeric_feature_value_construction_unchanged() -> None:
    fv = _numeric()
    assert fv.value == Decimal("1.5")
    assert isinstance(fv.value, Decimal)


# ---------------------------------------------------------------------------
# CategoricalFeatureValue: type safety, provenance, frozen/immutable.
# ---------------------------------------------------------------------------


def test_categorical_feature_value_constructs() -> None:
    cv = _categorical("TEST_CATEGORY_A")
    assert cv.category == "TEST_CATEGORY_A"
    assert cv.feature_name == "test_categorical_field"
    assert cv.instrument_id == RELIANCE
    assert cv.timeframe == Timeframe.FIVE_MINUTE
    assert cv.timestamp == TS


def test_categorical_feature_value_rejects_non_str_category() -> None:
    with pytest.raises(TypeError):
        CategoricalFeatureValue(
            feature_name="test_categorical_field",
            feature_version=Version(value="v1"),
            instrument_id=RELIANCE,
            timeframe=Timeframe.FIVE_MINUTE,
            timestamp=TS,
            category=Decimal("1"),  # type: ignore[arg-type]
        )


def test_categorical_feature_value_rejects_empty_category() -> None:
    with pytest.raises(ValueError):
        _categorical("   ")


def test_categorical_feature_value_rejects_empty_name() -> None:
    with pytest.raises(ValueError):
        CategoricalFeatureValue(
            feature_name="  ",
            feature_version=Version(value="v1"),
            instrument_id=RELIANCE,
            timeframe=Timeframe.FIVE_MINUTE,
            timestamp=TS,
            category="TEST_CATEGORY_A",
        )


def test_categorical_feature_value_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError):
        CategoricalFeatureValue(
            feature_name="test_categorical_field",
            feature_version=Version(value="v1"),
            instrument_id=RELIANCE,
            timeframe=Timeframe.FIVE_MINUTE,
            timestamp=datetime(2026, 1, 1, 9, 20),
            category="TEST_CATEGORY_A",
        )


def test_categorical_feature_value_is_frozen() -> None:
    cv = _categorical()
    with pytest.raises(FrozenInstanceError):
        cv.category = "OTHER"  # type: ignore[misc]


def test_categorical_feature_value_has_no_decimal_value_field() -> None:
    """Categorical and numeric values are not accidentally interchangeable
    - `CategoricalFeatureValue` has no `.value` attribute a caller could
    mistakenly treat as a Decimal, and `FeatureValue` has no `.category`."""
    cv = _categorical()
    fv = _numeric()
    assert not hasattr(cv, "value")
    assert not hasattr(fv, "category")


def test_categorical_and_numeric_are_distinct_types() -> None:
    cv = _categorical()
    fv = _numeric()
    assert type(cv) is not type(fv)
    assert not isinstance(cv, FeatureValue)
    assert not isinstance(fv, CategoricalFeatureValue)


# ---------------------------------------------------------------------------
# AnyFeatureValue union - both members flow through it, neither is coerced.
# ---------------------------------------------------------------------------


def test_any_feature_value_accepts_both_members() -> None:
    values: tuple[AnyFeatureValue, ...] = (_numeric(), _categorical())
    assert isinstance(values[0], FeatureValue)
    assert isinstance(values[1], CategoricalFeatureValue)


# ---------------------------------------------------------------------------
# FieldDataType / FieldDefinition: registry can identify a categorical field
# (Part K - test-only proof fixture, never registered in production _FIELDS).
# ---------------------------------------------------------------------------


def test_field_data_type_has_categorical_member() -> None:
    assert FieldDataType.CATEGORICAL.value == "CATEGORICAL"
    assert FieldDataType.DECIMAL.value == "DECIMAL"
    assert FieldDataType.CATEGORICAL != FieldDataType.DECIMAL


def test_field_definition_can_describe_a_categorical_field() -> None:
    """Test-only fixture proving `FieldDefinition` accepts
    `FieldDataType.CATEGORICAL` through the SAME dataclass numeric fields
    already use - no second registry, no CategoricalFeatureRegistry. This
    field is never added to the production `_FIELDS` tuple and is not
    `market_regime`."""
    fixture = FieldDefinition(
        field_id="test_categorical_fixture",
        display_name="Test Categorical Fixture",
        category=FieldCategory.DERIVED_FEATURE,
        data_type=FieldDataType.CATEGORICAL,
        source="test-only",
        timeframe_support="any",
        required_inputs=(),
        availability=FieldAvailability.HISTORICAL_AND_SAMPLE,
        version="v1",
        description="Checkpoint 65.07 test-only proof fixture - not a production field.",
    )
    assert fixture.data_type is FieldDataType.CATEGORICAL


def test_production_registry_does_not_contain_market_regime() -> None:
    # Checkpoint 65.08 update: `market_regime` IS NOW a registered
    # production categorical feature - see
    # signal_intelligence.feature_engine.market_regime and
    # test_checkpoint_65_08_market_regime.py for its dedicated coverage.
    # This 65.07 test is KEPT (per the checkpoint directive's "do not
    # delete or clean up carried-forward work"), but its assertion is
    # updated to reflect the 65.08 reality it now describes: the
    # CATEGORICAL infrastructure 65.07 proved now has exactly ONE real
    # production consumer, and it is `market_regime`.
    from intraday.signal_intelligence.feature_engine.field_registry import get_field, list_fields

    field = get_field("market_regime")
    assert field is not None
    assert field.data_type == FieldDataType.CATEGORICAL
    categorical_fields = [f for f in list_fields() if f.data_type == FieldDataType.CATEGORICAL]
    assert [f.field_id for f in categorical_fields] == ["market_regime"]


# ---------------------------------------------------------------------------
# Dispatcher typing: FeatureSeriesComputer accepts a categorical-returning
# callable without weakening a numeric-only one (Part H). No categorical
# dispatch logic exists in the real `compute_feature_series` - this proves
# only the TYPE SEAM, using a local fake, never real dispatcher wiring.
# ---------------------------------------------------------------------------


def test_feature_series_computer_type_accepts_categorical_returning_callable() -> None:
    from intraday.domain.market_data.contracts import Bar
    from intraday.trading_engine.strategy_execution.coordinator import FeatureSeriesComputer

    def fake_categorical_dispatcher(
        field_id: str, bars: tuple[Bar, ...]
    ) -> tuple[AnyFeatureValue, ...]:
        return (_categorical(),)

    computer: FeatureSeriesComputer = fake_categorical_dispatcher
    result = computer("test_categorical_field", ())
    assert isinstance(result[0], CategoricalFeatureValue)


def test_feature_series_computer_type_still_accepts_numeric_only_callable() -> None:
    """Existing numeric-only dispatchers remain valid - the union widening
    does not require every dispatcher to also handle categorical output."""
    from intraday.domain.market_data.contracts import Bar
    from intraday.trading_engine.strategy_execution.coordinator import FeatureSeriesComputer

    def fake_numeric_dispatcher(field_id: str, bars: tuple[Bar, ...]) -> tuple[FeatureValue, ...]:
        return (_numeric(),)

    computer: FeatureSeriesComputer = fake_numeric_dispatcher
    result = computer("ema_20", ())
    assert isinstance(result[0], FeatureValue)
