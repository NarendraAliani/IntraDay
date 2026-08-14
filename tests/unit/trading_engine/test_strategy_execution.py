# tests/unit/trading_engine/test_strategy_execution.py
#
# Checkpoint 26 backend test matrix: field registry, parameter schema
# validation, the strategy registry, all three executable strategies,
# and multi-strategy coordinator scenarios A-D (Part 9).
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import Timeframe
from intraday.signal_intelligence.feature_engine.field_registry import (
    FieldCategory,
    get_field,
    list_fields,
)
from intraday.trading_engine.strategy_execution.contracts import (
    ParameterType,
    StrategyConfigurationValues,
    StrategyDirection,
    validate_configuration,
)
from intraday.trading_engine.strategy_execution.coordinator import StrategyExecutionCoordinator
from intraday.trading_engine.strategy_execution.errors import (
    DuplicateStrategyRegistrationError,
    InvalidParameterValueError,
    MissingRequiredParameterError,
    UnknownFieldReferenceError,
    UnknownParameterError,
    UnknownStrategyError,
)
from intraday.trading_engine.strategy_execution.registry import (
    StrategyRegistry,
    build_default_registry,
)
from intraday.trading_engine.strategy_execution.strategies.atr_volatility_breakout import (
    AtrVolatilityBreakoutStrategy,
)
from intraday.trading_engine.strategy_execution.strategies.ema_crossover import (
    EmaCrossoverStrategy,
)
from intraday.trading_engine.strategy_execution.strategies.sma_trend_filter import (
    SmaTrendFilterStrategy,
)

INSTRUMENT = "NSE:TESTCO"
KNOWN_FIELD_IDS = frozenset(f.field_id for f in list_fields())


def _bars(prices: list[str], *, start_minute: int = 0) -> tuple[Bar, ...]:
    base = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)
    bars = []
    for i, price_str in enumerate(prices):
        price = Decimal(price_str)
        ts = base + timedelta(minutes=start_minute + i)
        bars.append(
            Bar(
                instrument_id=INSTRUMENT,
                timeframe=Timeframe.ONE_MINUTE,
                timestamp=ts,
                open=price - 1,
                high=price + 1,
                low=price - 2,
                close=price,
                volume=Decimal("0"),
            )
        )
    return tuple(bars)


def _rising_bars(count: int, *, start: int = 100) -> tuple[Bar, ...]:
    return _bars([str(start + i) for i in range(count)])


def _flat_bars(count: int, *, price: int = 100) -> tuple[Bar, ...]:
    return _bars([str(price)] * count)


def _fake_compute(field_id: str, bars: tuple[Bar, ...]):
    from intraday.signal_intelligence.feature_engine.atr import compute_average_true_range
    from intraday.signal_intelligence.feature_engine.definitions import (
        AverageTrueRangeDefinition,
        ExponentialMovingAverageDefinition,
        SimpleMovingAverageDefinition,
    )
    from intraday.signal_intelligence.feature_engine.ema import (
        compute_exponential_moving_average,
    )
    from intraday.signal_intelligence.feature_engine.sma import compute_simple_moving_average

    kind, _, raw_lookback = field_id.partition("_")
    lookback = int(raw_lookback)
    if kind == "sma":
        return compute_simple_moving_average(SimpleMovingAverageDefinition(lookback), bars)
    if kind == "ema":
        return compute_exponential_moving_average(
            ExponentialMovingAverageDefinition(lookback), bars
        )
    if kind == "atr":
        return compute_average_true_range(AverageTrueRangeDefinition(lookback), bars)
    raise ValueError(field_id)


# --- Field registry (Part 10) ------------------------------------------------


def test_field_registry_only_lists_implemented_fields() -> None:
    field_ids = {f.field_id for f in list_fields()}
    assert field_ids == {"open", "high", "low", "close", "volume", "sma", "ema", "atr"}


def test_field_registry_never_lists_unimplemented_indicators() -> None:
    field_ids = {f.field_id for f in list_fields()}
    for forbidden in ("rsi", "macd", "vwap", "supertrend", "bollinger", "bollinger_bands"):
        assert forbidden not in field_ids


def test_field_registry_deterministic_order() -> None:
    assert [f.field_id for f in list_fields()] == [f.field_id for f in list_fields()]


def test_field_registry_derived_features_declare_required_inputs() -> None:
    sma = get_field("sma")
    assert sma is not None
    assert sma.category == FieldCategory.DERIVED_FEATURE
    assert sma.required_inputs == ("close",)


def test_field_registry_get_unknown_field_returns_none() -> None:
    assert get_field("nonexistent") is None


