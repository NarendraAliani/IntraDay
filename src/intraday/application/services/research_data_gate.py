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

from typing import Callable

from intraday.application.repositories.historical_bars import HistoricalBarReadRepository
from intraday.application.services.historical_data_coverage import (
    CoverageReport,
    HistoricalDataCoverageService,
)
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.provenance import PROVENANCE_REAL_DHAN, is_research_eligible
from intraday.domain.market_data.quality import ensure_chronological
from intraday.domain.market_data.source_timestamp import (
    is_canonicalized,
    is_source_semantics_proven,
)
from intraday.domain.session.calendar import INDIA_STANDARD_TIME
from intraday.domain.session.resolver import ResolvedSession, resolve_market_session_for_instant
from intraday.domain.shared_kernel.contracts import Exchange, InstrumentId, Timeframe


class ResearchRejectionReason(enum.Enum):
    """Part 3/4's explicit, typed rejection taxonomy — a caller (or a
    test) can branch on `.reason` without parsing an error string."""

    NO_DATA = "NO_DATA"
    INCOMPLETE_COVERAGE = "INCOMPLETE_COVERAGE"
    INELIGIBLE_PROVENANCE = "INELIGIBLE_PROVENANCE"
    UNCANONICALIZED_TIMESTAMP = "UNCANONICALIZED_TIMESTAMP"
    """Checkpoint 67.3 Part 4/13/14, HARDENED 67.4 Part 6: raised when
    every row is `REAL_DHAN` (passes the provenance gate above) but at
    least one row fails EITHER of the two now-separate canonicalization
    checks: its `canonicalization_state` is not `CANONICALIZED` (the
    shift never ran — `UNCANONICALIZED`/`NOT_APPLICABLE`/`UNKNOWN`), OR
    its `source_timestamp_semantics` is not a PROVEN value (`OPEN`/
    `CLOSE`) — i.e. it is `UNKNOWN`/`NOT_APPLICABLE`. This is the 67.4
    fix for 67.3's own conflation flaw: a row can have
    `canonicalization_state=CANONICALIZED` (the `+interval` arithmetic
    ran) while `source_timestamp_semantics=UNKNOWN` (that arithmetic was
    never empirically proven for this row's timeframe/era, e.g. 1m or
    PRE-CAS 5m) — "code applied +interval" must never be treated as
    equivalent to "data is semantically proven canonical", so BOTH
    checks must independently pass. Distinguished from
    `INELIGIBLE_PROVENANCE` (a different row-level fact) so a caller/test
    can tell "wrong source" apart from "right source, timestamp not yet
    trustworthy"."""


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
    migration_status_resolver: Callable[..., object] | None = None
    """Checkpoint 67.9 Part 8-9 — dependency-injected resolver for the
    fail-closed migration control-plane check
    (`migration_research_gate_integration.resolve_migration_scope_status`
    by default, see `__post_init__`). Deliberately injectable (not a
    hardcoded import-time call) so:
      (1) EVERY real, production construction site (both explicit and
          via `BacktestingService.for_database_backed_research`) gets
          the REAL DB-backed resolver by default — the safety default
          is never "unrestricted", matching the directive's explicit
          "no feature flag defaulting to unrestricted access."
      (2) Pre-existing 66.1-era pure in-memory unit tests of THIS
          service's completeness/provenance/canonicalization gates
          (`test_research_data_gate.py`) can inject a trivial
          `lambda **_: None` fake ("no migration ever touches this
          scope") instead of requiring a real PostgreSQL connection for
          a check that file was never testing in the first place —
          exactly mirroring 67.9's OWN dedicated boundary tests
          (`test_checkpoint_67_9_research_gate_migration_wiring.py`),
          which use the REAL resolver against a REAL disposable-DB
          fixture specifically because migration-status wiring is
          what THEY test."""

    def __post_init__(self) -> None:
        if self.migration_status_resolver is None:
            from intraday.application.services.migration_research_gate_integration import (
                resolve_migration_scope_status,
            )

            object.__setattr__(self, "migration_status_resolver", resolve_migration_scope_status)

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

        # PART 4/6/13/14 — canonicalization gate (Checkpoint 67.3,
        # HARDENED 67.4 to check TWO independent, orthogonal facts
        # instead of one conflated field). Runs ONLY over rows that
        # already passed the provenance gate above (every
        # `provenanced_bar` reaching here is `REAL_DHAN` — the loop
        # above raised before this point if any row was not).
        #
        # A row is research-eligible ONLY if BOTH:
        #   (1) `canonicalization_state` is `CANONICALIZED` — the
        #       OPEN->CLOSE shift actually ran on this row
        #       (`is_canonicalized`); AND
        #   (2) `source_timestamp_semantics` is a PROVEN value (`OPEN`
        #       or `CLOSE`) — that shift was empirically justified for
        #       this row's provider/timeframe/era, never merely
        #       `UNKNOWN` (`is_source_semantics_proven`).
        #
        # This is the exact 67.4 fix: 67.3 alone would have accepted a
        # row whose `canonicalization_state=CANONICALIZED` regardless of
        # whether `source_timestamp_semantics` was ever proven — exactly
        # the bug that let 1m/PRE-CAS-5m data masquerade as
        # research-ready purely because `+interval` arithmetic ran on
        # it. Checking both here is what blocks that. Neither check ever
        # relabels or drops a row silently — any failure rejects the
        # whole range outright.
        uncanonicalized_counts: dict[str, int] = {}
        for provenanced_bar in provenanced:
            if provenanced_bar.provenance != PROVENANCE_REAL_DHAN:
                continue
            state_ok = is_canonicalized(provenanced_bar.canonicalization_state)
            semantics_ok = is_source_semantics_proven(provenanced_bar.source_timestamp_semantics)
            if not (state_ok and semantics_ok):
                key = (
                    f"canonicalization_state={provenanced_bar.canonicalization_state},"
                    f"source_timestamp_semantics={provenanced_bar.source_timestamp_semantics}"
                )
                uncanonicalized_counts[key] = uncanonicalized_counts.get(key, 0) + 1
        if uncanonicalized_counts:
            detail = ", ".join(
                f"{count}x ({key})" for key, count in sorted(uncanonicalized_counts.items())
            )
            raise ResearchDataRejectedError(
                ResearchRejectionReason.UNCANONICALIZED_TIMESTAMP,
                f"{detail} REAL_DHAN row(s) not both canonicalization_state=CANONICALIZED "
                f"AND source_timestamp_semantics proven (OPEN/CLOSE) for "
                f"{instrument_id} {timeframe} in [{start.isoformat()}, {end.isoformat()}] — "
                "REAL_DHAN provenance alone is not sufficient for performance-research "
                "eligibility, and neither is an applied-but-unproven canonicalization shift; "
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

        # PART 8/9 (Checkpoint 67.9) — FAIL-CLOSED MIGRATION CONTROL-
        # PLANE GATE, wired into the ACTUAL research/backtest boundary
        # (not merely tested against the standalone helper). Runs LAST,
        # after every existing 66.1/67.3/67.4 check has already passed
        # (this new gate never RELAXES anything those checks already
        # reject — it can only add a further rejection). For every
        # distinct trading date this call would return bars for,
        # resolve that unit's real migration status
        # (`migration_research_gate_integration.
        # enforce_migration_scope_or_deny`) and enforce the mechanical
        # mixed-grid rule. `unit_is_complete=True` here because the
        # completeness gate above (`coverage.is_complete`) has ALREADY
        # verified the whole requested range is 100% covered — this
        # call reuses that verdict rather than re-deriving per-date
        # completeness the audit schema does not yet track.
        #
        # `enforce_migration_scope_or_deny` propagates BOTH failure
        # modes verbatim, deliberately uncaught here: an ordinary
        # in-progress/incomplete migration rejection
        # (`MixedGridResearchRejection`) and, critically, an
        # UNDETERMINABLE migration status
        # (`MigrationStatusUndeterminable`) — the fail-closed case. No
        # `except Exception` anywhere in this path defaults to
        # "allowed"; an undetermined status DENIES by raising, exactly
        # like every other rejection this method already raises.
        from intraday.application.services.migration_research_gate_integration import (
            enforce_migration_scope_or_deny,
        )

        for trading_date in sessions_by_date:
            enforce_migration_scope_or_deny(
                instrument_id=instrument_id,
                timeframe=timeframe,
                trading_date=trading_date,
                unit_is_complete=True,
                resolver=self.migration_status_resolver,
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
