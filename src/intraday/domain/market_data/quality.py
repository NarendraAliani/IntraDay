# File: src/intraday/domain/market_data/quality.py
#
# Checkpoint 14: pure, technology-neutral market-data integrity functions
# — ordering/duplicate validation and deterministic missing-interval
# detection over a `Bar` series. Domain-layer, not application-layer,
# because these rules are intrinsic to what a valid Bar *series* means
# (the same way `Bar.__post_init__` validates what a valid single Bar
# means) and must be identically true for research/backtesting and live
# consumers alike (Rule 5.5 parity) — no infrastructure, no provider
# knowledge, no Django import.
#
# Policy (Checkpoint 14 §16, §6): invalid ordering is REJECTED (raises),
# never silently discarded or silently reordered. A caller that wants
# resilience against a misbehaving provider must catch these exceptions
# explicitly at the infrastructure boundary — the domain layer never
# guesses what "fixing" bad data would mean.
from __future__ import annotations

import enum
from datetime import datetime, timedelta

from intraday.domain.market_data.contracts import Bar, Quote
from intraday.domain.session.contracts import CasAwareSession, MarketSessionState, TradingSession
from intraday.domain.shared_kernel.contracts import Timeframe


class DuplicateBarTimestampError(ValueError):
    """Raised when two bars in a series share the same timestamp."""


class OutOfOrderBarError(ValueError):
    """Raised when a bar series is not strictly increasing by timestamp."""


def ensure_chronological(bars: tuple[Bar, ...]) -> tuple[Bar, ...]:
    """Validates that `bars` is strictly increasing by `timestamp` with no
    duplicates, and returns it unchanged if so. Never reorders or drops a
    bar itself — an out-of-order or duplicate series is a REJECTED input
    (Checkpoint 14 §16), the caller's responsibility to fix upstream, not
    this function's to paper over silently."""
    for previous, current in zip(bars, bars[1:], strict=False):
        if current.timestamp == previous.timestamp:
            raise DuplicateBarTimestampError(
                f"duplicate bar timestamp {current.timestamp.isoformat()} "
                f"for instrument {current.instrument_id!r}"
            )
        if current.timestamp < previous.timestamp:
            raise OutOfOrderBarError(
                f"bar at {current.timestamp.isoformat()} follows "
                f"{previous.timestamp.isoformat()} out of order for "
                f"instrument {current.instrument_id!r}"
            )
    return bars


def timeframe_to_timedelta(timeframe: Timeframe) -> timedelta:
    """The fixed duration one bar of `timeframe` spans. `TICK` has no
    fixed duration by definition (a tick is a single trade/quote event,
    not a time bucket) and deliberately raises rather than returning an
    arbitrary placeholder."""
    mapping = {
        Timeframe.ONE_MINUTE: timedelta(minutes=1),
        Timeframe.THREE_MINUTE: timedelta(minutes=3),
        Timeframe.FIVE_MINUTE: timedelta(minutes=5),
        Timeframe.FIFTEEN_MINUTE: timedelta(minutes=15),
        Timeframe.THIRTY_MINUTE: timedelta(minutes=30),
        Timeframe.ONE_HOUR: timedelta(hours=1),
        Timeframe.DAY: timedelta(days=1),
    }
    try:
        return mapping[timeframe]
    except KeyError as exc:
        raise ValueError(f"{timeframe!r} has no fixed bar duration") from exc


def expected_bar_timestamps(session: TradingSession, timeframe: Timeframe) -> tuple[datetime, ...]:
    """Every bar-close timestamp a complete, gap-free series for
    `timeframe` would have within `session` — deterministic arithmetic
    over the session's own already-determined open/close bounds, never a
    calendar computation (Checkpoint 14 §11). The first expected
    timestamp is `market_open + timeframe duration` (a bar's timestamp is
    its CLOSE time — see `Bar`'s docstring — so the bar covering
    [market_open, market_open + duration) closes at that instant, not at
    market_open itself)."""
    duration = timeframe_to_timedelta(timeframe)
    timestamps: list[datetime] = []
    current = session.market_open + duration
    while current <= session.market_close:
        timestamps.append(current)
        current += duration
    return tuple(timestamps)


