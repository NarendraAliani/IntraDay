# File: src/intraday/infrastructure/persistence/market_data_archive_read_model.py
#
# Checkpoint 64.83: the READ MODEL behind the archive / reconciliation
# HTTP surface, and the bulk archive lookup the correlation trace uses.
#
# WHAT THIS IS NOT: it is not a second archive, not a second
# reconciliation engine, and not a source of truth. Every value it
# returns is read from the EXISTING 64.73 archive projection
# (`MarketDataArchiveDay`, via `DjangoMarketDataArchiveRepository`) or
# computed by the EXISTING 64.79 domain comparator
# (`reconcile_bar_series`, via `MarketDataReconciliationService`). This
# module owns no completeness rule, no gap arithmetic and no verdict
# logic of its own - exactly the "read model, not new source of truth"
# discipline 64.82 established for the correlation surface.
#
# THE ONE GENUINELY NEW THING here is the ARCHIVE-EVIDENCE STATUS for a
# signal/trade (`archive_evidence_status`): a single vocabulary for
# answering "does archived market-data evidence exist for the instrument
# and trading date this decision was recorded on?" - a TRACEABILITY
# question, deliberately not a causal one. See the module-level note on
# `ArchiveEvidenceStatus` below.
from __future__ import annotations

import datetime as _dt
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime

from intraday.application.repositories.market_data_archive import ArchiveDayRecord
from intraday.domain.market_data.archive import (
    ArchiveStatus,
    ReconciliationStatus,
    trading_date_for,
)
from intraday.domain.market_data.quality import CasWindowStatus
from intraday.domain.market_data.reconciliation import ReconciliationOutcome
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.persistence.models import MarketDataArchiveDay

# ---------------------------------------------------------------------
# Archive-evidence vocabulary for a traced decision (Phase 6/7)
# ---------------------------------------------------------------------
#
# These are the states the directive names, minus the ones the platform
# cannot honestly reach today. Each maps DETERMINISTICALLY from values
# already stored on `MarketDataArchiveDay` - none is inferred, guessed,
# or softened.
#
# CRITICAL SEMANTIC BOUNDARY, stated once and enforced everywhere below:
# a status other than ARCHIVE_NOT_AVAILABLE means archived market-data
# evidence EXISTS for the same (instrument, trading date) as the traced
# decision. It does NOT mean that data was the input to the decision,
# and it does NOT mean the data caused the outcome. The platform stores
# no link between a signal and the specific bars a strategy read; this
# module will not manufacture one.

ARCHIVE_NOT_AVAILABLE = "ARCHIVE_NOT_AVAILABLE"
"""No archive cell exists for this instrument on this trading date -
either nothing was ever observed, or the decision predates the archive."""

ARCHIVE_PARTIAL = "ARCHIVE_PARTIAL"
"""An archive cell exists but the day is not a whole session
(`PARTIAL`, `IN_PROGRESS`, `NOT_OBSERVED` or `FAILED`). The honest
status for every day this platform currently holds."""

ARCHIVE_COMPLETE_NOT_RECONCILED = "ARCHIVE_COMPLETE_NOT_RECONCILED"
"""Every expected bar is present, but the day has never been checked
against an independent reference. Complete is not validated."""

ARCHIVE_RECONCILED = "ARCHIVE_RECONCILED"
"""Complete AND cross-checked against an independent reference. No day
in this database has ever reached this state."""

ARCHIVE_RECONCILIATION_FAILED = "ARCHIVE_RECONCILIATION_FAILED"
"""A reconciliation ran and the archived day DISAGREED with the
reference (`MISMATCH`)."""

ARCHIVE_EVIDENCE_STATUSES = (
    ARCHIVE_NOT_AVAILABLE,
    ARCHIVE_PARTIAL,
    ARCHIVE_COMPLETE_NOT_RECONCILED,
    ARCHIVE_RECONCILED,
    ARCHIVE_RECONCILIATION_FAILED,
)


def classify_archive_evidence(records: tuple[ArchiveDayRecord, ...]) -> str:
    """Reduces every archive cell for one (instrument, trading date) to
    one evidence status.

    Worst-wins, deliberately: a symbol-day archived at two timeframes
    where one is COMPLETE and one is PARTIAL is PARTIAL. Reporting the
    best cell would let a single healthy timeframe hide a broken one -
    the same rollup rule `MarketDataArchiveService._rollup_status`
    already applies to a whole day.
    """
    if not records:
        return ARCHIVE_NOT_AVAILABLE
    if any(r.reconciliation_status is ReconciliationStatus.MISMATCH for r in records):
        return ARCHIVE_RECONCILIATION_FAILED
    if any(r.status is not ArchiveStatus.COMPLETE for r in records):
        return ARCHIVE_PARTIAL
    if all(r.reconciliation_status is ReconciliationStatus.RECONCILED for r in records):
        return ARCHIVE_RECONCILED
    return ARCHIVE_COMPLETE_NOT_RECONCILED


# ---------------------------------------------------------------------
# Instrument identity
# ---------------------------------------------------------------------
#
# Signals carry `instrument_id` shaped `"NSE:RELIANCE"`; the archive is
# keyed on `exchange="NSE"` + `instrument_symbol="RELIANCE"`. This split
# is the ONLY translation performed between the two, and it is exact
# string surgery on a stored value - never a fuzzy or best-effort match.


