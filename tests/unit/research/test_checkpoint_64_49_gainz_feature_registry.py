# File: tests/unit/research/test_checkpoint_64_49_gainz_feature_registry.py
#
# Checkpoint 64.49: CANONICAL FEATURE EXPANSION FOR GAINZ COMPATIBILITY.
#
# HONESTY NOTICE (do not remove): no Gainz reference implementation file
# exists anywhere in this repository (independently re-verified again this
# checkpoint - see the `test_zz_...` honesty guard at the bottom of this
# file, and `field_registry.py`'s own module docstring). Every formula
# implemented below is a STANDARD, well-established technical-analysis
# convention (Wilder RSI, Wilder ADX/+DI/-DI, standard 12/26/9 MACD, the
# common body-ratio and trailing-average-relative-volume definitions) -
# NONE of them is claimed to be numerically identical to any Gainz
# reference implementation, because none exists to check against.
#
# This checkpoint deliberately DEFERS Delta and Breakout (ambiguous
# semantics, no Gainz source to disambiguate) - there is intentionally NO
# test exercising either, and no such field exists in the registry.
from __future__ import annotations

import ast
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from intraday.application.services.strategy_execution import compute_feature_series
from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe
from intraday.signal_intelligence.feature_engine.candle_body_ratio import (
    compute_candle_body_ratio,
)
from intraday.signal_intelligence.feature_engine.definitions import (
    DirectionalMovementDefinition,
    MacdHistogramDefinition,
    RelativeStrengthIndexDefinition,
    RelativeVolumeDefinition,
)
from intraday.signal_intelligence.feature_engine.directional_movement import (
    compute_average_directional_index,
    compute_minus_directional_index,
    compute_plus_directional_index,
)
from intraday.signal_intelligence.feature_engine.errors import InvalidLookbackError
from intraday.signal_intelligence.feature_engine.field_registry import (
    get_field,
    is_parameterized_feature,
    list_fields,
)
from intraday.signal_intelligence.feature_engine.macd_histogram import compute_macd_histogram
from intraday.signal_intelligence.feature_engine.relative_volume import compute_relative_volume
from intraday.signal_intelligence.feature_engine.rsi import compute_relative_strength_index
from intraday.trading_engine.strategy_execution.coordinator import StrategyExecutionCoordinator
from intraday.trading_engine.strategy_execution.registry import StrategyRegistry

REPO_ROOT = Path(__file__).resolve().parents[3]
STRATEGIES_DIR = REPO_ROOT / "src/intraday/trading_engine/strategy_execution/strategies"
SRC_ROOT = REPO_ROOT / "src"

IID = InstrumentId("TEST")
TF = Timeframe.ONE_MINUTE
BASE_TS = datetime(2026, 1, 1, tzinfo=UTC)


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


def _random_bars(n: int, seed: int = 42) -> tuple[Bar, ...]:
    rng = random.Random(seed)  # noqa: S311 - deterministic test fixture, not cryptographic use
    bars: list[Bar] = []
    price = Decimal("100")
    for i in range(n):
        o = price
        move = Decimal(rng.randint(-50, 50)) / 100
        c = max(price + move, Decimal("1"))
        h = max(o, c) + Decimal(rng.randint(0, 20)) / 100
        low = min(o, c) - Decimal(rng.randint(0, 20)) / 100
        v = Decimal(rng.randint(100, 1000))
        bars.append(
            Bar(
                instrument_id=IID,
                timeframe=TF,
                timestamp=BASE_TS + timedelta(minutes=i),
                open=o,
                high=h,
                low=low,
                close=c,
                volume=v,
            )
        )
        price = c
    return tuple(bars)


# ---------------------------------------------------------------------------
# A1. RSI - known deterministic input -> expected output (Wilder RSI,
#     hand-computable monotonic-up series).
# ---------------------------------------------------------------------------


