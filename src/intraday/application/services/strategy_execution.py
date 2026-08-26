# File: src/intraday/application/services/strategy_execution.py
#
# Checkpoint 26 Part 15/17: diagnostic/backtest strategy-execution
# service. This is the ONLY orchestration point that feeds bars into the
# `StrategyExecutionCoordinator` - and it is structurally, not just
# procedurally, prevented from ever touching live market data: it
# depends solely on `HistoricalMarketDataService`
# (application/services/market_data.py), which itself depends only on
# the `HistoricalMarketDataRepository` Protocol - the exact same
# fixture/historical-only pattern `SignalGenerationService`
# (Checkpoint 18) already established.
#
# This module imports NOTHING from:
#   - infrastructure.persistence.live_market_data_repositories
#   - application.services.bar_aggregation
#   - any Dhan-related module
# That import boundary is proven mechanically, not just declared, by
# tests/unit/architecture/test_strategy_execution_sample_bar_boundary.py
# (ast-based static import scan - Checkpoint 26 Part 15's own
# requirement for a "dedicated test", matching this project's
# established "prove don't just declare" discipline).
#
# A SAMPLE_BAR-derived `Bar` (Checkpoint 24A's `AggregatedBar.to_bar()`)
# is type-identical to a fixture/historical `Bar` - nothing at the type
# level distinguishes them. The import-boundary guarantee above is what
# actually prevents live data from reaching this service, not the type
# system. Activation status (StrategyRegistry.activate/get_active) is
# also explicitly NOT trading authorization - see Part 14 and
# docs/architecture/STRATEGY_ENGINE_ARCHITECTURE.md.
#
# `compute_feature_series` below is the real SMA/EMA/ATR dispatcher
# INJECTED into `StrategyExecutionCoordinator` (see that module's own
# header for why the injection exists - `.importlinter` contract 4
# forbids `trading_engine` from importing `signal_intelligence`
# directly). This application-layer module is exactly where that
# composition is architecturally permitted (contract 3's layering:
# application -> bounded contexts -> domain), so it is the correct,
# and only, place this dispatch function is allowed to live.
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from intraday.application.services.market_data import HistoricalMarketDataService
from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe
from intraday.signal_intelligence.feature_engine.atr import compute_average_true_range
from intraday.signal_intelligence.feature_engine.candle_body_ratio import (
    CANDLE_BODY_RATIO_FIELD_ID,
    compute_candle_body_ratio,
)
from intraday.signal_intelligence.feature_engine.definitions import (
    AverageTrueRangeDefinition,
    DirectionalMovementDefinition,
    ExponentialMovingAverageDefinition,
    MacdHistogramDefinition,
    RelativeStrengthIndexDefinition,
    RelativeVolumeDefinition,
    SimpleMovingAverageDefinition,
)
from intraday.signal_intelligence.feature_engine.directional_movement import (
    compute_average_directional_index,
    compute_minus_directional_index,
    compute_plus_directional_index,
)
from intraday.signal_intelligence.feature_engine.ema import compute_exponential_moving_average
from intraday.signal_intelligence.feature_engine.field_registry import parse_feature_name
from intraday.signal_intelligence.feature_engine.macd_histogram import compute_macd_histogram
from intraday.signal_intelligence.feature_engine.relative_volume import compute_relative_volume
from intraday.signal_intelligence.feature_engine.rsi import compute_relative_strength_index
from intraday.signal_intelligence.feature_engine.sma import compute_simple_moving_average
from intraday.trading_engine.strategy_execution.contracts import StrategyConfigurationValues
from intraday.trading_engine.strategy_execution.coordinator import (
    CoordinatorResult,
    StrategyExecutionCoordinator,
)
from intraday.trading_engine.strategy_execution.registry import StrategyRegistry


