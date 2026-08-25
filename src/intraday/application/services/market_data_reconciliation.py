# File: src/intraday/application/services/market_data_reconciliation.py
#
# Checkpoint 64.79: the application-layer orchestrator that reconciles
# archived equity bars against an INDEPENDENT reference series. Mirrors
# `market_data_archive.py` (64.73) exactly - it owns no rules of its
# own: session shape comes from `domain.session.calendar`, the verdict
# comes from `domain.market_data.reconciliation`. This service only
# gathers the two series and asks the domain to compare them.
#
# It writes NOTHING. 64.79 deliberately stops before persisting a
# reconciliation result: `MarketDataArchiveDay.reconciliation_status`
# already exists (64.73) and flipping it is a claim about stored data,
# which must not be made until a reconciliation has actually run
# against real overlapping reference data. Reporting the verdict is
# this checkpoint's scope; recording it is the next one's.
from __future__ import annotations

from datetime import date, datetime

from intraday.application.repositories.market_data_archive import MarketDataArchiveRepository
from intraday.application.repositories.market_data_reconciliation import ReferenceBarRepository
from intraday.domain.market_data.aggregation import BarStatus
from intraday.domain.market_data.archive import TradingSessionIdentity
from intraday.domain.market_data.reconciliation import (
    ObservedBar,
    ReconciliationOutcome,
    ReconciliationReport,
    ReconciliationTolerance,
    reconcile_bar_series,
)
from intraday.domain.session.calendar import build_session_for
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe, ensure_utc


class MarketDataReconciliationService:
    def __init__(
        self,
        archive_repository: MarketDataArchiveRepository,
        reference_repository: ReferenceBarRepository,
        *,
        exchange: Exchange = Exchange.NSE,
        tolerance: ReconciliationTolerance | None = None,
    ) -> None:
        self._archive = archive_repository
        self._reference = reference_repository
        self._exchange = exchange
        self._tolerance = tolerance or ReconciliationTolerance()

    def reconcile_cell(
        self,
        *,
        trading_date: date,
        instrument_symbol: str,
        timeframe: Timeframe,
        as_of: datetime,
    ) -> ReconciliationReport:
        """Reconciles ONE (day, symbol, timeframe) cell.

        Only CLOSED archived bars participate: a FORMING bar's close is
        provisional by definition (`AggregatedBar`'s own docstring), so
        comparing one against a finalised reference candle would
        manufacture a mismatch that says nothing about data quality."""
        ensure_utc(as_of, field_name="as_of")
        identity = TradingSessionIdentity(exchange=self._exchange, trading_date=trading_date)
        session = build_session_for(trading_date, as_of)

        archived = self._archive.list_bars(
            exchange=self._exchange,
            trading_date=trading_date,
            instrument_symbol=instrument_symbol,
            timeframe=timeframe,
        )
        observed = tuple(
            ObservedBar(
                timestamp=bar.interval_end,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
            )
            for bar in archived
            if bar.status is BarStatus.CLOSED
        )
        reference = self._reference.reference_bars_for(
            exchange=self._exchange,
            trading_date=trading_date,
            instrument_symbol=instrument_symbol,
            timeframe=timeframe,
        )
        return reconcile_bar_series(
            identity=identity,
            instrument_symbol=instrument_symbol,
            timeframe=timeframe,
            session=session,
            observed_bars=observed,
            reference_bars=reference,
            evidence_source=self._reference.describe_source(),
            tolerance=self._tolerance,
        )

    def reconcile_trading_date(
        self, *, trading_date: date, timeframe: Timeframe, as_of: datetime
    ) -> tuple[ReconciliationReport, ...]:
        """Reconciles every symbol the archive holds for `trading_date`.

        Symbols with no reference data are still reported - as
        NOT_RECONCILED. Silently omitting them would make a day of
        entirely un-reconcilable cells look like a day with nothing to
        reconcile, which is the exact confusion this checkpoint's
        findings turn on."""
        symbols = self._archive.archived_symbols_for_trading_date(
            exchange=self._exchange, trading_date=trading_date
        )
        return tuple(
            self.reconcile_cell(
                trading_date=trading_date,
                instrument_symbol=symbol,
                timeframe=timeframe,
                as_of=as_of,
            )
            for symbol in symbols
        )

    @staticmethod
    def summarise(reports: tuple[ReconciliationReport, ...]) -> ReconciliationOutcome:
        """The worst outcome across `reports`. An empty set of reports
        is NOT_RECONCILED, never PASS - "we reconciled nothing" must
        never read as "everything agreed"."""
        severity = (
            ReconciliationOutcome.FAIL,
            ReconciliationOutcome.NOT_RECONCILED,
            ReconciliationOutcome.PARTIAL,
            ReconciliationOutcome.PASS,
        )
        outcomes = {report.outcome for report in reports}
        for candidate in severity:
            if candidate in outcomes:
                return candidate
        return ReconciliationOutcome.NOT_RECONCILED


__all__ = ["MarketDataReconciliationService"]