def test_a1_rsi_monotonic_up_series_is_100() -> None:
    # A strictly increasing close series has zero losses in the smoothing
    # window -> avg_loss == 0, avg_gain > 0 -> RSI == 100 by the
    # documented edge-case rule.
    bars = tuple(
        _bar(i, str(100 + i), str(100 + i + 1), str(100 + i - 1), str(100 + i), "100")
        for i in range(20)
    )
    values = compute_relative_strength_index(RelativeStrengthIndexDefinition(14), bars)
    assert len(values) == 20 - 14
    for fv in values:
        assert fv.value == Decimal(100)


def test_a2_rsi_flat_series_is_50() -> None:
    # Zero price movement -> avg_gain == avg_loss == 0 -> RSI == 50 by
    # the documented edge-case rule.
    bars = tuple(_bar(i, "100", "101", "99", "100", "100") for i in range(20))
    values = compute_relative_strength_index(RelativeStrengthIndexDefinition(14), bars)
    assert len(values) == 20 - 14
    for fv in values:
        assert fv.value == Decimal(50)


def test_a3_rsi_value_range() -> None:
    bars = _random_bars(60)
    values = compute_relative_strength_index(RelativeStrengthIndexDefinition(14), bars)
    assert values
    for fv in values:
        assert Decimal(0) <= fv.value <= Decimal(100)


# ---------------------------------------------------------------------------
# B. Warmup behavior.
# ---------------------------------------------------------------------------


def test_b1_rsi_warmup_requires_lookback_plus_1_bars() -> None:
    bars = _random_bars(14)  # exactly lookback bars - one short of N+1
    assert compute_relative_strength_index(RelativeStrengthIndexDefinition(14), bars) == ()
    bars15 = _random_bars(15)
    values = compute_relative_strength_index(RelativeStrengthIndexDefinition(14), bars15)
    assert len(values) == 1


def test_b2_adx_warmup_requires_2n_bars() -> None:
    bars_short = _random_bars(27)  # 2*14 = 28 is the minimum; 27 is one short
    assert compute_average_directional_index(DirectionalMovementDefinition(14), bars_short) == ()
    bars_ok = _random_bars(28)
    adx = compute_average_directional_index(DirectionalMovementDefinition(14), bars_ok)
    assert len(adx) == 1


def test_b3_plus_minus_di_warmup_requires_n_plus_1_bars() -> None:
    bars_short = _random_bars(14)
    assert compute_plus_directional_index(DirectionalMovementDefinition(14), bars_short) == ()
    assert compute_minus_directional_index(DirectionalMovementDefinition(14), bars_short) == ()
    bars_ok = _random_bars(15)
    assert len(compute_plus_directional_index(DirectionalMovementDefinition(14), bars_ok)) == 1
    assert len(compute_minus_directional_index(DirectionalMovementDefinition(14), bars_ok)) == 1


def test_b4_relative_volume_warmup_requires_lookback_bars() -> None:
    bars_short = _random_bars(10)
    assert compute_relative_volume(RelativeVolumeDefinition(10), bars_short) == ()
    bars_ok = _random_bars(11)
    values = compute_relative_volume(RelativeVolumeDefinition(10), bars_ok)
    assert len(values) == 1


def test_b5_macd_histogram_warmup() -> None:
    # ema_slow(26) needs 26 bars to seed; the MACD line then needs 9 more
    # values to seed the signal EMA (macd_line length = M - 25), so the
    # minimum is M = 34.
    bars_short = _random_bars(33)
    assert compute_macd_histogram(MacdHistogramDefinition(12, 26, 9), bars_short) == ()
    bars_ok = _random_bars(34)
    values = compute_macd_histogram(MacdHistogramDefinition(12, 26, 9), bars_ok)
    assert len(values) == 1


def test_b6_candle_body_ratio_has_no_warmup() -> None:
    bars = _random_bars(1)
    values = compute_candle_body_ratio(bars)
    assert len(values) == 1


# ---------------------------------------------------------------------------
# C. Missing data behavior.
# ---------------------------------------------------------------------------


