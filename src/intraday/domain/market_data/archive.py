# File: src/intraday/domain/market_data/archive.py
#
# Checkpoint 64.73: THE daily market-data archive contract. 64.72 proved
# that real Dhan market data is PERSISTED (4,869 quote packets, 84 bars)
# but named the honest remaining gap: "DAILY MARKET DATA ARCHIVE = NOT
# YET COMPLETE" - there was no trading-date identity anywhere in the
# persistence layer, so "all of today's market data" was not a
# expressible query, and "rows exist" was the only available (and
# false) proxy for "the day was fully observed".
#
# This module is the pure, technology-neutral definition of what a
# daily archive IS - no Django, no provider knowledge, no I/O. It
# deliberately COMPOSES the two pieces of session/quality domain logic
# this project already had rather than re-implementing either:
#
#   * `domain.session.calendar` - IST-correct trading-date derivation,
#     NSE weekend/holiday awareness, and the 09:15-15:30 IST session
#     window. The archive does NOT define its own market hours.
#   * `domain.market_data.quality.expected_bar_timestamps` /
#     `missing_bar_timestamps` - deterministic expected-interval
#     enumeration and gap detection over a session. The archive does
#     NOT define its own gap arithmetic.
#
# What is genuinely NEW here is the ARCHIVE STATUS MODEL: the explicit
# refusal to equate "rows exist" with "the day is complete", and the
# vocabulary (NOT_OBSERVED / IN_PROGRESS / PARTIAL / COMPLETE / FAILED)
# that lets the system state honestly how much of a trading day it
# actually holds.
from __future__ import annotations

import enum
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime

from intraday.domain.market_data.quality import (
    CasWindowStatus,
    classify_cas_window_status,
    expected_bar_timestamps,
    timeframe_to_timedelta,
)
from intraday.domain.session.calendar import INDIA_STANDARD_TIME, is_trading_day
from intraday.domain.session.contracts import CasAwareSession, TradingSession
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe, ensure_utc


class SessionPurpose(enum.StrEnum):
    """Checkpoint 64.92: WHY this archive cell's underlying observations
    were captured - deliberately SEPARATE from `data_source` above.
    `data_source` answers "which provider/transport produced this
    quote/bar" (e.g. `"dhan"`, `"dhan_websocket"`); this answers "was
    that capture a genuine live operational session, or a later replay
    of historical data" - two independent questions. Conflating them
    (e.g. inferring LIVE from `data_source == "dhan"`) is exactly the
    64.92 checkpoint directive's named mistake to avoid, because a
    future replay path could easily reuse the same provider label.

    UNKNOWN is the safe default for every assessment computed without
    an explicit purpose (every pre-64.92 call site, and any future call
    site that genuinely cannot determine one) - never silently promoted
    to LIVE or REPLAY by inference from unrelated fields."""

    UNKNOWN = "UNKNOWN"
    LIVE = "LIVE"
    """A genuine live operational capture - the underlying quotes/bars
    were observed from a real, currently-connected market-data feed
    (today: exclusively the Dhan worker path). As of 64.92, this is the
    ONLY capture path that writes into `LiveQuoteObservation` /
    `AggregatedBarObservation` - no replay writer targets those tables
    (`infrastructure.market_data_providers.replay.
    DeterministicReplayBarSource` feeds the separate paper-session
    replay loop and never touches these tables). That is what makes it
    honest to stamp LIVE at refresh time rather than merely defaulting
    to it."""
    REPLAY = "REPLAY"
    """A deliberate replay of previously-captured or externally-sourced
    historical data. No code path writes this today (checkpoint 64.92
    is offline-only and introduces no replay writer for these tables) -
    the value exists so a FUTURE replay path has somewhere honest to
    say so, per the 64.92 replay-isolation contract. Never assigned to
    a row unless the writer genuinely is a replay path."""


