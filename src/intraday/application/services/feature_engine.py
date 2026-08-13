# File: src/intraday/application/services/feature_engine.py
#
# Checkpoint 15: the application-layer Feature Engine orchestrator -
# composes Checkpoint 14's `HistoricalMarketDataService` (provider-
# neutral bar retrieval) with `signal_intelligence.feature_engine`'s pure
# calculation (`compute_simple_moving_average`). This is exactly
# `application/`'s documented role: orchestrating the bounded contexts
# (`.importlinter` contract #3, "Application -> bounded contexts ->
# domain layering") - it never bypasses `HistoricalMarketDataService` to
# reach a concrete repository/fixture/Dhan adapter directly (Checkpoint
# 15 §15).
#
# Checkpoint 16 adds `exponential_moving_average()` following the exact
# same shape as `simple_moving_average()` - no new abstraction was needed
# to expose a second, recursively-computed feature through this service;
# it retrieves bars via `HistoricalMarketDataService` and delegates to
# `signal_intelligence.feature_engine.ema.compute_exponential_moving_average`.
#
# Checkpoint 17 adds `average_true_range()` - the third feature, again
# following the identical shape, confirming the service does not need to
# change even for a computation consuming OHLC instead of close-only.
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from intraday.application.services.market_data import HistoricalMarketDataService
from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe
from intraday.signal_intelligence.feature_engine.atr import compute_average_true_range
from intraday.signal_intelligence.feature_engine.definitions import (
    AverageTrueRangeDefinition,
    ExponentialMovingAverageDefinition,
    SimpleMovingAverageDefinition,
)
from intraday.signal_intelligence.feature_engine.ema import compute_exponential_moving_average
from intraday.signal_intelligence.feature_engine.sma import compute_simple_moving_average


@dataclass(frozen=True, slots=True)
class FeatureEngineService:
    """Retrieves validated historical bars via
    `HistoricalMarketDataService` and delegates the actual computation to
    `signal_intelligence.feature_engine` - this class contains no
    indicator math of its own. Testable with an in-memory fake market-
    data repository (mirrors every other application service in this
    codebase); never imports Django, PostgreSQL, Redis, Celery, HTTP, or
    Dhan."""

    market_data: HistoricalMarketDataService

    def simple_moving_average(
        self,
        definition: SimpleMovingAverageDefinition,
        instrument_id: InstrumentId,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> tuple[FeatureValue, ...]:
        bars = self.market_data.get_bars(instrument_id, timeframe, start, end)
        return compute_simple_moving_average(definition, bars)

    def exponential_moving_average(
        self,
        definition: ExponentialMovingAverageDefinition,
        instrument_id: InstrumentId,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> tuple[FeatureValue, ...]:
        bars = self.market_data.get_bars(instrument_id, timeframe, start, end)
        return compute_exponential_moving_average(definition, bars)

    def average_true_range(
        self,
        definition: AverageTrueRangeDefinition,
        instrument_id: InstrumentId,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> tuple[FeatureValue, ...]:
        bars = self.market_data.get_bars(instrument_id, timeframe, start, end)
        return compute_average_true_range(definition, bars)
