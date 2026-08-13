# tests/unit/domain/test_session.py
#
# Unit tests for the TradingSession contract (Checkpoint 5).
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from intraday.domain.session.contracts import SessionStatus, TradingSession
from intraday.domain.shared_kernel.contracts import Exchange

OPEN = datetime(2026, 1, 1, 3, 45, tzinfo=UTC)  # 09:15 IST
CLOSE = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)  # 15:30 IST


def test_valid_session_constructs() -> None:
    session = TradingSession(
        session_date=date(2026, 1, 1),
        exchange=Exchange.NSE,
        market_open=OPEN,
        market_close=CLOSE,
        square_off_deadline=CLOSE,
        status=SessionStatus.OPEN,
    )
    assert session.status is SessionStatus.OPEN


def test_market_close_must_be_after_market_open() -> None:
    with pytest.raises(ValueError):
        TradingSession(
            session_date=date(2026, 1, 1),
            exchange=Exchange.NSE,
            market_open=CLOSE,
            market_close=OPEN,
            square_off_deadline=OPEN,
            status=SessionStatus.CLOSED,
        )


def test_square_off_deadline_must_fall_within_session() -> None:
    after_close = datetime(2026, 1, 1, 11, 0, tzinfo=UTC)
    with pytest.raises(ValueError):
        TradingSession(
            session_date=date(2026, 1, 1),
            exchange=Exchange.NSE,
            market_open=OPEN,
            market_close=CLOSE,
            square_off_deadline=after_close,
            status=SessionStatus.OPEN,
        )


def _session() -> TradingSession:
    return TradingSession(
        session_date=date(2026, 1, 1),
        exchange=Exchange.NSE,
        market_open=OPEN,
        market_close=CLOSE,
        square_off_deadline=CLOSE,
        status=SessionStatus.OPEN,
    )


def test_contains_true_for_timestamp_inside_session() -> None:
    mid_session = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)  # 11:30 IST
    assert _session().contains(mid_session) is True


def test_contains_true_at_market_open_boundary() -> None:
    assert _session().contains(OPEN) is True


def test_contains_true_at_market_close_boundary() -> None:
    assert _session().contains(CLOSE) is True


def test_contains_false_before_market_open() -> None:
    before_open = datetime(2026, 1, 1, 3, 0, tzinfo=UTC)  # 08:30 IST
    assert _session().contains(before_open) is False


def test_contains_false_after_market_close() -> None:
    after_close = datetime(2026, 1, 1, 11, 0, tzinfo=UTC)  # 16:30 IST
    assert _session().contains(after_close) is False


def test_contains_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError):
        _session().contains(datetime(2026, 1, 1, 6, 0))
