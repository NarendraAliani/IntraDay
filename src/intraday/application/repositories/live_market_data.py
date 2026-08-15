# File: src/intraday/application/repositories/live_market_data.py
#
# Checkpoint 23: repository Protocols for live-observed market data and
# its health tracking. Mirrors `application/repositories/
# provider_settings.py`'s own file-split precedent (Checkpoint 22) -
# dedicated module, not crammed into `application/repositories/
# __init__.py`.
#
# `LiveQuoteRepository` deals only in the canonical domain `Quote`
# contract (Checkpoint 5) - never a Dhan-shaped type. The application
# layer, and this Protocol, have zero knowledge of Dhan's security_id/
# exchange-segment vocabulary; that translation happens entirely inside
# `infrastructure/api/market_data_views.py` (the one place allowed to
# import both `application/*` and `infrastructure/market_data_providers/
# dhan/*` - matching Checkpoint 22 decision 105's precedent for exactly
# this reason: `.importlinter` contract 6 forbids `application/*` from
# importing `intraday.infrastructure.*`).
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from intraday.domain.market_data.aggregation import AggregatedBar
from intraday.domain.market_data.contracts import Bar, Quote
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe


@dataclass(frozen=True, slots=True)
class MarketDataHealthRecord:
    """The persisted health facts - what `MarketDataHealthRepository.get()`
    returns. `control_plane.market_data_health.evaluator.evaluate_health()`
    turns this into a classified `MarketDataHealthSnapshot`; this record
    itself makes no classification judgement."""

    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_error_safe: str
    consecutive_failures: int


class LiveQuoteRepository(Protocol):
    """Persists and retrieves live-observed `Quote`s. Read-only from the
    perspective of `application/services/live_market_data.py`'s own
    business logic - it has no validation/business rule of its own
    beyond "store what was fetched, return the latest per instrument."""

    def save_all(self, quotes: tuple[Quote, ...], *, fetched_at: datetime) -> None: ...

    def get_latest(self) -> tuple[Quote, ...]:
        """The most recently observed `Quote` for each instrument in the
        configured observation universe that has ever been successfully
        fetched - empty tuple if none has."""
        ...

    def get_observations(self, *, since: datetime) -> tuple[Quote, ...]:
        """Checkpoint 24A: EVERY observed `Quote` (not just the latest
        per instrument) with `source_timestamp >= since`, across all
        instruments, in no particular guaranteed order - the caller
        (`domain.market_data.aggregation`) is responsible for sorting.
        This is the read path bar aggregation is built on; it exists
        alongside `get_latest()` rather than replacing it, since the
        Live Market Data Monitor's "current quotes" view only ever
        needs the latest value, not the full history."""
        ...


class AggregatedBarRepository(Protocol):
    """Checkpoint 24A: persists and retrieves aggregated bars
    (`domain.market_data.aggregation.AggregatedBar`). Unlike
    `LiveQuoteRepository` (append-only observations), this repository's
    `save_all()` is an UPSERT by (instrument, timeframe, interval_start)
    - bars are a derived, recomputable projection of the observation
    log, not an independent observation themselves, so revising a
    previously-stored bar when new/late data changes its OHLC (or when
    a FORMING bar becomes CLOSED) is the correct, intended behavior -
    see `domain/market_data/aggregation.py`'s own module docstring."""

    def save_all(self, bars: tuple[AggregatedBar, ...]) -> None: ...

    def get_recent(self, *, timeframe: Timeframe, limit: int = 200) -> tuple[AggregatedBar, ...]:
        """The most recent `limit` bars across all instruments, newest
        first - read-only, never triggers aggregation itself."""
        ...


class BarSource(Protocol):
    """Checkpoint 52: the canonical, technology-neutral interface
    between "something that supplies bars over time" and
    `active_loop_runtime.run_active_loop_tick_from_source()`. THE point
    of this Protocol: a real future Dhan-tick-driven bar source and the
    `DeterministicReplayBarSource` (`infrastructure/market_data_providers/
    replay/`) this checkpoint actually implements are INTERCHANGEABLE
    behind this one interface - the active loop caller never knows or
    cares which one it was given. No implementation exists yet for a
    real Dhan-tick-driven source (that remains a separate, undone,
    NAMED dependency - see `ACTIVE_PRODUCT_GAP_REGISTER.md`); this
    checkpoint proves the SHAPE of the boundary and provides the one
    concrete, honestly-labelled deterministic implementation."""

    def get_bars(
        self, *, instrument_id: InstrumentId, timeframe: Timeframe, as_of: datetime
    ) -> tuple[Bar, ...]:
        """Every bar this source can supply with `timestamp <= as_of`,
        for `instrument_id`/`timeframe` - safe to call repeatedly with
        an advancing `as_of` (a live source's natural calling pattern);
        the caller's OWN idempotency (already-processed signal IDs,
        already-submitted order idempotency keys - both already
        established, Checkpoint 36/39) is what prevents re-supplying
        the same historical bars from ever re-acting on them twice.
        This Protocol makes no promise about ordering; callers sort if
        they need to (mirrors `LiveQuoteRepository.get_observations()`'s
        own precedent)."""
        ...


class MarketDataHealthRepository(Protocol):
    """Reusable, single-row (singleton-by-convention, matching Checkpoint
    22's `ProviderConnectionStatus` precedent) health tracking - one
    process-wide record, since this checkpoint has exactly one market-
    data source (Dhan) and one observation universe, not per-instrument
    health."""

    def get(self) -> MarketDataHealthRecord: ...

    def record_success(self, *, checked_at: datetime) -> None: ...

    def record_failure(self, *, checked_at: datetime, error_safe: str) -> None: ...
