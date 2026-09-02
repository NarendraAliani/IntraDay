# File: src/intraday/infrastructure/persistence/historical_bar_repository.py
#
# Checkpoint 63.x: Django ORM implementation of the DB-first historical
# bar archive. `DjangoHistoricalBarRepository` structurally satisfies
# THREE Protocols with one class:
#
#   - `application.repositories.historical_bars.HistoricalBarReadRepository`
#     (used by `HistoricalDataCoverageService`)
#   - `application.repositories.historical_bars.HistoricalBarWriteRepository`
#     (used by `HistoricalDataPreparationService`, the only writer)
#   - `application.repositories.HistoricalMarketDataRepository`
#     (the PRE-EXISTING, unmodified read-only Protocol
#     `HistoricalMarketDataService`/`BacktestingService` already depend
#     on) — this is the load-bearing detail that gives the scanner
#     live/backtest parity for free: once bars are persisted here,
#     `BacktestingService.run()` (Checkpoint 27, unchanged) can be
#     handed a `HistoricalMarketDataService(repository=
#     DjangoHistoricalBarRepository())` instead of the fixture
#     repository, and every downstream line of that service — strategy
#     lookup, feature computation, `run_backtest()` itself — is IDENTICAL
#     code to every other backtest in this project (Phase 10 requires
#     exactly this: "only the data source should differ").
#
# `bulk_upsert()` uses `bulk_create(..., update_conflicts=True)` keyed on
# the model's own `uq_historical_bar_identity` constraint — a single
# batched statement per fetch, not one `save()` per bar (Phase 28's
# explicit "avoid one ORM save per bar" instruction).
#
# Checkpoint 67.8 Part 1 — closes the concurrency gap 67.7 Part 2
# named (see `migration_advisory_lock.py`'s docstring): `bulk_upsert`
# now groups its incoming bars by `(instrument_id, timeframe)` — the
# same two dimensions the migration runner's lock key is derived from
# — and, for each group, acquires
# `acquire_historical_bar_migration_lock(instrument_id, timeframe)`
# (the EXACT canonical lock from `migration_advisory_lock.py`, same
# key derivation, no parallel scheme) around that group's
# `bulk_create(..., update_conflicts=True)` call. This is the smallest
# safe change that closes the bypass: it does not alter what gets
# written, does not change the upsert semantics or conflict-resolution
# fields, only wraps each group's write in the transaction-scoped
# advisory lock so a concurrent migration commit for the same
# instrument/timeframe cannot race this ingestion path's
# read-modify-write window. A `bulk_upsert()` call touching several
# instruments/timeframes now issues one `bulk_create` per group instead
# of one for the whole batch — in production every call already comes
# from a single-instrument/single-timeframe fetch
# (`HistoricalDataPreparationService.prepare()`), so this is a no-op
# for the common case and only adds grouping overhead in the
# multi-group case, never changes correctness.
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from intraday.application.services.migration_advisory_lock import (
    acquire_historical_bar_migration_lock,
    historical_migration_lock_key,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.research_bar import ProvenancedBar
from intraday.domain.shared_kernel.contracts import Exchange, InstrumentId, Timeframe
from intraday.infrastructure.persistence.models import HistoricalBar


def _split_instrument_id(instrument_id: InstrumentId) -> tuple[str, str]:
    """`InstrumentId` is always `"{exchange}:{symbol}"`
    (`domain.instrument.contracts.make_instrument_id`) — this is the
    one place that splits it back apart to populate the two separate
    `exchange`/`symbol` display columns `HistoricalBar` stores
    alongside the canonical `instrument_id` string, matching the
    pattern `AggregatedBarObservation` already established."""
    exchange, _, symbol = str(instrument_id).partition(":")
    return exchange, symbol


class DjangoHistoricalBarRepository:
    def get_existing_timestamps(
        self,
        instrument_id: InstrumentId,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> frozenset[datetime]:
        rows = HistoricalBar.objects.filter(
            instrument_id=str(instrument_id),
            timeframe=timeframe.value,
            bar_timestamp__gte=start,
            bar_timestamp__lte=end,
        ).values_list("bar_timestamp", flat=True)
        return frozenset(rows)

    def bulk_upsert(
        self,
        bars: tuple[Bar, ...],
        *,
        source: str,
        provenance: str = "UNKNOWN",
        canonicalization_state: str = "UNKNOWN",
        source_timestamp_semantics: str = "UNKNOWN",
    ) -> int:
        if not bars:
            return 0
        groups: dict[tuple[InstrumentId, Timeframe], list[HistoricalBar]] = defaultdict(list)
        for bar in bars:
            exchange, symbol = _split_instrument_id(bar.instrument_id)
            groups[(bar.instrument_id, bar.timeframe)].append(
                HistoricalBar(
                    instrument_id=str(bar.instrument_id),
                    exchange=exchange,
                    symbol=symbol,
                    timeframe=bar.timeframe.value,
                    bar_timestamp=bar.timestamp,
                    open_price=bar.open,
                    high_price=bar.high,
                    low_price=bar.low,
                    close_price=bar.close,
                    volume=bar.volume,
                    source=source,
                    provenance=provenance,
                    canonicalization_state=canonicalization_state,
                    source_timestamp_semantics=source_timestamp_semantics,
                )
            )
        # Checkpoint 67.9 Part 2 — DETERMINISTIC LOCK ORDERING.
        #
        # 67.8 iterated `groups.items()` in whatever order Python's dict
        # preserved (== the order bars first appeared in the input
        # tuple). If a single `bulk_upsert()` call ever spans MORE THAN
        # ONE (instrument_id, timeframe) group, and two concurrent
        # callers pass their groups in opposite orders (call A: X then
        # Y; call B: Y then X), each acquiring a `pg_advisory_xact_lock`
        # per group in turn, that is the textbook lock-ordering deadlock
        # shape — A holds X, waits for Y; B holds Y, waits for X.
        #
        # The fix: sort groups by their CANONICAL lock key
        # (`historical_migration_lock_key`, the exact same deterministic
        # int this module already derives its lock from) before
        # acquiring anything, and acquire strictly ascending. Two callers
        # given the SAME set of groups in ANY input order now attempt
        # acquisition in the SAME order, so the "A holds X waits for Y /
        # B holds Y waits for X" shape cannot occur — one of the two
        # callers always acquires its (lowest-key) first lock before the
        # other even attempts it. This does not rely on PostgreSQL's
        # deadlock detector as the primary defense; canonical ordering
        # prevents the cycle from forming at all. See
        # `test_checkpoint_67_9_multi_lock_ordering_and_deadlock.py` for
        # the two-process proof (opposite input order, no deadlock) and
        # confirmation of which mechanism (ordering vs. detector) is
        # actually doing the preventing.
        ordered_groups = sorted(
            groups.items(),
            key=lambda item: historical_migration_lock_key(item[0][0], item[0][1]),
        )
        total = 0
        for (instrument_id, timeframe), records in ordered_groups:
            with acquire_historical_bar_migration_lock(instrument_id, timeframe):
                HistoricalBar.objects.bulk_create(
                    records,
                    update_conflicts=True,
                    unique_fields=["instrument_id", "timeframe", "bar_timestamp"],
                    update_fields=[
                        "open_price",
                        "high_price",
                        "low_price",
                        "close_price",
                        "volume",
                        "source",
                        "provenance",
                        "canonicalization_state",
                        "source_timestamp_semantics",
                    ],
                )
            total += len(records)
        return total

    def get_bars(
        self,
        instrument_id: InstrumentId,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> tuple[Bar, ...]:
        """Satisfies `HistoricalMarketDataRepository` (the pre-existing,
        read-only Protocol) — the scanner-facing read path. Rows are
        ordered by `bar_timestamp` at the query level so the returned
        tuple is already chronological, matching what
        `domain.market_data.quality.ensure_chronological` (called by
        `HistoricalMarketDataService.get_bars`) expects."""
        rows = HistoricalBar.objects.filter(
            instrument_id=str(instrument_id),
            timeframe=timeframe.value,
            bar_timestamp__gte=start,
            bar_timestamp__lte=end,
        ).order_by("bar_timestamp")
        return tuple(
            Bar(
                instrument_id=make_instrument_id(Exchange(row.exchange), row.symbol),
                timeframe=timeframe,
                timestamp=row.bar_timestamp,
                open=row.open_price,
                high=row.high_price,
                low=row.low_price,
                close=row.close_price,
                volume=row.volume,
            )
            for row in rows
        )

    def get_bars_with_provenance(
        self,
        instrument_id: InstrumentId,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> tuple[ProvenancedBar, ...]:
        """Checkpoint 66.1: satisfies `HistoricalBarReadRepository.
        get_bars_with_provenance` — the research/backtest boundary's
        provenance-aware read primitive. Reads the SAME rows `get_bars()`
        does (identical filter/ordering), additionally carrying each
        row's persisted `provenance` value verbatim — never inferred,
        never defaulted, never mutated."""
        rows = HistoricalBar.objects.filter(
            instrument_id=str(instrument_id),
            timeframe=timeframe.value,
            bar_timestamp__gte=start,
            bar_timestamp__lte=end,
        ).order_by("bar_timestamp")
        return tuple(
            ProvenancedBar(
                bar=Bar(
                    instrument_id=make_instrument_id(Exchange(row.exchange), row.symbol),
                    timeframe=timeframe,
                    timestamp=row.bar_timestamp,
                    open=row.open_price,
                    high=row.high_price,
                    low=row.low_price,
                    close=row.close_price,
                    volume=row.volume,
                ),
                provenance=row.provenance,
                canonicalization_state=row.canonicalization_state,
                source_timestamp_semantics=row.source_timestamp_semantics,
            )
            for row in rows
        )


__all__ = ["DjangoHistoricalBarRepository"]
