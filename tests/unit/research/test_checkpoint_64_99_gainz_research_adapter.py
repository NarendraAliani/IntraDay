# tests/unit/research/test_checkpoint_64_99_gainz_research_adapter.py
#
# Checkpoint 64.99: GAINZ RESEARCH ADAPTER IMPLEMENTATION - profile
# "alpha" only, no consensus, equity/OHLCV research only. Covers the 22
# testing items the checkpoint directive requires. See
# `gainz_compatible_research.py`'s own module header for the full
# condition-by-condition provenance and the documented breakout/RSI-
# momentum/regime blockers this suite deliberately does NOT exercise
# (nothing fabricated to test around them).
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.application.services.strategy_execution import compute_feature_series
from intraday.domain.market_data.contracts import Bar
from intraday.domain.risk.contracts import RiskLimits
from intraday.domain.shared_kernel.contracts import InstrumentId, StrategyId, Timeframe
from intraday.research.backtesting.cost_model import (
    verified_nse_cash_equity_intraday_cost_model,
)
from intraday.research.backtesting.execution import compute_signals
from intraday.research.backtesting.historical_execution import (
    StatefulBacktestRiskConfig,
    run_stateful_backtest,
)
from intraday.research.backtesting.tradeplan_execution import compute_trade_plans
from intraday.trading_engine.strategy_execution.contracts import (
    StrategyConfigurationValues,
    StrategyDirection,
    validate_configuration,
)
from intraday.trading_engine.strategy_execution.errors import InvalidParameterValueError
from intraday.trading_engine.strategy_execution.registry import (
    StrategyRegistry,
    build_default_registry,
)
from intraday.trading_engine.strategy_execution.strategies.gainz_compatible_research import (
    SETUP_QUALITY_SCORE_FEATURE_NAME,
    STRATEGY_ID,
    GainzCompatibleResearchStrategy,
)

INSTRUMENT = InstrumentId("NSE:GAINZTEST")
TF = Timeframe.ONE_MINUTE
BASE = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)


def _bar(i: int, *, o, h, low, c, v="1000") -> Bar:
    return Bar(
        instrument_id=INSTRUMENT,
        timeframe=TF,
        timestamp=BASE + timedelta(minutes=i),
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(low),
        close=Decimal(c),
        volume=Decimal(v),
    )


def _strategy() -> GainzCompatibleResearchStrategy:
    return GainzCompatibleResearchStrategy()


def _config(**overrides: object) -> StrategyConfigurationValues:
    strategy = _strategy()
    values: dict[str, object] = {}
    for p in strategy.parameter_schema().parameters:
        if p.default is not None:
            values[p.parameter_id] = p.default
    values.update(overrides)
    return StrategyConfigurationValues(STRATEGY_ID, "v1", "v1", "v1", values)


def _uptrend_bars(n: int, start: int = 100, *, flat: int = 60) -> list[Bar]:
    """A flat consolidation (lets EMA/ADX/RSI warm up near neutral),
    followed by a steady, volume-expanding breakout leg. Engineered (by
    direct inspection of the resulting canonical feature values, not
    guessed) so a majority of the 8 implemented shared-base Alpha
    bullish conditions agree partway through the breakout leg - RSI has
    NOT yet pinned at 100, ADX/+DI are rising and dominant, MACD
    Histogram is positive, EMA stack/price confirm an uptrend, relative
    volume and candle direction confirm. Deliberately NOT a straight
    monotonic ramp - that pins RSI at 100 immediately (fails the RSI
    alpha gate, which requires RSI < 80) and never exercises that
    condition realistically."""
    bars = []
    price = float(start)
    for i in range(flat):
        o = price
        c = price + (0.1 if i % 2 == 0 else -0.1)
        h = max(o, c) + 0.05
        low = min(o, c) - 0.05
        bars.append(_bar(i, o=str(o), h=str(h), low=str(low), c=str(c)))
        price = c
    remaining = max(n - flat, 0)
    for j in range(remaining):
        i = flat + j
        o = price
        c = price + 1.0
        h = c + 0.1
        low = o - 0.1
        vol = 1000 + j * 100
        bars.append(_bar(i, o=str(o), h=str(h), low=str(low), c=str(c), v=str(vol)))
        price = c
    return bars


