# tests/unit/infrastructure/api/test_eod_runtime.py
#
# Checkpoint 51 Part 11: coverage for the new EOD lifecycle - success,
# idempotency, and the crash-recovery pattern reused from Checkpoint 48.
from __future__ import annotations

import datetime as dt
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.order.contracts import OrderIntent, OrderType, TimeInForce
from intraday.domain.shared_kernel.contracts import Exchange, Side
from intraday.infrastructure.api.eod_runtime import run_eod_sequence
from intraday.infrastructure.api.paper_trading_runtime import (
    get_paper_trading_service,
    reset_paper_broker_for_testing,
)
from intraday.infrastructure.persistence.eod_run_repository import (
    EOD_IN_PROGRESS_STALENESS_SECONDS,
    DjangoEODRunRepository,
    EODRunStatus,
)
from intraday.infrastructure.persistence.models import EODRun, PaperOrderRecord

pytestmark = pytest.mark.django_db

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
NOW = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _reset():  # type: ignore[no-untyped-def]
    reset_paper_broker_for_testing()
    yield
    reset_paper_broker_for_testing()


def _open_a_position() -> None:
    trading_service = get_paper_trading_service()
    trading_service.broker.record_price(RELIANCE, Decimal("100"), NOW)
    order = OrderIntent(
        order_id="entry-1",  # type: ignore[arg-type]
        instrument_id=RELIANCE,
        side=Side.BUY,
        quantity=Decimal("10"),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        strategy_id="ema_crossover",  # type: ignore[arg-type]
        created_at=NOW,
        idempotency_key="idem-entry-1",
    )
    result = trading_service.submit_order(
        order,
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("1000"),
        already_submitted_idempotency_keys=frozenset(),
    )
    assert result.broker_report is not None


def test_eod_with_no_open_positions_completes_immediately() -> None:
    outcome = run_eod_sequence(current_prices={}, now=NOW)

    assert outcome.already_handled is False
    assert outcome.square_off is not None
    assert outcome.square_off.positions_found == 0
    assert outcome.zero_exposure_confirmed is True
    assert outcome.total_realized_pnl == Decimal("0")

    row = EODRun.objects.get(eod_date=NOW.date())
    assert row.status == EODRunStatus.COMPLETED.value


def test_eod_closes_an_open_position_and_reports_realized_pnl() -> None:
    _open_a_position()

    outcome = run_eod_sequence(current_prices={str(RELIANCE): Decimal("105")}, now=NOW)

    assert outcome.square_off is not None
    assert outcome.square_off.positions_closed == 1
    assert outcome.zero_exposure_confirmed is True
    assert outcome.reconciliation_divergence_count == 0
    assert outcome.total_realized_pnl is not None
    assert outcome.total_realized_pnl > Decimal("0")  # bought at 100, exited at 105

    trading_service = get_paper_trading_service()
    assert trading_service.broker.get_positions()[0].status.value == "CLOSED"
    assert PaperOrderRecord.objects.count() == 2  # entry + EOD exit


def test_eod_is_idempotent_for_the_same_trading_date() -> None:
    _open_a_position()
    first = run_eod_sequence(current_prices={str(RELIANCE): Decimal("105")}, now=NOW)
    assert first.already_handled is False
    assert first.zero_exposure_confirmed is True

    second = run_eod_sequence(current_prices={str(RELIANCE): Decimal("105")}, now=NOW)
    assert second.already_handled is True
    assert second.square_off is None
    assert PaperOrderRecord.objects.count() == 2  # never a duplicate EOD exit


def test_a_crashed_eod_attempt_is_reclaimed_and_finished() -> None:
    """Mirrors test_2_crash_mid_square_off_leaves_row_stuck_in_progress_
    and_is_reclaimed from Checkpoint 48's own crash-recovery suite -
    the exact same lesson, applied to EOD."""
    _open_a_position()
    repository = DjangoEODRunRepository()
    crash_time = NOW
    claim = repository.claim(eod_date=crash_time.date(), now=crash_time)
    assert claim.claimed is True
    # ...process dies here, never calling complete()/fail().

    row = EODRun.objects.get(eod_date=crash_time.date())
    assert row.status == EODRunStatus.IN_PROGRESS.value

    immediate_retry = run_eod_sequence(
        current_prices={str(RELIANCE): Decimal("105")}, now=crash_time
    )
    assert immediate_retry.already_handled is False
    assert immediate_retry.square_off is None  # refused, not run

    after_staleness = crash_time + dt.timedelta(seconds=EOD_IN_PROGRESS_STALENESS_SECONDS + 1)
    recovered = run_eod_sequence(
        current_prices={str(RELIANCE): Decimal("105")}, now=after_staleness
    )
    assert recovered.square_off is not None
    assert recovered.square_off.positions_closed == 1
    assert recovered.zero_exposure_confirmed is True

    row.refresh_from_db()
    assert row.status == EODRunStatus.COMPLETED.value
    assert row.attempt_count == 2