def compute_feature_series(field_id: str, bars: tuple[Bar, ...]) -> tuple[FeatureValue, ...]:
    """Dispatches one "sma_20"/"ema_9"/"atr_14"/"rsi_14"/"adx_14"/
    "plus_di_14"/"minus_di_14"/"relative_volume_20"/
    "macd_hist_12_26_9"/"candle_body_ratio"-shaped field_id to the
    matching existing compute function. Raises ValueError for anything
    else - callers only ever pass field_ids strategies themselves
    declared via `required_features()` (raw OHLCV fields are read
    straight off `Bar`, never computed).

    Checkpoint 64.49 adds RSI/ADX/+DI/-DI/Relative Volume/MACD Histogram/
    Candle Body Ratio dispatch, following the exact same parse-then-
    construct-a-Definition-then-call-the-pure-function shape SMA/EMA/ATR
    already established - no second dispatch mechanism introduced."""
    if field_id == CANDLE_BODY_RATIO_FIELD_ID:
        return compute_candle_body_ratio(bars)

    # Multi-word kinds ("plus_di", "minus_di", "relative_volume",
    # "macd_hist") need the SUFFIX of trailing integer parameters
    # stripped, not just a single first-`_`-partition - unlike
    # "sma_20"/"ema_9"/"atr_14"/"rsi_14"/"adx_14", which are already a
    # single-word kind.
    # Checkpoint 64.81: the parse itself now lives in
    # `feature_engine.field_registry.parse_feature_name()` - LIFTED, not
    # duplicated, so the traceability resolver that maps a feature name
    # back to its canonical registry field_id can never drift from this
    # dispatcher. The algorithm is byte-for-byte the one this function
    # has used since Checkpoint 64.49; no dispatch behaviour changes.
    kind, params = parse_feature_name(field_id)

    if kind == "sma":
        return compute_simple_moving_average(SimpleMovingAverageDefinition(params[0]), bars)
    if kind == "ema":
        return compute_exponential_moving_average(
            ExponentialMovingAverageDefinition(params[0]), bars
        )
    if kind == "atr":
        return compute_average_true_range(AverageTrueRangeDefinition(params[0]), bars)
    if kind == "rsi":
        return compute_relative_strength_index(RelativeStrengthIndexDefinition(params[0]), bars)
    if kind == "adx":
        return compute_average_directional_index(DirectionalMovementDefinition(params[0]), bars)
    if kind == "plus_di":
        return compute_plus_directional_index(DirectionalMovementDefinition(params[0]), bars)
    if kind == "minus_di":
        return compute_minus_directional_index(DirectionalMovementDefinition(params[0]), bars)
    if kind == "relative_volume":
        return compute_relative_volume(RelativeVolumeDefinition(params[0]), bars)
    if kind == "macd_hist":
        return compute_macd_histogram(MacdHistogramDefinition(*params), bars)
    raise ValueError(f"unrecognized computed field_id {field_id!r}")


def build_coordinator(registry: StrategyRegistry) -> StrategyExecutionCoordinator:
    """The single place a real (non-fake/non-test) `StrategyExecutionCoordinator`
    is constructed, with the real feature dispatcher wired in."""
    return StrategyExecutionCoordinator(registry, compute_feature_series)


@dataclass
class DiagnosticStrategyExecutionService:
    """Runs active strategies against FIXTURE/HISTORICAL bars only, for
    diagnostics, backtesting, and UI previews - never for live/actionable
    signal execution (Checkpoint 26's own explicit scope boundary; live
    signal execution remains blocked until TRADING_GRADE_BAR is accepted
    in a future checkpoint - Checkpoint 25.1)."""

    market_data: HistoricalMarketDataService
    coordinator: StrategyExecutionCoordinator

    def run(
        self,
        instrument_id: InstrumentId,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
        configurations: dict[str, StrategyConfigurationValues],
    ) -> CoordinatorResult:
        bars = self.market_data.get_bars(instrument_id, timeframe, start, end)
        return self.coordinator.run(bars, configurations)