# --- Strategy registry (Part 8) ----------------------------------------------


def test_registry_lists_at_least_three_distinct_strategies() -> None:
    registry = build_default_registry()
    ids = [s.strategy_id for s in registry.list()]
    assert len(ids) >= 3
    assert len(ids) == len(set(ids))


def test_registry_deterministic_listing() -> None:
    registry = build_default_registry()
    assert [s.strategy_id for s in registry.list()] == [s.strategy_id for s in registry.list()]


def test_registry_rejects_duplicate_registration() -> None:
    registry = StrategyRegistry()
    registry.register(EmaCrossoverStrategy())
    with pytest.raises(DuplicateStrategyRegistrationError):
        registry.register(EmaCrossoverStrategy())


def test_registry_rejects_unknown_strategy_lookup() -> None:
    registry = StrategyRegistry()
    with pytest.raises(UnknownStrategyError):
        registry.get("nonexistent")


def test_registry_activate_and_deactivate() -> None:
    registry = build_default_registry()
    registry.activate("ema_crossover")
    assert registry.is_active("ema_crossover")
    assert "ema_crossover" in [s.strategy_id for s in registry.get_active()]
    registry.deactivate("ema_crossover")
    assert not registry.is_active("ema_crossover")


def test_registry_activate_unknown_strategy_rejected() -> None:
    registry = build_default_registry()
    with pytest.raises(UnknownStrategyError):
        registry.activate("nonexistent")


def test_registry_validate_configuration_rejects_invalid() -> None:
    registry = build_default_registry()
    config = StrategyConfigurationValues(
        "ema_crossover", "v1", "v1", "v1", {"fast_lookback": "not-an-int", "slow_lookback": 10}
    )
    with pytest.raises(InvalidParameterValueError):
        registry.validate_configuration("ema_crossover", config, known_field_ids=KNOWN_FIELD_IDS)


# --- Parameter schema validation (Part 4/5) -----------------------------------


def test_validate_configuration_rejects_unknown_parameter() -> None:
    schema = EmaCrossoverStrategy().parameter_schema()
    with pytest.raises(UnknownParameterError):
        validate_configuration(
            schema,
            {"fast_lookback": 5, "slow_lookback": 10, "bogus": 1},
            known_field_ids=frozenset(),
        )


def test_validate_configuration_rejects_missing_required_without_default() -> None:
    schema = SmaTrendFilterStrategy().parameter_schema()
    with pytest.raises(MissingRequiredParameterError):
        validate_configuration(schema, {"lookback": 20}, known_field_ids=frozenset())


def test_validate_configuration_rejects_out_of_range() -> None:
    schema = EmaCrossoverStrategy().parameter_schema()
    with pytest.raises(InvalidParameterValueError):
        validate_configuration(
            schema,
            {"fast_lookback": 0, "slow_lookback": 10},
            known_field_ids=frozenset(),
        )


def test_validate_configuration_accepts_valid_values() -> None:
    schema = AtrVolatilityBreakoutStrategy().parameter_schema()
    validate_configuration(
        schema,
        {"lookback": 14, "atr_multiplier": Decimal("0.5")},
        known_field_ids=frozenset(),
    )


def test_field_reference_parameter_validates_against_known_fields() -> None:
    from intraday.trading_engine.strategy_execution.contracts import (
        ParameterDefinition,
        StrategyParameterSchema,
    )

    schema = StrategyParameterSchema(
        "probe",
        (ParameterDefinition("field", "Field", ParameterType.FIELD_REFERENCE, required=True),),
    )
    with pytest.raises(UnknownFieldReferenceError):
        validate_configuration(schema, {"field": "nonexistent"}, known_field_ids=KNOWN_FIELD_IDS)
    validate_configuration(schema, {"field": "close"}, known_field_ids=KNOWN_FIELD_IDS)


# --- Three genuinely different strategies (Part 3) ----------------------------


def test_ema_crossover_bullish_on_sustained_uptrend() -> None:
    strategy = EmaCrossoverStrategy()
    config = StrategyConfigurationValues(
        "ema_crossover", "v1", "v1", "v1", {"fast_lookback": 3, "slow_lookback": 6}
    )
    bars = _rising_bars(20)
    from intraday.signal_intelligence.feature_engine.definitions import (
        ExponentialMovingAverageDefinition,
    )
    from intraday.signal_intelligence.feature_engine.ema import (
        compute_exponential_moving_average,
    )

    fast = compute_exponential_moving_average(ExponentialMovingAverageDefinition(3), bars)
    slow = compute_exponential_moving_average(ExponentialMovingAverageDefinition(6), bars)
    features = {"ema_3": fast[-1], "ema_6": slow[-1]}
    signal = strategy.evaluate(bars[-1], features, config)
    assert signal is not None
    assert signal.direction == StrategyDirection.BULLISH


