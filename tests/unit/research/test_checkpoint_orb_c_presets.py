# tests/unit/research/test_checkpoint_orb_c_presets.py
#
# CHECKPOINT-ORB-C: 3 config presets (classic/tight/wide) for
# `orb_breakout`. Matches `test_checkpoint_vwap_c_presets.py`'s own
# rigor and structure: each preset's canonical values live in ONE
# shared module-level function, used BOTH to persist a real
# `StrategyConfigurationRecord` row (via the real
# `StrategyConfigurationService.save_configuration()` path, never a
# raw ORM insert) AND to construct an in-memory
# `StrategyConfigurationValues` directly for the behavioral-divergence
# tests (no database dependency there). `registry.py` untouched.
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from intraday.application.services.strategy_configuration import StrategyConfigurationService
from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe, Version
from intraday.infrastructure.persistence.models import StrategyConfigurationRecord
from intraday.infrastructure.persistence.repositories import DjangoStrategyConfigurationRepository
from intraday.trading_engine.strategy_execution.contracts import (
    StrategyConfigurationValues,
    StrategyDirection,
    coerce_configuration_values,
)
from intraday.trading_engine.strategy_execution.registry import StrategyRegistry
from intraday.trading_engine.strategy_execution.strategies.orb_breakout import (
    STRATEGY_ID,
    OrbBreakoutStrategy,
)

IID = InstrumentId("NSE:ORBCTEST")
TF = Timeframe.FIVE_MINUTE
TS = datetime(2026, 1, 5, 4, 0, tzinfo=UTC)
FV_VERSION = Version(value="v1")

CLASSIC_VERSION = "orb_classic"
TIGHT_VERSION = "orb_tight"
WIDE_VERSION = "orb_wide"


def classic_values() -> dict[str, object]:
    return {
        "opening_range_minutes": 15,
        "target_range_multiplier": "1.0",
        "stop_range_fraction": "1.0",
        "minimum_range_atr_multiplier": "0",
        "atr_lookback": 14,
    }


def tight_values() -> dict[str, object]:
    return {
        "opening_range_minutes": 5,
        "target_range_multiplier": "1.0",
        "stop_range_fraction": "1.0",
        "minimum_range_atr_multiplier": "0",
        "atr_lookback": 14,
    }


def wide_values() -> dict[str, object]:
    return {
        "opening_range_minutes": 30,
        "target_range_multiplier": "1.5",
        "stop_range_fraction": "0.75",
        "minimum_range_atr_multiplier": "0",
        "atr_lookback": 14,
    }


def _bar(close: str) -> Bar:
    price = Decimal(close)
    return Bar(
        instrument_id=IID,
        timeframe=TF,
        timestamp=TS,
        open=price,
        high=price + Decimal("1"),
        low=price - Decimal("1"),
        close=price,
        volume=Decimal("1000"),
    )


def _feature(name: str, value: str) -> FeatureValue:
    return FeatureValue(
        feature_name=name,
        feature_version=FV_VERSION,
        instrument_id=IID,
        timeframe=TF,
        timestamp=TS,
        value=Decimal(value),
    )


def _local_registry() -> StrategyRegistry:
    registry = StrategyRegistry()
    registry.register(OrbBreakoutStrategy())
    return registry


def _service() -> StrategyConfigurationService:
    return StrategyConfigurationService(
        repository=DjangoStrategyConfigurationRepository(), registry=_local_registry()
    )


def _config_from(values: dict[str, object], configuration_version: str) -> StrategyConfigurationValues:
    schema = OrbBreakoutStrategy().parameter_schema()
    coerced = coerce_configuration_values(schema, values)
    return StrategyConfigurationValues(STRATEGY_ID, "v1", "v1", configuration_version, coerced)


# ---------------------------------------------------------------------------
# 1. Creation, count, retrievability, distinctness - real DB rows.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_1_three_presets_created_retrievable_and_distinct() -> None:
    before = StrategyConfigurationRecord.objects.filter(strategy_id=STRATEGY_ID).count()
    assert before == 0

    service = _service()
    for configuration_version, values in (
        (CLASSIC_VERSION, classic_values()),
        (TIGHT_VERSION, tight_values()),
        (WIDE_VERSION, wide_values()),
    ):
        snapshot = service.save_configuration(
            STRATEGY_ID, "v1", "v1", configuration_version, values, created_by="checkpoint-orb-c",
        )
        assert snapshot.configuration_version == configuration_version

    after = StrategyConfigurationRecord.objects.filter(strategy_id=STRATEGY_ID).count()
    assert after == 3

    repo = DjangoStrategyConfigurationRepository()
    classic = repo.get(STRATEGY_ID, "v1", "v1", CLASSIC_VERSION)
    tight = repo.get(STRATEGY_ID, "v1", "v1", TIGHT_VERSION)
    wide = repo.get(STRATEGY_ID, "v1", "v1", WIDE_VERSION)
    assert classic is not None and tight is not None and wide is not None

    assert classic.parameter_values["opening_range_minutes"] == 15
    assert tight.parameter_values["opening_range_minutes"] == 5
    assert wide.parameter_values["opening_range_minutes"] == 30
    assert classic.parameter_values != tight.parameter_values != wide.parameter_values

    # minimum_range_atr_multiplier/atr_lookback deliberately identical
    # across all 3 (the filter stays disabled everywhere; no reason
    # found to vary the ATR lookback either).
    assert (
        classic.parameter_values["minimum_range_atr_multiplier"]
        == tight.parameter_values["minimum_range_atr_multiplier"]
        == wide.parameter_values["minimum_range_atr_multiplier"]
        == "0"
    )
    assert (
        classic.parameter_values["atr_lookback"]
        == tight.parameter_values["atr_lookback"]
        == wide.parameter_values["atr_lookback"]
        == 14
    )


