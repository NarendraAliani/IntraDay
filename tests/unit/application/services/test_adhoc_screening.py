# File: tests/unit/application/services/test_adhoc_screening.py
#
# CHECKPOINT-SCANNER-A, Phase A of SCANNER_BUILDER_ROADMAP.md: pure
# unit tests for `evaluate_condition`/`AdhocScreeningService` -
# fixture bars only, zero DB writes, zero API surface, exactly this
# checkpoint's own testing requirement.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.application.services.adhoc_screening import (
    AdhocScreeningService,
    evaluate_condition,
)
from intraday.domain.market_data.contracts import Bar
from intraday.domain.screening.contracts import (
    ComparisonOperator,
    RuleCombinator,
    ScreeningCondition,
    ScreeningRule,
)
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe

RELIANCE = InstrumentId("NSE:RELIANCE")
TCS = InstrumentId("NSE:TCS")
_BASE = datetime(2026, 9, 1, 4, 0, 0, tzinfo=UTC)


def _bars(closes: list[float], instrument_id: InstrumentId = RELIANCE) -> tuple[Bar, ...]:
    """A simple, ascending, 5-minute-spaced bar series with the given
    close prices - open/high/low set trivially around close, volume
    fixed, exactly enough to drive the feature-engine compute functions
    under test without asserting anything about their own internal math
    (that belongs to each feature's own dedicated test file)."""
    bars = []
    for i, close in enumerate(closes):
        c = Decimal(str(close))
        bars.append(
            Bar(
                instrument_id=instrument_id,
                timeframe=Timeframe.FIVE_MINUTE,
                timestamp=_BASE + timedelta(minutes=5 * i),
                open=c,
                high=c + Decimal("1"),
                low=c - Decimal("1"),
                close=c,
                volume=Decimal("1000"),
            )
        )
    return tuple(bars)


# ---------------------------------------------------------------------
# evaluate_condition - field-vs-constant
# ---------------------------------------------------------------------


def test_field_vs_constant_true_case() -> None:
    bars = _bars([100, 101, 102, 103, 104])
    assert evaluate_condition("close", ComparisonOperator.GREATER_THAN, Decimal("100"), bars) is True


def test_field_vs_constant_false_case() -> None:
    bars = _bars([100, 101, 102, 103, 104])
    assert (
        evaluate_condition("close", ComparisonOperator.LESS_THAN, Decimal("100"), bars) is False
    )


def test_field_vs_constant_equal_and_gte_lte() -> None:
    bars = _bars([100, 101, 102])
    assert evaluate_condition("close", ComparisonOperator.EQUAL, Decimal("102"), bars) is True
    assert (
        evaluate_condition("close", ComparisonOperator.GREATER_THAN_OR_EQUAL, Decimal("102"), bars)
        is True
    )
    assert (
        evaluate_condition("close", ComparisonOperator.LESS_THAN_OR_EQUAL, Decimal("102"), bars)
        is True
    )


def test_rsi_field_vs_constant() -> None:
    """A real indicator (not just raw OHLCV) evaluated against a
    constant - a steadily rising close series should show RSI(14) well
    above 30 once warmed up."""
    bars = _bars([100 + i for i in range(30)])  # 30 bars, steady uptrend
    assert evaluate_condition("rsi_14", ComparisonOperator.GREATER_THAN, Decimal("50"), bars) is True
    assert evaluate_condition("rsi_14", ComparisonOperator.LESS_THAN, Decimal("30"), bars) is False


# ---------------------------------------------------------------------
# evaluate_condition - field-vs-field
# ---------------------------------------------------------------------


def test_field_vs_field_close_above_ema() -> None:
    """A sharp, recent upward jump after a long flat run should put the
    latest close above a slow-reacting EMA(20)."""
    bars = _bars([100] * 25 + [150])
    assert evaluate_condition("close", ComparisonOperator.GREATER_THAN, "ema_20", bars) is True


def test_field_vs_field_close_below_ema() -> None:
    bars = _bars([100] * 25 + [50])
    assert evaluate_condition("close", ComparisonOperator.LESS_THAN, "ema_20", bars) is True
    assert evaluate_condition("close", ComparisonOperator.GREATER_THAN, "ema_20", bars) is False


# ---------------------------------------------------------------------
# graceful handling of insufficient (warm-up) data
# ---------------------------------------------------------------------


def test_insufficient_warmup_data_returns_false_not_an_exception() -> None:
    """EMA(20) needs 20 bars' worth of warm-up (per
    `ExponentialMovingAverageDefinition`/`compute_exponential_moving_average`'s
    own convention) - supplying only 3 bars must NOT raise; it must
    gracefully report "does not currently match"."""
    bars = _bars([100, 101, 102])
    assert evaluate_condition("close", ComparisonOperator.GREATER_THAN, "ema_20", bars) is False


