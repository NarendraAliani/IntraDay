# File: src/intraday/application/services/research_data_gate.py
#
# Checkpoint 66.1: the backtest/research-data ELIGIBILITY GATE — the
# single read boundary between raw `HistoricalBar` rows and
# `BacktestingService`. Composes THREE already-existing, UNCHANGED
# sources of truth rather than re-implementing any of them:
#
#   - `HistoricalDataCoverageService` (65.27, unchanged) for the
#     completeness gate (Part 4).
#   - `domain.market_data.provenance.is_research_eligible` (65.12,
#     unchanged) for the provenance gate (Part 3).
#   - `domain.session.resolver.resolve_market_session_for_instant`
#     (65.33, unchanged) for PRE_CAS/CAS_ERA/`HistoricalEligibility`
#     context (Part 5).
#
# RAW HISTORICAL DATA vs. TRUSTED RESEARCH DATA (Part 7): every row in
# `HistoricalBar` is RAW historical data — it may be `REAL_DHAN`,
# `SYNTHETIC_TEST`, or `UNKNOWN` provenance, and the requested range
# around it may be incomplete. TRUSTED RESEARCH DATA is the narrower
# subset THIS gate produces: a range that is 100% covered per
# `HistoricalDataCoverageService.is_complete` AND 100% `REAL_DHAN`
# provenance. `BacktestingService`, once handed a `ResearchDataGateService`
# (see `application.services.backtesting`), reads ONLY the latter —
# never raw `HistoricalBar` rows directly.
#
# HARD RULES this module enforces structurally, not just by convention:
#   - Never mutates a `HistoricalBar` row (this module performs reads
#     only — no repository write method is imported or called).
#   - Never relabels `UNKNOWN` (provenance is read and compared, never
#     assigned).
#   - Never fills a gap / interpolates / fabricates a bar — an
#     incomplete range is REJECTED (`ResearchRejectionReason.
#     INCOMPLETE_COVERAGE`), never silently completed.
#   - Never persists `PRE_CAS`/`CAS_ERA` — `sessions_by_date` is
#     computed in memory, once per call, from the unchanged resolver;
#     nothing here writes to `HistoricalBar` or any other table.
#   - A rejection always raises `ResearchDataRejectedError` with a
#     typed `.reason` and human-readable `.detail` — never a silent
#     downgrade, never an empty-tuple-instead-of-an-error.
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import date, datetime

from intraday.application.repositories.historical_bars import HistoricalBarReadRepository
from intraday.application.services.historical_data_coverage import (
    CoverageReport,
    HistoricalDataCoverageService,
)
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.provenance import is_research_eligible
from intraday.domain.market_data.quality import ensure_chronological
from intraday.domain.session.calendar import INDIA_STANDARD_TIME
from intraday.domain.session.resolver import ResolvedSession, resolve_market_session_for_instant
from intraday.domain.shared_kernel.contracts import Exchange, InstrumentId, Timeframe


class ResearchRejectionReason(enum.Enum):
    """Part 3/4's explicit, typed rejection taxonomy — a caller (or a
    test) can branch on `.reason` without parsing an error string."""

    NO_DATA = "NO_DATA"
    INCOMPLETE_COVERAGE = "INCOMPLETE_COVERAGE"
    INELIGIBLE_PROVENANCE = "INELIGIBLE_PROVENANCE"


class ResearchDataRejectedError(Exception):
    """Raised by `ResearchDataGateService.get_research_eligible_bars()`
    whenever the requested range fails the completeness gate (Part 4)
    or the provenance eligibility gate (Part 3). `.reason` is always a
    `ResearchRejectionReason` member; `.detail` carries the
    human-readable specifics (which sub-ranges are missing, which
    provenance values were rejected and how many rows) — Part 3's
    explicit requirement that "the rejection reason must be observable
    to the caller." Never silently swallowed or downgraded to a
    warning."""

    def __init__(self, reason: ResearchRejectionReason, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason.value}: {detail}")


@dataclass(frozen=True, slots=True)
class ResearchEligibleBars:
    """The gate's output — TRUSTED RESEARCH DATA (Part 7). `bars` are
    ordinary, unmodified `Bar` values (Part 2 Option B: no provenance
    field grafted onto `Bar` itself) that have ALREADY passed both the
    provenance gate and the completeness gate by the time a caller
    holds this object — a caller never needs to re-check either.

    `sessions_by_date` is resolved ONCE PER DISTINCT TRADING DATE
    present in `bars` (Part 6), never once per bar — the resolver's
    result for a given `(trading_date, symbol)` pair is invariant
    across every bar within that same trading day, so re-resolving per
    bar would be repeated, correctness-neutral work for no benefit.
    `PRE_CAS`/`CAS_ERA`/`HistoricalEligibility` are never persisted
    anywhere (Part 5) — this dict lives only in memory for the
    duration of one gate call."""

    instrument_id: InstrumentId
    timeframe: Timeframe
    bars: tuple[Bar, ...]
    coverage: CoverageReport
    sessions_by_date: dict[date, ResolvedSession]