def missing_bar_timestamps(
    bars: tuple[Bar, ...], session: TradingSession, timeframe: Timeframe
) -> tuple[datetime, ...]:
    """Which expected timestamps (per `expected_bar_timestamps`) are
    absent from `bars`. Deterministic and order-independent — does not
    require `bars` to already be validated chronological, so it can also
    diagnose a series before deciding whether to call
    `ensure_chronological` on it."""
    present = {bar.timestamp for bar in bars}
    return tuple(ts for ts in expected_bar_timestamps(session, timeframe) if ts not in present)


# ---------------------------------------------------------------------
# Checkpoint 64.87 Part B: raw observation IDENTITY and staleness.
#
# 64.85's evidence: ~600 rows/symbol/minute persisted with only ~50-60
# distinct `source_timestamp` values - the same provider observation
# (same `source_timestamp`, same quote content) was being re-persisted
# repeatedly as `fetched_at` advanced, as if each re-persistence were a
# fresh market event. It was not: `fetched_at` is local RECEIPT
# metadata (when THIS process happened to observe/re-poll/re-flush the
# quote), never itself proof of a new market event.
#
# CANONICAL OBSERVATION IDENTITY (the rule this checkpoint establishes,
# per the directive's explicit instruction to "determine the correct
# uniqueness semantics from the existing model" before touching
# schema): one instrument's market observation is identified by
# (instrument, source_timestamp). Two `Quote`s for the same instrument
# sharing a `source_timestamp` are the SAME observation IF AND ONLY IF
# their full observed snapshot (price + whatever else was actually
# measured) also matches - re-arrival of that identical snapshot is a
# STALE re-delivery, not a new observation. If the snapshot instead
# DIFFERS at the same `source_timestamp`, that is NOT silently treated
# as a duplicate (price equality alone is explicitly NOT the
# deduplication key, and the reverse - price difference alone - must
# not silently discard data either): it is flagged as CONFLICTING for
# the caller to log/investigate, and is NOT dropped, because this
# module has no way to know which of two disagreeing same-timestamp
# readings (if either) is correct.
class ObservationComparison(enum.Enum):
    """The outcome of comparing a candidate `Quote` against the most
    recently known `Quote` for the SAME instrument."""

    NEW = "NEW"
    """A genuinely new observation: no prior observation exists for this
    instrument, or the candidate's `source_timestamp` differs from the
    prior one (regardless of whether the price happens to match — three
    legitimate quotes at three different timestamps, same price, are
    each `NEW`)."""

    STALE_DUPLICATE = "STALE_DUPLICATE"
    """Same instrument, same `source_timestamp`, IDENTICAL snapshot as
    the most recently known observation - the exact 64.85 defect shape.
    Callers must not re-persist this as if it were a fresh observation."""

    CONFLICTING_SAME_TIMESTAMP = "CONFLICTING_SAME_TIMESTAMP"
    """Same instrument, same `source_timestamp`, but a DIFFERENT
    snapshot (e.g. a different price) than the most recently known
    observation. An anomaly, not a duplicate - never silently
    discarded; the caller is expected to persist it and surface/log the
    conflict rather than guessing which reading is correct."""


