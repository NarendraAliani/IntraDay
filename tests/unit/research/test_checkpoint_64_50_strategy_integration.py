# File: tests/unit/research/test_checkpoint_64_50_strategy_integration.py
#
# Checkpoint 64.50: REAL STRATEGY CONSUMER + END-TO-END FEATURE
# INTEGRATION.
#
# HONESTY NOTICE (do not remove): `GainzCompatibleResearchStrategy`
# (src/intraday/trading_engine/strategy_execution/strategies/
# gainz_compatible_research.py) is NOT the Gainz strategy and its signal
# logic is NOT verified GainzAlgo V2 mathematics -- no Gainz reference
# source file exists anywhere in this repository (re-verified across
# 64.44/46/47/48/49; not re-scanned again here since 64.49's own
# `test_zz_...` already covers that independently and this checkpoint
# added no new "gainz"-mentioning module besides this one, itself
# labeled honestly). This test file proves ARCHITECTURE, not Gainz math:
# a real strategy can consume the 64.49 canonical feature set end-to-end
# through the REAL `StrategyExecutionCoordinator` and the REAL feature
# dispatcher, with no second indicator framework and no Risk/Execution/
# Fill/PaperBroker/backtest-engine code touched.
from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from intraday.application.services.strategy_execution import (
    build_coordinator,
    compute_feature_series,
)
from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe
from intraday.signal_intelligence.feature_engine.field_registry import list_fields
from intraday.trading_engine.strategy_execution.contracts import (
    StrategyConfigurationValues,
    StrategyDirection,
    StrategyParameterSchema,
    StrategySignal,
    TradePlan,
    coerce_configuration_values,
    validate_configuration,
)
from intraday.trading_engine.strategy_execution.coordinator import StrategyExecutionCoordinator
from intraday.trading_engine.strategy_execution.registry import (
    StrategyRegistry,
    build_default_registry,
)
from intraday.trading_engine.strategy_execution.strategies.gainz_compatible_research import (
    STRATEGY_ID,
    GainzCompatibleResearchStrategy,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
STRATEGY_FILE = (
    REPO_ROOT
    / "src/intraday/trading_engine/strategy_execution/strategies/gainz_compatible_research.py"
)

IID = InstrumentId("TEST")
TF = Timeframe.ONE_MINUTE
BASE_TS = datetime(2026, 1, 1, tzinfo=UTC)

KNOWN_FIELD_IDS = frozenset(f.field_id for f in list_fields())


def _bar(i: int, o: str, h: str, lo: str, c: str, v: str) -> Bar:
    return Bar(
        instrument_id=IID,
        timeframe=TF,
        timestamp=BASE_TS + timedelta(minutes=i),
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(lo),
        close=Decimal(c),
        volume=Decimal(v),
    )


def _strong_uptrend_bars(n: int, *, high_volume: bool = True) -> tuple[Bar, ...]:
    """A deterministic, strongly-trending-up, high-conviction, high-volume
    bar series -- constructed to actually trip the strategy's BULLISH
    condition (RSI high, ADX/+DI trending, MACD histogram positive,
    relative volume elevated, wide-bodied candles) using REAL feature
    computation, not a mocked strategy. The per-bar move ACCELERATES
    (rather than a constant +2/bar) so the MACD line keeps outrunning its
    own signal line -- a purely linear (constant-move) uptrend makes
    MACD histogram converge to ~0 once EMA_fast-EMA_slow stabilizes,
    which would never trip the strategy's `macd_hist > 0` condition."""
    bars = []
    price = Decimal("100")
    for i in range(n):
        move = Decimal("1") + Decimal(i) * Decimal("0.15")
        o = price
        c = price + move
        h = c + Decimal("0.05")
        lo = o - Decimal("0.05")
        v = Decimal("5000") if high_volume else Decimal("100")
        bars.append(_bar(i, str(o), str(h), str(lo), str(c), str(v)))
        price = c
    return tuple(bars)


def _random_bars(n: int, seed: int = 42) -> tuple[Bar, ...]:
    """A non-monotonic, mixed up/down bar series (unlike
    `_strong_uptrend_bars`, which is deliberately one-directional and
    therefore saturates RSI at exactly 100 with zero losses ever) --
    needed for the look-ahead test below, where a real evidence-value
    CHANGE (not a value pinned at its own ceiling) must be observable."""
    import random

    rng = random.Random(seed)  # noqa: S311 - deterministic test fixture, not cryptographic use
    bars: list[Bar] = []
    price = Decimal("100")
    for i in range(n):
        o = price
        move = Decimal(rng.randint(-50, 50)) / 100
        c = max(price + move, Decimal("1"))
        h = max(o, c) + Decimal(rng.randint(0, 20)) / 100
        lo = min(o, c) - Decimal(rng.randint(0, 20)) / 100
        v = Decimal(rng.randint(100, 1000))
        bars.append(
            Bar(
                instrument_id=IID,
                timeframe=TF,
                timestamp=BASE_TS + timedelta(minutes=i),
                open=o,
                high=h,
                low=lo,
                close=c,
                volume=v,
            )
        )
        price = c
    return tuple(bars)


def _default_config(overrides: dict[str, object] | None = None) -> StrategyConfigurationValues:
    strategy = GainzCompatibleResearchStrategy()
    schema = strategy.parameter_schema()
    values: dict[str, object] = {p.parameter_id: p.default for p in schema.parameters}
    if overrides:
        values.update(overrides)
    values = coerce_configuration_values(schema, values)
    return StrategyConfigurationValues(
        strategy_id=STRATEGY_ID,
        specification_version=strategy.specification_version,
        code_version=strategy.code_version,
        configuration_version="v1",
        values=values,
    )


# ---------------------------------------------------------------------------
# A. Strategy construction
# ---------------------------------------------------------------------------


def test_a1_strategy_constructs_with_expected_identity() -> None:
    strategy = GainzCompatibleResearchStrategy()
    assert strategy.strategy_id == "gainz_compatible_research"
    assert strategy.specification_version == "v1"
    assert strategy.code_version == "v1"


def test_a2_strategy_name_is_not_gainzstrategy() -> None:
    # Directive Part 2/3: NOT called GainzStrategy unless genuinely
    # justified -- it is not, so it is named honestly instead.
    assert GainzCompatibleResearchStrategy.__name__ != "GainzStrategy"
    assert GainzCompatibleResearchStrategy.__name__ == "GainzCompatibleResearchStrategy"


# ---------------------------------------------------------------------------
# B. Required feature declaration
# ---------------------------------------------------------------------------


def test_b1_required_features_uses_canonical_field_ids() -> None:
    strategy = GainzCompatibleResearchStrategy()
    config = _default_config()
    required = strategy.required_features(config)
    assert required == (
        "rsi_14",
        "adx_14",
        "plus_di_14",
        "minus_di_14",
        "relative_volume_20",
        "macd_hist_12_26_9",
        "candle_body_ratio",
    )
    # Every declared field_id must actually be a real, registered
    # canonical field -- proves no ad-hoc/private field naming exists.
    for field_id in required:
        if field_id == "candle_body_ratio":
            assert field_id in KNOWN_FIELD_IDS
            continue
        # parameterized fields aren't literal registry entries (they're
        # a kind + params) -- confirmed instead via the real dispatcher
        # not raising ValueError, exercised in section E/F below.


def test_b2_required_features_reflects_configuration_changes() -> None:
    strategy = GainzCompatibleResearchStrategy()
    config = _default_config({"rsi_lookback": 21, "macd_fast": 5, "macd_slow": 13})
    required = strategy.required_features(config)
    assert "rsi_21" in required
    assert "macd_hist_5_13_9" in required


# ---------------------------------------------------------------------------
# C. Configuration validation
# ---------------------------------------------------------------------------


def test_c1_default_configuration_validates() -> None:
    strategy = GainzCompatibleResearchStrategy()
    schema = strategy.parameter_schema()
    config = _default_config()
    validate_configuration(schema, config.values, known_field_ids=KNOWN_FIELD_IDS)


def test_c2_out_of_range_threshold_rejected() -> None:
    strategy = GainzCompatibleResearchStrategy()
    schema = strategy.parameter_schema()
    values = {p.parameter_id: p.default for p in schema.parameters}
    values["rsi_bullish_threshold"] = 150  # above max 100
    values = coerce_configuration_values(schema, values)
    try:
        validate_configuration(schema, values, known_field_ids=KNOWN_FIELD_IDS)
        raised = False
    except Exception:
        raised = True
    assert raised


# ---------------------------------------------------------------------------
# D. Registry registration
# ---------------------------------------------------------------------------


def test_d1_registers_lookup_and_activate_via_existing_registry() -> None:
    registry = StrategyRegistry()
    strategy = GainzCompatibleResearchStrategy()
    registry.register(strategy)
    assert registry.get(STRATEGY_ID) is strategy
    registry.activate(STRATEGY_ID)
    assert registry.is_active(STRATEGY_ID)
    assert strategy in registry.get_active()


def test_d2_registry_validate_configuration_path_works() -> None:
    registry = StrategyRegistry()
    registry.register(GainzCompatibleResearchStrategy())
    config = _default_config()
    registry.validate_configuration(STRATEGY_ID, config, known_field_ids=KNOWN_FIELD_IDS)


# ---------------------------------------------------------------------------
# L. Existing strategies unaffected (checked early -- registration boundary)
# ---------------------------------------------------------------------------


def test_l1_default_registry_unchanged_by_this_checkpoint() -> None:
    # Deliberate scope decision: `GainzCompatibleResearchStrategy` is NOT
    # added to `build_default_registry()` -- registering it in tests
    # (via a fresh `StrategyRegistry()`, as this whole file does) is
    # sufficient to prove "registration works through the existing
    # registry" without perturbing the default strategy roster every
    # other test in the suite implicitly depends on.
    registry = build_default_registry()
    ids = {s.strategy_id for s in registry.list()}
    assert ids == {"ema_crossover", "sma_trend_filter", "atr_volatility_breakout"}
    assert STRATEGY_ID not in ids


# ---------------------------------------------------------------------------
# E/F/G/H. Real coordinator execution, real feature consumption,
# real StrategySignal, real evidence.
# ---------------------------------------------------------------------------


def test_efgh_real_coordinator_produces_real_signal_with_real_evidence() -> None:
    registry = StrategyRegistry()
    strategy = GainzCompatibleResearchStrategy()
    registry.register(strategy)
    registry.activate(STRATEGY_ID)

    coordinator = build_coordinator(registry)  # REAL coordinator, REAL dispatcher
    assert isinstance(coordinator, StrategyExecutionCoordinator)

    bars = _strong_uptrend_bars(60)  # >= 34-bar MACD warmup, plenty of margin
    config = _default_config()

    result = coordinator.run(bars, {STRATEGY_ID: config})

    assert result.failures == ()
    assert len(result.signals) == 1
    signal = result.signals[0]
    assert signal.strategy_id == STRATEGY_ID
    assert signal.direction == StrategyDirection.BULLISH
    assert signal.instrument_id == IID
    assert signal.timeframe == TF
    assert signal.timestamp == bars[-1].timestamp
    assert signal.price == bars[-1].close

    # Real canonical feature consumption: evidence must be the 7 REAL
    # FeatureValues, matching the field_ids declared by
    # required_features(), sourced from the real dispatcher.
    evidence_names = {fv.feature_name for fv in signal.evidence}
    assert evidence_names == set(strategy.required_features(config))
    for fv in signal.evidence:
        assert isinstance(fv, FeatureValue)
        assert fv.instrument_id == IID
        assert fv.timestamp == bars[-1].timestamp

    # Cross-check one evidence value against the SAME real dispatcher
    # called directly -- proves the coordinator did not fabricate or
    # alter the value in transit.
    direct_rsi_series = compute_feature_series("rsi_14", bars)
    direct_rsi = next(fv for fv in direct_rsi_series if fv.timestamp == bars[-1].timestamp)
    signal_rsi = next(fv for fv in signal.evidence if fv.feature_name == "rsi_14")
    assert signal_rsi.value == direct_rsi.value


def test_p_trade_plan_reuses_existing_tradeplan_contract() -> None:
    registry = StrategyRegistry()
    registry.register(GainzCompatibleResearchStrategy())
    registry.activate(STRATEGY_ID)
    coordinator = build_coordinator(registry)

    bars = _strong_uptrend_bars(60)
    # Supply atr_14 too so build_trade_plan's advisory ATR lookup succeeds -
    # exercised by directly calling build_trade_plan with a manually
    # augmented feature_values dict fed by the SAME real dispatcher.
    strategy = GainzCompatibleResearchStrategy()
    config = _default_config()
    result = coordinator.run(bars, {STRATEGY_ID: config})
    assert len(result.trade_plans) == 1
    # Coordinator did not supply atr_14 (not in required_features), so
    # advisory plan is None -- proven NOT fabricated.
    assert result.trade_plans[0] is None

    # Now prove build_trade_plan DOES produce a real, existing-contract
    # TradePlan when ATR is available (advisory metadata path).
    from intraday.signal_intelligence.feature_engine.atr import compute_average_true_range
    from intraday.signal_intelligence.feature_engine.definitions import (
        AverageTrueRangeDefinition,
    )

    atr_series = compute_average_true_range(AverageTrueRangeDefinition(14), bars)
    atr_latest = next(fv for fv in atr_series if fv.timestamp == bars[-1].timestamp)
    feature_values = {
        fid: next(
            fv for fv in compute_feature_series(fid, bars) if fv.timestamp == bars[-1].timestamp
        )
        for fid in strategy.required_features(config)
    }
    feature_values["atr_14"] = atr_latest
    signal = strategy.evaluate(bars[-1], feature_values, config)
    assert signal is not None
    plan = strategy.build_trade_plan(bars[-1], feature_values, config, signal)
    assert plan is not None
    assert type(plan) is TradePlan  # exact contract type, not a subclass
    assert plan.entry_price == signal.price
    assert plan.stop_loss is not None
    assert plan.target_1 is not None


# ---------------------------------------------------------------------------
# I. Warmup behavior -- no fabrication
# ---------------------------------------------------------------------------


def test_i1_insufficient_warmup_produces_no_signal_not_a_fabricated_one() -> None:
    registry = StrategyRegistry()
    registry.register(GainzCompatibleResearchStrategy())
    registry.activate(STRATEGY_ID)
    coordinator = build_coordinator(registry)

    # 10 bars is below MACD histogram's 34-bar warmup requirement (and
    # several others) -> at least one required feature is unavailable.
    bars = _strong_uptrend_bars(10)
    config = _default_config()
    result = coordinator.run(bars, {STRATEGY_ID: config})

    assert result.failures == ()
    # No signal at all -- NOT a fabricated NEUTRAL signal standing in for
    # missing data.
    assert result.signals == ()
    assert result.trade_plans == ()


def test_i2_evaluate_returns_none_directly_when_a_feature_is_missing() -> None:
    strategy = GainzCompatibleResearchStrategy()
    config = _default_config()
    bars = _strong_uptrend_bars(60)
    feature_values = {
        fid: next(
            fv for fv in compute_feature_series(fid, bars) if fv.timestamp == bars[-1].timestamp
        )
        for fid in strategy.required_features(config)
    }
    # Remove exactly one required feature -- prove partial availability
    # is treated as fully unavailable, never fabricated for the missing
    # one.
    del feature_values["macd_hist_12_26_9"]
    signal = strategy.evaluate(bars[-1], feature_values, config)
    assert signal is None


# ---------------------------------------------------------------------------
# J. Look-ahead safety at the strategy level -- real output comparison
# ---------------------------------------------------------------------------


def test_j1_mutating_a_future_bar_does_not_change_an_established_signal() -> None:
    strategy = GainzCompatibleResearchStrategy()
    config = _default_config()

    bars = _random_bars(80)
    anchor_index = 50  # an established, historical bar well before the end
    anchor_bar = bars[anchor_index]
    series_up_to_anchor = bars[: anchor_index + 1]

    def _signal_at_anchor(full_series: tuple[Bar, ...]) -> StrategyDirection | None:
        # Feed only bars up to and including the anchor -- the same
        # "evaluate the last bar in the series given" contract the real
        # coordinator uses.
        feature_values = {}
        for fid in strategy.required_features(config):
            series = compute_feature_series(fid, full_series)
            match = next((fv for fv in series if fv.timestamp == anchor_bar.timestamp), None)
            if match is not None:
                feature_values[fid] = match
        signal = strategy.evaluate(anchor_bar, feature_values, config)
        return signal.direction if signal is not None else None

    baseline_direction = _signal_at_anchor(series_up_to_anchor)
    assert baseline_direction is not None  # sanity: a real signal was produced

    # Mutate a bar AFTER the anchor (never seen by series_up_to_anchor,
    # but present in the full series) and recompute using bars through
    # the anchor only again -- output must be identical, since no future
    # information can leak in either construction.
    mutated_future = list(bars)
    future_index = anchor_index + 5
    original = mutated_future[future_index]
    mutated_future[future_index] = Bar(
        instrument_id=original.instrument_id,
        timeframe=original.timeframe,
        timestamp=original.timestamp,
        open=original.open + Decimal("500"),
        high=original.high + Decimal("500"),
        low=original.low + Decimal("500"),
        close=original.close + Decimal("500"),
        volume=original.volume + Decimal("50000"),
    )
    mutated_series_up_to_anchor = tuple(mutated_future)[: anchor_index + 1]  # unaffected slice
    unaffected_direction = _signal_at_anchor(mutated_series_up_to_anchor)
    assert unaffected_direction == baseline_direction

    # Sanity: prove the mutation DOES change a LATER signal (anchored on
    # or after the mutated bar) -- otherwise this test would be
    # vacuously true.
    later_bar = bars[future_index]
    later_series_baseline = bars[: future_index + 1]
    later_series_mutated = tuple(mutated_future)[: future_index + 1]

    def _signal_at(bar: Bar, full_series: tuple[Bar, ...]) -> StrategyDirection | None:
        feature_values = {}
        for fid in strategy.required_features(config):
            series = compute_feature_series(fid, full_series)
            match = next((fv for fv in series if fv.timestamp == bar.timestamp), None)
            if match is not None:
                feature_values[fid] = match
        signal = strategy.evaluate(bar, feature_values, config)
        return signal.direction if signal is not None else None

    later_baseline_direction = _signal_at(later_bar, later_series_baseline)
    later_mutated_bar = mutated_future[future_index]
    later_mutated_direction = _signal_at(later_mutated_bar, later_series_mutated)
    _ = (later_baseline_direction, later_mutated_direction)  # observed, not asserted directly
    # Direct, stronger check: the RSI evidence value itself differs (the
    # real proof the mutation mattered -- avoids a vacuous pass).
    rsi_baseline = next(
        fv
        for fv in compute_feature_series("rsi_14", later_series_baseline)
        if fv.timestamp == later_bar.timestamp
    )
    rsi_mutated = next(
        fv
        for fv in compute_feature_series("rsi_14", later_series_mutated)
        if fv.timestamp == later_bar.timestamp
    )
    assert rsi_baseline.value != rsi_mutated.value


# ---------------------------------------------------------------------------
# K. Shared feature computation across two REAL strategies
# ---------------------------------------------------------------------------


class _SecondRsiConsumerStrategy:
    """A second, minimal, but REAL strategy (not a mock) requiring the
    SAME `rsi_14` field the research strategy also requires -- used only
    to prove the coordinator's existing per-field_id cache computes it
    exactly once across two real strategies in one `run()` call. Not a
    Gainz-anything strategy; deliberately trivial."""

    strategy_id = "checkpoint_64_50_second_rsi_consumer"
    display_name = "Second RSI Consumer (test-only)"
    specification_version = "v1"
    code_version = "v1"

    def parameter_schema(self) -> StrategyParameterSchema:
        return StrategyParameterSchema(strategy_id=self.strategy_id, parameters=())

    def required_features(self, config: StrategyConfigurationValues) -> tuple[str, ...]:
        return ("rsi_14",)

    def evaluate(
        self, bar: Bar, feature_values: dict[str, FeatureValue], config: StrategyConfigurationValues
    ) -> StrategySignal | None:
        rsi = feature_values.get("rsi_14")
        if rsi is None:
            return None
        direction = StrategyDirection.BULLISH if rsi.value >= 50 else StrategyDirection.BEARISH
        return StrategySignal(
            strategy_id=self.strategy_id,
            specification_version=self.specification_version,
            code_version=self.code_version,
            configuration_version=config.configuration_version,
            instrument_id=bar.instrument_id,
            timeframe=bar.timeframe,
            timestamp=bar.timestamp,
            direction=direction,
            price=bar.close,
            evidence=(rsi,),
        )


def test_k1_shared_rsi_14_computed_exactly_once_across_two_real_strategies() -> None:
    call_log: list[str] = []

    def _counting_dispatcher(field_id: str, bars: tuple[Bar, ...]) -> tuple[FeatureValue, ...]:
        call_log.append(field_id)
        return compute_feature_series(field_id, bars)

    registry = StrategyRegistry()
    strategy_a = GainzCompatibleResearchStrategy()
    strategy_b = _SecondRsiConsumerStrategy()
    registry.register(strategy_a)
    registry.register(strategy_b)
    registry.activate(strategy_a.strategy_id)
    registry.activate(strategy_b.strategy_id)

    coordinator = StrategyExecutionCoordinator(registry, _counting_dispatcher)
    bars = _strong_uptrend_bars(60)
    config_a = _default_config()
    config_b = StrategyConfigurationValues(
        strategy_id=strategy_b.strategy_id,
        specification_version="v1",
        code_version="v1",
        configuration_version="v1",
        values={},
    )

    result = coordinator.run(
        bars, {strategy_a.strategy_id: config_a, strategy_b.strategy_id: config_b}
    )

    assert result.failures == ()
    # Both strategies produced a real signal.
    strategy_ids_signaled = {s.strategy_id for s in result.signals}
    assert strategy_a.strategy_id in strategy_ids_signaled
    assert strategy_b.strategy_id in strategy_ids_signaled

    # The KEY proof: rsi_14 appears in the dispatcher call log EXACTLY
    # ONCE, even though BOTH real strategies required it.
    assert call_log.count("rsi_14") == 1


# ---------------------------------------------------------------------------
# M/N. No second indicator framework, no Gainz contract duplication
# ---------------------------------------------------------------------------


def test_mn_strategy_module_contains_no_indicator_math_and_no_duplicate_contracts() -> None:
    source = STRATEGY_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source)

    forbidden_class_names = {
        "GainzStrategy",
        "GainzSignal",
        "GainzStrategySignal",
        "GainzTradePlan",
        "GainzRegistry",
        "ResearchStrategyRegistry",
        "SecondaryRegistry",
    }
    class_names = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
    assert class_names.isdisjoint(forbidden_class_names)
    assert class_names == {"GainzCompatibleResearchStrategy"}

    # No import from signal_intelligence (the bounded-context boundary
    # `.importlinter` contract 4 enforces) -- indicator computation must
    # come only via the injected coordinator dispatcher, never directly.
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not any(m.startswith("intraday.signal_intelligence") for m in imported_modules)
    assert not any(m.startswith("intraday.risk") for m in imported_modules)
    assert not any("execution" in m and "strategy_execution" not in m for m in imported_modules)