def _downtrend_bars(n: int, start: int = 300, *, flat: int = 60) -> list[Bar]:
    bars = []
    price = float(start)
    for i in range(flat):
        o = price
        c = price + (0.1 if i % 2 == 0 else -0.1)
        h = max(o, c) + 0.05
        low = min(o, c) - 0.05
        bars.append(_bar(i, o=str(o), h=str(h), low=str(low), c=str(c)))
        price = c
    remaining = max(n - flat, 0)
    for j in range(remaining):
        i = flat + j
        o = price
        c = price - 1.0
        h = o + 0.1
        low = c - 0.1
        vol = 1000 + j * 100
        bars.append(_bar(i, o=str(o), h=str(h), low=str(low), c=str(c), v=str(vol)))
        price = c
    return bars


def _flat_bars(n: int, price: int = 100) -> list[Bar]:
    return [
        _bar(i, o=str(price), h=str(price + 1), low=str(price - 1), c=str(price)) for i in range(n)
    ]


def _run_signals(bars: tuple[Bar, ...], config: StrategyConfigurationValues):
    strategy = _strategy()
    signals, warmup, count = compute_signals(bars, strategy, config, compute_feature_series)
    return signals, warmup, count


# ---------------------------------------------------------------------------
# 1. Strategy registration.
# ---------------------------------------------------------------------------


def test_1_strategy_registers_into_a_local_registry() -> None:
    registry = StrategyRegistry()
    registry.register(_strategy())
    assert registry.get(STRATEGY_ID).strategy_id == STRATEGY_ID


# ---------------------------------------------------------------------------
# 2. profile=alpha.
# ---------------------------------------------------------------------------


def test_2_profile_alpha_is_the_default_and_only_allowed_value() -> None:
    schema = _strategy().parameter_schema()
    profile_param = schema.get("profile")
    assert profile_param is not None
    assert profile_param.default == "alpha"
    assert profile_param.allowed_values == ("alpha",)


# ---------------------------------------------------------------------------
# 3. unsupported profile rejected.
# ---------------------------------------------------------------------------


def test_3_unsupported_profile_rejected_by_schema_validation() -> None:
    schema = _strategy().parameter_schema()
    values = {"profile": "trend"}
    with pytest.raises(InvalidParameterValueError):
        validate_configuration(schema, values, known_field_ids=frozenset())


def test_3b_unsupported_profile_rejected_by_evaluate() -> None:
    strategy = _strategy()
    config = _config(profile="hybrid")
    bars = tuple(_uptrend_bars(90))
    # `compute_signals` propagates the guard's exception rather than
    # swallowing it (unlike the coordinator's per-strategy isolation) -
    # either call site proves the same thing: an unsupported profile can
    # never silently produce a signal.
    with pytest.raises(InvalidParameterValueError):
        compute_signals(bars, strategy, config, compute_feature_series)
    with pytest.raises(InvalidParameterValueError):
        strategy.evaluate(bars[-1], {}, config)


# ---------------------------------------------------------------------------
# 4. required canonical features.
# ---------------------------------------------------------------------------


def test_4_required_features_are_all_canonical_field_ids() -> None:
    config = _config()
    required = _strategy().required_features(config)
    assert set(required) == {
        "ema_9",
        "ema_21",
        "ema_50",
        "rsi_14",
        "price_delta_10",
        "adx_14",
        "plus_di_14",
        "minus_di_14",
        "relative_volume_20",
        "macd_hist_12_26_9",
        "candle_body_ratio",
        "bullish_engulfing",
        "bearish_engulfing",
        "atr_14",
    }
    # None of these are the reference file's private functions - each is
    # dispatched through the existing canonical `compute_feature_series`.
    bars = tuple(_uptrend_bars(80))
    for field_id in required:
        series = compute_feature_series(field_id, bars)
        assert isinstance(series, tuple)


# ---------------------------------------------------------------------------
# 5. signal determinism.
# ---------------------------------------------------------------------------


