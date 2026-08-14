# tests/unit/application/services/test_live_market_data.py
#
# Checkpoint 23: application-service coverage using in-memory fake
# repositories (mirrors every other application-service test in this
# codebase - no Django, no HTTP, no Dhan involved).
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from intraday.application.repositories.live_market_data import MarketDataHealthRecord
from intraday.application.services.live_market_data import LiveMarketDataService
from intraday.control_plane.market_data_health.contracts import MarketDataHealthState
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Quote
from intraday.domain.shared_kernel.contracts import Exchange


@dataclass
class FakeQuoteRepository:
    saved: list[tuple[Quote, ...]] = field(default_factory=list)
    latest: tuple[Quote, ...] = ()

    def save_all(self, quotes: tuple[Quote, ...], *, fetched_at: datetime) -> None:
        self.saved.append(quotes)
        self.latest = quotes

    def get_latest(self) -> tuple[Quote, ...]:
        return self.latest


@dataclass
class FakeHealthRepository:
    record: MarketDataHealthRecord = field(
        default_factory=lambda: MarketDataHealthRecord(
            last_success_at=None, last_failure_at=None, last_error_safe="", consecutive_failures=0
        )
    )

    def get(self) -> MarketDataHealthRecord:
        return self.record

    def record_success(self, *, checked_at: datetime) -> None:
        self.record = MarketDataHealthRecord(
            last_success_at=checked_at,
            last_failure_at=self.record.last_failure_at,
            last_error_safe="",
            consecutive_failures=0,
        )

    def record_failure(self, *, checked_at: datetime, error_safe: str) -> None:
        self.record = MarketDataHealthRecord(
            last_success_at=self.record.last_success_at,
            last_failure_at=checked_at,
            last_error_safe=error_safe,
            consecutive_failures=self.record.consecutive_failures + 1,
        )


NOW = datetime(2026, 1, 5, 6, 0, tzinfo=UTC)  # inside market hours
RELIANCE_QUOTE = Quote(
    instrument_id=make_instrument_id(Exchange.NSE, "RELIANCE"),
    timestamp=NOW,
    last_price=Decimal("1234"),
)


def _service() -> tuple[LiveMarketDataService, FakeQuoteRepository, FakeHealthRepository]:
    quotes = FakeQuoteRepository()
    health = FakeHealthRepository()
    return LiveMarketDataService(quote_repository=quotes, health_repository=health), quotes, health


def test_record_refresh_success_saves_quotes_and_marks_health_success() -> None:
    service, quotes, health = _service()

    service.record_refresh_success((RELIANCE_QUOTE,), fetched_at=NOW)

    assert quotes.get_latest() == (RELIANCE_QUOTE,)
    assert health.get().last_success_at == NOW
    assert health.get().consecutive_failures == 0


def test_record_refresh_failure_does_not_touch_previously_saved_quotes() -> None:
    service, quotes, health = _service()
    service.record_refresh_success((RELIANCE_QUOTE,), fetched_at=NOW)

    service.record_refresh_failure(checked_at=NOW, error_safe="Could not reach Dhan.")

    assert quotes.get_latest() == (RELIANCE_QUOTE,)  # unchanged
    assert health.get().last_failure_at == NOW
    assert health.get().consecutive_failures == 1


def test_get_quotes_returns_empty_when_never_refreshed() -> None:
    service, _quotes, _health = _service()

    assert service.get_quotes() == ()


def test_get_health_combines_persisted_facts_with_current_session() -> None:
    service, _quotes, health = _service()
    health.record = MarketDataHealthRecord(
        last_success_at=NOW, last_failure_at=None, last_error_safe="", consecutive_failures=0
    )

    snapshot = service.get_health(now=NOW)

    assert snapshot.state is MarketDataHealthState.CONNECTED_FRESH


def test_get_health_reports_market_closed_outside_session_hours() -> None:
    service, _quotes, health = _service()
    outside_hours = datetime(2026, 1, 5, 20, 0, tzinfo=UTC)  # well after market close
    health.record = MarketDataHealthRecord(
        last_success_at=outside_hours,
        last_failure_at=None,
        last_error_safe="",
        consecutive_failures=0,
    )

    snapshot = service.get_health(now=outside_hours)

    assert snapshot.state is MarketDataHealthState.MARKET_CLOSED


def test_get_session_reflects_current_instant() -> None:
    service, _quotes, _health = _service()

    session = service.get_session(now=NOW)

    assert session.session_date == NOW.date()


def test_service_never_imports_signal_generation() -> None:
    """Checkpoint 23 §13 - signals must remain off this checkpoint. Uses
    `ast`-based import scanning (this codebase's established pattern for
    architecture boundary tests, e.g.
    tests/unit/architecture/test_narrow_dependency_exception.py) so a
    mention of "signal_intelligence" in a comment/docstring - like this
    very module's own explanatory comment - can never produce a false
    positive the way a naive text search would."""
    import ast

    import intraday.application.services.live_market_data as module

    source = module.__file__
    assert source is not None
    with open(source, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())

    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    assert not any("signal_intelligence" in name for name in imported_modules)