def test_ema_crossover_returns_none_when_warmup_incomplete() -> None:
    strategy = EmaCrossoverStrategy()
    config = StrategyConfigurationValues(
        "ema_crossover", "v1", "v1", "v1", {"fast_lookback": 3, "slow_lookback": 6}
    )
    bars = _rising_bars(20)
    signal = strategy.evaluate(bars[-1], {}, config)
    assert signal is None


def test_sma_trend_filter_neutral_within_band() -> None:
    strategy = SmaTrendFilterStrategy()
    config = StrategyConfigurationValues(
        "sma_trend_filter", "v1", "v1", "v1", {"lookback": 5, "band_percent": Decimal("5")}
    )
    bars = _flat_bars(10)
    from intraday.signal_intelligence.feature_engine.definitions import (
        SimpleMovingAverageDefinition,
    )
    from intraday.signal_intelligence.feature_engine.sma import compute_simple_moving_average

    sma = compute_simple_moving_average(SimpleMovingAverageDefinition(5), bars)
    signal = strategy.evaluate(bars[-1], {"sma_5": sma[-1]}, config)
    assert signal is not None
    assert signal.direction == StrategyDirection.NEUTRAL


def test_atr_volatility_breakout_bullish_on_large_upward_move() -> None:
    strategy = AtrVolatilityBreakoutStrategy()
    config = StrategyConfigurationValues(
        "atr_volatility_breakout",
        "v1",
        "v1",
        "v1",
        {"lookback": 5, "atr_multiplier": Decimal("0.1")},
    )
    bars = _flat_bars(10)
    from intraday.signal_intelligence.feature_engine.atr import compute_average_true_range
    from intraday.signal_intelligence.feature_engine.definitions import (
        AverageTrueRangeDefinition,
    )

    atr = compute_average_true_range(AverageTrueRangeDefinition(5), bars)
    signal = strategy.evaluate(bars[-1], {"atr_5": atr[-1]}, config)
    assert signal is not None
    # bar.close - bar.open == 1 for every synthetic bar above, threshold is
    # small (0.1 * ATR) so this is a genuine breakout, not a coincidence.
    assert signal.direction == StrategyDirection.BULLISH


def test_three_strategies_have_distinct_required_features() -> None:
    """Part 3: the three strategies must genuinely differ, not be
    cosmetic variations - proven here by distinct required-feature
    shapes for the same configuration intent."""
    ema_config = StrategyConfigurationValues(
        "ema_crossover", "v1", "v1", "v1", {"fast_lookback": 5, "slow_lookback": 10}
    )
    sma_config = StrategyConfigurationValues(
        "sma_trend_filter", "v1", "v1", "v1", {"lookback": 10, "band_percent": Decimal("1")}
    )
    atr_config = StrategyConfigurationValues(
        "atr_volatility_breakout",
        "v1",
        "v1",
        "v1",
        {"lookback": 10, "atr_multiplier": Decimal("1")},
    )
    ema_features = EmaCrossoverStrategy().required_features(ema_config)
    sma_features = SmaTrendFilterStrategy().required_features(sma_config)
    atr_features = AtrVolatilityBreakoutStrategy().required_features(atr_config)

    assert len(ema_features) == 2  # two-EMA crossover shape
    assert len(sma_features) == 1  # single-feature-vs-price shape
    assert len(atr_features) == 1  # volatility-threshold shape
    assert {f[:3] for f in ema_features} == {"ema"}
    assert sma_features[0].startswith("sma")
    assert atr_features[0].startswith("atr")


# --- Multi-strategy coordinator (Part 9) --------------------------------------


def _coordinator(registry: StrategyRegistry) -> StrategyExecutionCoordinator:
    return StrategyExecutionCoordinator(registry, _fake_compute)


def _standard_configs() -> dict[str, StrategyConfigurationValues]:
    return {
        "ema_crossover": StrategyConfigurationValues(
            "ema_crossover", "v1", "v1", "v1", {"fast_lookback": 3, "slow_lookback": 6}
        ),
        "sma_trend_filter": StrategyConfigurationValues(
            "sma_trend_filter", "v1", "v1", "v1", {"lookback": 5, "band_percent": Decimal("0.1")}
        ),
        "atr_volatility_breakout": StrategyConfigurationValues(
            "atr_volatility_breakout",
            "v1",
            "v1",
            "v1",
            {"lookback": 5, "atr_multiplier": Decimal("0.1")},
        ),
    }