@pytest.mark.django_db
def test_2_each_preset_persists_and_reloads_through_coerce_into_valid_values() -> None:
    service = _service()
    repo = DjangoStrategyConfigurationRepository()
    for configuration_version, values in (
        (CLASSIC_VERSION, classic_values()),
        (TIGHT_VERSION, tight_values()),
        (WIDE_VERSION, wide_values()),
    ):
        service.save_configuration(
            STRATEGY_ID, "v1", "v1", configuration_version, values, created_by="checkpoint-orb-c",
        )
        rec = repo.get(STRATEGY_ID, "v1", "v1", configuration_version)
        assert rec is not None
        config = _config_from(dict(rec.parameter_values), configuration_version)
        assert isinstance(config.values["opening_range_minutes"], int)
        assert isinstance(config.values["target_range_multiplier"], Decimal)
        assert isinstance(config.values["stop_range_fraction"], Decimal)


def test_3_ascending_window_duration_tight_lt_classic_lt_wide() -> None:
    assert (
        tight_values()["opening_range_minutes"]
        < classic_values()["opening_range_minutes"]
        < wide_values()["opening_range_minutes"]
    )


def test_4_every_preset_produces_a_valid_internally_consistent_plan() -> None:
    """Direct verification, not assumed from `CHECKPOINT-ORB-B`'s own
    structural-safety claim alone: for each preset's REAL values, a
    genuine breakout must produce a plan with `stop < entry < target`
    (BULLISH) - confirmed against all 3 presets, not just the schema
    defaults."""
    strategy = OrbBreakoutStrategy()
    for name, values in (
        (CLASSIC_VERSION, classic_values()),
        (TIGHT_VERSION, tight_values()),
        (WIDE_VERSION, wide_values()),
    ):
        config = _config_from(values, name)
        n = config.values["opening_range_minutes"]
        feature_values = {
            f"opening_range_high_{n}": _feature(f"opening_range_high_{n}", "110"),
            f"opening_range_low_{n}": _feature(f"opening_range_low_{n}", "100"),
        }
        bar = _bar("112")
        signal = strategy.evaluate(bar, feature_values, config)
        assert signal is not None
        assert signal.direction is StrategyDirection.BULLISH
        plan = strategy.build_trade_plan(bar, feature_values, config, signal)
        assert plan is not None, f"{name}: expected a valid plan"
        assert plan.stop_loss < plan.entry_price < plan.target_1, f"{name}: degenerate plan"


# ---------------------------------------------------------------------------
# 2. Real behavioral divergence - the actual point of this checkpoint.
#    A constructed bar sequence where orb_tight's 5-minute window
#    produces a range (and therefore a signal) BEFORE orb_classic's
#    15-minute window has even completed.
# ---------------------------------------------------------------------------


def _session_bars(open_ts: datetime, closes: list[tuple[str, str, str, str]]) -> tuple[Bar, ...]:
    from datetime import timedelta

    return tuple(
        Bar(
            instrument_id=IID,
            timeframe=TF,
            timestamp=open_ts + timedelta(minutes=5 * (i + 1)),
            open=Decimal(o),
            high=Decimal(h),
            low=Decimal(lo),
            close=Decimal(c),
            volume=Decimal("1000"),
        )
        for i, (o, h, lo, c) in enumerate(closes)
    )