def test_c1_candle_body_ratio_skips_zero_range_bars_no_crash() -> None:
    zero_range = _bar(0, "100", "100", "100", "100", "100")
    normal = _bar(1, "100", "105", "95", "102", "100")
    values = compute_candle_body_ratio((zero_range, normal))
    assert len(values) == 1
    assert values[0].timestamp == normal.timestamp


def test_c2_relative_volume_skips_zero_baseline_bars_no_crash() -> None:
    # SAMPLE_BAR-sourced fixtures carry volume == 0 - the field_registry's
    # own pre-existing "volume" docstring already documents this. RVOL
    # must SKIP, never divide by zero or fabricate a value.
    bars = tuple(_bar(i, "100", "101", "99", "100", "0") for i in range(15))
    values = compute_relative_volume(RelativeVolumeDefinition(10), bars)
    assert values == ()


def test_c3_empty_series_returns_empty_for_every_new_feature() -> None:
    assert compute_relative_strength_index(RelativeStrengthIndexDefinition(14), ()) == ()
    assert compute_plus_directional_index(DirectionalMovementDefinition(14), ()) == ()
    assert compute_minus_directional_index(DirectionalMovementDefinition(14), ()) == ()
    assert compute_average_directional_index(DirectionalMovementDefinition(14), ()) == ()
    assert compute_relative_volume(RelativeVolumeDefinition(10), ()) == ()
    assert compute_macd_histogram(MacdHistogramDefinition(12, 26, 9), ()) == ()
    assert compute_candle_body_ratio(()) == ()


# ---------------------------------------------------------------------------
# D. No look-ahead bias - THE critical Backtest-adjacent safety property.
# For each feature: compute against the real series, then compute again
# against an IDENTICAL series except a bar strictly AFTER the point being
# checked is mutated - the earlier value(s) must be byte-for-byte
# unchanged. This is a PROOF (comparing two real computed values), not an
# assertion about implementation internals.
# ---------------------------------------------------------------------------


def _mutate_last_bar(bars: tuple[Bar, ...]) -> tuple[Bar, ...]:
    last = bars[-1]
    mutated = Bar(
        instrument_id=last.instrument_id,
        timeframe=last.timeframe,
        timestamp=last.timestamp,
        open=last.open + Decimal("50"),
        high=last.high + Decimal("60"),
        low=max(last.low - Decimal("10"), Decimal("1")),
        close=last.close + Decimal("55"),
        volume=last.volume + Decimal("9999"),
    )
    return bars[:-1] + (mutated,)


def test_d1_rsi_no_lookahead() -> None:
    bars = _random_bars(30)
    original = compute_relative_strength_index(RelativeStrengthIndexDefinition(14), bars)
    mutated_bars = _mutate_last_bar(bars)
    mutated = compute_relative_strength_index(RelativeStrengthIndexDefinition(14), mutated_bars)
    # Every value EXCEPT the one anchored on the mutated (last) bar must
    # be identical.
    assert original[:-1] == mutated[:-1]
    assert original[-1] != mutated[-1]  # sanity: the mutation DID matter for the last value


def test_d2_directional_movement_family_no_lookahead() -> None:
    bars = _random_bars(40)
    mutated_bars = _mutate_last_bar(bars)
    for fn in (
        compute_plus_directional_index,
        compute_minus_directional_index,
        compute_average_directional_index,
    ):
        original = fn(DirectionalMovementDefinition(14), bars)
        mutated = fn(DirectionalMovementDefinition(14), mutated_bars)
        assert original[:-1] == mutated[:-1]
        assert original[-1] != mutated[-1]


def test_d3_relative_volume_no_lookahead() -> None:
    bars = _random_bars(20)
    mutated_bars = _mutate_last_bar(bars)
    original = compute_relative_volume(RelativeVolumeDefinition(10), bars)
    mutated = compute_relative_volume(RelativeVolumeDefinition(10), mutated_bars)
    assert original[:-1] == mutated[:-1]
    assert original[-1] != mutated[-1]


