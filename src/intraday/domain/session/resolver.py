# File: src/intraday/domain/session/resolver.py
#
# Checkpoint 65.33: the "smallest safe" market-session RESOLUTION
# foundation identified by the 65.28->65.32 research arc (accepted
# 9.5/10 at 65.32). This module is a pure COMPOSITION layer — it
# resolves (trading_date, exchange, segment, instrument category,
# as_of instant) into one coherent `ResolvedSession` snapshot by
# calling the EXISTING `domain.session.calendar` functions and wrapping
# their EXISTING `TradingSession`/`CasAwareSession` results. It
# introduces exactly two genuinely new things:
#
#   1. `Regime` (PRE_CAS vs CAS_ERA vs UNKNOWN_HISTORICAL) — 65.32's
#      finding that PRE_CAS and CAS_ERA must remain distinguishable,
#      and that historical eligibility must never be silently guessed.
#   2. `ResolvedSession.exit_eligible` — 65.32's identified genuine gap:
#      existing-position EXIT admission is currently NOT CAS-aware
#      anywhere in this codebase (65.29's gate in
#      `active_loop_runtime.py` is NEW-ENTRY-ONLY, by its own docstring).
#
# NOT wired into any consumer this checkpoint (checkpoint directive,
# explicit): `active_loop_runtime.py`, `PaperBroker`, EOD scheduling are
# all untouched. This module is a foundation piece for FUTURE
# consumers, not a replacement for 65.29's already-working entry gate.
#
# NOT a parallel session framework: every timing fact here is read off
# `TradingSession`/`CasAwareSession`, computed via `build_session_for`/
# `build_cas_aware_session_for`/`instrument_category_for` exactly as
# they exist today. This module adds no new market-hours arithmetic,
# no new 15:15/15:30/15:20 computation of its own, and does not
# introduce `15:10` as a constant anywhere (that remains an undecided,
# documented-only future policy candidate — see `Regime`'s own
# docstring and `ResolvedSession.exit_eligible`'s docstring below).
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import date, datetime

from intraday.domain.session.calendar import (
    CAS_EFFECTIVE_DATE,
    build_cas_aware_session_for,
    build_session_for,
    instrument_category_for,
)
from intraday.domain.session.contracts import (
    CasAwareSession,
    InstrumentCategory,
    SessionStatus,
    TradingSession,
)
from intraday.domain.shared_kernel.contracts import Exchange, ensure_utc

# Checkpoint 65.33: cash-equity segment identifier. Deliberately a bare
# string constant, not a new enum type — this resolver's contract is
# scoped to NSE/BSE intraday CASH-EQUITY trading only (this platform's
# entire scope, per every prior checkpoint); a richer segment taxonomy
# (F&O, currency, commodity) is explicitly out of scope and not
# invented here.
CASH_EQUITY_SEGMENT = "CASH_EQUITY"


class Regime(enum.Enum):
    """Checkpoint 65.33: which CAS-POLICY era `trading_date` falls in,
    for a `CATEGORY_I_CAS` instrument. This is NOT a new session-timing
    computation — `TradingSession`/`CasAwareSession` already compute the
    correct clock boundaries for any date; `Regime` only answers a
    DIFFERENT question 65.32 identified as missing: "was NSE's CAS
    circular actually in effect on this historical date?"

    PRE_CAS: `trading_date` is strictly before `CAS_EFFECTIVE_DATE` —
    CAS did not exist yet; `CasAwareSession.is_cas`/`.cas_start`/
    `.cas_end` for that date are computable (calendar.py always
    computes them) but describe a window NSE was not actually running
    on that historical date. A consumer that needs "was CAS a real
    market event on this date" must consult `Regime`, not just
    `CasAwareSession` in isolation.

    CAS_ERA: `trading_date` is on/after `CAS_EFFECTIVE_DATE` — CAS is
    (as far as this resolver knows) actually in effect. This does NOT
    mean per-instrument CAS *eligibility* on that historical date is
    known (see `HistoricalEligibility` below) — only that the CAS
    *regime itself* had begun.

    UNKNOWN_HISTORICAL_ELIGIBILITY: reserved value — see
    `HistoricalEligibility.UNKNOWN`'s docstring; `Regime` itself never
    takes this value (regime is a pure date comparison, always
    knowable), it is documented here only to point readers to the
    field that DOES carry unknown-state, so the two are not conflated.

    Deliberately does NOT encode `15:10` anywhere — the 15:10 square-off
    idea floated during the 65.28-65.32 research arc remains an
    undecided, un-implemented future policy candidate. `Regime` is a
    date-only, whole-trading-day concept and carries no intraday clock
    constants at all.
    """

    PRE_CAS = "PRE_CAS"
    CAS_ERA = "CAS_ERA"


