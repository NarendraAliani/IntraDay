# File: src/intraday/application/services/theoretical_outcome.py
#
# Checkpoint 21: the application-layer Theoretical Outcome orchestrator
# - composes Checkpoint 14's `HistoricalMarketDataService` (future-bar
# retrieval) with `signal_intelligence.theoretical_outcome`'s pure
# measurement function. Exactly `application/`'s documented role
# (`.importlinter` contract #3) - contains no MFE/MAE mathematics of its
# own. Mirrors `SignalVerificationService`'s (Checkpoint 19) exact shape
# - orchestration was genuinely required here (real bar retrieval),
# unlike Checkpoint 20's `signal_lifecycle`, which needed none.
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from intraday.application.services.market_data import HistoricalMarketDataService
from intraday.domain.market_data.quality import timeframe_to_timedelta
from intraday.signal_intelligence.signal_generation.contracts import DirectionalIndication
from intraday.signal_intelligence.theoretical_outcome.contracts import TheoreticalOutcome
from intraday.signal_intelligence.theoretical_outcome.outcome import compute_theoretical_outcome


@dataclass(frozen=True, slots=True)
class TheoreticalOutcomeService:
    """Retrieves the bars following a `DirectionalIndication` via
    `HistoricalMarketDataService` and delegates measurement to
    `signal_intelligence.theoretical_outcome` - this class contains no
    MFE/MAE logic of its own. Testable with an in-memory fake market-
    data repository (mirrors every other application-service test in
    this codebase); never imports Django, PostgreSQL, Redis, Celery,
    HTTP, or Dhan."""

    market_data: HistoricalMarketDataService

    def measure(self, indication: DirectionalIndication, horizon_bars: int) -> TheoreticalOutcome:
        duration = timeframe_to_timedelta(indication.timeframe) * horizon_bars
        end = indication.timestamp + duration + timedelta(seconds=1)
        start = indication.timestamp
        bars = self.market_data.get_bars(indication.instrument_id, indication.timeframe, start, end)
        future_bars = tuple(bar for bar in bars if bar.timestamp > indication.timestamp)
        return compute_theoretical_outcome(indication, future_bars, horizon_bars)