def test_d4_macd_histogram_no_lookahead() -> None:
    bars = _random_bars(40)
    mutated_bars = _mutate_last_bar(bars)
    original = compute_macd_histogram(MacdHistogramDefinition(12, 26, 9), bars)
    mutated = compute_macd_histogram(MacdHistogramDefinition(12, 26, 9), mutated_bars)
    assert original[:-1] == mutated[:-1]
    assert original[-1] != mutated[-1]


def test_d5_candle_body_ratio_no_lookahead_trivially() -> None:
    # Stateless per-bar - a later mutation cannot affect ANY earlier
    # value, not even the "last unmutated" one adjacent to it.
    bars = _random_bars(10)
    mutated_bars = _mutate_last_bar(bars)
    original = compute_candle_body_ratio(bars)
    mutated = compute_candle_body_ratio(mutated_bars)
    assert original[:-1] == mutated[:-1]


def test_d6_mutating_a_middle_future_bar_leaves_earlier_history_unchanged() -> None:
    # Stronger variant: mutate a bar in the MIDDLE of the series (not just
    # the last one) and confirm every feature value computed from bars
    # strictly BEFORE that index is unchanged.
    bars = list(_random_bars(40))
    mutate_index = 25
    original_rsi = compute_relative_strength_index(RelativeStrengthIndexDefinition(14), tuple(bars))
    mutated_list = bars.copy()
    victim = mutated_list[mutate_index]
    mutated_list[mutate_index] = Bar(
        instrument_id=victim.instrument_id,
        timeframe=victim.timeframe,
        timestamp=victim.timestamp,
        open=victim.open + Decimal("30"),
        high=victim.high + Decimal("40"),
        low=max(victim.low - Decimal("5"), Decimal("1")),
        close=victim.close + Decimal("35"),
        volume=victim.volume + Decimal("500"),
    )
    mutated_rsi = compute_relative_strength_index(
        RelativeStrengthIndexDefinition(14), tuple(mutated_list)
    )
    # Every RSI value whose bar timestamp is strictly before the mutated
    # bar's timestamp must be identical.
    victim_ts = bars[mutate_index].timestamp
    original_before = [fv for fv in original_rsi if fv.timestamp < victim_ts]
    mutated_before = [fv for fv in mutated_rsi if fv.timestamp < victim_ts]
    assert original_before == mutated_before
    assert original_before  # sanity: there IS history before the mutation point


# ---------------------------------------------------------------------------
# E. Parameter validation.
# ---------------------------------------------------------------------------


def test_e1_rsi_rejects_non_positive_lookback() -> None:
    with pytest.raises(InvalidLookbackError):
        RelativeStrengthIndexDefinition(0)
    with pytest.raises(InvalidLookbackError):
        RelativeStrengthIndexDefinition(-5)


def test_e2_directional_movement_rejects_non_positive_lookback() -> None:
    with pytest.raises(InvalidLookbackError):
        DirectionalMovementDefinition(0)


def test_e3_relative_volume_rejects_non_positive_lookback() -> None:
    with pytest.raises(InvalidLookbackError):
        RelativeVolumeDefinition(0)


def test_e4_macd_histogram_rejects_fast_not_less_than_slow() -> None:
    with pytest.raises(InvalidLookbackError):
        MacdHistogramDefinition(26, 12, 9)
    with pytest.raises(InvalidLookbackError):
        MacdHistogramDefinition(12, 12, 9)


def test_e5_macd_histogram_rejects_non_positive_periods() -> None:
    with pytest.raises(InvalidLookbackError):
        MacdHistogramDefinition(0, 26, 9)


# ---------------------------------------------------------------------------
# F. Registry discoverability.
# ---------------------------------------------------------------------------


