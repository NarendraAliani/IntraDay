# tests/unit/infrastructure/api/test_paper_reconciliation_runtime.py
#
# Checkpoint 38 Part 13: proves paper-mode reconciliation actually runs
# against the REAL `PaperBroker` + durable Django ledger - not just
# synthetic dicts/tuples (that proof already exists,
# tests/unit/control_plane/reconciliation/test_reconciler.py,
# Checkpoint 34). This is the "build paper-mode reconciliation FIRST"
# proof the checkpoint explicitly asks for.
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from intraday.application.services.paper_trading import PaperTradingService
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.order.contracts import OrderIntent, OrderType, TimeInForce
from intraday.domain.risk.contracts import RiskLimits, TradingHaltStatus
from intraday.domain.shared_kernel.contracts import Exchange, Side
from intraday.infrastructure.api.paper_reconciliation_runtime import reconcile_paper_state
from intraday.infrastructure.brokers.paper.broker import PaperBroker
from intraday.infrastructure.persistence.models import PaperOrderRecord
from intraday.infrastructure.persistence.paper_ledger_repository import (
    DjangoPaperLedgerRepository,
)

pytestmark = pytest.mark.django_db

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
BASE = datetime(2026, 1, 5, 4, 0, tzinfo=UTC)

DEFAULT_LIMITS = RiskLimits(
    max_intraday_loss=Decimal("50000"),
    max_position_size=Decimal("1000"),
    max_per_trade_risk=Decimal("10000"),
)


def _no_cost(is_buy: bool, notional: Decimal) -> Decimal:  # noqa: ARG001
    return Decimal("0")


def _service() -> tuple[PaperTradingService, PaperBroker, DjangoPaperLedgerRepository]:
    broker = PaperBroker(
        initial_capital=Decimal("1000000"), compute_cost=_no_cost, clock=lambda: BASE
    )
    ledger = DjangoPaperLedgerRepository()
    service = PaperTradingService(
        broker=broker,
        risk_limits=DEFAULT_LIMITS,
        risk_configuration_version="v1",
        max_concurrent_positions=5,
        max_total_exposure=Decimal("500000"),
        kill_switch_status_provider=lambda: TradingHaltStatus.ACTIVE,
        clock=lambda: BASE,
        ledger=ledger,
    )
    return service, broker, ledger


def test_freshly_synced_state_reconciles_clean() -> None:
    """After a normal submit_order() call (which auto-syncs the
    ledger, Checkpoint 35), the ledger and broker MUST agree - the
    baseline "everything is fine" case."""
    service, broker, ledger = _service()
    broker.record_price(RELIANCE, Decimal("100"), BASE)
    order = OrderIntent(
        order_id="ord-clean",  # type: ignore[arg-type]
        instrument_id=RELIANCE,
        side=Side.BUY,
        quantity=Decimal("10"),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        strategy_id="manual",  # type: ignore[arg-type]
        created_at=BASE,
        idempotency_key="idem-clean",
    )
    service.submit_order(
        order,
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("1000"),
        already_submitted_idempotency_keys=frozenset(),
    )

    report = reconcile_paper_state(broker=broker, ledger=ledger, now=BASE)

    assert report.is_clean
    assert report.total_divergence_count == 0


def test_ledger_drift_from_broker_is_detected() -> None:
    """Simulates a sync that never happened (e.g. a crash between the
    broker mutation and the ledger write) by directly mutating the
    persisted row out from under the broker's real state - this is
    EXACTLY the class of bug reconciliation exists to catch."""
    service, broker, ledger = _service()
    broker.record_price(RELIANCE, Decimal("100"), BASE)
    order = OrderIntent(
        order_id="ord-drift",  # type: ignore[arg-type]
        instrument_id=RELIANCE,
        side=Side.BUY,
        quantity=Decimal("10"),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        strategy_id="manual",  # type: ignore[arg-type]
        created_at=BASE,
        idempotency_key="idem-drift",
    )
    service.submit_order(
        order,
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("1000"),
        already_submitted_idempotency_keys=frozenset(),
    )
    # The broker reports FILLED (a real market order against a recorded
    # price); corrupt the LOCAL ledger row to a stale status, simulating
    # a missed/failed sync.
    PaperOrderRecord.objects.filter(order_id="ord-drift").update(status="PENDING")

    report = reconcile_paper_state(broker=broker, ledger=ledger, now=BASE)

    assert not report.is_clean
    assert report.total_divergence_count >= 1
    order_divergence = next(d for d in report.order_divergences if d.entity_id == "ord-drift")
    assert order_divergence.local_value == "PENDING"
    assert order_divergence.broker_value == "FILLED"


def test_order_missing_from_ledger_entirely_is_detected() -> None:
    """The broker knows about an order the ledger has no row for at
    all - MISSING_LOCALLY, the other direction of drift."""
    service, broker, ledger = _service()
    broker.record_price(RELIANCE, Decimal("100"), BASE)
    order = OrderIntent(
        order_id="ord-orphan",  # type: ignore[arg-type]
        instrument_id=RELIANCE,
        side=Side.BUY,
        quantity=Decimal("10"),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        strategy_id="manual",  # type: ignore[arg-type]
        created_at=BASE,
        idempotency_key="idem-orphan",
    )
    service.submit_order(
        order,
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("1000"),
        already_submitted_idempotency_keys=frozenset(),
    )
    PaperOrderRecord.objects.filter(order_id="ord-orphan").delete()

    report = reconcile_paper_state(broker=broker, ledger=ledger, now=BASE)

    assert not report.is_clean
    missing = [d for d in report.order_divergences if d.entity_id == "ord-orphan"]
    assert len(missing) == 1


def test_no_persisted_funds_row_never_raises_and_never_fabricates_a_comparison() -> None:
    """Before the very first order, the ledger has no PaperFundsRecord
    row yet - reconciliation must handle "no local funds data exists
    yet" honestly (skip the funds check) rather than crashing or
    inventing a comparison value."""
    _, broker, ledger = _service()

    report = reconcile_paper_state(broker=broker, ledger=ledger, now=BASE)

    assert report.funds_divergences == ()