def test_coordinator_scenario_a_all_strategies_succeed() -> None:
    registry = build_default_registry()
    for strategy in registry.list():
        registry.activate(strategy.strategy_id)
    coordinator = _coordinator(registry)
    result = coordinator.run(_rising_bars(20), _standard_configs())
    assert len(result.signals) == 3
    assert result.failures == ()


def test_coordinator_scenario_b_one_strategy_failure_is_isolated() -> None:
    registry = build_default_registry()
    for strategy in registry.list():
        registry.activate(strategy.strategy_id)
    coordinator = _coordinator(registry)

    configs = _standard_configs()
    # Missing required "band_percent" -> KeyError inside SmaTrendFilterStrategy.evaluate
    configs["sma_trend_filter"] = StrategyConfigurationValues(
        "sma_trend_filter", "v1", "v1", "v1", {"lookback": 5}
    )
    result = coordinator.run(_rising_bars(20), configs)

    failed_ids = {f.strategy_id for f in result.failures}
    succeeded_ids = {s.strategy_id for s in result.signals}
    assert failed_ids == {"sma_trend_filter"}
    assert succeeded_ids == {"ema_crossover", "atr_volatility_breakout"}


def test_coordinator_scenario_c_shared_feature_computed_once() -> None:
    """Two strategies configured to require the identical feature_id
    must trigger only one computation - proven by counting calls to an
    instrumented compute function, not by inference."""
    call_log: list[str] = []

    def counting_compute(field_id: str, bars: tuple[Bar, ...]):
        call_log.append(field_id)
        return _fake_compute(field_id, bars)

    registry = StrategyRegistry()
    registry.register(SmaTrendFilterStrategy())
    registry.register(EmaCrossoverStrategy())

    # Reconfigure EMA crossover so it (indirectly) doesn't collide; instead
    # directly prove sharing using two SMA-based configurations pointed at
    # the SAME strategy instance is not representative of "two strategies" -
    # so register a second, distinctly-identified SMA-trend-filter-shaped
    # strategy that requires the same sma_5 field_id as a probe strategy.
    class ProbeStrategy(SmaTrendFilterStrategy):
        strategy_id = "sma_trend_filter_probe"

    registry.register(ProbeStrategy())
    for strategy_id in ("sma_trend_filter", "sma_trend_filter_probe"):
        registry.activate(strategy_id)

    coordinator = StrategyExecutionCoordinator(registry, counting_compute)
    configs = {
        "sma_trend_filter": StrategyConfigurationValues(
            "sma_trend_filter", "v1", "v1", "v1", {"lookback": 5, "band_percent": Decimal("0.1")}
        ),
        "sma_trend_filter_probe": StrategyConfigurationValues(
            "sma_trend_filter_probe",
            "v1",
            "v1",
            "v1",
            {"lookback": 5, "band_percent": Decimal("0.1")},
        ),
    }
    result = coordinator.run(_rising_bars(20), configs)

    assert call_log.count("sma_5") == 1  # computed once, reused for both strategies
    assert len(result.signals) == 2


def test_coordinator_scenario_d_only_required_features_are_computed() -> None:
    call_log: list[str] = []

    def counting_compute(field_id: str, bars: tuple[Bar, ...]):
        call_log.append(field_id)
        return _fake_compute(field_id, bars)

    registry = build_default_registry()
    registry.activate("ema_crossover")
    registry.activate("atr_volatility_breakout")
    coordinator = StrategyExecutionCoordinator(registry, counting_compute)
    configs = _standard_configs()
    coordinator.run(_rising_bars(20), configs)

    assert set(call_log) == {"ema_3", "ema_6", "atr_5"}
    assert "sma_5" not in call_log  # sma_trend_filter was never activated


def test_coordinator_returns_no_signals_for_empty_bars() -> None:
    registry = build_default_registry()
    registry.activate("ema_crossover")
    coordinator = _coordinator(registry)
    result = coordinator.run((), _standard_configs())
    assert result.signals == ()
    assert result.failures == ()


def test_coordinator_skips_strategies_without_a_supplied_configuration() -> None:
    registry = build_default_registry()
    registry.activate("ema_crossover")
    registry.activate("sma_trend_filter")
    coordinator = _coordinator(registry)
    configs = {"ema_crossover": _standard_configs()["ema_crossover"]}
    result = coordinator.run(_rising_bars(20), configs)
    assert {s.strategy_id for s in result.signals} == {"ema_crossover"}
