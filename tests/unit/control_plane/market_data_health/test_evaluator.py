# tests/unit/control_plane/market_data_health/test_evaluator.py
#
# Checkpoint 23: coverage for the pure market-data health classifier -
# every state in Checkpoint 23 §9's explicit list, and the documented
# precedence order between them.
from __future__ import annotations

from datetime import UTC, datetime

from intraday.control_plane.market_data_health.contracts import MarketDataHealthState
from intraday.control_plane.market_data_health.evaluator import (
    FRESHNESS_THRESHOLD_SECONDS,
    evaluate_health,
)
from intraday.domain.session.contracts import SessionStatus

NOW = datetime(2026, 1, 5, 6, 0, tzinfo=UTC)  # 11:30 IST - inside market hours


def test_never_succeeded_is_disconnected() -> None:
    snapshot = evaluate_health(
        last_success_at=None,
        last_failure_at=None,
        last_error_safe="",
        consecutive_failures=0,
        session_status=SessionStatus.OPEN,
        now=NOW,
    )

    assert snapshot.state is MarketDataHealthState.DISCONNECTED
    assert snapshot.freshness_age_seconds is None


def test_most_recent_attempt_failure_with_auth_wording_is_authentication_failed() -> None:
    snapshot = evaluate_health(
        last_success_at=datetime(2026, 1, 5, 5, 0, tzinfo=UTC),
        last_failure_at=datetime(2026, 1, 5, 5, 30, tzinfo=UTC),
        last_error_safe="Dhan rejected the configured Client ID/Access Token.",
        consecutive_failures=1,
        session_status=SessionStatus.OPEN,
        now=NOW,
    )

    assert snapshot.state is MarketDataHealthState.AUTHENTICATION_FAILED


def test_most_recent_attempt_failure_without_auth_wording_is_error() -> None:
    snapshot = evaluate_health(
        last_success_at=datetime(2026, 1, 5, 5, 0, tzinfo=UTC),
        last_failure_at=datetime(2026, 1, 5, 5, 30, tzinfo=UTC),
        last_error_safe="Could not reach Dhan.",
        consecutive_failures=1,
        session_status=SessionStatus.OPEN,
        now=NOW,
    )

    assert snapshot.state is MarketDataHealthState.ERROR


def test_success_but_market_closed_is_market_closed_not_fresh() -> None:
    snapshot = evaluate_health(
        last_success_at=datetime(2026, 1, 5, 5, 59, tzinfo=UTC),
        last_failure_at=None,
        last_error_safe="",
        consecutive_failures=0,
        session_status=SessionStatus.CLOSED,
        now=NOW,
    )

    assert snapshot.state is MarketDataHealthState.MARKET_CLOSED


def test_recent_success_during_market_hours_is_connected_fresh() -> None:
    snapshot = evaluate_health(
        last_success_at=NOW,
        last_failure_at=None,
        last_error_safe="",
        consecutive_failures=0,
        session_status=SessionStatus.OPEN,
        now=NOW,
    )

    assert snapshot.state is MarketDataHealthState.CONNECTED_FRESH
    assert snapshot.freshness_age_seconds == 0.0


def test_old_success_during_market_hours_is_connected_stale() -> None:
    from datetime import timedelta

    old_success = NOW - timedelta(seconds=FRESHNESS_THRESHOLD_SECONDS + 1)

    snapshot = evaluate_health(
        last_success_at=old_success,
        last_failure_at=None,
        last_error_safe="",
        consecutive_failures=0,
        session_status=SessionStatus.OPEN,
        now=NOW,
    )

    assert snapshot.state is MarketDataHealthState.CONNECTED_STALE
    assert snapshot.freshness_age_seconds == FRESHNESS_THRESHOLD_SECONDS + 1


def test_success_after_a_prior_failure_clears_the_error_state() -> None:
    """A later success must not be shadowed by an earlier failure -
    precedence is "most recent attempt," not "any failure ever"."""
    snapshot = evaluate_health(
        last_success_at=NOW,
        last_failure_at=datetime(2026, 1, 5, 4, 0, tzinfo=UTC),  # before the success
        last_error_safe="Could not reach Dhan.",
        consecutive_failures=0,
        session_status=SessionStatus.OPEN,
        now=NOW,
    )

    assert snapshot.state is MarketDataHealthState.CONNECTED_FRESH


def test_reconnect_count_and_subscription_active_are_always_zero_false_for_rest_polling() -> None:
    """This checkpoint's adapter has no reconnect/subscription concept
    (REST polling, not WebSocket) - these fields must never be fabricated
    as though it did."""
    snapshot = evaluate_health(
        last_success_at=NOW,
        last_failure_at=None,
        last_error_safe="",
        consecutive_failures=0,
        session_status=SessionStatus.OPEN,
        now=NOW,
    )

    assert snapshot.reconnect_count == 0
    assert snapshot.subscription_active is False