# ---------------------------------------------------------------------
# Checkpoint 64.88: CAS-AWARE missing-interval detection.
#
# 64.85's incident could not be told apart from ordinary CAS quiet
# because `missing_bar_timestamps` above only ever knew ONE session
# shape - `TradingSession`'s uniform [market_open, market_close]. For a
# CATEGORY_I_CAS instrument that shape is simply WRONG after 15:15 IST:
# continuous-trading bar expectations end at 15:15, not 15:30, and the
# 15:15-15:35 CAS window is not a gap in continuous data - it is a
# different kind of interval this function must not flag at all.
#
# CRITICAL PRINCIPLE (per the checkpoint directive, restated here so it
# cannot be missed by a future reader of just this function): this
# module does NOT know, and must never claim to know, what Dhan's feed
# actually transmits during CAS. The only fact encoded below is the
# EXCHANGE session fact - "CAS is not continuous trading" - never a
# provider-behavior claim.
def missing_continuous_bar_timestamps(
    bars: tuple[Bar, ...], cas_session: CasAwareSession, timeframe: Timeframe
) -> tuple[datetime, ...]:
    """The CAS-aware sibling of `missing_bar_timestamps`: which expected
    CONTINUOUS-TRADING bar-close timestamps (per `cas_session.
    expected_continuous_bar_timestamps`, bounded by
    `continuous_trading_close` - never CAS or post-CAS) are absent from
    `bars`.

    For `InstrumentCategory.CATEGORY_II_NON_CAS` this is arithmetically
    identical to `missing_bar_timestamps` against the equivalent plain
    `TradingSession` (continuous trading still runs the full session,
    unchanged) - this function exists so a CATEGORY_I_CAS caller gets
    the correct, narrower 09:15-15:15 expectation instead of the old
    09:15-15:30 one, without a second, parallel implementation of the
    gap-detection arithmetic itself (delegated to `CasAwareSession.
    expected_continuous_bar_timestamps`, per that method's own
    docstring)."""
    duration = timeframe_to_timedelta(timeframe)
    present = {bar.timestamp for bar in bars}
    expected = cas_session.expected_continuous_bar_timestamps(duration)
    return tuple(ts for ts in expected if ts not in present)


class CasWindowStatus(enum.Enum):
    """Checkpoint 64.88: the CAS-WINDOW-STATUS concept the directive
    requires to be kept SEPARATE from continuous-data completeness
    (`missing_continuous_bar_timestamps` above / `ArchiveStatus`).
    Deliberately does NOT reuse `ArchiveStatus`'s COMPLETE/PARTIAL/
    MISSING vocabulary - CAS is not a completeness question at all, and
    forcing it into that vocabulary is exactly how the 64.85 incident
    became indistinguishable from a real gap."""

    NOT_APPLICABLE = "NOT_APPLICABLE"
    """This instrument has no CAS window at all
    (`InstrumentCategory.CATEGORY_II_NON_CAS`), or the session for this
    date/category never entered CAS state (still PRE_OPEN/CONTINUOUS_
    TRADING/HOLIDAY/CLOSED as of the classification instant)."""

    EXPECTED_NON_CONTINUOUS = "EXPECTED_NON_CONTINUOUS"
    """The session state is `MarketSessionState.CAS`. The ABSENCE of
    ordinary continuous-trading bars during this window is expected and
    must never be reported as a missing-data defect - but this value
    makes NO claim about what data, if any, the provider actually sent
    during the window (see `PROVIDER_BEHAVIOR_UNKNOWN`, and the module-
    level Dhan-behavior disclaimer above)."""

    PROVIDER_BEHAVIOR_UNKNOWN = "PROVIDER_BEHAVIOR_UNKNOWN"
    """The session has passed through (or is past) a CAS window for a
    CATEGORY_I_CAS instrument, and the honest answer to "was CAS data
    itself observed/complete" is UNRESOLVED - no verified Dhan-behavior
    contract exists yet (see `docs/architecture/
    LIVE_MARKET_DATA_ARCHITECTURE.md`'s open question). Used for
    `MarketSessionState.POST_CAS_TRANSITION`: continuous-trading
    completeness for 09:15-15:15 is fully decidable by then
    (`missing_continuous_bar_timestamps` answers it), but this
    checkpoint deliberately does NOT invent a CAS-window completeness
    verdict alongside it."""


