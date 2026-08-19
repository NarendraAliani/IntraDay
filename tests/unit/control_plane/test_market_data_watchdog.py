# tests/unit/control_plane/test_market_data_watchdog.py
#
# Checkpoint 64.1: unit coverage for the continuous-worker watchdog
# evaluator - pure, no I/O, no real worker or socket involved anywhere
# in this file.
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from intraday.control_plane.market_data_watchdog.contracts import (
    MarketDataWatchdogSnapshot,
    MarketDataWatchdogState,
)
from intraday.control_plane.market_data_watchdog.evaluator import (
    STALE_PACKET_AGE,
    evaluate_market_data_watchdog,
)

NOW = datetime(2026, 8, 19, 10, 0, 0, tzinfo=UTC)


def _snapshot(**overrides: object) -> MarketDataWatchdogSnapshot:
    defaults: dict[str, object] = {
        "connection_state": "RUNNING",
        "token_state": "VALID",
        "last_packet_at": NOW - timedelta(seconds=1),
        "last_valid_quote_at": NOW - timedelta(seconds=1),
        "last_bar_at": NOW - timedelta(seconds=30),
        "reconnect_count": 0,
        "consecutive_failures": 0,
    }
    defaults.update(overrides)
    return MarketDataWatchdogSnapshot(**defaults)  # type: ignore[arg-type]


def test_a_fully_flowing_feed_is_healthy() -> None:
    evaluation = evaluate_market_data_watchdog(_snapshot(), now=NOW)
    assert evaluation.state is MarketDataWatchdogState.HEALTHY
    assert evaluation.reasons == ()


def test_an_unusable_token_is_failed_even_while_the_socket_reports_running() -> None:
    """The exact "must never pretend to be connected with an expired
    token" requirement - proven with a RUNNING connection state to show
    token state genuinely outranks it."""
    evaluation = evaluate_market_data_watchdog(
        _snapshot(connection_state="RUNNING", token_state="EXPIRED"), now=NOW
    )
    assert evaluation.state is MarketDataWatchdogState.FAILED
    assert any("token_state_unusable" in reason for reason in evaluation.reasons)


def test_connection_state_failed_is_failed() -> None:
    evaluation = evaluate_market_data_watchdog(_snapshot(connection_state="FAILED"), now=NOW)
    assert evaluation.state is MarketDataWatchdogState.FAILED


def test_reconnecting_connection_state_is_disconnected() -> None:
    evaluation = evaluate_market_data_watchdog(_snapshot(connection_state="RECONNECTING"), now=NOW)
    assert evaluation.state is MarketDataWatchdogState.DISCONNECTED


def test_no_packet_ever_received_is_disconnected_never_healthy() -> None:
    """A worker whose own state machine says RUNNING but has never
    actually received a packet must not be reported healthy - a bare
    process-alive/state-name check would get this wrong."""
    evaluation = evaluate_market_data_watchdog(
        _snapshot(
            connection_state="RUNNING",
            last_packet_at=None,
            last_valid_quote_at=None,
            last_bar_at=None,
        ),
        now=NOW,
    )
    assert evaluation.state is MarketDataWatchdogState.DISCONNECTED


def test_a_packet_older_than_the_stale_threshold_is_stale_not_healthy() -> None:
    """The socket-alive-but-market-data-stopped failure mode - a bare
    process/socket check can never catch this."""
    evaluation = evaluate_market_data_watchdog(
        _snapshot(last_packet_at=NOW - STALE_PACKET_AGE - timedelta(seconds=1)), now=NOW
    )
    assert evaluation.state is MarketDataWatchdogState.STALE
    assert evaluation.last_packet_age_seconds is not None
    assert evaluation.last_packet_age_seconds > STALE_PACKET_AGE.total_seconds()


def test_no_bar_ever_closed_despite_fresh_packets_is_degraded() -> None:
    evaluation = evaluate_market_data_watchdog(_snapshot(last_bar_at=None), now=NOW)
    assert evaluation.state is MarketDataWatchdogState.DEGRADED
    assert "no_bar_ever_closed" in evaluation.reasons


def test_a_stale_bar_despite_fresh_packets_is_degraded() -> None:
    evaluation = evaluate_market_data_watchdog(
        _snapshot(last_bar_at=NOW - timedelta(minutes=10)), now=NOW
    )
    assert evaluation.state is MarketDataWatchdogState.DEGRADED


def test_recent_consecutive_failures_are_surfaced_even_inside_a_healthy_result() -> None:
    evaluation = evaluate_market_data_watchdog(_snapshot(consecutive_failures=3), now=NOW)
    assert evaluation.state is MarketDataWatchdogState.HEALTHY
    assert any("recent_consecutive_failures:3" in reason for reason in evaluation.reasons)


def test_token_unusable_outranks_a_stale_packet_the_most_severe_reason_wins() -> None:
    evaluation = evaluate_market_data_watchdog(
        _snapshot(
            token_state="OPERATOR_ACTION_REQUIRED",
            last_packet_at=NOW - timedelta(minutes=5),
        ),
        now=NOW,
    )
    assert evaluation.state is MarketDataWatchdogState.FAILED