class ArchiveStatus(enum.StrEnum):
    """How much of one trading day this archive actually holds for one
    (symbol, timeframe, source). Deliberately FIVE distinct values -
    the whole point of this checkpoint is that "we have some rows" and
    "we have the whole day" must never collapse into one another."""

    NOT_OBSERVED = "NOT_OBSERVED"
    """No data at all. Either nothing was ever ingested for this
    day/symbol, or the date is not an NSE trading day. `reason`
    distinguishes the two - a weekend being empty is CORRECT, an open
    trading day being empty is a real operational gap."""

    IN_PROGRESS = "IN_PROGRESS"
    """The session has not closed yet (as-of < market_close). A day
    that is still being observed can NEVER be COMPLETE or PARTIAL -
    calling a half-finished live session "PARTIAL" would confuse "the
    day is not over" with "the day is over and we missed data"."""

    PARTIAL = "PARTIAL"
    """The session is over, data exists, but the expected bar series
    for this timeframe has gaps (or completeness cannot be evaluated
    for this timeframe - see `completeness_supported`). This is the
    HONEST status for 64.72's own ~20-minute observe-only window: real
    data, genuinely not a whole trading day."""

    COMPLETE = "COMPLETE"
    """The session is over and EVERY expected bar interval for this
    timeframe is present. This is the only status that entitles a
    downstream consumer (research, reconciliation, and any future
    signal-research milestone) to
    treat the day as a whole-session series."""

    FAILED = "FAILED"
    """An ingestion run for this day terminated in a state the worker
    itself classified as unrecoverable. Never inferred from row counts
    - only ever recorded explicitly by the ingestion side, because
    "few rows" and "the feed broke" are not the same claim."""


class ReconciliationStatus(enum.StrEnum):
    """Whether this archived day has been cross-checked against an
    INDEPENDENT source of truth (e.g. a provider's own historical
    candle API). Checkpoint 64.73 MODELS this; it does not yet perform
    it - `NOT_RECONCILED` is therefore the honest value on every row
    this checkpoint writes."""

    NOT_RECONCILED = "NOT_RECONCILED"
    RECONCILED = "RECONCILED"
    MISMATCH = "MISMATCH"


# Completeness can only be evaluated for timeframes whose bar
# boundaries actually line up with the NSE session window. The session
# is 375 minutes (09:15-15:30 IST) and `aggregation.py` anchors its
# buckets at the UTC epoch; 09:15 IST is 03:45 UTC. A timeframe is
# supported here only when BOTH the session length and the session
# open are exact multiples of the bar duration - otherwise the first
# and/or last bucket straddles the session boundary and an
# "expected bar count" would be a fiction. 30m and 1h fail both tests
# (225 and 375 are not multiples of 30 or 60), so they are explicitly
# declared UNSUPPORTED rather than silently mis-measured.
_SESSION_MINUTES = 375
_SESSION_OPEN_OFFSET_MINUTES = 225  # 03:45 UTC since midnight UTC


def is_completeness_supported(timeframe: Timeframe) -> bool:
    """Whether a defensible expected-bar count exists for `timeframe`
    against the NSE cash-equity session. See the comment above for the
    arithmetic - this returns `False` (never a guess) for TICK, DAY,
    30m and 1h."""
    return _minutes_supported(timeframe, _SESSION_MINUTES, _SESSION_OPEN_OFFSET_MINUTES)


