# File: src/intraday/application/repositories/historical_bars.py
#
# Checkpoint 63.x: repository Protocols for the DB-first historical-bar
# archive. Split into a READ Protocol (`HistoricalBarReadRepository`,
# used by `HistoricalDataCoverageService`) and a WRITE Protocol
# (`HistoricalBarWriteRepository`, used only by
# `HistoricalDataPreparationService` after a provider fetch) — mirrors
# the existing `HistoricalMarketDataRepository`'s own explicit
# "read-only... ingestion is a separate concern" boundary
# (application/repositories/__init__.py) rather than widening that
# Protocol's contract. The concrete `DjangoHistoricalBarRepository`
# (infrastructure/persistence/repositories.py) satisfies BOTH of these
# Protocols AND the pre-existing `HistoricalMarketDataRepository`
# Protocol, so it can be handed directly to the unmodified
# `HistoricalMarketDataService`/`BacktestingService` for scanning once
# data is persisted — one concrete class, three narrow interfaces.
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.research_bar import ProvenancedBar
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe


class HistoricalBarReadRepository(Protocol):
    def get_existing_timestamps(
        self,
        instrument_id: InstrumentId,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> frozenset[datetime]:
        """Every bar-close timestamp already persisted for
        `instrument_id`/`timeframe` within `[start, end]` — used only for
        set-membership coverage checks, never as a bar's actual price
        data."""
        ...

    def get_bars_with_provenance(
        self,
        instrument_id: InstrumentId,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> tuple[ProvenancedBar, ...]:
        """Checkpoint 66.1: every bar for `instrument_id`/`timeframe`
        within `[start, end]`, paired with the `HistoricalBar.provenance`
        it was persisted with — the read primitive
        `application.services.research_data_gate.ResearchDataGateService`
        uses to enforce the Part 3 research-eligibility contract. Never
        used by `HistoricalDataCoverageService` (which only needs
        timestamps) or by the generic `HistoricalMarketDataRepository`
        read path (which returns bare `Bar`s to every non-research
        consumer) — scoped to the research/backtest boundary only."""
        ...


class HistoricalBarWriteRepository(Protocol):
    def bulk_upsert(
        self,
        bars: tuple[Bar, ...],
        *,
        source: str,
        provenance: str = "UNKNOWN",
        canonicalization_state: str = "UNKNOWN",
        source_timestamp_semantics: str = "UNKNOWN",
    ) -> int:
        """Persists `bars`, upserting by the
        `(instrument_id, timeframe, bar_timestamp)` identity (Phase 2's
        uniqueness rule) — re-persisting an already-cached bar is a safe
        no-op, never a duplicate row. Returns the number of bars actually
        written (inserted or updated).

        `provenance` (Checkpoint 65.12) is the explicit REAL_DHAN /
        SYNTHETIC_TEST / UNKNOWN classification
        (`domain.market_data.provenance`), orthogonal to `source`
        (which pipeline stage wrote the row). Defaults to `"UNKNOWN"` —
        a caller that does not know what kind of data it is fetching
        must never guess `"REAL_DHAN"`.

        `canonicalization_state` (Checkpoint 67.3, renamed values 67.4)
        is the explicit UNCANONICALIZED / CANONICALIZED / NOT_APPLICABLE
        / UNKNOWN PROCESSING-STATE marker
        (`domain.market_data.source_timestamp.CANONICALIZATION_STATE_*`)
        — orthogonal to `source` and `provenance`: it answers only
        whether THIS bar's timestamp has already been passed through
        `canonicalize_close_timestamp`. Defaults to `"UNKNOWN"` — a
        caller that does not know must never guess `"CANONICALIZED"`.

        `source_timestamp_semantics` (Checkpoint 67.4) is the explicit
        OPEN / CLOSE / UNKNOWN / NOT_APPLICABLE SEMANTICS marker
        (`domain.market_data.source_timestamp.SourceTimestampSemantics`)
        — a FOURTH, orthogonal fact: whether this bar's provider raw
        timestamp convention was ever empirically PROVEN, independent of
        whether `canonicalization_state` says the shift ran. Defaults to
        `"UNKNOWN"` — a caller that does not know must never guess
        `"OPEN"`/`"CLOSE"`."""
        ...
