# File: src/intraday/application/repositories/market_data_reconciliation.py
#
# Checkpoint 64.79: the persistence-neutral Protocol for the INDEPENDENT
# reference side of an equity reconciliation. Follows the exact
# dependency-inversion shape `market_data_archive.py` (64.73)
# established: the interface lives here, the Django implementation
# depends inward on it.
#
# WHY A SEPARATE PROTOCOL rather than another method on
# `MarketDataArchiveRepository`: the whole validity of a reconciliation
# rests on the reference series coming from a DIFFERENT pipeline than
# the archive it checks. Hanging `reference_bars_for()` off the archive
# repository would let one concrete class serve both sides from the
# same table, which is precisely the fake reconciliation this
# checkpoint exists to prevent. Two Protocols make the independence a
# structural property, not a convention.
from __future__ import annotations

from datetime import date
from typing import Protocol

from intraday.domain.market_data.reconciliation import ReferenceBar
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe


class ReferenceBarRepository(Protocol):
    """Reads bars from a source INDEPENDENT of this platform's live
    ingestion path - in this codebase today, the `HistoricalBar` table
    populated by the Dhan historical-candle REST API
    (`dhan/historical_client.py` -> `dhan/historical_provider.py`),
    which is a different transport, a different Dhan subsystem and a
    different table from the live WebSocket -> `LiveQuoteObservation`
    -> `AggregatedBarObservation` pipeline the archive assesses."""

    def reference_bars_for(
        self,
        *,
        exchange: Exchange,
        trading_date: date,
        instrument_symbol: str,
        timeframe: Timeframe,
    ) -> tuple[ReferenceBar, ...]:
        """Every reference bar held for this cell, ordered by close
        timestamp. Returns an EMPTY tuple when no reference data exists
        - which the domain treats as NOT_RECONCILED, never as
        agreement."""
        ...

    def describe_source(self) -> str:
        """The `evidence_source` string every report produced from this
        repository is stamped with, e.g.
        `"dhan_historical_intraday_api"`. Required to be non-empty by
        `reconcile_bar_series` - an unattributed reference is not
        evidence."""
        ...


__all__ = ["ReferenceBarRepository"]
