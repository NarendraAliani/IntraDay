# File: src/intraday/infrastructure/persistence/correlation_repository.py
#
# Checkpoint 64.82: the READ MODEL behind the correlation query surface.
#
# WHAT THIS IS: a read-only traversal of relationships Checkpoint 64.81
# already persisted. It creates NO table, NO migration, and NO second
# source of truth - every value returned here is read verbatim from a
# column another checkpoint already writes:
#
#   SignalRecord.scan_run_id                 (64.81) scanner run -> signal
#   SignalRecord.strategy_version_identifier (64.81) signal -> strategy version
#   PaperOrderRecord.signal_id               (36)    signal -> paper order
#   PaperTradeRecord.signal_id               (64.81) signal -> paper trade
#   SignalEvidenceRecord.fields[*][2]        (64.81) evidence -> feature name
#
# WHAT THIS IS NOT: an inference engine. No relationship is ever derived
# from a timestamp proximity, a price match, an instrument match, or a
# string similarity. A link either exists as a stored identifier or the
# view reports `None`/`()`. That rule is absolute - see
# `_trace_for_record()`'s own comments at each nullable boundary.
#
# N+1 PROTECTION (Checkpoint 64.82 Phase 8): every builder below is
# BULK by construction. `build_signal_traces()` issues a fixed FOUR
# queries for ANY number of signals (signals, evidence, orders, trades),
# never one query per signal. `test_correlation_query_count.py` asserts
# this with `assertNumQueries` against a growing signal set, so a future
# refactor that reintroduces per-signal querying fails the suite rather
# than silently degrading.
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from intraday.application.repositories.signal_evidence import SignalEvidenceFieldView
from intraday.infrastructure.persistence.market_data_archive_read_model import (
    ARCHIVE_NOT_AVAILABLE,
    ArchiveEvidenceKey,
    bulk_archive_evidence,
    evidence_key_for,
)
from intraday.infrastructure.persistence.models import (
    PaperOrderRecord,
    PaperTradeRecord,
    ScannerScanProgress,
    SignalEvidenceRecord,
    SignalRecord,
)
from intraday.infrastructure.persistence.signal_evidence_repository import (
    evidence_field_to_view,
)

# Checkpoint 64.82 Phase 12 recorded the ONE honest answer available at
# that time: `"ARCHIVE_API_NOT_IMPLEMENTED"` on every trace, because no
# archive API existed to consult.
#
# Checkpoint 64.83 Phase 7 makes it more precise, and ONLY because the
# archive domain truth now backs it. Each trace is now resolved against
# the EXISTING 64.73 `MarketDataArchiveDay` projection on its own
# (instrument, trading date) - see
# `market_data_archive_read_model.bulk_archive_evidence`, one bulk query
# for the whole response.
#
# THE CLAIM THIS STATUS MAKES, AND THE THREE IT DOES NOT:
#   IT SAYS: archived market-data evidence for the same instrument and
#     the same trading date as this decision does / does not exist, and
#     how complete and how validated that evidence is.
#   IT DOES NOT SAY the strategy read that data.
#   IT DOES NOT SAY that data produced this signal.
#   IT DOES NOT SAY that data caused the realised outcome.
# The platform stores no link between a signal and the specific bars a
# strategy consumed. This is TRACEABILITY plus CORRELATION - never
# causality - and no amount of archive completeness upgrades it.
MARKET_DATA_OUTCOME_UNAVAILABLE = ARCHIVE_NOT_AVAILABLE


@dataclass(frozen=True, slots=True)
class CorrelationOrderView:
    """One paper order reached by EXACT `PaperOrderRecord.signal_id`
    equality - never by instrument/timestamp proximity."""

    order_id: str
    instrument_id: str
    side: str
    order_type: str
    quantity: Decimal
    filled_quantity: Decimal
    status: str
    created_at: dt.datetime


