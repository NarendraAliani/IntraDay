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
# `compute_feature_series` was the real SMA/EMA/ATR dispatcher INJECTED
# into `StrategyExecutionCoordinator` (see that module's own header for
# why the injection exists - `.importlinter` contract 4 forbids
# `trading_engine` from importing `signal_intelligence` directly).
#
# CHECKPOINT-SCANNER-A: `compute_feature_series` itself has RELOCATED to
# `signal_intelligence.feature_engine.dispatch` (imported below) - a
# pure move, not a rewrite (see that module's own header comment for the
# full architectural rationale: the function never actually depended on
# anything strategy-execution-specific, only on `domain` and its own
# `feature_engine` siblings, so composing it there needs no special
# permission at all). `build_coordinator()` below still does the
# INJECTION this module's own header describes - that composition step
# (wiring the dispatcher into `StrategyExecutionCoordinator`) is still
# exactly where `.importlinter` contract 3's layering requires it to
# happen; only the dispatcher's own definition moved.
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from intraday.application.services.market_data import HistoricalMarketDataService
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe
from intraday.signal_intelligence.feature_engine.dispatch import compute_feature_series
from intraday.trading_engine.strategy_execution.contracts import StrategyConfigurationValues
from intraday.trading_engine.strategy_execution.coordinator import (
    CoordinatorResult,
    StrategyExecutionCoordinator,
)
from intraday.trading_engine.strategy_execution.registry import StrategyRegistry


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
