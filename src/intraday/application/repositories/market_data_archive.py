# File: src/intraday/application/repositories/market_data_archive.py
#
# Checkpoint 64.73: the persistence-neutral Protocol for the daily
# market-data archive. Follows this project's established dependency
# inversion discipline exactly (Checkpoint 7 / .importlinter contract
# 6): the interface lives here in `application.repositories`, the
# Django ORM implementation lives in `infrastructure.persistence` and
# depends INWARD on this - never the reverse.
#
# The read methods are deliberately shaped as WHOLE-DAY sweeps
# (`*_for_trading_date`) rather than per-symbol calls in a loop. One
# archive refresh for a trading day must be a bounded number of indexed
# queries, not N+1 - see `models.py`'s `trading_date` indexes, which
# exist precisely so these are index scans rather than the full-table
# scans a future research workload could not tolerate.
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from intraday.domain.market_data.aggregation import AggregatedBar
from intraday.domain.market_data.archive import (
    ArchiveDayAssessment,
    ArchiveStatus,
    ReconciliationStatus,
)
from intraday.domain.market_data.contracts import Quote
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe


@dataclass(frozen=True, slots=True)
class QuoteObservationSummary:
    """Per-symbol raw-observation facts for one trading date - the
    evidence `assess_archive_day()` needs about the RAW tick/quote
    layer, without loading thousands of individual observation rows
    into memory (64.72 alone persisted 4,869 of them in 20 minutes)."""

    instrument_symbol: str
    observation_count: int
    first_observation_at: datetime | None
    last_observation_at: datetime | None
    data_source: str = ""
    """Checkpoint 64.75: the provenance these observations were recorded
    under (`LiveQuoteObservation.data_source`). Summaries are now grouped
    by (symbol, source) rather than symbol alone, so a symbol-day
    observed by two providers no longer attributes ONE undifferentiated
    quote count to BOTH of its archive cells.

    `""` is the group of pre-64.75 rows that carry no recorded
    provenance; `MarketDataArchiveService` deliberately still attributes
    that group to a cell of any source (see `_summary_for_cell`), so
    64.62-64.74 evidence days keep the exact quote counts they already
    had rather than silently dropping to zero."""


@dataclass(frozen=True, slots=True)
class BarCell:
    """One (symbol, timeframe, data_source) bar cell for one trading
    date. `closed_bar_close_timestamps` are bar CLOSE instants
    (`AggregatedBarObservation.interval_end`), matching the vocabulary
    `domain.market_data.quality` already speaks."""

    instrument_symbol: str
    timeframe: Timeframe
    data_source: str
    closed_bar_close_timestamps: tuple[datetime, ...]
    forming_bar_count: int


@dataclass(frozen=True, slots=True)
class ArchiveDayRecord:
    """The PERSISTED projection of an `ArchiveDayAssessment` - what a
    later query reads back without recomputing. Always reproducible
    from the underlying observations; the stored row is a cache for
    queryability, never a second source of truth."""

    exchange: Exchange
    trading_date: date
    instrument_symbol: str
    timeframe: Timeframe
    data_source: str
    status: ArchiveStatus
    reason: str
    completeness_supported: bool
    expected_bar_count: int
    closed_bar_count: int
    forming_bar_count: int
    missing_bar_count: int
    duplicate_bar_count: int
    quote_observation_count: int
    first_observation_at: datetime | None
    last_observation_at: datetime | None
    reconciliation_status: ReconciliationStatus
    reconciled_at: datetime | None
    computed_at: datetime | None


class MarketDataArchiveRepository(Protocol):
    # --- evidence gathering (drives assessment) ----------------------
    def quote_summaries_for_trading_date(
        self, *, exchange: Exchange, trading_date: date
    ) -> tuple[QuoteObservationSummary, ...]: ...

    def bar_cells_for_trading_date(
        self, *, exchange: Exchange, trading_date: date
    ) -> tuple[BarCell, ...]: ...

    # --- assessment persistence (idempotent upsert) ------------------
    def save_assessment(self, assessment: ArchiveDayAssessment, *, computed_at: datetime) -> None:
        """UPSERT keyed on `(exchange, trading_date, instrument_symbol,
        timeframe, data_source)`. Re-running an archive refresh for the
        same day MUST update the same row, never append a second one -
        this is the archive's idempotency guarantee."""
        ...

    # --- queryability (Phase 4) --------------------------------------
    def list_archive_days(
        self,
        *,
        trading_date: date,
        exchange: Exchange | None = None,
        instrument_symbol: str | None = None,
        timeframe: Timeframe | None = None,
    ) -> tuple[ArchiveDayRecord, ...]: ...

    def list_bars(
        self,
        *,
        exchange: Exchange,
        trading_date: date,
        instrument_symbol: str,
        timeframe: Timeframe,
    ) -> tuple[AggregatedBar, ...]: ...

    def list_quote_observations(
        self, *, exchange: Exchange, trading_date: date, instrument_symbol: str
    ) -> tuple[Quote, ...]: ...

    def archived_symbols_for_trading_date(
        self, *, exchange: Exchange, trading_date: date
    ) -> tuple[str, ...]: ...


__all__ = [
    "ArchiveDayRecord",
    "BarCell",
    "MarketDataArchiveRepository",
    "QuoteObservationSummary",
]
