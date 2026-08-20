# tests/unit/trading_engine/test_signal_evidence.py
#
# Checkpoint 64.18 §5-9: coverage for the generic signal-evidence
# formatter - proves every field comes from the signal's OWN already-
# computed `evidence`/`price`/`direction`, never a new calculation.
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe, Version
from intraday.trading_engine.strategy_execution.contracts import StrategyDirection, StrategySignal
from intraday.trading_engine.strategy_execution.evidence import (
    SIGNAL_EVIDENCE_SCHEMA_VERSION,
    build_signal_evidence,
    describe_atr_volatility_breakout_evidence,
    describe_ema_crossover_evidence,
    describe_sma_trend_filter_evidence,
)

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
WHEN = datetime(2026, 8, 20, 5, 0, tzinfo=UTC)


def _feature(name: str, value: Decimal) -> FeatureValue:
    return FeatureValue(
        feature_name=name,
        feature_version=Version("v1"),
        instrument_id=RELIANCE,
        timeframe=Timeframe.FIVE_MINUTE,
        timestamp=WHEN,
        value=value,
    )


def _signal(
    *,
    strategy_id: str,
    evidence: tuple[FeatureValue, ...],
    direction: StrategyDirection,
    price: Decimal,
) -> StrategySignal:
    return StrategySignal(
        strategy_id=strategy_id,
        specification_version="v1",
        code_version="v1",
        configuration_version="v1",
        instrument_id=RELIANCE,
        timeframe=Timeframe.FIVE_MINUTE,
        timestamp=WHEN,
        direction=direction,
        price=price,
        evidence=evidence,
    )


def test_ema_crossover_evidence_uses_the_real_fast_and_slow_values() -> None:
    signal = _signal(
        strategy_id="ema_crossover",
        evidence=(_feature("ema_12", Decimal("1234.50")), _feature("ema_26", Decimal("1229.40"))),
        direction=StrategyDirection.BULLISH,
        price=Decimal("1236.00"),
    )

    evidence = describe_ema_crossover_evidence(signal)

    assert evidence.schema_version == SIGNAL_EVIDENCE_SCHEMA_VERSION
    assert evidence.strategy_id == "ema_crossover"
    labels_to_values = {f.label: f.value for f in evidence.fields}
    assert labels_to_values["Fast EMA"] == "1234.50"
    assert labels_to_values["Slow EMA"] == "1229.40"
    assert labels_to_values["Price"] == "1236.00"
    assert labels_to_values["Crossover"] == "Bullish"


def test_sma_trend_filter_evidence_computes_distance_from_the_real_sma_and_price() -> None:
    signal = _signal(
        strategy_id="sma_trend_filter",
        evidence=(_feature("sma_30", Decimal("100")),),
        direction=StrategyDirection.BULLISH,
        price=Decimal("101"),
    )

    evidence = describe_sma_trend_filter_evidence(signal)

    labels_to_values = {f.label: f.value for f in evidence.fields}
    assert labels_to_values["SMA"] == "100"
    assert labels_to_values["Price"] == "101"
    assert labels_to_values["Distance %"] == "1.00%"
    assert labels_to_values["Direction"] == "Bullish"


def test_atr_volatility_breakout_evidence_uses_the_real_atr_value() -> None:
    signal = _signal(
        strategy_id="atr_volatility_breakout",
        evidence=(_feature("atr_14", Decimal("12.5")),),
        direction=StrategyDirection.BEARISH,
        price=Decimal("2500"),
    )

    evidence = describe_atr_volatility_breakout_evidence(signal)

    labels_to_values = {f.label: f.value for f in evidence.fields}
    assert labels_to_values["ATR"] == "12.5"
    assert labels_to_values["Price"] == "2500"
    assert labels_to_values["Breakout"] == "Bearish"


def test_build_signal_evidence_dispatches_by_strategy_id() -> None:
    signal = _signal(
        strategy_id="ema_crossover",
        evidence=(_feature("ema_12", Decimal("1")), _feature("ema_26", Decimal("2"))),
        direction=StrategyDirection.NEUTRAL,
        price=Decimal("1.5"),
    )

    evidence = build_signal_evidence(signal)

    assert evidence is not None
    assert evidence.strategy_id == "ema_crossover"


def test_build_signal_evidence_returns_none_for_an_unregistered_strategy() -> None:
    """An honest absence - never a fabricated empty evidence record for
    a strategy this module doesn't know how to describe."""
    signal = _signal(
        strategy_id="some_future_strategy",
        evidence=(),
        direction=StrategyDirection.NEUTRAL,
        price=Decimal("1"),
    )

    assert build_signal_evidence(signal) is None


def test_missing_evidence_values_are_shown_as_not_provided_never_fabricated() -> None:
    signal = _signal(
        strategy_id="ema_crossover",
        evidence=(),  # no feature values supplied at all
        direction=StrategyDirection.BULLISH,
        price=Decimal("100"),
    )

    evidence = describe_ema_crossover_evidence(signal)

    labels_to_values = {f.label: f.value for f in evidence.fields}
    assert labels_to_values["Fast EMA"] == "Not provided"
    assert labels_to_values["Slow EMA"] == "Not provided"