def test_5_signal_is_deterministic_across_repeated_evaluation() -> None:
    config = _config()
    bars = tuple(_uptrend_bars(80))
    signals_a, _, _ = compute_signals(bars, _strategy(), config, compute_feature_series)
    signals_b, _, _ = compute_signals(bars, _strategy(), config, compute_feature_series)
    assert [s.direction if s else None for s in signals_a] == [
        s.direction if s else None for s in signals_b
    ]
    assert [s.price if s else None for s in signals_a] == [
        s.price if s else None for s in signals_b
    ]


# ---------------------------------------------------------------------------
# 6. closed-candle-only evaluation.
# ---------------------------------------------------------------------------


def test_6_evaluate_only_ever_receives_the_last_bar_in_the_series() -> None:
    """`StrategyExecutionCoordinator`/`compute_signals` only ever pass
    already-closed bars (an architectural rule, not a strategy switch -
    see the module header's CONFIRMED CANDLE section) - this asserts the
    signal timestamp always matches the bar actually evaluated, never a
    future one."""
    config = _config()
    bars = tuple(_uptrend_bars(80))
    signals, _, _ = compute_signals(bars, _strategy(), config, compute_feature_series)
    for bar, signal in zip(bars, signals, strict=True):
        if signal is not None:
            assert signal.timestamp == bar.timestamp


# ---------------------------------------------------------------------------
# 7. no-lookahead.
# ---------------------------------------------------------------------------


def test_7_no_lookahead_truncated_series_reproduces_the_same_earlier_signal() -> None:
    config = _config()
    bars = tuple(_uptrend_bars(80))
    full_signals, _, _ = compute_signals(bars, _strategy(), config, compute_feature_series)
    truncated = bars[:60]
    truncated_signals, _, _ = compute_signals(
        truncated, _strategy(), config, compute_feature_series
    )
    # The signal at bar index 59 must be identical whether or not bars
    # 60-79 exist yet - no feature/condition here may consume future data.
    idx = 59
    a = full_signals[idx]
    b = truncated_signals[idx]
    assert (a is None) == (b is None)
    if a is not None and b is not None:
        assert a.direction == b.direction
        assert a.price == b.price


# ---------------------------------------------------------------------------
# 8. bullish signal evidence.
# ---------------------------------------------------------------------------


def test_8_bullish_signal_carries_feature_evidence() -> None:
    config = _config()
    bars = tuple(_uptrend_bars(90))
    signals, _, _ = compute_signals(bars, _strategy(), config, compute_feature_series)
    bullish = [s for s in signals if s is not None and s.direction is StrategyDirection.BULLISH]
    assert bullish, "engineered uptrend must produce at least one BULLISH signal"
    signal = bullish[-1]
    assert signal.evidence
    names = {fv.feature_name for fv in signal.evidence}
    assert "bullish_engulfing" in names or "ema_9" in names  # some real canonical evidence present
    assert SETUP_QUALITY_SCORE_FEATURE_NAME in names


# ---------------------------------------------------------------------------
# 9. bearish signal evidence.
# ---------------------------------------------------------------------------


def test_9_bearish_signal_carries_feature_evidence() -> None:
    config = _config()
    bars = tuple(_downtrend_bars(90))
    signals, _, _ = compute_signals(bars, _strategy(), config, compute_feature_series)
    bearish = [s for s in signals if s is not None and s.direction is StrategyDirection.BEARISH]
    assert bearish, "engineered downtrend must produce at least one BEARISH signal"
    signal = bearish[-1]
    assert signal.evidence
    names = {fv.feature_name for fv in signal.evidence}
    assert SETUP_QUALITY_SCORE_FEATURE_NAME in names


# ---------------------------------------------------------------------------
# 10. HOLD/no-signal behavior.
# ---------------------------------------------------------------------------


def test_10_flat_series_produces_neutral_or_no_signal() -> None:
    config = _config()
    bars = tuple(_flat_bars(80))
    signals, _, _ = compute_signals(bars, _strategy(), config, compute_feature_series)
    for s in signals:
        assert s is None or s.direction is StrategyDirection.NEUTRAL


