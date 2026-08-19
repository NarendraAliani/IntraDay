# tests/unit/infrastructure/market_data_providers/dhan/test_worker_health_tracker.py
#
# Checkpoint 64.3: THE safety-critical proof the review explicitly
# demanded - a bar must never be promotable (`is_healthy()` must be
# `False`) unless the worker is GENUINELY healthy, never just
# "currently running." Uses the real, existing watchdog evaluator
# (Checkpoint 64.1) - never a second one.
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from intraday.control_plane.market_data_watchdog.evaluator import STALE_PACKET_AGE
from intraday.infrastructure.market_data_providers.dhan.worker_health_tracker import (
    WorkerHealthTracker,
)
from intraday.infrastructure.market_data_providers.dhan.worker_state import WorkerState

NOW = datetime(2026, 8, 20, 10, 0, 0, tzinfo=UTC)


def _healthy_tracker() -> WorkerHealthTracker:
    tracker = WorkerHealthTracker()
    tracker.mark_token_state("VALID")
    tracker.mark_connected(subscribed_instrument_count=4)
    tracker.record_packet(now=NOW - timedelta(seconds=1))
    tracker.record_bar(now=NOW - timedelta(seconds=30))
    return tracker


def test_a_genuinely_healthy_worker_can_promote() -> None:
    tracker = _healthy_tracker()
    assert tracker.is_healthy(now=NOW) is True


def test_a_degraded_worker_cannot_promote() -> None:
    """Packets flowing, but no bar has closed recently enough -
    DEGRADED, not HEALTHY."""
    tracker = _healthy_tracker()
    tracker.record_bar(now=NOW - timedelta(minutes=30))
    assert tracker.is_healthy(now=NOW) is False


def test_a_reconnecting_worker_cannot_promote() -> None:
    tracker = _healthy_tracker()
    tracker.mark_reconnecting(reason="connection_lost")
    assert tracker.is_healthy(now=NOW) is False


def test_a_stale_feed_cannot_promote() -> None:
    """The socket-alive-but-market-data-stopped case - a bare
    RUNNING state must not be trusted on its own."""
    tracker = _healthy_tracker()
    tracker.record_packet(now=NOW - STALE_PACKET_AGE - timedelta(seconds=5))
    assert tracker.is_healthy(now=NOW) is False


def test_an_expired_token_cannot_promote_even_while_running() -> None:
    tracker = _healthy_tracker()
    tracker.mark_token_state("EXPIRED")
    assert tracker.is_healthy(now=NOW) is False


def test_a_failed_worker_cannot_promote() -> None:
    tracker = _healthy_tracker()
    tracker.mark_failed(WorkerState.FAILED, reason="reconnect_attempts_exhausted")
    assert tracker.is_healthy(now=NOW) is False


def test_a_worker_that_never_connected_cannot_promote() -> None:
    tracker = WorkerHealthTracker()  # default STOPPED, no token, no packets
    assert tracker.is_healthy(now=NOW) is False


def test_reconnecting_then_reconnected_recovers_to_healthy() -> None:
    """Proves the tracker's own state is genuinely mutable, not stuck -
    a real reconnect recovery must be reflected, not permanently
    poisoned by an earlier failure."""
    tracker = _healthy_tracker()
    tracker.mark_reconnecting(reason="connection_lost")
    assert tracker.is_healthy(now=NOW) is False

    tracker.mark_connected(subscribed_instrument_count=4)
    tracker.record_packet(now=NOW)
    tracker.record_bar(now=NOW - timedelta(seconds=10))
    assert tracker.is_healthy(now=NOW) is True