def _minutes_supported(timeframe: Timeframe, window_minutes: int, open_offset_minutes: int) -> bool:
    """Shared arithmetic behind `is_completeness_supported` (the plain,
    uniform 09:15-15:30 window) and `is_continuous_completeness_
    supported` below (Checkpoint 64.88's narrower, category-specific
    continuous-trading window) - the SAME "does this timeframe's bar
    duration tile the window without straddling either edge" test,
    parameterised by window instead of duplicated per window."""
    try:
        duration = timeframe_to_timedelta(timeframe)
    except ValueError:
        return False  # TICK has no fixed duration.
    minutes = int(duration.total_seconds() // 60)
    if minutes <= 0 or minutes > window_minutes:
        return False
    return window_minutes % minutes == 0 and open_offset_minutes % minutes == 0


# ---------------------------------------------------------------------
# Checkpoint 64.88: CATEGORY-I continuous-trading completeness support.
#
# CATEGORY_I_CAS instruments run continuous trading 09:15-15:15 IST
# (360 minutes), not the 375-minute 09:15-15:30 window
# `is_completeness_supported` checks against - reusing that function
# unmodified for a CATEGORY_I_CAS instrument would silently apply the
# WRONG window's alignment test. `CasAwareSession` already carries the
# correct, already-computed `continuous_trading_open`/`_close` for
# whichever category it was built for (CATEGORY_II_NON_CAS included -
# its window is 375 minutes, identical to the plain-session case), so
# this derives the window length/offset from the session ITSELF rather
# than hand-duplicating the 360-vs-375 distinction as a second pair of
# constants that could drift out of sync with `domain.session.calendar`.
def is_continuous_completeness_supported(
    timeframe: Timeframe, cas_session: CasAwareSession
) -> bool:
    """Whether a defensible expected-bar count exists for `timeframe`
    against `cas_session`'s CONTINUOUS-TRADING window only (never CAS
    or post-CAS) - the CAS-aware sibling of `is_completeness_supported`."""
    window_minutes = int(
        (cas_session.continuous_trading_close - cas_session.continuous_trading_open).total_seconds()
        // 60
    )
    midnight_utc = cas_session.continuous_trading_open.replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    open_offset_minutes = int(
        (cas_session.continuous_trading_open - midnight_utc).total_seconds() // 60
    )
    return _minutes_supported(timeframe, window_minutes, open_offset_minutes)


def trading_date_for(instant: datetime) -> date:
    """THE canonical trading-date derivation for this platform: the IST
    calendar date of a UTC instant. This single function is why the
    archive is trading-day aware - a naive `instant.date()` would be
    wrong for the ~5.5 hours per day where the UTC and IST calendar
    dates differ, which for an NSE session means EVERY bar before
    05:30 UTC (i.e. the entire 09:15-11:00 IST opening range) would be
    filed under the previous day."""
    ensure_utc(instant, field_name="instant")
    return instant.astimezone(INDIA_STANDARD_TIME).date()


@dataclass(frozen=True, slots=True)
class TradingSessionIdentity:
    """The unique identity of one archived trading session. NOT a
    random UUID and NOT a per-process run id - identity is the natural
    key `(exchange, trading_date)`, so two ingestion runs on the same
    day converge on the SAME session rather than creating a second
    "session" for the same calendar day (the idempotency guarantee
    this archive rests on)."""

    exchange: Exchange
    trading_date: date

    @property
    def key(self) -> str:
        """A stable, human-readable, log-safe identity string, e.g.
        `"NSE:2026-08-25"`."""
        return f"{self.exchange.value}:{self.trading_date.isoformat()}"

    @property
    def is_trading_day(self) -> bool:
        return is_trading_day(self.trading_date)


@dataclass(frozen=True, slots=True)
class ArchiveDayAssessment:
    """The computed archival verdict for one
    (exchange, trading_date, symbol, timeframe, data_source) cell.

    This is a pure VALUE - computing it never writes anything. The
    persistence layer stores it so it is queryable; it can always be
    recomputed from the underlying observations, so the stored copy is
    a projection, never a second source of truth."""

    identity: TradingSessionIdentity
    instrument_symbol: str
    timeframe: Timeframe
    data_source: str
    status: ArchiveStatus
    reason: str
    completeness_supported: bool
    expected_bar_count: int
    closed_bar_count: int
    forming_bar_count: int
    quote_observation_count: int
    first_observation_at: datetime | None
    last_observation_at: datetime | None
    missing_bar_timestamps: tuple[datetime, ...] = field(default_factory=tuple)
    duplicate_bar_timestamps: tuple[datetime, ...] = field(default_factory=tuple)
    reconciliation_status: ReconciliationStatus = ReconciliationStatus.NOT_RECONCILED
    cas_window_status: CasWindowStatus = CasWindowStatus.NOT_APPLICABLE
    session_purpose: SessionPurpose = SessionPurpose.UNKNOWN
    """Checkpoint 64.92: ADDITIVE field - see `SessionPurpose`'s own
    docstring for the full LIVE/REPLAY/UNKNOWN contract. Defaults to
    UNKNOWN for every assessment computed without an explicit
    `session_purpose` argument, so every pre-64.92 call site keeps
    compiling and keeps meaning what it meant."""
    """Checkpoint 64.88: ADDITIVE field, `NOT_APPLICABLE` for every
    assessment computed WITHOUT a `cas_session` (every pre-64.88 caller,
    and every CATEGORY_II_NON_CAS instrument) - existing behavior is
    unchanged by its mere presence. See `quality.CasWindowStatus` for
    what each value claims and, just as importantly, does not claim.
    Deliberately kept SEPARATE from `status`/`reason` above (continuous
    completeness) rather than folded into them - CAS applicability is
    not a completeness verdict (per the checkpoint directive: do not
    mark CAS COMPLETE merely because no bars are expected, and do not
    mark it FAILED merely because ordinary bars are absent)."""

    @property
    def missing_bar_count(self) -> int:
        return len(self.missing_bar_timestamps)

    @property
    def coverage_ratio(self) -> float:
        """Observed CLOSED bars / expected bars, in [0.0, 1.0]. Returns
        `0.0` when completeness is not supported for this timeframe -
        never a misleading `1.0` for a day whose expected count is
        itself undefined."""
        if not self.completeness_supported or self.expected_bar_count <= 0:
            return 0.0
        return min(self.closed_bar_count / self.expected_bar_count, 1.0)


def assess_archive_day(
    *,
    identity: TradingSessionIdentity,
    instrument_symbol: str,
    timeframe: Timeframe,
    data_source: str,
    session: TradingSession,
    closed_bar_timestamps: Sequence[datetime],
    forming_bar_count: int,
    quote_observation_count: int,
    first_observation_at: datetime | None,
    last_observation_at: datetime | None,
    as_of: datetime,
    ingestion_failed: bool = False,
    cas_session: CasAwareSession | None = None,
    session_purpose: SessionPurpose = SessionPurpose.UNKNOWN,
) -> ArchiveDayAssessment:
    """Classifies one archived (symbol, timeframe, day) cell.

    `closed_bar_timestamps` are bar CLOSE instants (matching `Bar.
    timestamp` and `AggregatedBar.interval_end` - see `contracts.py`),
    because that is the vocabulary `quality.expected_bar_timestamps`
    already speaks. Gap detection is delegated to that existing domain
    function; this function's own job is only the STATUS decision.

    `cas_session` (Checkpoint 64.88, OPTIONAL, defaults to `None`):
    when given, CONTINUOUS-TRADING completeness (`status`/`reason`/
    `missing_bar_timestamps`/`expected_bar_count`) is assessed against
    `cas_session`'s own continuous-trading window instead of `session`'s
    plain [market_open, market_close] bounds - the fix for the 64.85-
    class defect where a CATEGORY_I_CAS instrument's 15:15-15:35 CAS
    quiet was indistinguishable from a real 09:15-15:30 gap.
    `cas_window_status` (see its own field docstring) is populated from
    it independently. Omitting `cas_session` (every pre-64.88 call site)
    reproduces the EXACT prior behavior - this parameter is purely
    additive.

    Decision order is deliberate and is the core honesty rule of this
    checkpoint:
      1. a non-trading date is NOT_OBSERVED (and that is CORRECT);
      2. an explicitly failed ingestion is FAILED, whatever the counts;
      3. no data at all is NOT_OBSERVED;
      4. a session that has not closed yet is IN_PROGRESS - never
         COMPLETE, never PARTIAL;
      5. a timeframe with no defensible expected count is PARTIAL, with
         the limitation named in `reason` - never COMPLETE by default;
      6. otherwise COMPLETE only when ZERO expected bars are missing.
    """
    ensure_utc(as_of, field_name="as_of")

    if cas_session is not None:
        supported = is_continuous_completeness_supported(timeframe, cas_session)
        duration = timeframe_to_timedelta(timeframe) if supported else None
        expected = cas_session.expected_continuous_bar_timestamps(duration) if duration else ()
        cas_window_status = classify_cas_window_status(cas_session)
    else:
        supported = is_completeness_supported(timeframe)
        expected = expected_bar_timestamps(session, timeframe) if supported else ()
        cas_window_status = CasWindowStatus.NOT_APPLICABLE

    seen: set[datetime] = set()
    duplicates: list[datetime] = []
    for stamp in closed_bar_timestamps:
        ensure_utc(stamp, field_name="closed_bar_timestamp")
        if stamp in seen:
            duplicates.append(stamp)
        seen.add(stamp)

    missing = tuple(stamp for stamp in expected if stamp not in seen)
    closed_count = len(seen)

    def build(status: ArchiveStatus, reason: str) -> ArchiveDayAssessment:
        return ArchiveDayAssessment(
            identity=identity,
            instrument_symbol=instrument_symbol,
            timeframe=timeframe,
            data_source=data_source,
            status=status,
            reason=reason,
            completeness_supported=supported,
            expected_bar_count=len(expected),
            closed_bar_count=closed_count,
            forming_bar_count=forming_bar_count,
            quote_observation_count=quote_observation_count,
            first_observation_at=first_observation_at,
            last_observation_at=last_observation_at,
            missing_bar_timestamps=missing,
            duplicate_bar_timestamps=tuple(sorted(set(duplicates))),
            cas_window_status=cas_window_status,
            session_purpose=session_purpose,
        )

    # Checkpoint 64.88: when `cas_session` is given, CONTINUOUS-TRADING
    # completeness is decidable as soon as the CONTINUOUS window itself
    # closes (`continuous_trading_close`, 15:15 IST for CATEGORY_I_CAS) -
    # not the plain session's 15:30 `market_close`. Waiting for 15:30
    # would misreport a fully-complete 09:15-15:15 continuous series as
    # still `IN_PROGRESS` for the entire CAS window, for no reason: CAS
    # data availability is tracked separately by `cas_window_status`,
    # never by delaying the continuous verdict.
    continuous_closed_at = (
        cas_session.continuous_trading_close if cas_session is not None else session.market_close
    )
    if not identity.is_trading_day:
        return build(ArchiveStatus.NOT_OBSERVED, "non_trading_day")
    if ingestion_failed:
        return build(ArchiveStatus.FAILED, "ingestion_reported_failure")
    if closed_count == 0 and forming_bar_count == 0 and quote_observation_count == 0:
        return build(ArchiveStatus.NOT_OBSERVED, "no_observations_persisted")
    if as_of < continuous_closed_at:
        return build(ArchiveStatus.IN_PROGRESS, "session_not_closed")
    if not supported:
        return build(
            ArchiveStatus.PARTIAL,
            f"completeness_unsupported_timeframe:{timeframe.value}",
        )
    if missing:
        return build(ArchiveStatus.PARTIAL, f"missing_bars:{len(missing)}")
    return build(ArchiveStatus.COMPLETE, "all_expected_bars_present")


__all__ = [
    "ArchiveDayAssessment",
    "ArchiveStatus",
    "ReconciliationStatus",
    "SessionPurpose",
    "TradingSessionIdentity",
    "assess_archive_day",
    "is_completeness_supported",
    "is_continuous_completeness_supported",
    "trading_date_for",
]