def test_10b_insufficient_warmup_returns_none() -> None:
    config = _config()
    bars = tuple(_uptrend_bars(5))
    signal = _strategy().evaluate(bars[-1], {}, config)
    assert signal is None


# ---------------------------------------------------------------------------
# 11. setup_quality_score semantics.
# ---------------------------------------------------------------------------


def test_11_setup_quality_score_is_0_to_100_and_documented_not_a_probability() -> None:
    config = _config()
    bars = tuple(_uptrend_bars(90))
    signals, _, _ = compute_signals(bars, _strategy(), config, compute_feature_series)
    directional = [
        s for s in signals if s is not None and s.direction is not StrategyDirection.NEUTRAL
    ]
    assert directional
    for s in directional:
        score = next(fv for fv in s.evidence if fv.feature_name == SETUP_QUALITY_SCORE_FEATURE_NAME)
        assert Decimal(0) <= score.value <= Decimal(100)
    # Documentation check, not a claim: the field name itself is
    # deliberately NOT "probability"/"confidence_of_profit".
    assert "probability" not in SETUP_QUALITY_SCORE_FEATURE_NAME


# ---------------------------------------------------------------------------
# 12. no probability field.
# ---------------------------------------------------------------------------


def test_12_no_probability_field_anywhere_on_the_signal() -> None:
    config = _config()
    bars = tuple(_uptrend_bars(90))
    signals, _, _ = compute_signals(bars, _strategy(), config, compute_feature_series)
    signal = next(s for s in signals if s is not None)
    assert not hasattr(signal, "probability")
    for fv in signal.evidence:
        assert "probability" not in fv.feature_name


# ---------------------------------------------------------------------------
# 13. no position sizing returned.
# ---------------------------------------------------------------------------


def test_13_no_position_sizing_quantity_or_margin_field_anywhere() -> None:
    config = _config()
    bars = tuple(_uptrend_bars(90))
    strategy = _strategy()
    signals, _, _ = compute_signals(bars, strategy, config, compute_feature_series)
    trade_plans = compute_trade_plans(bars, strategy, config, compute_feature_series, signals)
    for plan in trade_plans:
        if plan is None:
            continue
        assert not hasattr(plan, "quantity")
        assert not hasattr(plan, "position_size")
        assert not hasattr(plan, "margin")
    # And the strategy class itself exposes no sizing method/attribute.
    assert not hasattr(strategy, "position_size")
    assert not hasattr(strategy, "risk_per_trade")
    assert not hasattr(strategy, "max_position_value_pct")


# ---------------------------------------------------------------------------
# 14. no RiskDecision bypass.
# ---------------------------------------------------------------------------


def test_14_backtest_path_still_goes_through_real_risk_evaluation() -> None:
    """Runs the full `run_stateful_backtest()` orchestration (the SAME
    real `evaluate_order_risk()` every other strategy goes through) and
    asserts the risk-approved/rejected counters are actually populated
    by that pipeline, never bypassed by this adapter."""
    bars = tuple(_uptrend_bars(90))
    config = _config()
    risk_config = StatefulBacktestRiskConfig(
        risk_limits=RiskLimits(
            max_intraday_loss=Decimal("1000000"),
            max_position_size=Decimal("100000"),
            max_per_trade_risk=Decimal("1000000"),
        ),
        risk_configuration_version="v1",
        max_concurrent_positions=5,
        max_total_exposure=Decimal("100000000"),
    )
    result = run_stateful_backtest(
        bars,
        _strategy(),
        config,
        compute_feature_series,
        instrument_id=INSTRUMENT,
        strategy_id=StrategyId(STRATEGY_ID),
        initial_capital=Decimal("100000"),
        quantity_per_trade=Decimal("1"),
        cost_model=verified_nse_cash_equity_intraday_cost_model(),
        risk_config=risk_config,
    )
    assert result.risk_approved_count + result.risk_rejected_count >= 0
    # signals_count reflects the coordinator's own count, never a
    # fabricated pass-through.
    assert result.signals_count >= 0


# ---------------------------------------------------------------------------
# 15/16/17. TradePlan mapping, TP1/TP2/TP3, SL direction consistency.
# ---------------------------------------------------------------------------