@dataclass(frozen=True, slots=True)
class CorrelationTradeView:
    """One completed paper round trip reached by EXACT
    `PaperTradeRecord.signal_id` equality."""

    trade_id: str
    instrument_id: str
    direction: str
    order_ids: tuple[str, ...]
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    realized_pnl: Decimal
    costs: Decimal
    opened_at: dt.datetime
    closed_at: dt.datetime


@dataclass(frozen=True, slots=True)
class CorrelationTraceView:
    """The full recorded lineage of ONE signal.

    Every field is either a stored value or an honest absence. In
    particular:

    - `scan_run_id` is `None` when the signal was genuinely not produced
      by a tracked scanner run (replay sessions and direct service calls
      are real, supported workflows), and for every signal recorded
      before 64.81.
    - `strategy_version_identifier` is `None` for signals recorded
      before version tracking existed. It is NEVER back-filled from the
      strategy's CURRENT active version, which would attribute a past
      decision to code that did not make it.
    - `evidence` is `()` when no evidence row exists. An empty tuple
      means "the strategy cited nothing", which is materially different
      from a required feature list - see `CorrelationStrategyTraceView`.
    - `realized_pnl` is `None` when NO trade is linked, and is the sum
      over linked trades otherwise. `None` never means zero.
    """

    signal_id: str
    strategy_id: str
    strategy_version_identifier: str | None
    scan_run_id: str | None
    instrument_id: str
    direction: str
    price: Decimal
    timeframe: str
    signal_timestamp: dt.datetime
    risk_status: str
    order_status: str | None
    evidence: tuple[SignalEvidenceFieldView, ...]
    evidence_schema_version: str | None
    orders: tuple[CorrelationOrderView, ...]
    trades: tuple[CorrelationTradeView, ...]
    realized_pnl: Decimal | None
    market_data_outcome_status: str = MARKET_DATA_OUTCOME_UNAVAILABLE


@dataclass(frozen=True, slots=True)
class CorrelationScanRunTraceView:
    """A scanner run and the signals it is RECORDED as having produced.

    `scan_run_id` is preserved byte-for-byte as stored - it is the
    timestamp-shaped `ScannerScanProgress.scan_id` written by the worker
    (`clock.isoformat()`), deliberately NOT redesigned into a UUID here.

    `scan_started_at`/`timeframe`/`status` are populated ONLY when the
    scanner-progress singleton still holds THIS run's `scan_id`. That
    row is overwritten by each subsequent run, so for any older run the
    honest answer is `None` - the platform genuinely does not retain
    per-run scanner history, and this read model will not invent it.
    """

    scan_run_id: str
    signal_count: int
    signals: tuple[CorrelationTraceView, ...]
    strategy_ids: tuple[str, ...]
    scan_started_at: dt.datetime | None
    timeframe: str | None
    status: str | None
    run_metadata_available: bool


@dataclass(frozen=True, slots=True)
class CorrelationStrategyTraceView:
    """A strategy configuration, the features it REQUIRES, and the
    signals recorded against its exact version identity.

    THE DISTINCTION THIS TYPE EXISTS TO PRESERVE (Phase 6): a strategy
    may REQUIRE a feature without ever CITING it in a signal's evidence.
    `required_features` is a declaration about the configuration;
    evidence (on each trace) is what the strategy itself chose to
    record as its explanation. Neither is a causal claim, and this API
    never merges the two lists.
    """

    strategy_id: str
    specification_version: str
    code_version: str
    configuration_version: str
    strategy_version_identifier: str
    required_features: tuple[dict[str, object], ...] | None
    signal_count: int
    signals: tuple[CorrelationTraceView, ...]


def _order_view(row: PaperOrderRecord) -> CorrelationOrderView:
    return CorrelationOrderView(
        order_id=row.order_id,
        instrument_id=row.instrument_id,
        side=row.side,
        order_type=row.order_type,
        quantity=row.quantity,
        filled_quantity=row.filled_quantity,
        status=row.status,
        created_at=row.created_at,
    )


