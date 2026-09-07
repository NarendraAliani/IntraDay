# File: src/intraday/application/services/daily_coverage_backfill.py
#
# Checkpoint 72: the lightweight, OPERATOR-TRIGGERED routine that keeps
# RELIANCE/TCS/HDFCBANK/INFY's 5m CANONICALIZED `HistoricalBar` coverage
# current as trading days pass, without a manual checkpoint every day.
#
# This module NEVER auto-runs itself - nothing in this codebase calls it
# on a schedule (see CHECKPOINT_72_SUMMARY.md for why Celery Beat, which
# already exists and already runs other tasks on a schedule in this
# codebase, was deliberately NOT used here). The operator runs it
# explicitly, either by hand (`manage.py backfill_daily_coverage`) or via
# a Windows Task Scheduler entry THEY set up themselves, per this
# checkpoint's own "no surprise automation" rule.
#
# Reuses `HistoricalDataPreparationService.prepare()` VERBATIM - the
# exact same DB-coverage-check -> fetch-missing -> upsert path every
# prior real-data checkpoint this session has used (`67.12.2-F`/`Q`,
# `68.4`, `CHECKPOINT_69`, `CHECKPOINT_70`, `CHECKPOINT_71`). No new
# fetch mechanism, no new provider code, no new persistence path - this
# file adds only the "which window should be requested, and how often"
# decision on top of already-proven machinery, plus the idempotency and
# safety properties that machinery already guarantees.
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from intraday.application.services.historical_data_preparation import (
    HistoricalDataPreparationService,
    PreparationOutcome,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.session.calendar import build_session_for, is_trading_day
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe, ensure_utc

DEFAULT_SYMBOLS: tuple[str, ...] = ("RELIANCE", "TCS", "HDFCBANK", "INFY")
"""The exact 4 symbols every real-data walk-forward checkpoint this
session has backfilled and validated since `67.12.2-F`/`Q`. Deliberately
a fixed, small, already-proven symbol set — not "every instrument in
the universe" — matching this checkpoint's own "keep it simple, don't
over-build" instruction. Extending this set to more symbols is a future
decision, not something this routine guesses at."""

DEFAULT_TIMEFRAME = Timeframe.FIVE_MINUTE
"""The only timeframe with a PROVEN `(NSE_EQ, FIVE_MINUTE, CAS_ERA)`
canonicalization scope (`historical_provider.py`'s own
`_PROVEN_INTRADAY_SCOPES`) — this routine deliberately never attempts
any other timeframe."""

DEFAULT_LOOKBACK_DAYS = 7
"""Calendar days back from the most recent closed trading day that this
routine re-checks on every run. Deliberately SMALL and FIXED — not "as
far back as anything is missing". `HistoricalDataCoverageService`'s own
completeness diffing (`CoverageReport.is_complete`) makes re-checking an
already-fully-cached day a ZERO-provider-call no-op, so a generous but
bounded window costs nothing extra on a normal day while guaranteeing
this routine can never accidentally reach back far enough to touch the
pre-existing, UNRELATED `2026-08-17`–`2026-08-28` gap (`CHECKPOINT_71`)
— that gap remains the operator's own deferred migration decision,
untouched BY DESIGN, not by accident.

VALUE CHOSEN DELIBERATELY, NOT ARBITRARILY (Checkpoint 72's own recon):
a 10-day lookback, checked live against today's real data
(`2026-09-07`), was found to land its window's start boundary EXACTLY
on `2026-08-28` — the last day of the old gap block, which this
checkpoint's own read-only coverage check discovered is missing not
just its day-start bar but ALSO its day-end bar (70/72 bars, every one
of the 10 days in that block, uniformly — a more complete
characterization of that pre-existing gap than `CHECKPOINT_71`'s own
recon captured, though still the SAME already-known block, not a new
one). A 10-day lookback would therefore have made this routine's very
first real run silently write 2 new bars into that historical day —
technically still upsert-only/non-destructive (P4-safe), but in clear
tension with this checkpoint's own "extends forward from today, does
not touch historical gaps" instruction. `7` was chosen specifically
because, as of the date this was written, it keeps the window's start
comfortably inside the SECOND real block (`2026-08-31` onward) with
margin to spare, while still covering a full week of normal weekend/
holiday gaps.

KNOWN, DELIBERATE TRADE-OFF: if this routine is not run for longer than
`DEFAULT_LOOKBACK_DAYS` calendar days, the days that fall outside the
window on the next run are NOT silently recovered — they would need a
manual checkpoint, exactly like every other real gap discovered this
session. This routine is a "keep it current" tool, not a full
historical-backfill tool, and does not pretend otherwise."""


def most_recent_closed_trading_day(as_of: datetime) -> date:
    """Walks backward from `as_of`'s own calendar date until it finds a
    trading day whose session has ALREADY closed relative to `as_of` —
    reuses the exact same `is_trading_day`/`build_session_for` calendar
    machinery every checkpoint this session has used to reason about
    "is the market closed right now", never a hardcoded clock-time
    guess of its own. Bounded to 10 calendar days of walk-back: for any
    real NSE calendar this always terminates within a few days (the
    longest realistic non-trading stretch is a long weekend), so hitting
    the bound means something is genuinely wrong and this fails loudly
    rather than looping forever or silently returning a stale date."""
    ensure_utc(as_of, field_name="as_of")
    candidate = as_of.date()
    for _ in range(10):
        if is_trading_day(candidate):
            session = build_session_for(candidate, as_of)
            if as_of > session.market_close:
                return candidate
        candidate -= timedelta(days=1)
    raise RuntimeError(
        f"most_recent_closed_trading_day: no closed trading day found within 10 "
        f"calendar days back from {as_of.isoformat()} — this should never happen "
        "for a real NSE calendar; refusing to guess further back."
    )


@dataclass(frozen=True, slots=True)
class DailyBackfillOutcome:
    """One symbol's `PreparationOutcome` from a single `run_daily_backfill()`
    call, plus the symbol itself (the underlying `PreparationOutcome`
    doesn't carry a human-readable symbol, only an `InstrumentId`)."""

    symbol: str
    window_start: date
    window_end: date
    outcome: PreparationOutcome


def run_daily_backfill(
    *,
    as_of: datetime,
    preparation: HistoricalDataPreparationService,
    symbols: tuple[str, ...] = DEFAULT_SYMBOLS,
    timeframe: Timeframe = DEFAULT_TIMEFRAME,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> tuple[DailyBackfillOutcome, ...]:
    """The routine itself: for each symbol, calls
    `HistoricalDataPreparationService.prepare()` — completely
    unmodified, the same call every prior real-data checkpoint this
    session has made — for the `[most_recent_closed_trading_day -
    lookback_days, most_recent_closed_trading_day]` calendar window.

    IDEMPOTENT BY CONSTRUCTION, not by any new logic here: `prepare()`'s
    own Phase 22 optimization (`CoverageReport.is_complete`) means a day
    already fully cached costs ZERO provider calls on a second run the
    same day (or any later day, as long as it's still inside the
    window), and `HistoricalBarWriteRepository.bulk_upsert()`'s
    upsert-by-identity guarantee means even a bar that WAS re-fetched
    can never duplicate or alter an existing row. This function adds no
    new idempotency or safety mechanism of its own — it inherits both
    entirely from the already-proven pipeline, exactly as this
    checkpoint's own "no new fetch mechanism" rule requires.

    Whole-calendar-day boundaries (`00:00`–`23:59:59` UTC) are passed
    for `start`/`end`, not a specific canonical bar-close pair —
    `HistoricalDataCoverageService._expected_timestamps()` already
    filters down to each trading day's own real expected bar-close set
    internally, so a generous outer boundary is simplest and cannot
    exclude a legitimate expected bar."""
    ensure_utc(as_of, field_name="as_of")
    end_date = most_recent_closed_trading_day(as_of)
    start_date = end_date - timedelta(days=lookback_days)
    start = datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0, tzinfo=UTC)
    end = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=UTC)

    outcomes: list[DailyBackfillOutcome] = []
    for symbol in symbols:
        instrument_id = make_instrument_id(Exchange.NSE, symbol)
        outcome = preparation.prepare(instrument_id, timeframe, start, end)
        outcomes.append(
            DailyBackfillOutcome(
                symbol=symbol, window_start=start_date, window_end=end_date, outcome=outcome
            )
        )
    return tuple(outcomes)


__all__ = [
    "DEFAULT_SYMBOLS",
    "DEFAULT_TIMEFRAME",
    "DEFAULT_LOOKBACK_DAYS",
    "DailyBackfillOutcome",
    "most_recent_closed_trading_day",
    "run_daily_backfill",
]