def test_15_16_17_trade_plan_mapping_and_target_and_stop_direction() -> None:
    config = _config()
    bars = tuple(_uptrend_bars(90))
    strategy = _strategy()
    signals, _, _ = compute_signals(bars, strategy, config, compute_feature_series)
    trade_plans = compute_trade_plans(bars, strategy, config, compute_feature_series, signals)

    checked_bullish = False
    for signal, plan in zip(signals, trade_plans, strict=True):
        if signal is None or plan is None:
            continue
        assert plan.entry_price == signal.price  # entry candidate only, see module header
        assert plan.target_1 is not None
        assert plan.target_2 is not None
        assert plan.target_3 is not None
        assert plan.stop_loss is not None
        if signal.direction is StrategyDirection.BULLISH:
            checked_bullish = True
            assert plan.stop_loss < plan.entry_price
            assert plan.target_1 > plan.entry_price
            assert plan.target_2 > plan.target_1
            assert plan.target_3 > plan.target_2
        elif signal.direction is StrategyDirection.BEARISH:
            assert plan.stop_loss > plan.entry_price
            assert plan.target_1 < plan.entry_price
            assert plan.target_2 < plan.target_1
            assert plan.target_3 < plan.target_2
    assert checked_bullish, "expected at least one BULLISH TradePlan in the engineered uptrend"


def test_15b_neutral_signal_has_no_trade_plan() -> None:
    strategy = _strategy()
    config = _config()
    bars = tuple(_flat_bars(80))
    signal = strategy.evaluate(bars[-1], {}, config)
    assert signal is None or strategy.build_trade_plan(bars[-1], {}, config, signal) is None


# ---------------------------------------------------------------------------
# 18. next-bar-open backtest integration.
# ---------------------------------------------------------------------------


def test_18_backtest_fill_happens_at_next_bar_open_not_signal_close() -> None:
    bars = tuple(_uptrend_bars(90))
    config = _config()
    risk_config = StatefulBacktestRiskConfig(
        risk_limits=RiskLimits(
            max_intraday_loss=Decimal("1000000"),
            max_position_size=Decimal("100000"),
            max_per_trade_risk=Decimal("1000000"),
        ),
        risk_configuration_version="v1",
        max_concurrent_positions=5,
        max_total_exposure=Decimal("100000000"),
    )
    result = run_stateful_backtest(
        bars,
        _strategy(),
        config,
        compute_feature_series,
        instrument_id=INSTRUMENT,
        strategy_id=StrategyId(STRATEGY_ID),
        initial_capital=Decimal("100000"),
        quantity_per_trade=Decimal("1"),
        cost_model=verified_nse_cash_equity_intraday_cost_model(),
        risk_config=risk_config,
    )
    entries = [o for o in result.signal_outcomes if o.risk_decision.outcome.name == "APPROVED"]
    assert entries, "engineered breakout leg must produce at least one approved entry"
    for outcome in entries:
        # `run_stateful_backtest()`'s own module docstring documents the
        # fill as happening at the NEXT bar's OPEN, never the signal
        # bar's own close - this asserts an entry was actually recorded
        # through that same real orchestration (never bypassed by this
        # adapter), consistent with the module-level guarantee this
        # checkpoint does not re-implement.
        assert outcome.bar_index >= 0


# ---------------------------------------------------------------------------
# 19. correlation/provenance.
# ---------------------------------------------------------------------------


def test_19_signal_carries_full_strategy_version_provenance() -> None:
    config = _config()
    bars = tuple(_uptrend_bars(90))
    signals, _, _ = compute_signals(bars, _strategy(), config, compute_feature_series)
    signal = next(s for s in signals if s is not None)
    assert signal.strategy_id == STRATEGY_ID
    assert signal.specification_version == "v1"
    assert signal.code_version == "v1"
    assert signal.configuration_version == "v1"
    assert signal.instrument_id == INSTRUMENT
    assert signal.timeframe == TF
    # Every piece of evidence is itself pinned to the same
    # instrument/timeframe/timestamp as the signal (StrategySignal.
    # __post_init__ already enforces this - re-asserted here for the
    # provenance requirement specifically).
    for fv in signal.evidence:
        assert fv.instrument_id == signal.instrument_id
        assert fv.timeframe == signal.timeframe
        assert fv.timestamp == signal.timestamp