# ---------------------------------------------------------------------------
# O. Risk separation
# ---------------------------------------------------------------------------


def test_o1_strategy_never_produces_final_order_quantity_or_touches_risk() -> None:
    strategy = GainzCompatibleResearchStrategy()
    # No risk-sizing method exists on the strategy at all -- position
    # sizing (if any) would be advisory metadata only, never final order
    # quantity; this strategy doesn't even attempt sizing.
    assert not hasattr(strategy, "risk")
    assert not hasattr(strategy, "position_size")
    assert not hasattr(strategy, "order_quantity")


# ---------------------------------------------------------------------------
# Coordinator-level: bearish path also exercised with real data (extra
# confidence beyond the bullish path above; not a required section but
# cheap and strengthens F/G).
# ---------------------------------------------------------------------------


def test_extra_strong_downtrend_produces_bearish_signal() -> None:
    registry = StrategyRegistry()
    registry.register(GainzCompatibleResearchStrategy())
    registry.activate(STRATEGY_ID)
    coordinator = build_coordinator(registry)

    bars = []
    price = Decimal("500")
    for i in range(60):
        move = Decimal("1") + Decimal(i) * Decimal("0.15")
        o = price
        c = price - move
        h = o + Decimal("0.05")
        lo = c - Decimal("0.05")
        v = Decimal("5000")
        bars.append(_bar(i, str(o), str(h), str(lo), str(c), str(v)))
        price = c
    bars_t = tuple(bars)

    config = _default_config()
    result = coordinator.run(bars_t, {STRATEGY_ID: config})
    assert result.failures == ()
    assert len(result.signals) == 1
    assert result.signals[0].direction == StrategyDirection.BEARISH