def _trade_view(row: PaperTradeRecord) -> CorrelationTradeView:
    return CorrelationTradeView(
        trade_id=row.trade_id,
        instrument_id=row.instrument_id,
        direction=row.direction,
        order_ids=tuple(str(o) for o in row.order_ids),
        entry_price=row.entry_price,
        exit_price=row.exit_price,
        quantity=row.quantity,
        realized_pnl=row.realized_pnl,
        costs=row.costs,
        opened_at=row.opened_at,
        closed_at=row.closed_at,
    )


def _archive_status_for(
    key: ArchiveEvidenceKey | None, statuses: dict[ArchiveEvidenceKey, str]
) -> str:
    """The resolved archive-evidence status, or the honest unavailable
    value when the signal's instrument id could not be split into an
    exchange and a symbol."""
    if key is None:
        return ARCHIVE_NOT_AVAILABLE
    return statuses.get(key, ARCHIVE_NOT_AVAILABLE)


def _trace_for_record(
    record: SignalRecord,
    evidence: SignalEvidenceRecord | None,
    orders: list[PaperOrderRecord],
    trades: list[PaperTradeRecord],
    *,
    market_data_outcome_status: str = ARCHIVE_NOT_AVAILABLE,
) -> CorrelationTraceView:
    # Blank-in-database means "no such relationship", which the wire
    # contract reports as `null`. This mapping is the ONLY place a blank
    # becomes a null, and a blank NEVER becomes a guess.
    return CorrelationTraceView(
        signal_id=record.signal_id,
        strategy_id=record.strategy_id,
        strategy_version_identifier=record.strategy_version_identifier or None,
        scan_run_id=record.scan_run_id or None,
        instrument_id=record.instrument_id,
        direction=record.direction,
        price=record.price,
        timeframe=record.timeframe,
        signal_timestamp=record.signal_timestamp,
        risk_status=record.risk_status,
        order_status=record.order_status or None,
        evidence=(
            tuple(evidence_field_to_view(entry) for entry in evidence.fields)
            if evidence is not None
            else ()
        ),
        evidence_schema_version=evidence.schema_version if evidence is not None else None,
        orders=tuple(_order_view(o) for o in orders),
        trades=tuple(_trade_view(t) for t in trades),
        # `None` (no linked trade) is deliberately distinct from
        # `Decimal("0")` (a linked trade that broke even).
        realized_pnl=(sum((t.realized_pnl for t in trades), Decimal("0")) if trades else None),
        market_data_outcome_status=market_data_outcome_status,
    )