@dataclass(frozen=True, slots=True)
class ResearchDataGateService:
    """Application-layer research-eligibility gate. Depends only on
    `HistoricalBarReadRepository` (Protocol) and
    `HistoricalDataCoverageService` — never a concrete Django model —
    matching every other application service in this codebase."""

    repository: HistoricalBarReadRepository
    coverage_service: HistoricalDataCoverageService

    def get_research_eligible_bars(
        self,
        instrument_id: InstrumentId,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
        *,
        exchange: Exchange,
        segment: str,
        symbol: str,
    ) -> ResearchEligibleBars:
        """The one entry point `BacktestingService` (or any future
        research consumer, Gainz included — Part 13) calls instead of
        reading `HistoricalBarReadRepository`/`HistoricalMarketDataService`
        directly. Raises `ResearchDataRejectedError` — never returns an
        incomplete or provenance-ineligible result."""
        # PART 4 — completeness gate. Evaluated ONCE for the whole
        # requested range (not per bar) — `HistoricalDataCoverageService`
        # is itself already a whole-range computation; this gate simply
        # consults its existing, unchanged verdict.
        coverage = self.coverage_service.get_coverage(instrument_id, timeframe, start, end)
        if coverage.expected_bar_count == 0:
            raise ResearchDataRejectedError(
                ResearchRejectionReason.NO_DATA,
                f"no expected bars for {instrument_id} {timeframe} in "
                f"[{start.isoformat()}, {end.isoformat()}]",
            )
        if not coverage.is_complete:
            raise ResearchDataRejectedError(
                ResearchRejectionReason.INCOMPLETE_COVERAGE,
                f"{len(coverage.missing_ranges)} missing sub-range(s); "
                f"{coverage.cached_bar_count}/{coverage.expected_bar_count} bars "
                f"({coverage.coverage_percent}%) cached for {instrument_id} {timeframe} in "
                f"[{start.isoformat()}, {end.isoformat()}] — rejected, never gap-filled",
            )

        # PART 3 — provenance eligibility gate. One repository call for
        # the whole range; every returned row's provenance is checked.
        provenanced = self.repository.get_bars_with_provenance(
            instrument_id, timeframe, start, end
        )
        ineligible_counts: dict[str, int] = {}
        for provenanced_bar in provenanced:
            if not is_research_eligible(provenanced_bar.provenance):
                ineligible_counts[provenanced_bar.provenance] = (
                    ineligible_counts.get(provenanced_bar.provenance, 0) + 1
                )
        if ineligible_counts:
            detail = ", ".join(
                f"{count}x {provenance}" for provenance, count in sorted(ineligible_counts.items())
            )
            raise ResearchDataRejectedError(
                ResearchRejectionReason.INELIGIBLE_PROVENANCE,
                f"{detail} not research-eligible (only REAL_DHAN is) for "
                f"{instrument_id} {timeframe} in [{start.isoformat()}, {end.isoformat()}] — "
                "no row relabeled, no row dropped silently, request rejected outright",
            )

        bars = ensure_chronological(tuple(pb.bar for pb in provenanced))

        # PART 5/6 — resolver/regime context, computed ONCE PER
        # DISTINCT trading date in the returned bars (not per bar).
        sessions_by_date: dict[date, ResolvedSession] = {}
        for bar in bars:
            trading_date = bar.timestamp.astimezone(INDIA_STANDARD_TIME).date()
            if trading_date not in sessions_by_date:
                sessions_by_date[trading_date] = resolve_market_session_for_instant(
                    exchange=exchange,
                    segment=segment,
                    symbol=symbol,
                    as_of=bar.timestamp,
                    is_historical=True,
                )

        return ResearchEligibleBars(
            instrument_id=instrument_id,
            timeframe=timeframe,
            bars=bars,
            coverage=coverage,
            sessions_by_date=sessions_by_date,
        )


__all__ = [
    "ResearchRejectionReason",
    "ResearchDataRejectedError",
    "ResearchEligibleBars",
    "ResearchDataGateService",
]
