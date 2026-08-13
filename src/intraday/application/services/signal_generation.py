# File: src/intraday/application/services/signal_generation.py
#
# Checkpoint 18: the application-layer Signal Generation orchestrator -
# composes Checkpoint 14's `HistoricalMarketDataService` (bar retrieval)
# with Checkpoint 15-17's `FeatureEngineService` (SMA/EMA/ATR
# computation) and `signal_intelligence.signal_generation`'s pure
# alignment/interpretation function. Exactly `application/`'s documented
# role (`.importlinter` contract #3) - it never bypasses either service
# to reach a concrete repository/fixture/Dhan adapter directly, and it
# contains NO signal-generation mathematics of its own (Checkpoint 18
# §15: "the application layer may coordinate... it must not duplicate
# signal-generation mathematics").
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from intraday.application.services.feature_engine import FeatureEngineService
from intraday.application.services.market_data import HistoricalMarketDataService
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe
from intraday.signal_intelligence.feature_engine.definitions import (
    AverageTrueRangeDefinition,
    ExponentialMovingAverageDefinition,
    SimpleMovingAverageDefinition,
)
from intraday.signal_intelligence.signal_generation.contracts import DirectionalIndication
from intraday.signal_intelligence.signal_generation.directional import (
    generate_directional_indications,
)


@dataclass(frozen=True, slots=True)
class SignalGenerationService:
    """Retrieves bars via `HistoricalMarketDataService`, computes
    SMA/EMA/ATR via `FeatureEngineService`, and delegates alignment plus
    interpretation to `signal_intelligence.signal_generation` - this
    class contains no directional-rule logic of its own. Testable with
    an in-memory fake market-data repository (mirrors every other
    application service in this codebase); never imports Django,
    PostgreSQL, Redis, Celery, HTTP, or Dhan."""

    market_data: HistoricalMarketDataService
    feature_engine: FeatureEngineService

    def generate_directional_indications(
        self,
        sma_definition: SimpleMovingAverageDefinition,
        ema_definition: ExponentialMovingAverageDefinition,
        atr_definition: AverageTrueRangeDefinition,
        instrument_id: InstrumentId,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> tuple[DirectionalIndication, ...]:
        bars = self.market_data.get_bars(instrument_id, timeframe, start, end)
        sma_values = self.feature_engine.simple_moving_average(
            sma_definition, instrument_id, timeframe, start, end
        )
        ema_values = self.feature_engine.exponential_moving_average(
            ema_definition, instrument_id, timeframe, start, end
        )
        atr_values = self.feature_engine.average_true_range(
            atr_definition, instrument_id, timeframe, start, end
        )
        return generate_directional_indications(bars, sma_values, ema_values, atr_values)
