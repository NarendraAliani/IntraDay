# File: src/intraday/application/services/bar_aggregation.py
#
# Checkpoint 24A: application-layer orchestration for live quote-to-bar
# aggregation. Depends only on repository Protocols and pure domain
# logic (`domain.market_data.aggregation`) - never a concrete Dhan/HTTP
# client, matching `application/services/live_market_data.py`'s own
# `.importlinter` contract 6 discipline. This service makes NO broker
# call of its own - it only reads already-persisted `Quote` observations
# and writes derived `AggregatedBar`s.
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from intraday.application.repositories.live_market_data import (
    AggregatedBarRepository,
    LiveQuoteRepository,
)
from intraday.domain.market_data.aggregation import (
    AggregatedBar,
    BarAggregationResult,
    aggregate_quotes_into_bars,
)
from intraday.domain.shared_kernel.contracts import Timeframe

DHAN_DATA_SOURCE = "dhan"

# How far back to look when aggregating (Checkpoint 24A §4's "1-minute
# bars... unless the existing architecture establishes a different
# canonical base timeframe" - no such timeframe exists yet, so 1-minute
# is this checkpoint's canonical base). A generous lookback (the full
# trading session) rather than "since the last aggregation run" keeps
# aggregation a genuinely pure, stateless recomputation each time
# (matching `domain/market_data/aggregation.py`'s own documented
# design) - it does not need to remember where it left off.
DEFAULT_LOOKBACK = timedelta(hours=8)
DEFAULT_TIMEFRAME = Timeframe.ONE_MINUTE


@dataclass(frozen=True, slots=True)
class BarAggregationService:
    quote_repository: LiveQuoteRepository
    bar_repository: AggregatedBarRepository

    def aggregate_and_persist(
        self, *, as_of: datetime, timeframe: Timeframe = DEFAULT_TIMEFRAME
    ) -> BarAggregationResult:
        """Reads recent quote observations, aggregates them into bars
        (pure, deterministic - see `domain/market_data/aggregation.py`),
        and persists the result (upsert - see `AggregatedBarRepository`'s
        own docstring for why this differs from the append-only quote
        log). Returns the full result, including missing intervals and
        anomalous observations, so the caller (the view layer) can
        report them - never silently swallowed."""
        since = as_of - DEFAULT_LOOKBACK
        quotes = self.quote_repository.get_observations(since=since)
        result = aggregate_quotes_into_bars(
            quotes, timeframe=timeframe, as_of=as_of, data_source=DHAN_DATA_SOURCE
        )
        self.bar_repository.save_all(result.bars)
        return result

    def get_recent_bars(
        self, *, timeframe: Timeframe = DEFAULT_TIMEFRAME, limit: int = 200
    ) -> tuple[AggregatedBar, ...]:
        """Read-only - never triggers aggregation itself (Checkpoint
        24A §11's "the API must not trigger broker calls," and more
        generally must not trigger any write as a side effect of a
        read)."""
        return self.bar_repository.get_recent(timeframe=timeframe, limit=limit)