def test_5_tight_window_completes_and_signals_while_classic_window_is_still_forming() -> None:
    """The actual proof: on the SAME real bar sequence, `orb_tight`'s
    5-minute (1-bar) window is already complete and breaking out by the
    2nd bar - while `orb_classic`'s 15-minute (3-bar) window has not
    even finished forming yet (needs 3 bars before it can emit
    anything at all, per CHECKPOINT-ORB-A's own warm-up rule) -
    isolating `orb_tight`'s own shorter window as the cause of the
    earlier signal, not a different bar series."""
    from datetime import timedelta

    from intraday.application.services.strategy_execution import compute_feature_series

    open_ts = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)  # 09:15 IST market_open
    bars = _session_bars(
        open_ts,
        [
            ("100", "105", "98", "102"),  # 09:20 IST - orb_tight's ENTIRE window (5 min = 1 bar)
            ("102", "112", "101", "110"),  # 09:25 IST - first bar AFTER tight's window
            ("110", "111", "109", "110"),  # 09:30 IST - classic's window still needs this bar
        ],
    )

    tight_config = _config_from(tight_values(), TIGHT_VERSION)
    classic_config = _config_from(classic_values(), CLASSIC_VERSION)

    tight_high_name = f"opening_range_high_{tight_config.values['opening_range_minutes']}"
    tight_low_name = f"opening_range_low_{tight_config.values['opening_range_minutes']}"
    classic_high_name = f"opening_range_high_{classic_config.values['opening_range_minutes']}"
    classic_low_name = f"opening_range_low_{classic_config.values['opening_range_minutes']}"

    tight_high_series = compute_feature_series(tight_high_name, bars)
    tight_low_series = compute_feature_series(tight_low_name, bars)
    classic_high_series = compute_feature_series(classic_high_name, bars)
    classic_low_series = compute_feature_series(classic_low_name, bars)

    # orb_tight (5-min window = bar 0 only) already has a frozen range
    # by bar 1 (09:25 IST) - its window closed after just 1 bar.
    assert len(tight_high_series) == 2  # bars 1 and 2 both get a value
    assert tight_high_series[0].timestamp == bars[1].timestamp

    # orb_classic (15-min window = bars 0,1,2) has NOT completed even
    # by the 3rd bar (09:30 IST) itself - no output at all yet in this
    # 3-bar series (the classic window's own first possible output is
    # the 4th bar, which this fixture doesn't include).
    assert classic_high_series == ()
    assert classic_low_series == ()

    strategy = OrbBreakoutStrategy()
    # Evaluate orb_tight at bar 1 (09:25 IST): range = [98,105] (bar 0's
    # own high/low), close=110 > 105 -> BULLISH breakout already fired.
    tight_feature_values = {
        tight_high_name: tight_high_series[0],
        tight_low_name: tight_low_series[0],
    }
    tight_signal = strategy.evaluate(bars[1], tight_feature_values, tight_config)
    assert tight_signal is not None
    assert tight_signal.direction is StrategyDirection.BULLISH

    # orb_classic at the SAME bar 1: no range feature available at all
    # yet (window incomplete) - genuinely no opinion, not a fabricated
    # NEUTRAL.
    classic_signal = strategy.evaluate(bars[1], {}, classic_config)
    assert classic_signal is None


def test_6_wide_presets_own_target_and_stop_differ_from_classic_on_identical_range() -> None:
    """A second, complementary divergence proof: the SAME range feeds
    `orb_classic` and `orb_wide` (both use compatible windows on
    different real data, but here isolated to just the target/stop
    math itself) - `orb_wide`'s own target_range_multiplier=1.5/
    stop_range_fraction=0.75 must produce a genuinely different
    target/stop than `orb_classic`'s 1.0/1.0, on the IDENTICAL range
    and entry price."""
    strategy = OrbBreakoutStrategy()
    range_high, range_low, entry = "110", "100", "112"

    classic_config = _config_from(classic_values(), CLASSIC_VERSION)
    n_classic = classic_config.values["opening_range_minutes"]
    classic_features = {
        f"opening_range_high_{n_classic}": _feature(f"opening_range_high_{n_classic}", range_high),
        f"opening_range_low_{n_classic}": _feature(f"opening_range_low_{n_classic}", range_low),
    }
    classic_bar = _bar(entry)
    classic_signal = strategy.evaluate(classic_bar, classic_features, classic_config)
    assert classic_signal is not None
    classic_plan = strategy.build_trade_plan(classic_bar, classic_features, classic_config, classic_signal)
    assert classic_plan is not None

    wide_config = _config_from(wide_values(), WIDE_VERSION)
    n_wide = wide_config.values["opening_range_minutes"]
    wide_features = {
        f"opening_range_high_{n_wide}": _feature(f"opening_range_high_{n_wide}", range_high),
        f"opening_range_low_{n_wide}": _feature(f"opening_range_low_{n_wide}", range_low),
    }
    wide_bar = _bar(entry)
    wide_signal = strategy.evaluate(wide_bar, wide_features, wide_config)
    assert wide_signal is not None
    wide_plan = strategy.build_trade_plan(wide_bar, wide_features, wide_config, wide_signal)
    assert wide_plan is not None

    # classic: target = 112 + 1.0*10 = 122; stop = range_low = 100
    assert classic_plan.target_1 == Decimal("122")
    assert classic_plan.stop_loss == Decimal("100")
    # wide: target = 112 + 1.5*10 = 127; stop = 110 - 0.75*10 = 102.5
    assert wide_plan.target_1 == Decimal("127")
    assert wide_plan.stop_loss == Decimal("102.50")

    assert classic_plan.target_1 != wide_plan.target_1
    assert classic_plan.stop_loss != wide_plan.stop_loss
