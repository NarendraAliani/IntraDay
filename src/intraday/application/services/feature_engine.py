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
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from intraday.application.services.market_data import HistoricalMarketDataService
from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe
from intraday.signal_intelligence.feature_engine.definitions import (
    SimpleMovingAverageDefinition,
)
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
