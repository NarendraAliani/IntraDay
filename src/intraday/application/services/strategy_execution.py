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
from intraday.signal_intelligence.feature_engine.definitions import (
    AverageTrueRangeDefinition,
    ExponentialMovingAverageDefinition,
    SimpleMovingAverageDefinition,
)
from intraday.signal_intelligence.feature_engine.ema import compute_exponential_moving_average
from intraday.signal_intelligence.feature_engine.sma import compute_simple_moving_average
from intraday.trading_engine.strategy_execution.contracts import StrategyConfigurationValues
from intraday.trading_engine.strategy_execution.coordinator import (
    CoordinatorResult,
    StrategyExecutionCoordinator,
)
from intraday.trading_engine.strategy_execution.registry import StrategyRegistry


def compute_feature_series(field_id: str, bars: tuple[Bar, ...]) -> tuple[FeatureValue, ...]:
    """Dispatches one "sma_20"/"ema_9"/"atr_14"-shaped field_id to the
    matching existing compute function. Raises ValueError for anything
    else - callers only ever pass field_ids strategies themselves
    declared via `required_features()`, which are always SMA/EMA/ATR
    (raw OHLCV fields are read straight off `Bar`, never computed)."""
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