def test_empty_bars_returns_false_not_an_exception() -> None:
    assert evaluate_condition("close", ComparisonOperator.GREATER_THAN, Decimal("100"), ()) is False
    assert evaluate_condition("rsi_14", ComparisonOperator.LESS_THAN, Decimal("30"), ()) is False


# ---------------------------------------------------------------------
# categorical fields
# ---------------------------------------------------------------------


def _uptrend_bars(count: int) -> tuple[Bar, ...]:
    """A steady, strong uptrend - the same shape
    `test_checkpoint_65_08_market_regime.py`'s own `_uptrend_bars`
    fixture uses to reliably drive a BULL classification, reused here
    (not duplicated math, just the same simple linear-increase shape)
    so this test proves the screening layer, not market_regime's own
    classification rules."""
    return _bars([100 + i for i in range(count)])


def test_categorical_field_equal_constant_is_supported() -> None:
    """market_regime resolves to a category string - EQUAL against
    another category string works. A strong, sustained uptrend reliably
    classifies BULL (same fixture shape market_regime's own dedicated
    test file uses) - this test only proves the screening/comparison
    layer handles a categorical resolve+compare correctly, not
    market_regime's own classification rules."""
    bars = _uptrend_bars(45)
    assert evaluate_condition("market_regime_20_9_20", ComparisonOperator.EQUAL, "BULL", bars) is True
    assert (
        evaluate_condition("market_regime_20_9_20", ComparisonOperator.EQUAL, "BEAR", bars) is False
    )


def test_categorical_field_with_non_equal_operator_raises() -> None:
    bars = _uptrend_bars(45)
    with pytest.raises(ValueError, match="not valid for a categorical field"):
        evaluate_condition("market_regime_20_9_20", ComparisonOperator.GREATER_THAN, "BULL", bars)


def test_categorical_vs_numeric_type_mismatch_raises() -> None:
    bars = _uptrend_bars(45)
    with pytest.raises(ValueError, match="type mismatch"):
        evaluate_condition("market_regime_20_9_20", ComparisonOperator.EQUAL, Decimal("1"), bars)


# ---------------------------------------------------------------------
# AdhocScreeningService - AND/OR combination, multi-instrument
# ---------------------------------------------------------------------


def test_screen_and_combinator_requires_every_condition() -> None:
    rule = ScreeningRule(
        conditions=(
            ScreeningCondition("close", ComparisonOperator.GREATER_THAN, Decimal("100")),
            ScreeningCondition("close", ComparisonOperator.LESS_THAN, Decimal("200")),
        ),
        combinator=RuleCombinator.AND,
    )
    bars_by_instrument = {
        str(RELIANCE): _bars([100, 150]),  # 150 > 100 AND 150 < 200 -> match
        str(TCS): _bars([100, 250]),  # 250 > 100 but NOT < 200 -> no match
    }
    service = AdhocScreeningService()
    matches = service.screen(
        rule, (str(RELIANCE), str(TCS)), Timeframe.FIVE_MINUTE, bars_by_instrument
    )
    matched_ids = {m.instrument_id for m in matches}
    assert matched_ids == {str(RELIANCE)}
    assert len(matches) == 1
    assert len(matches[0].matched_condition_details) == 2


def test_screen_or_combinator_requires_any_condition() -> None:
    rule = ScreeningRule(
        conditions=(
            ScreeningCondition("close", ComparisonOperator.LESS_THAN, Decimal("50")),
            ScreeningCondition("close", ComparisonOperator.GREATER_THAN, Decimal("200")),
        ),
        combinator=RuleCombinator.OR,
    )
    bars_by_instrument = {
        str(RELIANCE): _bars([100, 250]),  # matches the 2nd condition only
        str(TCS): _bars([100, 150]),  # matches neither
    }
    service = AdhocScreeningService()
    matches = service.screen(
        rule, (str(RELIANCE), str(TCS)), Timeframe.FIVE_MINUTE, bars_by_instrument
    )
    matched_ids = {m.instrument_id for m in matches}
    assert matched_ids == {str(RELIANCE)}


def test_screen_instrument_with_no_bars_never_matches_but_never_raises() -> None:
    rule = ScreeningRule(
        conditions=(ScreeningCondition("close", ComparisonOperator.GREATER_THAN, Decimal("0")),),
        combinator=RuleCombinator.AND,
    )
    service = AdhocScreeningService()
    matches = service.screen(rule, (str(RELIANCE),), Timeframe.FIVE_MINUTE, {})
    assert matches == ()


# ---------------------------------------------------------------------
# domain contract validation
# ---------------------------------------------------------------------


def test_screening_condition_rejects_empty_field_id() -> None:
    with pytest.raises(ValueError):
        ScreeningCondition("", ComparisonOperator.GREATER_THAN, Decimal("1"))


def test_screening_rule_rejects_empty_conditions() -> None:
    with pytest.raises(ValueError):
        ScreeningRule(conditions=(), combinator=RuleCombinator.AND)
