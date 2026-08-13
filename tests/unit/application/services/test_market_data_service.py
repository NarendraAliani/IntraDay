# tests/unit/application/services/test_market_data_service.py
#
# Unit tests for HistoricalMarketDataService (Checkpoint 14) using an
# in-memory FAKE repository - no Django, no database, no network. Proves
# the application layer is testable in isolation from any concrete
# market-data provider, mirroring RiskConfigurationService's own tests
# (Checkpoint 8).
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.application.services.market_data import HistoricalMarketDataService
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.quality import (
    DuplicateBarTimestampError,
    OutOfOrderBarError,
    expected_bar_timestamps,
)
from intraday.domain.session.contracts import SessionStatus, TradingSession
from intraday.domain.shared_kernel.contracts import Exchange, InstrumentId, Timeframe

INSTRUMENT = make_instrument_id(Exchange.NSE, "FIXTURE01")
OPEN = datetime(2026, 1, 1, 3, 45, tzinfo=UTC)  # 09:15 IST
CLOSE = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)  # 15:30 IST


def _bar(timestamp: datetime) -> Bar:
    return Bar(
        instrument_id=INSTRUMENT,
        timeframe=Timeframe.FIVE_MINUTE,
        timestamp=timestamp,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.5"),
        volume=Decimal("1000"),
    )


class FakeHistoricalMarketDataRepository:
    """In-memory stand-in implementing the same shape as
    `HistoricalMarketDataRepository` (a Protocol - structural typing is
    the point, no explicit inheritance needed)."""

    def __init__(self, bars: tuple[Bar, ...]) -> None:
        self._bars = bars

    def get_bars(
        self, instrument_id: InstrumentId, timeframe: Timeframe, start: datetime, end: datetime
    ) -> tuple[Bar, ...]:
        return tuple(
            bar
            for bar in self._bars
            if bar.instrument_id == instrument_id
            and bar.timeframe == timeframe
            and start <= bar.timestamp <= end
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


def test_get_bars_returns_ordered_bars_from_the_repository() -> None:
    bars = (_bar(OPEN + timedelta(minutes=5)), _bar(OPEN + timedelta(minutes=10)))
    service = HistoricalMarketDataService(repository=FakeHistoricalMarketDataRepository(bars))

    result = service.get_bars(INSTRUMENT, Timeframe.FIVE_MINUTE, OPEN, CLOSE)

    assert result == bars


def test_get_bars_raises_on_duplicate_timestamps_never_silently_drops() -> None:
    duplicate_ts = OPEN + timedelta(minutes=5)
    bars = (_bar(duplicate_ts), _bar(duplicate_ts))
    service = HistoricalMarketDataService(repository=FakeHistoricalMarketDataRepository(bars))

    with pytest.raises(DuplicateBarTimestampError):
        service.get_bars(INSTRUMENT, Timeframe.FIVE_MINUTE, OPEN, CLOSE)


def test_get_bars_raises_on_out_of_order_repository_data() -> None:
    bars = (_bar(OPEN + timedelta(minutes=10)), _bar(OPEN + timedelta(minutes=5)))
    service = HistoricalMarketDataService(repository=FakeHistoricalMarketDataRepository(bars))

    with pytest.raises(OutOfOrderBarError):
        service.get_bars(INSTRUMENT, Timeframe.FIVE_MINUTE, OPEN, CLOSE)


def test_get_bars_output_is_deterministic() -> None:
    bars = (_bar(OPEN + timedelta(minutes=5)), _bar(OPEN + timedelta(minutes=10)))
    service = HistoricalMarketDataService(repository=FakeHistoricalMarketDataRepository(bars))

    first = service.get_bars(INSTRUMENT, Timeframe.FIVE_MINUTE, OPEN, CLOSE)
    second = service.get_bars(INSTRUMENT, Timeframe.FIVE_MINUTE, OPEN, CLOSE)

    assert first == second


def test_completeness_reports_no_gaps_for_a_full_session_series() -> None:
    session = _session()
    full = tuple(_bar(ts) for ts in expected_bar_timestamps(session, Timeframe.FIVE_MINUTE))
    service = HistoricalMarketDataService(repository=FakeHistoricalMarketDataRepository(full))

    assert service.completeness(INSTRUMENT, Timeframe.FIVE_MINUTE, session) == ()


def test_completeness_reports_gaps_for_a_partial_series() -> None:
    session = _session()
    partial = (_bar(OPEN + timedelta(minutes=5)),)
    service = HistoricalMarketDataService(repository=FakeHistoricalMarketDataRepository(partial))

    missing = service.completeness(INSTRUMENT, Timeframe.FIVE_MINUTE, session)

    assert len(missing) > 0


def test_service_has_no_infrastructure_import() -> None:
    """Static proof, not just behavioral: the service module itself never
    imports Django/infrastructure - it only ever sees the Protocol."""
    import ast
    import inspect

    import intraday.application.services.market_data as module

    source = inspect.getsource(module)
    tree = ast.parse(source)
    imported_roots = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "django" not in imported_roots
    assert "intraday.infrastructure" not in imported_roots
