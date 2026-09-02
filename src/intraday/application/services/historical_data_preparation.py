# File: src/intraday/application/services/historical_data_preparation.py
#
# Checkpoint 63.x Phase 5/6/7: the ONLY place in this codebase where a
# historical-data API is ever consulted for a backtest/scan request, and
# the ONLY place that ever writes to `HistoricalBar`. Implements exactly
# the required sequence:
#
#     DB coverage check -> missing range -> historical API -> validate
#     -> normalize -> upsert -> verify persistence
#
# `HistoricalDataCoverageService` (this checkpoint's other new service)
# decides WHAT is missing; this service decides what to DO about it. The
# scanner/backtester never calls this service or the provider directly —
# only `HistoricalBacktestRunOrchestrator` does, strictly BEFORE handing
# control to `BacktestingService.run()` against the now-DB-backed
# repository (Phase 5: "The API adapter must not return data directly to
# the strategy engine").
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from intraday.application.repositories.historical_bars import HistoricalBarWriteRepository
from intraday.application.services.historical_data_coverage import (
    HistoricalDataCoverageService,
)
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.provenance import PROVENANCE_UNKNOWN
from intraday.domain.market_data.source_timestamp import (
    CANONICALIZATION_STATE_UNKNOWN,
    SourceTimestampSemantics,
)
from intraday.domain.market_data.quality import (
    DuplicateBarTimestampError,
    OutOfOrderBarError,
    ensure_chronological,
)
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe

MAX_FETCH_ATTEMPTS = 3
PROVENANCE_API_FETCH = "API_FETCH"
"""`HistoricalBar.source` value — WHICH PIPELINE STAGE wrote the row.
Not to be confused with `HistoricalBar.provenance`
(`domain.market_data.provenance`), which is WHAT KIND of data it is.
This constant's meaning is unchanged from 63.x; see that field's own
docstring in `infrastructure.persistence.models` for the distinction
65.12 introduced."""


