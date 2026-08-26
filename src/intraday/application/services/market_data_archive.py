# File: src/intraday/application/services/market_data_archive.py
#
# Checkpoint 64.73: the application-layer orchestrator for the daily
# market-data archive. It owns NO rules of its own - trading-date
# derivation, session shape, expected-bar arithmetic and the status
# decision all live in `domain.market_data.archive` /
# `domain.market_data.quality` / `domain.session.calendar`. This
# service only:
#
#   1. gathers evidence for a trading date (two bounded, indexed reads),
#   2. asks the domain to classify each (symbol, timeframe, source) cell,
#   3. upserts the resulting assessments idempotently,
#   4. exposes the Phase 4 query surface over what was stored.
#
# It NEVER writes market data, never touches the ingestion path, and
# never deletes anything.
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from intraday.application.repositories.market_data_archive import (
    ArchiveDayRecord,
    BarCell,
    MarketDataArchiveRepository,
    QuoteObservationSummary,
)
from intraday.domain.market_data.aggregation import AggregatedBar
from intraday.domain.market_data.archive import (
    ArchiveDayAssessment,
    ArchiveStatus,
    TradingSessionIdentity,
    assess_archive_day,
    trading_date_for,
)
from intraday.domain.market_data.contracts import Quote
from intraday.domain.session.calendar import (
    build_cas_aware_session_for,
    build_session_for,
    instrument_category_for,
)
from intraday.domain.session.contracts import CasAwareSession, TradingSession
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe, ensure_utc


@dataclass(frozen=True, slots=True)
class TradingDayArchiveSummary:
    """The whole-day answer to "what does the archive hold for date X?"
    `status` is the WORST cell status on the day (see
    `_rollup_status`) - a day is only COMPLETE when every archived
    (symbol, timeframe) cell on it is COMPLETE, never when merely one
    is."""

    identity: TradingSessionIdentity
    status: ArchiveStatus
    symbol_count: int
    cells: tuple[ArchiveDayRecord, ...]

    @property
    def is_trading_day(self) -> bool:
        return self.identity.is_trading_day


# Worst-to-best. A day rolls up to the WORST status present, so a
# single un-observed or failed symbol can never be hidden behind a
# majority of healthy ones.
_SEVERITY: tuple[ArchiveStatus, ...] = (
    ArchiveStatus.FAILED,
    ArchiveStatus.NOT_OBSERVED,
    ArchiveStatus.IN_PROGRESS,
    ArchiveStatus.PARTIAL,
    ArchiveStatus.COMPLETE,
)


def _rollup_status(statuses: tuple[ArchiveStatus, ...]) -> ArchiveStatus:
    if not statuses:
        return ArchiveStatus.NOT_OBSERVED
    for candidate in _SEVERITY:
        if candidate in statuses:
            return candidate
    return ArchiveStatus.NOT_OBSERVED


class MarketDataArchiveService:
    def __init__(
        self,
        repository: MarketDataArchiveRepository,
        *,
        exchange: Exchange = Exchange.NSE,
    ) -> None:
        self._repository = repository
        self._exchange = exchange

    # ---------------------------------------------------------------
    # Refresh (idempotent)
    # ---------------------------------------------------------------
    def refresh_trading_date(
        self, *, trading_date: date, as_of: datetime, ingestion_failed: bool = False
    ) -> tuple[ArchiveDayAssessment, ...]:
        """Recomputes and upserts every archive cell for `trading_date`.

        Safe to call repeatedly - `save_assessment()` is an upsert on
        the natural key, so a second refresh of an unchanged day
        rewrites the same rows with the same values rather than
        duplicating them."""
        ensure_utc(as_of, field_name="as_of")
        identity = TradingSessionIdentity(exchange=self._exchange, trading_date=trading_date)
        session = build_session_for(trading_date, as_of)

        quote_summaries = self._repository.quote_summaries_for_trading_date(
            exchange=self._exchange, trading_date=trading_date
        )
        cells = self._repository.bar_cells_for_trading_date(
            exchange=self._exchange, trading_date=trading_date
        )

        assessments: list[ArchiveDayAssessment] = []
        for cell in cells:
            summary = _summary_for_cell(quote_summaries, cell)
            assessment = assess_cell(
                identity=identity,
                session=session,
                as_of=as_of,
                cell_symbol=cell.instrument_symbol,
                timeframe=cell.timeframe,
                data_source=cell.data_source,
                closed_bar_close_timestamps=cell.closed_bar_close_timestamps,
                forming_bar_count=cell.forming_bar_count,
                quote_observation_count=summary.observation_count if summary else 0,
                first_observation_at=summary.first_observation_at if summary else None,
                last_observation_at=summary.last_observation_at if summary else None,
                ingestion_failed=ingestion_failed,
            )
            self._repository.save_assessment(assessment, computed_at=as_of)
            assessments.append(assessment)
        return tuple(assessments)

    def refresh_for_instant(
        self, *, as_of: datetime, ingestion_failed: bool = False
    ) -> tuple[ArchiveDayAssessment, ...]:
        """Refreshes whichever trading date `as_of` falls in, deriving
        it through the one canonical IST rule (`trading_date_for`)."""
        return self.refresh_trading_date(
            trading_date=trading_date_for(as_of),
            as_of=as_of,
            ingestion_failed=ingestion_failed,
        )

    # ---------------------------------------------------------------
    # Queryability (Phase 4)
    # ---------------------------------------------------------------
    def describe_trading_date(self, *, trading_date: date) -> TradingDayArchiveSummary:
        records = self._repository.list_archive_days(
            trading_date=trading_date, exchange=self._exchange
        )
        identity = TradingSessionIdentity(exchange=self._exchange, trading_date=trading_date)
        if not identity.is_trading_day:
            return TradingDayArchiveSummary(
                identity=identity,
                status=ArchiveStatus.NOT_OBSERVED,
                symbol_count=0,
                cells=records,
            )
        return TradingDayArchiveSummary(
            identity=identity,
            status=_rollup_status(tuple(record.status for record in records)),
            symbol_count=len({record.instrument_symbol for record in records}),
            cells=records,
        )

    def archived_symbols(self, *, trading_date: date) -> tuple[str, ...]:
        return self._repository.archived_symbols_for_trading_date(
            exchange=self._exchange, trading_date=trading_date
        )

    def bars_for(
        self, *, instrument_symbol: str, trading_date: date, timeframe: Timeframe
    ) -> tuple[AggregatedBar, ...]:
        return self._repository.list_bars(
            exchange=self._exchange,
            trading_date=trading_date,
            instrument_symbol=instrument_symbol,
            timeframe=timeframe,
        )

    def quote_observations_for(
        self, *, instrument_symbol: str, trading_date: date
    ) -> tuple[Quote, ...]:
        return self._repository.list_quote_observations(
            exchange=self._exchange,
            trading_date=trading_date,
            instrument_symbol=instrument_symbol,
        )

    def gaps_for(
        self, *, instrument_symbol: str, trading_date: date, timeframe: Timeframe
    ) -> tuple[ArchiveDayRecord, ...]:
        """The archive cells for one symbol/day/timeframe, carrying
        `missing_bar_count`. The exact missing timestamps are always
        recomputable via `assess_archive_day()`; the stored row keeps
        the COUNT so "which days have gaps" is an indexed query rather
        than a recomputation over every day ever observed."""
        return self._repository.list_archive_days(
            trading_date=trading_date,
            exchange=self._exchange,
            instrument_symbol=instrument_symbol,
            timeframe=timeframe,
        )