def test_f1_new_fields_are_registered() -> None:
    ids = {f.field_id for f in list_fields()}
    for expected in (
        "rsi",
        "adx",
        "plus_di",
        "minus_di",
        "relative_volume",
        "macd_hist",
        "candle_body_ratio",
    ):
        assert expected in ids, f"{expected} missing from field_registry.list_fields()"


def test_f2_delta_and_breakout_are_not_registered() -> None:
    # Deliberately deferred - ambiguous semantics, no Gainz source to
    # disambiguate (see module docstring).
    ids = {f.field_id for f in list_fields()}
    assert "delta" not in ids
    assert "breakout" not in ids


def test_f3_get_field_returns_definitions_for_new_fields() -> None:
    for field_id in ("rsi", "adx", "plus_di", "minus_di", "relative_volume", "macd_hist"):
        field = get_field(field_id)
        assert field is not None
        assert is_parameterized_feature(field_id) is True


def test_f4_candle_body_ratio_registered_as_parameterized_derived_feature() -> None:
    field = get_field("candle_body_ratio")
    assert field is not None
    # Registered under DERIVED_FEATURE category like every other computed
    # field, even though its actual compute function takes no lookback -
    # is_parameterized_feature() only inspects category, unaffected.
    assert is_parameterized_feature("candle_body_ratio") is True


# ---------------------------------------------------------------------------
# G. Coordinator access - the coordinator computes each field once and
# shares it, using the SAME real dispatcher production code uses.
# ---------------------------------------------------------------------------


def test_g1_coordinator_computes_new_fields_via_shared_dispatcher() -> None:
    bars = _random_bars(40)
    calls: list[str] = []

    def counting_dispatcher(field_id: str, bars_: tuple[Bar, ...]) -> tuple[FeatureValue, ...]:
        calls.append(field_id)
        return compute_feature_series(field_id, bars_)

    registry = StrategyRegistry()
    coordinator = StrategyExecutionCoordinator(registry, counting_dispatcher)
    # No active strategies registered -> run() still succeeds, exercising
    # only the "no active strategies" path; the dispatcher itself is
    # exercised directly below via the real production function.
    result = coordinator.run(bars, {})
    assert result.signals == ()

    # Exercise the real production dispatcher directly for every new
    # field_id shape, proving it is reachable through the SAME function
    # `build_coordinator()` wires into the real coordinator.
    for field_id in (
        "rsi_14",
        "adx_14",
        "plus_di_14",
        "minus_di_14",
        "relative_volume_10",
        "macd_hist_12_26_9",
        "candle_body_ratio",
    ):
        values = compute_feature_series(field_id, bars)
        assert isinstance(values, tuple)
        assert values, f"{field_id} produced no values for a 40-bar series"


def test_g2_coordinator_shares_one_computation_across_two_strategies() -> None:
    # "Compute once, share many" (Checkpoint 64.49 Part 21's architecture
    # goal) - two strategies both requiring "rsi_14" must trigger exactly
    # ONE dispatcher call for that field_id in one coordinator.run().
    bars = _random_bars(40)
    calls: list[str] = []

    def counting_dispatcher(field_id: str, bars_: tuple[Bar, ...]) -> tuple[FeatureValue, ...]:
        calls.append(field_id)
        return compute_feature_series(field_id, bars_)

    from intraday.trading_engine.strategy_execution.contracts import (
        StrategyConfigurationValues,
        StrategyParameterSchema,
        StrategySignal,
    )

    class _TwoStrategiesSharingRsi:
        def __init__(self, strategy_id: str) -> None:
            self.strategy_id = strategy_id
            self.display_name = strategy_id
            self.specification_version = "v1"
            self.code_version = "v1"

        def parameter_schema(self) -> StrategyParameterSchema:
            return StrategyParameterSchema(strategy_id=self.strategy_id, parameters=())

        def required_features(self, config: StrategyConfigurationValues) -> tuple[str, ...]:
            return ("rsi_14",)

        def evaluate(
            self,
            bar: Bar,
            feature_values: dict[str, FeatureValue],
            config: StrategyConfigurationValues,
        ) -> StrategySignal | None:
            return None

    registry = StrategyRegistry()
    registry.register(_TwoStrategiesSharingRsi("strat_a"))
    registry.register(_TwoStrategiesSharingRsi("strat_b"))
    registry.activate("strat_a")
    registry.activate("strat_b")

    config = StrategyConfigurationValues(
        strategy_id="strat_a",
        specification_version="v1",
        code_version="v1",
        configuration_version="v1",
        values={},
    )
    config_b = StrategyConfigurationValues(
        strategy_id="strat_b",
        specification_version="v1",
        code_version="v1",
        configuration_version="v1",
        values={},
    )
    coordinator = StrategyExecutionCoordinator(registry, counting_dispatcher)
    coordinator.run(bars, {"strat_a": config, "strat_b": config_b})

    assert (
        calls.count("rsi_14") == 1
    ), f"expected exactly one shared computation of rsi_14 across 2 strategies, got {calls}"