class HistoricalEligibility(enum.Enum):
    """Checkpoint 65.33: whether THIS instrument's CAS eligibility is
    actually known for `trading_date`, kept explicitly separate from
    `Regime` (era) and from `InstrumentCategory` (today's static
    classification list, `CATEGORY_I_CAS_SYMBOLS`).

    `calendar.py`'s `CATEGORY_I_CAS_SYMBOLS` is a CURRENT, present-day
    classification list (its own docstring: "closed, checkpoint-scoped
    classification list") — it carries no historical dimension at all.
    NSE's actual CAS-eligible instrument list is known to change over
    time (additions/removals to the F&O/Category-I universe), and this
    codebase has NO historical eligibility dataset. Per the checkpoint
    directive's HARD RULE, this resolver must not fabricate one.

    KNOWN_CURRENT: `trading_date` is "today" (or otherwise treated as
    the live/current classification) — `instrument_category_for()`'s
    present-day answer is used directly, exactly as 65.29's gate
    already does.

    UNKNOWN_HISTORICAL: `trading_date` is a PAST date and the resolver
    has no historical eligibility record for it. This is the explicit,
    typed "unknown" state the checkpoint directive requires instead of
    silently defaulting to either PRE_CAS or CAS_ERA behavior. A
    consumer that receives `UNKNOWN_HISTORICAL` must not assume either
    CATEGORY_I_CAS or CATEGORY_II_NON_CAS was actually correct for that
    historical date — it must fall back to whatever conservative policy
    the CONSUMER (not this resolver) decides is appropriate.
    """

    KNOWN_CURRENT = "KNOWN_CURRENT"
    UNKNOWN_HISTORICAL = "UNKNOWN_HISTORICAL"


@dataclass(frozen=True, slots=True)
class ResolvedSession:
    """Checkpoint 65.33: the resolver's output — a coherent snapshot
    composed ENTIRELY from existing session objects (`trading_session`,
    `cas_session`) plus the two new fields 65.32 identified as missing
    (`regime`, `exit_eligible`) and the historical-eligibility caveat
    (`historical_eligibility`). Deliberately NOT a replacement for
    `TradingSession`/`CasAwareSession` — both are carried here verbatim,
    unchanged, so a caller that only needs the pre-existing contracts
    can use `.trading_session`/`.cas_session` exactly as before.

    `exit_eligible`: THE genuinely new query 65.32 flagged as missing —
    "is this an admissible instant to process an EXISTING POSITION's
    exit for this instrument?" As of this checkpoint the answer is
    DELIBERATELY conservative and permissive: it mirrors current
    platform behavior (existing-position exits are not currently
    CAS-gated anywhere — `position_monitor_runtime.py`/
    `run_emergency_square_off()` submit unconditionally per 65.29's own
    comment) by being `True` whenever the underlying `TradingSession`
    is not fully `CLOSED`/`HOLIDAY`. It is NOT wired into any exit path
    this checkpoint (checkpoint directive: do not touch PaperBroker/
    EOD/position lifecycle) — it exists so a FUTURE checkpoint has a
    single, typed place to make exit admission genuinely CAS-aware
    without another cross-cutting change. It deliberately does NOT
    reference `15:10` — no such boundary is implemented here; a future
    checkpoint choosing to make `exit_eligible` CAS/auction-aware must
    decide that boundary explicitly and separately.
    """

    trading_date: date
    exchange: Exchange
    segment: str
    instrument_category: InstrumentCategory
    regime: Regime
    historical_eligibility: HistoricalEligibility
    trading_session: TradingSession
    cas_session: CasAwareSession
    exit_eligible: bool

    @property
    def is_pre_cas(self) -> bool:
        return self.regime is Regime.PRE_CAS

    @property
    def is_cas_era(self) -> bool:
        return self.regime is Regime.CAS_ERA

    @property
    def historical_eligibility_unknown(self) -> bool:
        return self.historical_eligibility is HistoricalEligibility.UNKNOWN_HISTORICAL


