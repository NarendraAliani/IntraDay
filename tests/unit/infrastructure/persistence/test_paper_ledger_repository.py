# tests/unit/infrastructure/persistence/test_paper_ledger_repository.py
#
# Checkpoint 35 Part 3/18: proves the durable ledger - persistence,
# reload, restart recovery, duplicate-event idempotency.
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from intraday.application.services.paper_trading import PaperTradingService
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.order.contracts import OrderIntent, OrderStatus, OrderType, TimeInForce
from intraday.domain.risk.contracts import RiskLimits, TradingHaltStatus
from intraday.domain.shared_kernel.contracts import Exchange, Side
from intraday.infrastructure.brokers.paper.broker import PaperBroker
from intraday.infrastructure.persistence.models import (
    PaperFundsRecord,
    PaperOrderRecord,
    PaperPositionRecord,
)
from intraday.infrastructure.persistence.paper_ledger_repository import (
    DjangoPaperLedgerRepository,
)
from tests.postgres_utils import requires_postgres

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
NOW = datetime(2026, 1, 5, 4, 0, tzinfo=UTC)


def _no_cost(is_buy: bool, notional: Decimal) -> Decimal:  # noqa: ARG001
    return Decimal("0")


def _order(**overrides: object) -> OrderIntent:
    fields: dict[str, object] = {
        "order_id": "ord-1",
        "instrument_id": RELIANCE,
        "side": Side.BUY,
        "quantity": Decimal("10"),
        "order_type": OrderType.MARKET,
        "time_in_force": TimeInForce.DAY,
        "strategy_id": "orb-v1",
        "created_at": NOW,
        "idempotency_key": "idem-1",
    }
    fields.update(overrides)
    return OrderIntent(**fields)  # type: ignore[arg-type]


def _service(ledger: DjangoPaperLedgerRepository) -> tuple[PaperTradingService, PaperBroker]:
    broker = PaperBroker(
        initial_capital=Decimal("100000"), compute_cost=_no_cost, clock=lambda: NOW
    )
    service = PaperTradingService(
        broker=broker,
        risk_limits=RiskLimits(
            max_intraday_loss=Decimal("5000"),
            max_position_size=Decimal("100"),
            max_per_trade_risk=Decimal("1000"),
        ),
        risk_configuration_version="v1",
        max_concurrent_positions=5,
        max_total_exposure=Decimal("50000"),
        kill_switch_status_provider=lambda: TradingHaltStatus.ACTIVE,
        clock=lambda: NOW,
        ledger=ledger,
    )
    return service, broker


@requires_postgres
@pytest.mark.django_db
def test_approved_order_is_persisted() -> None:
    ledger = DjangoPaperLedgerRepository()
    service, broker = _service(ledger)
    broker.record_price(RELIANCE, Decimal("100"), NOW)
    service.submit_order(
        _order(),
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("1000"),
        already_submitted_idempotency_keys=frozenset(),
    )
    row = PaperOrderRecord.objects.get(order_id="ord-1")
    assert row.status == OrderStatus.FILLED.value
    assert row.instrument_id == str(RELIANCE)
    assert len(row.state_history) > 0


@requires_postgres
@pytest.mark.django_db
def test_position_and_funds_are_persisted() -> None:
    ledger = DjangoPaperLedgerRepository()
    service, broker = _service(ledger)
    broker.record_price(RELIANCE, Decimal("100"), NOW)
    service.submit_order(
        _order(),
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("1000"),
        already_submitted_idempotency_keys=frozenset(),
    )
    positions = list(PaperPositionRecord.objects.all())
    assert len(positions) == 1
    assert positions[0].quantity == Decimal("10")

    funds = PaperFundsRecord.objects.get(pk=1)
    assert funds.available_balance == Decimal("99000")


@requires_postgres
@pytest.mark.django_db
def test_restart_recovery_reads_from_the_durable_ledger_not_broker_memory() -> None:
    """Simulates a process restart: a brand-new `DjangoPaperLedgerRepository`
    instance (no shared Python state with the one that wrote the data)
    can still read back the persisted order status."""
    ledger = DjangoPaperLedgerRepository()
    service, broker = _service(ledger)
    broker.record_price(RELIANCE, Decimal("100"), NOW)
    order = _order()
    service.submit_order(
        order,
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("1000"),
        already_submitted_idempotency_keys=frozenset(),
    )

    # A fresh repository instance - simulates a new process/request with
    # no in-memory PaperBroker state at all.
    fresh_repository = DjangoPaperLedgerRepository()
    statuses = fresh_repository.load_order_status_by_id()
    assert statuses[order.order_id] == OrderStatus.FILLED.value


@requires_postgres
@pytest.mark.django_db
def test_duplicate_sync_is_idempotent() -> None:
    """Calling sync_snapshot twice with the same broker state produces
    exactly one row per entity, not duplicates."""
    ledger = DjangoPaperLedgerRepository()
    service, broker = _service(ledger)
    broker.record_price(RELIANCE, Decimal("100"), NOW)
    order = _order()
    service.submit_order(
        order,
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("1000"),
        already_submitted_idempotency_keys=frozenset(),
    )
    # Manually re-sync the identical current broker state a second time.
    ledger.sync_snapshot(
        order=order,
        report=broker.get_order_status(order.order_id),
        correlation_id="idem-1",
        events=broker.get_order_events(order.order_id),
        trades=broker.get_trades(),
        positions=broker.get_positions(),
        funds=broker.get_funds(),
    )
    assert PaperOrderRecord.objects.filter(order_id="ord-1").count() == 1
    assert PaperPositionRecord.objects.count() == 1


@requires_postgres
@pytest.mark.django_db
def test_ledger_is_optional_and_never_required() -> None:
    """A `PaperTradingService` with no injected ledger works identically
    to before (Checkpoint 34) - persistence is additive, never a hard
    dependency of order submission."""
    broker = PaperBroker(
        initial_capital=Decimal("100000"), compute_cost=_no_cost, clock=lambda: NOW
    )
    service = PaperTradingService(
        broker=broker,
        risk_limits=RiskLimits(
            max_intraday_loss=Decimal("5000"),
            max_position_size=Decimal("100"),
            max_per_trade_risk=Decimal("1000"),
        ),
        risk_configuration_version="v1",
        max_concurrent_positions=5,
        max_total_exposure=Decimal("50000"),
        kill_switch_status_provider=lambda: TradingHaltStatus.ACTIVE,
        clock=lambda: NOW,
        # no ledger injected
    )
    broker.record_price(RELIANCE, Decimal("100"), NOW)
    result = service.submit_order(
        _order(),
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("1000"),
        already_submitted_idempotency_keys=frozenset(),
    )
    assert result.broker_report is not None
    assert PaperOrderRecord.objects.count() == 0