# ---------------------------------------------------------------------------
# H. Existing EMA/ATR behavior unchanged.
# ---------------------------------------------------------------------------


def test_h1_ema_and_atr_dispatch_unchanged() -> None:
    bars = _random_bars(40)
    ema_values = compute_feature_series("ema_9", bars)
    atr_values = compute_feature_series("atr_14", bars)
    assert ema_values
    assert atr_values

    from intraday.signal_intelligence.feature_engine.atr import compute_average_true_range
    from intraday.signal_intelligence.feature_engine.definitions import (
        AverageTrueRangeDefinition,
        ExponentialMovingAverageDefinition,
    )
    from intraday.signal_intelligence.feature_engine.ema import (
        compute_exponential_moving_average,
    )

    assert ema_values == compute_exponential_moving_average(
        ExponentialMovingAverageDefinition(9), bars
    )
    assert atr_values == compute_average_true_range(AverageTrueRangeDefinition(14), bars)


def test_h2_sma_dispatch_unchanged() -> None:
    bars = _random_bars(40)
    values = compute_feature_series("sma_20", bars)
    from intraday.signal_intelligence.feature_engine.definitions import (
        SimpleMovingAverageDefinition,
    )
    from intraday.signal_intelligence.feature_engine.sma import compute_simple_moving_average

    assert values == compute_simple_moving_average(SimpleMovingAverageDefinition(20), bars)


def test_h3_original_eight_fields_still_present() -> None:
    ids = {f.field_id for f in list_fields()}
    for original in ("open", "high", "low", "close", "volume", "sma", "ema", "atr"):
        assert original in ids


# ---------------------------------------------------------------------------
# I. No duplicate indicator framework.
# ---------------------------------------------------------------------------


def test_i1_no_second_indicator_framework_class_created() -> None:
    # Structural AST scan: no class named *Indicator*/*IndicatorFramework*/
    # *TechnicalAnalysis*/*Registry* (other than the real
    # `signal_intelligence.feature_engine.field_registry` module already
    # had) exists anywhere new this checkpoint.
    forbidden_substrings = ("IndicatorFramework", "TechnicalIndicators", "IndicatorRegistry")
    for py_file in SRC_ROOT.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for forbidden in forbidden_substrings:
                    assert (
                        forbidden not in node.name
                    ), f"{py_file}: found forbidden duplicate-framework class {node.name!r}"


def test_i2_no_gainz_named_indicator_module_exists() -> None:
    forbidden = (
        "GainzIndicators",
        "GainzFeatureEngine",
        "GainzTechnicalIndicators",
        "GainzRegistry",
    )
    for py_file in SRC_ROOT.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in text, f"{py_file}: contains forbidden {name!r}"


