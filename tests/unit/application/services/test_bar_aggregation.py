# tests/unit/application/services/test_bar_aggregation.py
#
# Checkpoint 24A: application-service coverage using in-memory fake
# repositories - no Django, no HTTP, no Dhan involved.
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from intraday.application.services.bar_aggregation import BarAggregationService
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.aggregation import AggregatedBar
from intraday.domain.market_data.contracts import Quote
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
BASE = datetime(2026, 1, 5, 6, 0, 0, tzinfo=UTC)


@dataclass
class FakeQuoteRepository:
    observations: tuple[Quote, ...] = ()

    def save_all(self, quotes: tuple[Quote, ...], *, fetched_at: datetime) -> None:
        raise NotImplementedError("not exercised by bar aggregation")

    def get_latest(self) -> tuple[Quote, ...]:
        raise NotImplementedError("not exercised by bar aggregation")

    def get_observations(self, *, since: datetime) -> tuple[Quote, ...]:
        return tuple(q for q in self.observations if q.timestamp >= since)


@dataclass
class FakeBarRepository:
    saved_calls: list[tuple[AggregatedBar, ...]] = field(default_factory=list)
    rows: dict[tuple, AggregatedBar] = field(default_factory=dict)

    def save_all(self, bars: tuple[AggregatedBar, ...]) -> None:
        self.saved_calls.append(bars)
        for bar in bars:
            key = (bar.instrument_id, bar.timeframe, bar.interval_start)
            self.rows[key] = bar

    def get_recent(self, *, timeframe: Timeframe, limit: int = 200) -> tuple[AggregatedBar, ...]:
        matching = [b for b in self.rows.values() if b.timeframe is timeframe]
        matching.sort(key=lambda b: b.interval_start, reverse=True)
        return tuple(matching[:limit])


def _quote(offset_seconds: int, price: str) -> Quote:
    return Quote(
        instrument_id=RELIANCE,
        timestamp=BASE + timedelta(seconds=offset_seconds),
        last_price=Decimal(price),
    )


def test_aggregate_and_persist_saves_bars_and_returns_full_result() -> None:
    quote_repo = FakeQuoteRepository(observations=(_quote(0, "100.00"), _quote(70, "102.00")))
    bar_repo = FakeBarRepository()
    service = BarAggregationService(quote_repository=quote_repo, bar_repository=bar_repo)

    result = service.aggregate_and_persist(as_of=BASE + timedelta(seconds=80))

    assert len(result.bars) == 2
    assert len(bar_repo.saved_calls) == 1
    assert len(bar_repo.saved_calls[0]) == 2


def test_aggregate_and_persist_uses_default_1_minute_timeframe() -> None:
    quote_repo = FakeQuoteRepository(observations=(_quote(0, "100.00"),))
    bar_repo = FakeBarRepository()
    service = BarAggregationService(quote_repository=quote_repo, bar_repository=bar_repo)

    result = service.aggregate_and_persist(as_of=BASE + timedelta(seconds=10))

    assert result.bars[0].timeframe is Timeframe.ONE_MINUTE


def test_get_recent_bars_never_calls_the_quote_repository() -> None:
    """Checkpoint 24A §11: reading recent bars must never trigger
    aggregation (or any read of the quote log) itself."""

    class ExplodingQuoteRepository:
        def save_all(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("must not be called")

        def get_latest(self) -> tuple[Quote, ...]:
            raise AssertionError("must not be called")

        def get_observations(self, *args: object, **kwargs: object) -> tuple[Quote, ...]:
            raise AssertionError("must not be called")

    bar_repo = FakeBarRepository()
    service = BarAggregationService(
        quote_repository=ExplodingQuoteRepository(),  # type: ignore[arg-type]
        bar_repository=bar_repo,
    )

    result = service.get_recent_bars()

    assert result == ()


def test_no_broker_or_infrastructure_import_anywhere_in_this_module() -> None:
    import ast

    import intraday.application.services.bar_aggregation as module

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

    assert not any(name.startswith("intraday.infrastructure") for name in imported_modules)
    assert not any("signal_intelligence" in name for name in imported_modules)
    assert not any("trading_engine" in name for name in imported_modules)