def _summary_for_cell(
    summaries: tuple[QuoteObservationSummary, ...], cell: BarCell
) -> QuoteObservationSummary | None:
    """Which raw-observation group belongs to this bar cell.

    Checkpoint 64.75. Two rules, in order:

    1. EXACT provenance match on (symbol, data_source) - the correct
       attribution once observations record their source. Before 64.75
       every cell for a symbol received the SAME symbol-wide count, so a
       symbol-day observed by two providers double-counted its quotes
       across both cells.
    2. Otherwise, fall back to that symbol's UNRECORDED-provenance group
       (`data_source == ""`). This is not a convenience: every
       observation persisted before migration 0029 carries `""`, so a
       strict match alone would silently collapse the quote counts of
       the 64.62/64.70/64.72/64.74 evidence days - and of every archive
       day recomputed from them - to zero. Attributing an
       unknown-provenance group to a known-provenance cell is the
       honest reading of "we did not record where this came from", and
       it is exactly the behaviour that existed before this checkpoint.

    A cell with neither match gets `None` (0 observations), unchanged.
    """
    for summary in summaries:
        if summary.instrument_symbol == cell.instrument_symbol and (
            summary.data_source == cell.data_source
        ):
            return summary
    for summary in summaries:
        if summary.instrument_symbol == cell.instrument_symbol and summary.data_source == "":
            return summary
    return None


def assess_cell(
    *,
    identity: TradingSessionIdentity,
    session: TradingSession,
    as_of: datetime,
    cell_symbol: str,
    timeframe: Timeframe,
    data_source: str,
    closed_bar_close_timestamps: tuple[datetime, ...],
    forming_bar_count: int,
    quote_observation_count: int,
    first_observation_at: datetime | None,
    last_observation_at: datetime | None,
    ingestion_failed: bool,
) -> ArchiveDayAssessment:
    """Thin adapter onto the domain classifier - kept as a module-level
    function (not a method) so tests can exercise the exact same call
    the service makes without constructing a repository.

    Checkpoint 64.88: derives `cas_session` from `cell_symbol` via
    `instrument_category_for` + `build_cas_aware_session_for` and passes
    it through to `assess_archive_day`, so every symbol the archive
    already refreshes gets the correct CAS-aware continuous-trading
    window automatically - CATEGORY_I_CAS symbols (09:15-15:15) and
    CATEGORY_II_NON_CAS symbols (09:15-15:30, identical to the prior
    behavior) alike. No new call site or opt-in flag is needed."""
    category = instrument_category_for(cell_symbol)
    cas_session: CasAwareSession = build_cas_aware_session_for(
        category, identity.trading_date, as_of
    )
    return assess_archive_day(
        identity=identity,
        instrument_symbol=cell_symbol,
        timeframe=timeframe,
        data_source=data_source,
        session=session,
        closed_bar_timestamps=closed_bar_close_timestamps,
        forming_bar_count=forming_bar_count,
        quote_observation_count=quote_observation_count,
        first_observation_at=first_observation_at,
        last_observation_at=last_observation_at,
        as_of=as_of,
        ingestion_failed=ingestion_failed,
        cas_session=cas_session,
    )


__all__ = ["MarketDataArchiveService", "TradingDayArchiveSummary"]
