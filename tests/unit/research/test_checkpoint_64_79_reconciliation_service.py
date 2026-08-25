# File: tests/unit/research/test_checkpoint_64_79_reconciliation_service.py
#
# Checkpoint 64.79: proof tests for `MarketDataReconciliationService` -
# the application-layer orchestration around the domain contract.
#
# Deterministic and offline: fake repositories only, no Django, no
# database, no Dhan. The service is tested for the three properties
# that actually matter operationally:
#   1. it reads the OBSERVED side from the archive repository and the
#      REFERENCE side from a genuinely separate repository;
#   2. FORMING bars never participate (a provisional close compared
#      against a finalised candle is a manufactured mismatch);
#   3. a symbol with no reference data is REPORTED as NOT_RECONCILED,
#      never silently omitted.
from __future__ import annotations

import datetime as dt
from datetime import date
from decimal import Decimal

from intraday.application.services.market_data_reconciliation import (
    MarketDataReconciliationService,
)
from intraday.domain.market_data.aggregation import AggregatedBar, BarStatus
from intraday.domain.market_data.quality import expected_bar_timestamps
from intraday.domain.market_data.reconciliation import (
    ReconciliationOutcome,
    ReferenceBar,
)
from intraday.domain.session.calendar import build_session_for
from intraday.domain.shared_kernel.contracts import Exchange, InstrumentId, Timeframe

TRADING_DAY = date(2026, 8, 25)
AFTER_CLOSE = dt.datetime(2026, 8, 25, 12, 0, tzinfo=dt.UTC)
SESSION = build_session_for(TRADING_DAY, AFTER_CLOSE)
STAMPS = expected_bar_timestamps(SESSION, Timeframe.FIVE_MINUTE)


def _aggregated(stamp: dt.datetime, status: BarStatus = BarStatus.CLOSED) -> AggregatedBar:
    return AggregatedBar(
        instrument_id=InstrumentId("NSE:TCS"),
        timeframe=Timeframe.FIVE_MINUTE,
        interval_start=stamp - dt.timedelta(minutes=5),
        interval_end=stamp,
        open=Decimal("100.00"),
        high=Decimal("101.00"),
        low=Decimal("99.00"),
        close=Decimal("100.00"),
        status=status,
        observation_count=5,
        data_source="dhan",
        volume=Decimal("0"),
    )


def _reference(stamp: dt.datetime) -> ReferenceBar:
    return ReferenceBar(
        timestamp=stamp,
        open=Decimal("100.00"),
        high=Decimal("101.00"),
        low=Decimal("99.00"),
        close=Decimal("100.00"),
        volume=Decimal("1000"),
    )


class FakeArchiveRepository:
    """Only the two methods the reconciliation service actually uses -
    deliberately narrow, so this fake cannot accidentally also serve the
    reference side."""

    def __init__(self, bars, symbols=("TCS",)) -> None:
        self._bars = tuple(bars)
        self._symbols = tuple(symbols)

    def list_bars(self, *, exchange, trading_date, instrument_symbol, timeframe):
        return self._bars

    def archived_symbols_for_trading_date(self, *, exchange, trading_date):
        return self._symbols


class FakeReferenceRepository:
    def __init__(self, bars, source="dhan_historical_candle_api") -> None:
        self._bars = tuple(bars)
        self._source = source
        self.calls: list[tuple] = []

    def reference_bars_for(self, *, exchange, trading_date, instrument_symbol, timeframe):
        self.calls.append((trading_date, instrument_symbol, timeframe))
        return self._bars

    def describe_source(self) -> str:
        return self._source


def _service(archive_bars, reference_bars):
    return MarketDataReconciliationService(
        FakeArchiveRepository(archive_bars),  # type: ignore[arg-type]
        FakeReferenceRepository(reference_bars),  # type: ignore[arg-type]
        exchange=Exchange.NSE,
    )


def test_full_day_agreement_passes_through_the_service() -> None:
    service = _service([_aggregated(s) for s in STAMPS], [_reference(s) for s in STAMPS])
    report = service.reconcile_cell(
        trading_date=TRADING_DAY,
        instrument_symbol="TCS",
        timeframe=Timeframe.FIVE_MINUTE,
        as_of=AFTER_CLOSE,
    )
    assert report.outcome is ReconciliationOutcome.PASS
    assert report.evidence_source == "dhan_historical_candle_api"


def test_forming_bars_are_excluded_from_reconciliation() -> None:
    """A FORMING bar's close is provisional; including it would compare
    an unfinished interval against a finalised candle."""
    bars = [_aggregated(s) for s in STAMPS[:-1]]
    bars.append(_aggregated(STAMPS[-1], status=BarStatus.FORMING))
    report = _service(bars, [_reference(s) for s in STAMPS]).reconcile_cell(
        trading_date=TRADING_DAY,
        instrument_symbol="TCS",
        timeframe=Timeframe.FIVE_MINUTE,
        as_of=AFTER_CLOSE,
    )
    assert report.observed_bar_count == len(STAMPS) - 1
    assert report.outcome is ReconciliationOutcome.PARTIAL


def test_symbol_without_reference_data_is_reported_not_omitted() -> None:
    """The exact situation 64.79 found in the real database: archived
    live cells with no overlapping reference bars. It must surface as
    NOT_RECONCILED, not vanish."""
    reports = _service([_aggregated(s) for s in STAMPS], []).reconcile_trading_date(
        trading_date=TRADING_DAY, timeframe=Timeframe.FIVE_MINUTE, as_of=AFTER_CLOSE
    )
    assert len(reports) == 1
    assert reports[0].outcome is ReconciliationOutcome.NOT_RECONCILED
    assert reports[0].reason == "no_reference_bars_available"


def test_summarise_returns_worst_outcome_and_never_pass_when_empty() -> None:
    assert MarketDataReconciliationService.summarise(()) is ReconciliationOutcome.NOT_RECONCILED
    service = _service([_aggregated(s) for s in STAMPS], [_reference(s) for s in STAMPS])
    passing = service.reconcile_trading_date(
        trading_date=TRADING_DAY, timeframe=Timeframe.FIVE_MINUTE, as_of=AFTER_CLOSE
    )
    assert MarketDataReconciliationService.summarise(passing) is ReconciliationOutcome.PASS

    mixed = passing + _service([], []).reconcile_trading_date(
        trading_date=TRADING_DAY, timeframe=Timeframe.FIVE_MINUTE, as_of=AFTER_CLOSE
    )
    assert MarketDataReconciliationService.summarise(mixed) is ReconciliationOutcome.NOT_RECONCILED


def test_reference_repository_is_queried_for_the_requested_cell() -> None:
    reference = FakeReferenceRepository([_reference(s) for s in STAMPS])
    service = MarketDataReconciliationService(
        FakeArchiveRepository([_aggregated(s) for s in STAMPS]),  # type: ignore[arg-type]
        reference,  # type: ignore[arg-type]
    )
    service.reconcile_cell(
        trading_date=TRADING_DAY,
        instrument_symbol="TCS",
        timeframe=Timeframe.FIVE_MINUTE,
        as_of=AFTER_CLOSE,
    )
    assert reference.calls == [(TRADING_DAY, "TCS", Timeframe.FIVE_MINUTE)]