def resolve_market_session(
    *,
    trading_date: date,
    exchange: Exchange,
    segment: str,
    symbol: str,
    as_of: datetime,
    is_historical: bool = False,
) -> ResolvedSession:
    """Checkpoint 65.33: the resolver entry point. Resolves
    `(trading_date, exchange, segment, symbol, as_of)` into a
    `ResolvedSession` by COMPOSING the existing `build_session_for()`
    and `build_cas_aware_session_for()` (both unchanged, imported
    verbatim from `domain.session.calendar`) with `instrument_category_for()`
    (also unchanged) — this function performs NO market-hours
    arithmetic of its own.

    `exchange`/`segment` are accepted and carried through the returned
    `ResolvedSession` for forward-compatibility with future non-NSE/
    non-cash-equity consumers (the architectural requirement's stated
    dependency chain: Market Calendar -> Market Session Resolution ->
    ... -> Backtest/Paper/Live adapters), but are NOT yet used to alter
    computation — `build_session_for()`/`build_cas_aware_session_for()`
    are themselves NSE-cash-equity-only today (unchanged this
    checkpoint); a mismatched `exchange`/`segment` is accepted, not
    validated against, matching this module's "compose, don't
    reimplement" scope.

    `is_historical`: the caller's OWN explicit declaration of whether
    `trading_date` should be treated as a past date needing the
    `HistoricalEligibility.UNKNOWN_HISTORICAL` caveat, or as the current/
    live classification (`HistoricalEligibility.KNOWN_CURRENT`). This
    resolver deliberately does not infer "today" by comparing
    `trading_date` to wall-clock `now()` itself (that would silently
    couple resolution to invocation time); the caller states its own
    intent explicitly.
    Defaults to `False` (current/live) — 65.29's existing entry-gate
    callers, and any live/paper caller resolving "right now," need no
    behavior change; a BACKTEST or historical-analysis caller resolving
    a past date must pass `is_historical=True` explicitly.
    """
    ensure_utc(as_of, field_name="as_of")

    category = instrument_category_for(symbol)
    trading_session = build_session_for(trading_date, as_of)
    cas_session = build_cas_aware_session_for(category, trading_date, as_of)

    regime = Regime.CAS_ERA if trading_date >= CAS_EFFECTIVE_DATE else Regime.PRE_CAS

    historical_eligibility = (
        HistoricalEligibility.UNKNOWN_HISTORICAL if is_historical else HistoricalEligibility.KNOWN_CURRENT
    )

    exit_eligible = trading_session.status not in (SessionStatus.CLOSED, SessionStatus.HOLIDAY)

    return ResolvedSession(
        trading_date=trading_date,
        exchange=exchange,
        segment=segment,
        instrument_category=category,
        regime=regime,
        historical_eligibility=historical_eligibility,
        trading_session=trading_session,
        cas_session=cas_session,
        exit_eligible=exit_eligible,
    )


def resolve_market_session_for_instant(
    *,
    exchange: Exchange,
    segment: str,
    symbol: str,
    as_of: datetime,
    is_historical: bool = False,
) -> ResolvedSession:
    """Convenience wrapper mirroring `session_for_instant()`/
    `cas_aware_session_for_instant()`'s own precedent: derives the
    correct IST calendar date for `as_of` (UTC) and resolves that
    date's `ResolvedSession`."""
    ensure_utc(as_of, field_name="as_of")
    from intraday.domain.session.calendar import INDIA_STANDARD_TIME

    ist_date = as_of.astimezone(INDIA_STANDARD_TIME).date()
    return resolve_market_session(
        trading_date=ist_date,
        exchange=exchange,
        segment=segment,
        symbol=symbol,
        as_of=as_of,
        is_historical=is_historical,
    )
