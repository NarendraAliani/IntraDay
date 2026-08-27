# File: tests/unit/research/test_checkpoint_64_51_registry_regression.py
#
# Checkpoint 64.51: REPOSITORY-WIDE REGRESSION CLEANUP + STRATEGY
# REGISTRY BOUNDARY.
#
# 64.50 discovered (and honestly flagged, out-of-scope) that
# `tests/unit/trading_engine/test_strategy_execution.py` had two stale
# assertions hard-coding the PRE-64.49 8-field canonical registry
# inventory - a real regression once 64.49 intentionally added 7 more
# fields (rsi/adx/plus_di/minus_di/relative_volume/macd_hist/
# candle_body_ratio). Those two tests were fixed IN PLACE in that file
# (see `test_field_registry_every_field_has_a_real_dispatchable_
# implementation` and the rewritten `test_field_registry_never_lists_
# unimplemented_indicators`), replacing the stale fixed-inventory
# assertion with an architectural one: every field the registry lists
# must have a real, dispatchable implementation.
#
# This file holds only NEW 64.51 architectural tests (per the
# checkpoint directive's own Part 14 instruction not to duplicate that
# fix's purpose here) - it proves the surrounding CONTRACT stays
# internally consistent: the canonical feature registry, the default
# strategy roster, and `GainzCompatibleResearchStrategy`'s deliberate
# research-only registry boundary.
from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from intraday.application.services.strategy_execution import compute_feature_series
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import Timeframe
from intraday.signal_intelligence.feature_engine.field_registry import (
    FieldCategory,
    get_field,
    list_fields,
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
from intraday.trading_engine.strategy_execution.strategies.gainz_compatible_research import (
    STRATEGY_ID as GAINZ_RESEARCH_STRATEGY_ID,
)
from intraday.trading_engine.strategy_execution.strategies.gainz_compatible_research import (
    GainzCompatibleResearchStrategy,
)
from intraday.trading_engine.strategy_execution.strategies.sma_trend_filter import (
    SmaTrendFilterStrategy,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
INSTRUMENT = "NSE:TESTCO"


def _bars_with_volume(count: int) -> tuple[Bar, ...]:
    base = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)
    bars = []
    for i in range(count):
        price = Decimal(100 + i)
        bars.append(
            Bar(
                instrument_id=INSTRUMENT,
                timeframe=Timeframe.ONE_MINUTE,
                timestamp=base + timedelta(minutes=i),
                open=price - 1,
                high=price + 1,
                low=price - 2,
                close=price,
                volume=Decimal(1000 + (i % 5) * 25),
            )
        )
    return tuple(bars)


# ---------------------------------------------------------------------------
# A/B. Current canonical registry contract: every registered field is real
# and dispatchable, using the CURRENT 15-field registry - not a hard-coded
# historical count. Derives its expectations from `list_fields()` itself
# for the SHAPE (raw vs. derived), but proves REAL implementation by
# actually invoking the real dispatcher/Bar attributes, so it cannot pass
# merely because the registry says it should.
# ---------------------------------------------------------------------------


def test_a_canonical_registry_field_count_is_the_current_15_not_the_stale_8() -> None:
    """Documents, with an explicit assertion (not just a comment), the
    CURRENT canonical field count following 64.49's intentional
    expansion, and 64.97's further addition of bullish_engulfing/
    bearish_engulfing/price_delta (18 total). This is a deliberate
    architectural assertion (Part 3's permitted exception: "unless that
    is genuinely the correct architectural assertion") - the count is
    pinned so a future accidental field removal/addition is caught,
    exactly the class of regression this checkpoint exists to prevent
    recurring. (Test name kept historically accurate to 64.49/64.51 - the
    count itself is the current, up-to-date 18.)"""
    field_ids = {f.field_id for f in list_fields()}
    assert len(field_ids) == 18
    assert field_ids == {
        "open",
        "high",
        "low",
        "close",
        "volume",
        "sma",
        "ema",
        "atr",
        "rsi",
        "adx",
        "plus_di",
        "minus_di",
        "relative_volume",
        "macd_hist",
        "candle_body_ratio",
        "bullish_engulfing",
        "bearish_engulfing",
        "price_delta",
    }


def test_b_every_registered_field_is_dispatchable_through_the_real_dispatcher() -> None:
    """B: every registered field_id has a real implementation reachable
    through the exact dispatcher `build_coordinator()` wires into the
    real coordinator - not a second, test-only computation path."""
    bars = _bars_with_volume(80)
    lookback_by_kind = {
        "sma": "20",
        "ema": "20",
        "atr": "14",
        "rsi": "14",
        "adx": "14",
        "plus_di": "14",
        "minus_di": "14",
        "relative_volume": "20",
    }
    for field_def in list_fields():
        if field_def.category in (FieldCategory.RAW_PRICE, FieldCategory.RAW_VOLUME):
            assert hasattr(bars[0], field_def.field_id)
            continue
        if field_def.field_id == "candle_body_ratio":
            concrete = "candle_body_ratio"
        elif field_def.field_id == "macd_hist":
            concrete = "macd_hist_12_26_9"
        elif field_def.field_id in ("bullish_engulfing", "bearish_engulfing"):
            concrete = field_def.field_id
        elif field_def.field_id == "price_delta":
            concrete = "price_delta_10"
        else:
            concrete = f"{field_def.field_id}_{lookback_by_kind[field_def.field_id]}"
        values = compute_feature_series(concrete, bars)
        assert isinstance(values, tuple)
        assert len(values) > 0


def test_b_registered_but_unimplemented_field_would_be_caught_not_a_circular_test() -> None:
    """Anti-circularity proof, kept as an executable test (not just a
    narrative claim in a report): a field_id shaped like a registered
    one but with a kind the real dispatcher does not recognize still
    raises - proving `test_b_every_registered_field_is_dispatchable...`
    is not vacuously true merely because it asks the registry about
    itself. (The registry->dispatcher mismatch scenario itself was
    manually verified during this checkpoint's own work by temporarily
    injecting a fake `_derived("supertrend", ...)` registry entry and
    confirming both this file's and `test_strategy_execution.py`'s
    field-registry tests failed loudly - reverted before this file was
    finalized, per the checkpoint's regression-safety discipline.)"""
    with pytest.raises(ValueError):
        compute_feature_series("supertrend_14", _bars_with_volume(20))


# ---------------------------------------------------------------------------
# C. No stale pre-64.49 8-field assumption remains in ACTIVE tests.
# ---------------------------------------------------------------------------


def test_c_no_active_test_still_asserts_the_stale_pre_64_49_eight_field_set() -> None:
    """A repository-wide static scan (not a narrative claim) for the
    exact stale literal set
    `{"open", "high", "low", "close", "volume", "sma", "ema", "atr"}`
    used as an EQUALITY assertion (`==`) against `list_fields()`'s
    field_ids anywhere under tests/. A SUBSET/membership check (e.g.
    `test_h3_original_eight_fields_still_present` in
    test_checkpoint_64_49_gainz_feature_registry.py, which legitimately
    asserts the ORIGINAL 8 are still present, not that they are the
    ONLY 15) is a different, still-valid claim and must not trip this
    scan."""
    tests_root = REPO_ROOT / "tests"
    stale_pattern = '{"open", "high", "low", "close", "volume", "sma", "ema", "atr"}'
    offenders: list[str] = []
    for py_file in tests_root.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        if stale_pattern not in text:
            continue
        # Only flag it if used as an EQUALITY comparison against
        # field_ids - not a subset/membership check (those are fine).
        idx = text.index(stale_pattern)
        preceding = text[max(0, idx - 40) : idx]
        if "==" in preceding and "for" not in preceding:
            offenders.append(str(py_file.relative_to(REPO_ROOT)))
    assert offenders == [], f"stale 8-field equality assertion still present in: {offenders}"


# ---------------------------------------------------------------------------
# D/E. Default production roster stays intentional; the research strategy
# stays outside it unless the architecture explicitly changes that policy.
# ---------------------------------------------------------------------------


def test_d_default_registry_contains_exactly_the_intended_production_roster() -> None:
    registry = build_default_registry()
    ids = {s.strategy_id for s in registry.list()}
    assert ids == {"ema_crossover", "sma_trend_filter", "atr_volatility_breakout"}
    assert len(registry.list()) == 3


def test_e_gainz_compatible_research_strategy_is_not_in_the_default_registry() -> None:
    """Architectural test, not a hard-coded workaround: constructs the
    REAL `build_default_registry()` and proves the research strategy's
    `strategy_id` is genuinely absent - if a future checkpoint adds it
    to the default roster, this test fails, forcing that decision to be
    made explicitly rather than silently."""
    registry = build_default_registry()
    ids = {s.strategy_id for s in registry.list()}
    assert GAINZ_RESEARCH_STRATEGY_ID not in ids
    assert GAINZ_RESEARCH_STRATEGY_ID == "gainz_compatible_research"


def test_e_gainz_compatible_research_strategy_remains_separately_registrable() -> None:
    """Documents, with a passing test, the exact minimal mechanism this
    checkpoint's Part 7 audit found ALREADY exists: `StrategyRegistry`
    is one canonical class with a public `register()` method. Production
    code calls `build_default_registry()` (a curated, fixed roster);
    research/test code may construct its own `StrategyRegistry()` and
    `register()` any additional strategy explicitly - exactly what
    64.50's own test suite already did. No second registry class, no
    `ResearchStrategyRegistry`, was needed or created."""
    registry = StrategyRegistry()
    registry.register(GainzCompatibleResearchStrategy())
    assert registry.get(GAINZ_RESEARCH_STRATEGY_ID) is not None
    registry.activate(GAINZ_RESEARCH_STRATEGY_ID)
    assert registry.is_active(GAINZ_RESEARCH_STRATEGY_ID)


# ---------------------------------------------------------------------------
# F. Registry lookup remains correct.
# ---------------------------------------------------------------------------


def test_f_field_registry_lookup_is_consistent_between_list_and_get() -> None:
    for field_def in list_fields():
        looked_up = get_field(field_def.field_id)
        assert looked_up is field_def


def test_f_strategy_registry_lookup_is_consistent_between_list_and_get() -> None:
    registry = build_default_registry()
    for strategy in registry.list():
        assert registry.get(strategy.strategy_id) is strategy


# ---------------------------------------------------------------------------
# G/H. Existing 64.50 strategy registration still works; existing
# strategies remain unaffected by this checkpoint's test-only changes.
# ---------------------------------------------------------------------------


def test_g_gainz_compatible_research_strategy_still_registers_and_validates() -> None:
    registry = StrategyRegistry()
    registry.register(GainzCompatibleResearchStrategy())
    strategy = registry.get(GAINZ_RESEARCH_STRATEGY_ID)
    schema = strategy.parameter_schema()
    assert schema.strategy_id == GAINZ_RESEARCH_STRATEGY_ID
    known_field_ids = frozenset(f.field_id for f in list_fields())
    # Empty values dict must be fine - every parameter carries a
    # conservative default (64.50's own documented invariant).
    from intraday.trading_engine.strategy_execution.contracts import validate_configuration

    validate_configuration(schema, {}, known_field_ids=known_field_ids)


def test_h_original_three_strategies_are_unaffected_by_this_checkpoint() -> None:
    """H: the three pre-existing production strategies still construct,
    still expose a parameter_schema, and are still the ONLY members of
    the default roster - proving this checkpoint's test-only regression
    cleanup touched no production strategy behavior."""
    for cls, expected_id in (
        (EmaCrossoverStrategy, "ema_crossover"),
        (SmaTrendFilterStrategy, "sma_trend_filter"),
        (AtrVolatilityBreakoutStrategy, "atr_volatility_breakout"),
    ):
        instance = cls()
        assert instance.strategy_id == expected_id
        assert instance.parameter_schema().strategy_id == expected_id


# ---------------------------------------------------------------------------
# No Gainz mathematics / Delta / Breakout honesty guard (64.51 repeats the
# same discipline every prior checkpoint since 64.44 has independently
# re-verified) - a fast, file-local AST scan, not a repo-wide re-scan
# (that remains 64.49's `test_zz_...`/64.50's own guards' job).
# ---------------------------------------------------------------------------


def test_no_delta_or_breakout_implementation_was_added_this_checkpoint() -> None:
    field_ids = {f.field_id for f in list_fields()}
    assert "delta" not in field_ids
    assert "breakout" not in field_ids
    with pytest.raises(ValueError):
        compute_feature_series("delta_14", _bars_with_volume(20))
    with pytest.raises(ValueError):
        compute_feature_series("breakout_14", _bars_with_volume(20))


def test_gainz_compatible_research_strategy_source_still_carries_no_gainz_math_claim() -> None:
    strategy_file = (
        REPO_ROOT
        / "src/intraday/trading_engine/strategy_execution/strategies"
        / "gainz_compatible_research.py"
    )
    text = strategy_file.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(strategy_file))
    class_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    assert class_names == {"GainzCompatibleResearchStrategy"}
    assert "GainzStrategy" not in class_names
    assert "NOT" in text and "GainzAlgo V2" in text
