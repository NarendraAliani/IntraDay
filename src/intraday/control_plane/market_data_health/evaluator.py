# File: src/intraday/control_plane/market_data_health/evaluator.py
#
# Checkpoint 23: pure classification of market-data health state from
# raw observed facts (last success/failure instants, error state,
# session state, "now"). No I/O, no persistence, no provider knowledge
# - this is the domain-equivalent evaluator this bounded context's
# README promises ("detects stale/missing/anomalous... feeds"),
# deliberately kept as pure as `domain/market_data/quality.py`'s own
# functions even though it lives in `control_plane` (a bounded context,
# not `domain/`) because health classification is specific to this
# platform's OWN operational concerns (freshness threshold, "what counts
# as an error"), not a concept two-or-more bounded contexts share -
# the shared-kernel test from Checkpoint 2/3 does not apply here.
from __future__ import annotations

from datetime import datetime

from intraday.control_plane.market_data_health.contracts import (
    MarketDataHealthSnapshot,
    MarketDataHealthState,
)
from intraday.domain.session.contracts import SessionStatus

# Checkpoint 23 §9: "define explicit freshness thresholds... do not
# invent arbitrary thresholds without documenting the rationale."
#
# This checkpoint's adapter (see infrastructure/market_data_providers/
# dhan/client.py) is EXPLICIT-TRIGGER REST polling, not a continuous
# stream (see docs/architecture/LIVE_MARKET_DATA_ARCHITECTURE.md for the
# full rationale) - "staleness" here therefore does not mean "a
# continuous feed stopped ticking," it means "the last successful
# Refresh is old enough that a human should press Refresh again before
# trusting the displayed price." 120 seconds (2 minutes) is chosen as a
# deliberately generous default for this manual, operator-triggered
# workflow - short enough that a genuinely abandoned/forgotten session
# is flagged, long enough that normal operator pacing (reading a quote,
# thinking, glancing away) never falsely flags CONNECTED_STALE.
FRESHNESS_THRESHOLD_SECONDS = 120.0


def evaluate_health(
    *,
    last_success_at: datetime | None,
    last_failure_at: datetime | None,
    last_error_safe: str,
    consecutive_failures: int,
    session_status: SessionStatus,
    now: datetime,
) -> MarketDataHealthSnapshot:
    """Classifies the current `MarketDataHealthState` from raw observed
    facts. Precedence (most to least specific):

    1. Never attempted a fetch at all (no success AND no failure ever
       recorded) -> DISCONNECTED. Note this is distinct from "attempted
       and failed" - an authentication failure is always classified
       specifically (rule 2), never collapsed into this generic state.
    2. The most recent attempt was a failure whose safe error text
       names an authentication problem -> AUTHENTICATION_FAILED.
    3. The most recent attempt was any other failure -> ERROR.
    4. The market is not open right now -> MARKET_CLOSED (a fresh quote
       from a closed market is still meaningfully different from a
       genuinely live one - the operator should know which they're
       looking at).
    5. Otherwise: fresh vs. stale, purely a function of
       `FRESHNESS_THRESHOLD_SECONDS`.
    """
    freshness_age_seconds = (now - last_success_at).total_seconds() if last_success_at else None

    most_recent_event_is_a_failure = last_failure_at is not None and (
        last_success_at is None or last_failure_at >= last_success_at
    )

    if last_success_at is None and last_failure_at is None:
        # Truly never attempted - nothing to classify as an error yet.
        state = MarketDataHealthState.DISCONNECTED
    elif most_recent_event_is_a_failure:
        state = (
            MarketDataHealthState.AUTHENTICATION_FAILED
            if "auth" in last_error_safe.lower() or "token" in last_error_safe.lower()
            else MarketDataHealthState.ERROR
        )
    elif session_status is not SessionStatus.OPEN:
        state = MarketDataHealthState.MARKET_CLOSED
    elif freshness_age_seconds is not None and freshness_age_seconds > FRESHNESS_THRESHOLD_SECONDS:
        state = MarketDataHealthState.CONNECTED_STALE
    else:
        state = MarketDataHealthState.CONNECTED_FRESH

    return MarketDataHealthSnapshot(
        state=state,
        last_success_at=last_success_at,
        last_failure_at=last_failure_at,
        last_error_safe=last_error_safe,
        freshness_age_seconds=freshness_age_seconds,
        consecutive_failures=consecutive_failures,
        reconnect_count=0,
        subscription_active=False,
    )
