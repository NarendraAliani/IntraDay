# File: src/intraday/application/services/market_data.py
#
# Checkpoint 14: historical market-data application service — the use-
# case layer between a future API/consumer (feature_engine,
# research.backtesting, etc.) and the repository Protocol
# (application/repositories.HistoricalMarketDataRepository). Depends only
# on that Protocol — never a concrete Django/Dhan/fixture implementation
# — so this class is fully testable with an in-memory fake repository
# (see tests/unit/application/services/test_market_data_service.py),
# mirroring the pattern established by RiskConfigurationService
# (Checkpoint 8).
#
# No API view, URL, or OpenAPI schema consumes this service yet
# (Checkpoint 14 §19 — no premature API boundary or frontend). It exists
# so `feature_engine`/`signal_generation`/`research.backtesting` (future
# checkpoints) have one, tested, provider-neutral place to ask for
# validated historical bars, rather than each reaching into a repository
# directly and re-implementing the same ordering/completeness checks.
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from intraday.application.repositories import HistoricalMarketDataRepository
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.quality import (
    ensure_chronological,
    missing_bar_timestamps,
)
from intraday.domain.session.contracts import TradingSession
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe


@dataclass(frozen=True, slots=True)
class HistoricalMarketDataService:
    """Use cases for retrieving and validating historical market data.
    Contains no persistence logic and no provider knowledge of its own —
    it only orchestrates a call to the injected repository and applies
    the domain-layer integrity rules every consumer needs, once."""

    repository: HistoricalMarketDataRepository

    def get_bars(
        self,
        instrument_id: InstrumentId,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> tuple[Bar, ...]:
        """Returns bars in strict chronological order with no duplicates.
        Raises `domain.market_data.quality.OutOfOrderBarError`/
        `DuplicateBarTimestampError` if the repository's data violates
        that — never silently reorders or drops a bar (Checkpoint 14
        §16). Callers that need resilience against a specific
        misbehaving provider handle that at the infrastructure adapter,
        not here."""
        bars = self.repository.get_bars(instrument_id, timeframe, start, end)
        return ensure_chronological(bars)

    def completeness(
        self,
        instrument_id: InstrumentId,
        timeframe: Timeframe,
        session: TradingSession,
    ) -> tuple[datetime, ...]:
        """The bar-close timestamps expected for a complete `timeframe`
        series within `session` that are missing from the repository's
        data — empty when the series is complete. Deterministic: depends
        only on `session`'s own bounds and `timeframe`'s fixed duration,
        never an exchange-calendar lookup (Checkpoint 14 §11)."""
        bars = self.repository.get_bars(
            instrument_id, timeframe, session.market_open, session.market_close
        )
        return missing_bar_timestamps(bars, session, timeframe)