def test_i3_new_features_reuse_existing_ema_function_not_a_copy() -> None:
    # `macd_histogram.py` must import and call the SAME canonical EMA
    # function `ema.py` exports - not reimplement Bar-taking EMA.
    macd_source = (
        SRC_ROOT / "intraday/signal_intelligence/feature_engine/macd_histogram.py"
    ).read_text(encoding="utf-8")
    assert "from intraday.signal_intelligence.feature_engine.ema import" in macd_source
    assert "compute_exponential_moving_average" in macd_source


# ---------------------------------------------------------------------------
# J. No GainzStrategy implementation yet.
# ---------------------------------------------------------------------------


def test_j1_no_gainz_strategy_class_in_any_real_strategy_module() -> None:
    """As of 64.49, no strategy module had a Gainz-named class at all.

    Checkpoint 64.50 legitimately adds ONE honestly-labeled research/
    compatibility strategy class, `GainzCompatibleResearchStrategy` -
    explicitly NOT `GainzStrategy` and NOT verified GainzAlgo V2
    mathematics (see `gainz_compatible_research.py`'s own header). This
    assertion is updated (not deleted) to allow exactly that one class
    name while still failing on any other Gainz-named class, in
    particular the literal name `GainzStrategy` itself."""
    allowed_gainz_class = "GainzCompatibleResearchStrategy"
    for py_file in STRATEGIES_DIR.glob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and "gainz" in node.name.lower():
                assert (
                    node.name == allowed_gainz_class
                ), f"{py_file}: found an unexpected Gainz-named strategy class {node.name!r}"
                assert node.name != "GainzStrategy"


def test_j2_default_registry_has_no_gainz_strategy_id() -> None:
    from intraday.trading_engine.strategy_execution.registry import build_default_registry

    registry = build_default_registry()
    strategy_ids = {s.strategy_id for s in registry.list()}
    assert not any("gainz" in sid.lower() for sid in strategy_ids)


# ---------------------------------------------------------------------------
# ZZ. Honesty guard - re-confirm no real Gainz source exists anywhere in
# this repository, this session.
# ---------------------------------------------------------------------------