class HistoricalBarProvider(Protocol):
    """The historical-data-API boundary Protocol. Any adapter satisfying
    this (the synthetic stand-in today, a future real Dhan adapter
    tomorrow) is interchangeable here without this service or anything
    above it changing — see `synthetic_historical.py`'s own disclosure
    for what "the historical API" concretely means in this codebase
    right now.

    `provenance` (Checkpoint 65.12): each concrete provider MUST
    declare what kind of data it produces
    (`domain.market_data.provenance.PROVENANCE_REAL_DHAN` /
    `PROVENANCE_SYNTHETIC_TEST`) so this service can stamp
    `HistoricalBar.provenance` correctly per-provider instead of
    (65.01's root-cause bug #1) writing the same label regardless of
    which provider actually ran. A provider that does not declare one
    is treated as `PROVENANCE_UNKNOWN` — never silently upgraded."""

    provenance: str

    def fetch(
        self,
        instrument_id: InstrumentId,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> tuple[Bar, ...]: ...


class PreparationStatus(enum.Enum):
    """Phase 6's required disclosure vocabulary — never silently
    collapsed to a bare success/failure boolean."""

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    NOT_AVAILABLE = "NOT_AVAILABLE"


@dataclass(frozen=True, slots=True)
class PreparationOutcome:
    instrument_id: InstrumentId
    timeframe: Timeframe
    status: PreparationStatus
    cache_hits: int
    """Bars that were ALREADY in the DB before this call — never
    refetched (Phase 22's acceptance requirement)."""
    bars_fetched: int
    """Bars actually retrieved from the provider this call."""
    bars_persisted: int
    api_requests: int
    attempts: int
    error_message: str = ""


@dataclass
class HistoricalDataPreparationService:
    coverage: HistoricalDataCoverageService
    provider: HistoricalBarProvider
    writer: HistoricalBarWriteRepository

    def prepare(
        self,
        instrument_id: InstrumentId,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> PreparationOutcome:
        report = self.coverage.get_coverage(instrument_id, timeframe, start, end)
        cache_hits = report.cached_bar_count

        if report.is_complete:
            # Already fully cached - THE mandatory Phase 22 optimization:
            # zero provider calls for an already-satisfied range.
            return PreparationOutcome(
                instrument_id=instrument_id,
                timeframe=timeframe,
                status=PreparationStatus.COMPLETE,
                cache_hits=cache_hits,
                bars_fetched=0,
                bars_persisted=0,
                api_requests=0,
                attempts=0,
            )

        bars_fetched = 0
        bars_persisted = 0
        api_requests = 0
        attempts = 0
        last_error = ""

        for missing_range in report.missing_ranges:
            fetched: tuple[Bar, ...] | None = None
            for attempt in range(1, MAX_FETCH_ATTEMPTS + 1):
                attempts += 1
                api_requests += 1
                try:
                    fetched = self.provider.fetch(
                        instrument_id, timeframe, missing_range.start, missing_range.end
                    )
                    break
                except Exception as exc:  # noqa: BLE001 - provider failures are all "unavailable" to us
                    last_error = str(exc)
                    if attempt == MAX_FETCH_ATTEMPTS:
                        fetched = None

            if fetched is None:
                # This missing range could not be fetched after bounded
                # retries - stop trying further ranges for this
                # instrument and report the failure honestly (Phase 6:
                # "do NOT silently continue and produce a supposedly
                # complete result").
                final_report = self.coverage.get_coverage(instrument_id, timeframe, start, end)
                status = (
                    PreparationStatus.PARTIAL
                    if final_report.cached_bar_count > 0
                    else PreparationStatus.NOT_AVAILABLE
                )
                return PreparationOutcome(
                    instrument_id=instrument_id,
                    timeframe=timeframe,
                    status=status,
                    cache_hits=cache_hits,
                    bars_fetched=bars_fetched,
                    bars_persisted=bars_persisted,
                    api_requests=api_requests,
                    attempts=attempts,
                    error_message=last_error,
                )

            try:
                validated = ensure_chronological(fetched)
            except (DuplicateBarTimestampError, OutOfOrderBarError) as exc:
                return PreparationOutcome(
                    instrument_id=instrument_id,
                    timeframe=timeframe,
                    status=PreparationStatus.PARTIAL
                    if bars_persisted > 0
                    else PreparationStatus.FAILED,
                    cache_hits=cache_hits,
                    bars_fetched=bars_fetched,
                    bars_persisted=bars_persisted,
                    api_requests=api_requests,
                    attempts=attempts,
                    error_message=f"provider returned invalid bar data: {exc}",
                )

            bars_fetched += len(validated)
            provider_provenance = getattr(self.provider, "provenance", PROVENANCE_UNKNOWN)
            # Checkpoint 67.3 Part 3, corrected 67.4 Part 4: the provider
            # itself is the ONLY party that knows whether the bars it
            # just returned were canonicalized (`canonicalize_close_
            # timestamp`) AND whether that shift was empirically PROVEN
            # for this specific timeframe — this service never guesses
            # either. Two SEPARATE optional provider methods are
            # consulted (67.4 split what used to be one conflated
            # question into two):
            #   `canonicalization_state_for(timeframe)` — PROCESSING
            #   STATE only: did the +interval shift actually run?
            #   `source_timestamp_semantics_for(timeframe)` — SEMANTICS
            #   only: was that shift's OPEN/CLOSE convention ever
            #   empirically proven (67.0-class proof) for this
            #   timeframe? `DhanHistoricalBarProvider` now answers this
            #   honestly per-timeframe — CANONICALIZED/OPEN only for the
            #   67.0-proven 5m scope, UNKNOWN/UNKNOWN for 1m/15m/1h
            #   (the shift still runs, but is not claimed proven), so
            #   "code applied +interval" is never conflated with "data
            #   is semantically proven canonical" (the exact 67.3 defect
            #   this checkpoint fixes). A provider that exposes neither
            #   method (e.g. the synthetic fixture provider — its rows
            #   are `SYNTHETIC_TEST` provenance and therefore never
            #   research-eligible regardless) defaults both to
            #   `UNKNOWN`, never `CANONICALIZED`/`OPEN`.
            # Checkpoint 67.5 Parts 1-3: both provider hooks are now
            # ERA-AWARE — they need to know WHICH request window this
            # batch of bars came from (`missing_range.start`/`.end`),
            # not just `timeframe`, so a PRE-CAS 5m request can no longer
            # inherit the CAS-era-only 67.0 proof merely because it is
            # 5-minute. `missing_range` is exactly the per-gap window
            # this loop already fetched from `self.provider.fetch()`
            # above — the same date scope the provider used to decide
            # what to return is the same date scope it must use to
            # decide how to classify what it returned.
            # Checkpoint 67.6 Parts 1-2: both hooks now take `instrument_id`
            # too, not just `timeframe`/window — the proof-scope lookup
            # inside the provider needs the instrument's exchange segment
            # (NSE_EQ vs BSE_EQ) to avoid extending 67.0's NSE-only
            # empirical proof to BSE. `instrument_id` is already in scope
            # here (this whole loop is per-instrument).
            state_for = getattr(self.provider, "canonicalization_state_for", None)
            provider_canonicalization_state = (
                state_for(instrument_id, timeframe, missing_range.start, missing_range.end)
                if state_for is not None
                else CANONICALIZATION_STATE_UNKNOWN
            )
            semantics_for = getattr(self.provider, "source_timestamp_semantics_for", None)
            provider_source_timestamp_semantics = (
                semantics_for(instrument_id, timeframe, missing_range.start, missing_range.end)
                if semantics_for is not None
                else SourceTimestampSemantics.UNKNOWN.value
            )
            bars_persisted += self.writer.bulk_upsert(
                validated,
                source=PROVENANCE_API_FETCH,
                provenance=provider_provenance,
                canonicalization_state=provider_canonicalization_state,
                source_timestamp_semantics=provider_source_timestamp_semantics,
            )

        # STORE -> VERIFY PERSISTENCE (Phase 5's final step): re-check
        # coverage against the DB itself, never assume the write
        # succeeded just because bulk_upsert() didn't raise.
        final_report = self.coverage.get_coverage(instrument_id, timeframe, start, end)
        status = (
            PreparationStatus.COMPLETE if final_report.is_complete else PreparationStatus.PARTIAL
        )
        return PreparationOutcome(
            instrument_id=instrument_id,
            timeframe=timeframe,
            status=status,
            cache_hits=cache_hits,
            bars_fetched=bars_fetched,
            bars_persisted=bars_persisted,
            api_requests=api_requests,
            attempts=attempts,
        )


__all__ = [
    "HistoricalBarProvider",
    "PreparationStatus",
    "PreparationOutcome",
    "HistoricalDataPreparationService",
    "MAX_FETCH_ATTEMPTS",
]
