# File: src/intraday/application/services/signal_verification.py
#
# Checkpoint 19: the application-layer Signal Verification orchestrator
# - composes Checkpoint 14's `HistoricalMarketDataService` (future-bar
# retrieval) with `signal_intelligence.signal_verification`'s pure
# evaluation function. Exactly `application/`'s documented role
# (`.importlinter` contract #3) - contains no verification mathematics
# of its own (Checkpoint 19 §18).
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from intraday.application.services.market_data import HistoricalMarketDataService
from intraday.domain.market_data.quality import timeframe_to_timedelta
from intraday.signal_intelligence.signal_generation.contracts import DirectionalIndication
from intraday.signal_intelligence.signal_verification.contracts import VerificationResult
from intraday.signal_intelligence.signal_verification.verification import (
    verify_directional_indication,
)


@dataclass(frozen=True, slots=True)
class SignalVerificationService:
    """Retrieves the bars following a `DirectionalIndication` via
    `HistoricalMarketDataService` and delegates evaluation to
    `signal_intelligence.signal_verification` - this class contains no
    outcome-determination logic of its own. Testable with an in-memory
    fake market-data repository (mirrors every other application-service
    test in this codebase); never imports Django, PostgreSQL, Redis,
    Celery, HTTP, or Dhan."""

    market_data: HistoricalMarketDataService

    def verify(self, indication: DirectionalIndication, horizon_bars: int) -> VerificationResult:
        # Retrieve a generous upper bound of bars after the signal (the
        # verifier itself only ever uses the one bar at `horizon_bars`
        # ahead - see verification.py's own docstring - extra bars are
        # simply ignored, never a look-ahead risk since they're all
        # already-strictly-future by construction of the query window).
        duration = timeframe_to_timedelta(indication.timeframe) * horizon_bars
        end = indication.timestamp + duration + timedelta(seconds=1)
        start = indication.timestamp
        bars = self.market_data.get_bars(indication.instrument_id, indication.timeframe, start, end)
        future_bars = tuple(bar for bar in bars if bar.timestamp > indication.timestamp)
        return verify_directional_indication(indication, future_bars, horizon_bars)