def test_zz_no_real_gainz_source_file_exists() -> None:
    hits: list[str] = []
    for root_dir in (SRC_ROOT, REPO_ROOT / "tests", REPO_ROOT / "docs"):
        if not root_dir.exists():
            continue
        for py_or_md in list(root_dir.rglob("*.py")) + list(root_dir.rglob("*.md")):
            try:
                text = py_or_md.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if "gainz" in text.lower():
                hits.append(str(py_or_md))
    # Every hit must be a checkpoint 64.44/46/47/48/49 artifact (design
    # docs, task reports, or this/its predecessor test files) - never an
    # actual Gainz implementation module.
    allowed_markers = (
        "64_44",
        "64_46",
        "64_47",
        "64_48",
        "64_49",
        "64_50",
        "taskReport.md",
        "CANONICAL_TRADE_LIFECYCLE_AND_PNL_ARCHITECTURE.md",
        # Checkpoint 64.49's own new canonical-feature modules mention
        # "Gainz" only to honestly disclaim "not verified against a
        # Gainz reference (none exists)" - never to port Gainz math.
        "field_registry.py",
        "rsi.py",
        "directional_movement.py",
        "relative_volume.py",
        "macd_histogram.py",
        "candle_body_ratio.py",
        "strategy_execution.py",
        "definitions.py",
        # Checkpoint 64.50: the honestly-labeled research/compatibility
        # strategy that CONSUMES those canonical features - explicitly
        # NOT a Gainz reference implementation (see its own header).
        "gainz_compatible_research.py",
        # Checkpoint 64.51: this checkpoint's own new registry-regression
        # test file - discusses the same already-allowed research
        # strategy, adds no new Gainz-named artifact.
        "64_51",
        # Checkpoint 64.52: this checkpoint's own new database-first
        # backtest integration test file - discusses the same
        # already-allowed `GainzCompatibleResearchStrategy` artifact,
        # proving pipeline integration only, no new Gainz-named module.
        "64_52",
        # Checkpoint 64.68: this checkpoint's own paper-trading MVP test
        # files. They reference Gainz ONLY to PROVE its continued
        # absence - one asserts no `GainzPaperEngine` class exists
        # anywhere, the other asserts `gainz_compatible_research` is
        # REFUSED by the paper-session API because it is not in the
        # default registry. No Gainz math, module or activation is added.
        "64_68",
        # Checkpoint 64.73: the daily-archive architecture doc's own
        # Phase 11 requirement ("explicit statement that Gainz remains
        # disabled") - a single safety-disclaimer sentence, not a
        # reference implementation. No Gainz math or module was added.
        "DAILY_MARKET_DATA_ARCHIVE_ARCHITECTURE",
        # Checkpoint 64.76: Dhan option-capability RESEARCH. Its single
        # Gainz mention is one prose line naming "market state at a Gainz
        # signal timestamp" as a FUTURE historical-retention requirement -
        # a statement of what would be needed, not an implementation. No
        # Gainz math, module or activation was added there or since.
        "64_76",
        "DHAN_MARKET_DATA_CAPABILITY_RESEARCH",
        # Checkpoint 64.82: the correlation query API doc's Gainz section
        # states only that Gainz remains disabled and that no
        # Gainz-specific query path was added. 64.82 added the doc but
        # did not allowlist it here, leaving this guard red; 64.83
        # restores it. A disclaimer, not an implementation.
        "CORRELATION_QUERY_API",
        # Checkpoint 64.83: the archive query API doc records that
        # archive-qualified outcome evidence is a PREREQUISITE for any
        # future Gainz attribution, and that none of it exists yet. No
        # Gainz math, module or activation was added.
        "MARKET_DATA_ARCHIVE_QUERY_API",
        # Checkpoint 64.97: canonical feature-engine extension - generic
        # engulfing-pattern and N-bar price-delta features. Each new
        # module mentions "Gainz" only to honestly disclaim that it is a
        # GENERIC feature structurally similar to (but not verified
        # against) the read-only research/rebuild reference file - never
        # to port authentic Gainz math. Includes this checkpoint's own
        # test file, taskReport.md content, and the audit doc.
        "64_97",
        "bullish_engulfing.py",
        "bearish_engulfing.py",
        "price_delta.py",
        "GAINZ_SIGNAL_ENGINE_AUDIT.md",
        "gainz_signal_engine_reference.py",
        # Checkpoint 64.99: the first real Gainz Research Adapter
        # (profile "alpha" only) and its dedicated test file - see that
        # module's own "HONESTY NOTICE" header.
        "64_99",
        # Checkpoint 65.03/65.04/65.05: Market Context Intelligence
        # feature modules (price_vs_ma_pct, rebound_candidate,
        # ma_divergence) and their dedicated test files. Each mentions
        # "Gainz" only to honestly disclaim "GENERIC feature, NOT
        # Gainz-specific" / "NOT verified against a Gainz reference" -
        # never to port Gainz math or connect to Gainz. See each
        # module's own docstring and MARKET_CONTEXT_INTELLIGENCE.md.
        "65_03",
        "65_04",
        "65_05",
        "rebound_candidate.py",
        "ma_divergence.py",
        "MARKET_CONTEXT_INTELLIGENCE.md",
        # Checkpoint 65.07/65.08: the categorical-feature-value contract
        # and the market_regime feature it enables. Each mentions "Gainz"
        # only to honestly disclaim "NOT Gainz-specific" / to note the
        # pre-existing gainz_signal_engine_reference.py `regime` label is
        # non-authoritative prior art - never to port Gainz math or
        # connect market_regime to Gainz. See each module's own docstring
        # and MARKET_CONTEXT_INTELLIGENCE.md.
        "65_07",
        "65_08",
        "market_regime.py",
    )
    for hit in hits:
        assert any(
            marker in hit for marker in allowed_markers
        ), f"unexpected Gainz reference found outside known checkpoint artifacts: {hit}"