def split_instrument_id(instrument_id: str) -> tuple[Exchange, str] | None:
    """`"NSE:RELIANCE"` -> `(Exchange.NSE, "RELIANCE")`.

    Returns `None` - never a guess - when the id carries no exchange
    prefix or an exchange this platform does not model. An unparseable
    id must surface as "no archive evidence", not as a lookup against an
    assumed default exchange.
    """
    exchange_text, separator, symbol = instrument_id.partition(":")
    if not separator or not symbol:
        return None
    try:
        exchange = Exchange(exchange_text)
    except ValueError:
        return None
    return exchange, symbol


@dataclass(frozen=True, slots=True)
class ArchiveEvidenceKey:
    exchange: Exchange
    trading_date: date
    instrument_symbol: str


def evidence_key_for(instrument_id: str, signal_timestamp: datetime) -> ArchiveEvidenceKey | None:
    """The archive cell a decision recorded at `signal_timestamp` on
    `instrument_id` would be filed under.

    The trading date comes from `archive.trading_date_for` - THE
    canonical IST rule - so a signal fired at 09:20 IST (03:50 UTC) is
    looked up under its own IST date, not the previous UTC one.
    """
    split = split_instrument_id(instrument_id)
    if split is None:
        return None
    exchange, symbol = split
    return ArchiveEvidenceKey(
        exchange=exchange,
        trading_date=trading_date_for(signal_timestamp),
        instrument_symbol=symbol,
    )


def bulk_archive_evidence(keys: list[ArchiveEvidenceKey]) -> dict[ArchiveEvidenceKey, str]:
    """Archive-evidence status for MANY (exchange, date, symbol) keys in
    exactly ONE database query.

    This is the Phase 10 requirement in one function: a trace request
    covering N signals across N instruments performs one archive query,
    not N. The filter is a bounded `__in` over the indexed
    `trading_date` and `instrument_symbol` columns (migration 0028),
    over-fetching the cross product of dates and symbols and discarding
    non-matching pairs in memory - which is correct and cheap, because
    both lists are bounded by the number of signals in one response.
    """
    if not keys:
        return {}
    rows = MarketDataArchiveDay.objects.filter(
        trading_date__in={k.trading_date for k in keys},
        instrument_symbol__in={k.instrument_symbol for k in keys},
        exchange__in={k.exchange.value for k in keys},
    )
    grouped: dict[ArchiveEvidenceKey, list[ArchiveDayRecord]] = defaultdict(list)
    for row in rows:
        try:
            key = ArchiveEvidenceKey(
                exchange=Exchange(row.exchange),
                trading_date=row.trading_date,
                instrument_symbol=row.instrument_symbol,
            )
        except ValueError:  # pragma: no cover - defensive
            continue
        grouped[key].append(archive_row_to_record(row))
    return {key: classify_archive_evidence(tuple(grouped.get(key, ()))) for key in keys}


def archive_row_to_record(row: MarketDataArchiveDay) -> ArchiveDayRecord:
    """Row -> the EXISTING 64.73 `ArchiveDayRecord` contract.

    Duplicated from `market_data_archive_repository._row_to_archive_day`
    only because that helper is private to its module; the mapping is
    identical field for field, and no new field is introduced here.
    """
    return ArchiveDayRecord(
        exchange=Exchange(row.exchange),
        trading_date=row.trading_date,
        instrument_symbol=row.instrument_symbol,
        timeframe=Timeframe(row.timeframe),
        data_source=row.data_source,
        status=ArchiveStatus(row.status),
        reason=row.reason,
        completeness_supported=row.completeness_supported,
        expected_bar_count=row.expected_bar_count,
        closed_bar_count=row.closed_bar_count,
        forming_bar_count=row.forming_bar_count,
        missing_bar_count=row.missing_bar_count,
        duplicate_bar_count=row.duplicate_bar_count,
        quote_observation_count=row.quote_observation_count,
        first_observation_at=_as_utc(row.first_observation_at),
        last_observation_at=_as_utc(row.last_observation_at),
        reconciliation_status=ReconciliationStatus(row.reconciliation_status),
        reconciled_at=_as_utc(row.reconciled_at),
        computed_at=_as_utc(row.computed_at),
        reconciliation_outcome=ReconciliationOutcome(row.reconciliation_outcome),
        reconciliation_reason=row.reconciliation_reason,
        reconciliation_evidence_source=row.reconciliation_evidence_source,
        # Checkpoint 64.88: additive field, kept in sync with
        # `market_data_archive_repository._row_to_archive_day`'s own
        # mapping of the same column.
        cas_window_status=CasWindowStatus(row.cas_window_status),
    )


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=_dt.UTC)
    return value.astimezone(_dt.UTC)


__all__ = [
    "ARCHIVE_COMPLETE_NOT_RECONCILED",
    "ARCHIVE_EVIDENCE_STATUSES",
    "ARCHIVE_NOT_AVAILABLE",
    "ARCHIVE_PARTIAL",
    "ARCHIVE_RECONCILED",
    "ARCHIVE_RECONCILIATION_FAILED",
    "ArchiveEvidenceKey",
    "archive_row_to_record",
    "bulk_archive_evidence",
    "classify_archive_evidence",
    "evidence_key_for",
    "split_instrument_id",
]