class DjangoCorrelationRepository:
    """Read-only. This class has no write method, by design."""

    def build_signal_traces(self, records: list[SignalRecord]) -> tuple[CorrelationTraceView, ...]:
        """Assemble full traces for N signals in a FIXED number of
        queries (FOUR here as of 64.83 - evidence, orders, trades and
        archive evidence - plus whatever produced `records`).

        The related rows are fetched with four `__in` lookups and
        grouped in memory - never one query per signal. `signal_id` is
        indexed or unique on every table involved
        (`SignalRecord.signal_id` unique, `PaperTradeRecord.signal_id`
        db_index, `SignalEvidenceRecord.signal_id` db_index), so these
        stay index lookups as the tables grow.
        """
        if not records:
            return ()
        signal_ids = [r.signal_id for r in records]

        evidence_by_signal: dict[str, SignalEvidenceRecord] = {}
        for row in SignalEvidenceRecord.objects.filter(signal_id__in=signal_ids):
            # `update_or_create(signal_id=...)` keeps this one-per-signal;
            # first-wins here matches `get_by_signal_id()`'s own behaviour.
            evidence_by_signal.setdefault(row.signal_id, row)

        orders_by_signal: dict[str, list[PaperOrderRecord]] = defaultdict(list)
        for order in PaperOrderRecord.objects.filter(signal_id__in=signal_ids).order_by(
            "created_at", "order_id"
        ):
            orders_by_signal[order.signal_id].append(order)

        trades_by_signal: dict[str, list[PaperTradeRecord]] = defaultdict(list)
        for trade in PaperTradeRecord.objects.filter(signal_id__in=signal_ids).order_by(
            "closed_at", "trade_id"
        ):
            trades_by_signal[trade.signal_id].append(trade)

        # Checkpoint 64.83 Phase 7/10: archive evidence for EVERY signal
        # in ONE query, keyed on (exchange, IST trading date, symbol)
        # derived from each signal's own stored `instrument_id` and
        # `signal_timestamp`. A signal whose `instrument_id` carries no
        # parseable exchange prefix resolves to `None` and is reported
        # ARCHIVE_NOT_AVAILABLE - never looked up under an assumed
        # default exchange.
        keys_by_signal = {
            record.signal_id: evidence_key_for(record.instrument_id, record.signal_timestamp)
            for record in records
        }
        statuses = bulk_archive_evidence([k for k in keys_by_signal.values() if k is not None])

        return tuple(
            _trace_for_record(
                record,
                evidence_by_signal.get(record.signal_id),
                orders_by_signal.get(record.signal_id, []),
                trades_by_signal.get(record.signal_id, []),
                market_data_outcome_status=_archive_status_for(
                    keys_by_signal[record.signal_id], statuses
                ),
            )
            for record in records
        )

    def get_signal_trace(self, signal_id: str) -> CorrelationTraceView | None:
        record = SignalRecord.objects.filter(signal_id=signal_id).first()
        if record is None:
            return None
        return self.build_signal_traces([record])[0]

    def get_scan_run_trace(self, scan_run_id: str) -> CorrelationScanRunTraceView:
        """Signals belonging to EXACTLY this run.

        An unknown / never-used run id yields `signal_count=0` and an
        empty `signals` tuple rather than a 404: "this run produced no
        recorded signals" and "this run id was never seen" are not
        distinguishable from stored data, and the read model will not
        pretend otherwise. A blank id is rejected by the view.
        """
        records = list(
            SignalRecord.objects.filter(scan_run_id=scan_run_id).order_by("signal_timestamp")
        )
        traces = self.build_signal_traces(records)

        progress = ScannerScanProgress.objects.filter(scan_id=scan_run_id).first()
        return CorrelationScanRunTraceView(
            scan_run_id=scan_run_id,
            signal_count=len(traces),
            signals=traces,
            # Only strategies genuinely recorded on this run's own
            # signals - never the full registry, never the active set.
            strategy_ids=tuple(sorted({r.strategy_id for r in records})),
            scan_started_at=progress.scan_started_at if progress is not None else None,
            timeframe=(progress.timeframe or None) if progress is not None else None,
            status=(progress.status or None) if progress is not None else None,
            run_metadata_available=progress is not None,
        )

    def get_signals_for_version(self, strategy_version_identifier: str) -> list[SignalRecord]:
        """Signals recorded against an EXACT flattened version identity.

        Exact equality only. A signal whose `strategy_version_identifier`
        is blank (recorded before 64.81) is never matched to any version,
        because nothing stored on that row proves which version it was.
        """
        if not strategy_version_identifier:
            return []
        return list(
            SignalRecord.objects.filter(
                strategy_version_identifier=strategy_version_identifier
            ).order_by("signal_timestamp")
        )

    def get_trade_signal_id(self, trade_id: str) -> tuple[bool, str | None]:
        """`(trade_exists, signal_id_or_None)`.

        A manually-created trade legitimately carries a blank
        `signal_id`; that is reported as `None`, and the reverse trace
        stops there rather than searching for a plausible signal.
        """
        row = PaperTradeRecord.objects.filter(trade_id=trade_id).first()
        if row is None:
            return (False, None)
        return (True, row.signal_id or None)


__all__ = [
    "MARKET_DATA_OUTCOME_UNAVAILABLE",
    "CorrelationOrderView",
    "CorrelationScanRunTraceView",
    "CorrelationStrategyTraceView",
    "CorrelationTradeView",
    "CorrelationTraceView",
    "DjangoCorrelationRepository",
]