def classify_cas_window_status(cas_session: CasAwareSession) -> CasWindowStatus:
    """Classifies the CAS-window status implied by `cas_session`'s
    current `state` - pure lookup, no I/O, no provider knowledge. See
    `CasWindowStatus` for what each value does and does not claim."""
    if cas_session.state is MarketSessionState.CAS:
        return CasWindowStatus.EXPECTED_NON_CONTINUOUS
    if cas_session.state is MarketSessionState.POST_CAS_TRANSITION:
        return CasWindowStatus.PROVIDER_BEHAVIOR_UNKNOWN
    return CasWindowStatus.NOT_APPLICABLE


class ObservationSessionClassification(enum.Enum):
    """Checkpoint 64.88 (64.85 replay): classifies WHEN, relative to
    session state, a provider observation arrived - deliberately never
    a claim about WHAT the observation semantically IS. The 64.85
    incident's core error was treating "a packet arrived" as proof of
    "a continuous trade happened"; this enum exists so a caller cannot
    make that same substitution again."""

    CONTINUOUS_TRADING_OBSERVATION = "CONTINUOUS_TRADING_OBSERVATION"
    """Arrived while `MarketSessionState.CONTINUOUS_TRADING` was in
    effect - ordinary continuous-trading data."""

    PROVIDER_OBSERVATION_DURING_CAS = "PROVIDER_OBSERVATION_DURING_CAS"
    """Arrived while `MarketSessionState.CAS` was in effect. Its
    semantic meaning (reference price? auction price? LTP carry-
    forward? something else entirely?) is DELIBERATELY UNCLASSIFIED
    here - this checkpoint does not know, and must not guess, what a
    CAS-window packet from Dhan represents. Callers must never rename
    or reinterpret this value as "trade print", "auction price", or
    any other invented semantic without new, independently verified
    evidence."""

    OBSERVATION_OUTSIDE_SESSION = "OBSERVATION_OUTSIDE_SESSION"
    """Arrived during PRE_OPEN, POST_CAS_TRANSITION, CLOSED, or HOLIDAY
    - outside both continuous trading and CAS."""


def classify_observation_session(cas_session: CasAwareSession) -> ObservationSessionClassification:
    """Classifies an observation timestamped to fall within
    `cas_session` (i.e. `cas_session` was built with `as_of` equal to
    the observation's own timestamp) by session state alone. Pure
    lookup - callers own resolving the observation's timestamp into the
    right `CasAwareSession` (`domain.session.calendar.
    cas_aware_session_for_instant`)."""
    if cas_session.state is MarketSessionState.CONTINUOUS_TRADING:
        return ObservationSessionClassification.CONTINUOUS_TRADING_OBSERVATION
    if cas_session.state is MarketSessionState.CAS:
        return ObservationSessionClassification.PROVIDER_OBSERVATION_DURING_CAS
    return ObservationSessionClassification.OBSERVATION_OUTSIDE_SESSION


def classify_observation(previous: Quote | None, candidate: Quote) -> ObservationComparison:
    """Classifies `candidate` against `previous` (the most recently known
    `Quote` for the SAME instrument, or `None` if this is the first
    observation ever seen for it) per the canonical observation-identity
    rule documented above. Pure and side-effect-free — callers (e.g. the
    persistence boundary) decide what to DO with the classification
    (skip a `STALE_DUPLICATE` insert, log a `CONFLICTING_SAME_TIMESTAMP`
    insert); this function only classifies.

    Comparison fields, deliberately limited to what the domain `Quote`
    contract treats as the observed snapshot: `last_price` and
    `cumulative_volume`. `fetched_at` is NEVER a comparison input here -
    it is receipt metadata, not part of the observation's identity."""
    if previous is None:
        return ObservationComparison.NEW
    if previous.instrument_id != candidate.instrument_id:
        raise ValueError(
            "classify_observation() requires previous and candidate to share the "
            "same instrument_id"
        )
    if candidate.timestamp != previous.timestamp:
        return ObservationComparison.NEW
    if (
        candidate.last_price == previous.last_price
        and candidate.cumulative_volume == previous.cumulative_volume
    ):
        return ObservationComparison.STALE_DUPLICATE
    return ObservationComparison.CONFLICTING_SAME_TIMESTAMP