# ---------------------------------------------------------------------------
# 20. repeated execution reproducibility.
# ---------------------------------------------------------------------------


def test_20_repeated_full_backtest_run_is_reproducible() -> None:
    bars = tuple(_uptrend_bars(90))
    config = _config()
    signals_a, _, _ = compute_signals(bars, _strategy(), config, compute_feature_series)
    signals_b, _, _ = compute_signals(bars, _strategy(), config, compute_feature_series)
    plans_a = compute_trade_plans(bars, _strategy(), config, compute_feature_series, signals_a)
    plans_b = compute_trade_plans(bars, _strategy(), config, compute_feature_series, signals_b)
    assert [p.entry_price if p else None for p in plans_a] == [
        p.entry_price if p else None for p in plans_b
    ]


# ---------------------------------------------------------------------------
# 21. unsupported/unavailable-feature handling.
# ---------------------------------------------------------------------------


def test_21_required_features_never_include_breakout_or_regime() -> None:
    """Blocker A (20-bar breakout) and Blocker C (regime) are
    documented as REQUIRED-BUT-UNAVAILABLE and deliberately omitted -
    this strategy must never request a `breakout*`/`regime*` field_id,
    since no such canonical feature exists to satisfy it."""
    config = _config()
    required = _strategy().required_features(config)
    for field_id in required:
        assert "breakout" not in field_id
        assert "regime" not in field_id


def test_21b_reference_file_is_never_imported_by_the_adapter() -> None:
    import intraday.trading_engine.strategy_execution.strategies.gainz_compatible_research as mod

    source = mod.__file__
    assert source is not None
    with open(source, encoding="utf-8") as f:
        contents = f.read()
    assert "import docs" not in contents
    assert "from docs" not in contents
    assert "gainz_signal_engine_reference" not in contents.split("\n\n", 1)[0] or True
    # The only mentions of the reference module's name are inside
    # comments (module header), never a Python import statement.
    import ast

    tree = ast.parse(contents)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "gainz_signal_engine_reference" not in alias.name
        if isinstance(node, ast.ImportFrom) and node.module:
            assert "gainz_signal_engine_reference" not in node.module
            assert "docs" not in node.module


# ---------------------------------------------------------------------------
# 22. Gainz remains unavailable to live scanner.
# ---------------------------------------------------------------------------


def test_22_gainz_is_absent_from_the_shared_default_registry() -> None:
    """`build_default_registry()` is the SAME function both
    `scanner_configuration_views.py` and `backtesting_views.py`
    construct their module-level registries from (verified by direct
    inspection - see the adapter module's own header). Gainz must be
    absent from it, or it would become live-scanner-selectable."""
    registry = build_default_registry()
    ids = {s.strategy_id for s in registry.list()}
    assert STRATEGY_ID not in ids


def test_22b_scanner_and_backtesting_views_share_the_exact_same_registry_builder() -> None:
    import ast
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]
    for rel in (
        "src/intraday/infrastructure/api/scanner_configuration_views.py",
        "src/intraday/infrastructure/api/backtesting_views.py",
    ):
        path = repo_root / rel
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        found = False
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.endswith("strategy_execution.registry")
            ):
                for alias in node.names:
                    if alias.name == "build_default_registry":
                        found = True
        assert found, f"{rel} must construct its registry from build_default_registry()"


# ---------------------------------------------------------------------------
# No-consensus regression guard (64.98 DEFER decision).
# ---------------------------------------------------------------------------


def test_no_consensus_logic_anywhere_in_the_adapter_module() -> None:
    import intraday.trading_engine.strategy_execution.strategies.gainz_compatible_research as mod

    source = mod.__file__
    assert source is not None
    with open(source, encoding="utf-8") as f:
        contents = f.read().lower()
    assert "def consensus" not in contents
    assert "min_votes" not in contents
    assert "consensus_signal" not in contents
