# tests/unit/application/services/test_paper_trading.py
#
# Checkpoint 34 Part 8/18: proves the orchestration order (kill switch
# -> risk -> broker) end-to-end against a real PaperBroker instance.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from intraday.application.services.paper_trading import PaperTradingService
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.order.contracts import OrderIntent, OrderStatus, OrderType, TimeInForce
from intraday.domain.risk.contracts import RiskDecisionOutcome, RiskLimits, TradingHaltStatus
from intraday.domain.shared_kernel.contracts import Exchange, Side
from intraday.infrastructure.brokers.paper.broker import PaperBroker
from intraday.trading_engine.risk_engine.contracts import RiskRejectionReason

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
BASE = datetime(2026, 1, 5, 4, 0, tzinfo=UTC)

DEFAULT_LIMITS = RiskLimits(
    max_intraday_loss=Decimal("5000"),
    max_position_size=Decimal("100"),
    max_per_trade_risk=Decimal("1000"),
)


def _no_cost(is_buy: bool, notional: Decimal) -> Decimal:  # noqa: ARG001
    return Decimal("0")


def _clock_sequence(start: datetime):  # type: ignore[no-untyped-def]
    state = {"t": start}

    def _clock() -> datetime:
        state["t"] += timedelta(seconds=1)
        return state["t"]

    return _clock


def _order(**overrides: object) -> OrderIntent:
    fields: dict[str, object] = {
        "order_id": "ord-1",
        "instrument_id": RELIANCE,
        "side": Side.BUY,
        "quantity": Decimal("10"),
        "order_type": OrderType.MARKET,
        "time_in_force": TimeInForce.DAY,
        "strategy_id": "orb-v1",
        "created_at": BASE,
        "idempotency_key": "idem-1",
    }
    fields.update(overrides)
    return OrderIntent(**fields)  # type: ignore[arg-type]


def _service(
    *, kill_switch_status: TradingHaltStatus = TradingHaltStatus.ACTIVE
) -> tuple[PaperTradingService, PaperBroker]:
    broker = PaperBroker(
        initial_capital=Decimal("100000"), compute_cost=_no_cost, clock=_clock_sequence(BASE)
    )
    service = PaperTradingService(
        broker=broker,
        risk_limits=DEFAULT_LIMITS,
        risk_configuration_version="v1",
        max_concurrent_positions=5,
        max_total_exposure=Decimal("50000"),
        kill_switch_status_provider=lambda: kill_switch_status,
        clock=_clock_sequence(BASE),
    )
    return service, broker


def test_approved_order_reaches_the_broker() -> None:
    service, broker = _service()
    broker.record_price(RELIANCE, Decimal("100"), BASE)
    result = service.submit_order(
        _order(),
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("1000"),
        already_submitted_idempotency_keys=frozenset(),
    )
    assert result.risk_decision.outcome is RiskDecisionOutcome.APPROVED
    assert result.broker_report is not None
    assert result.broker_report.status is OrderStatus.FILLED


def test_kill_switch_engaged_never_reaches_the_broker() -> None:
    service, broker = _service(kill_switch_status=TradingHaltStatus.HALTED)
    broker.record_price(RELIANCE, Decimal("100"), BASE)
    result = service.submit_order(
        _order(),
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("1000"),
        already_submitted_idempotency_keys=frozenset(),
    )
    assert result.risk_decision.outcome is RiskDecisionOutcome.REJECTED
    assert result.risk_decision.reason_code is RiskRejectionReason.KILL_SWITCH_ENGAGED
    assert result.broker_report is None
    assert broker.get_orders() == ()  # never touched the broker


def test_inactive_strategy_never_reaches_the_broker() -> None:
    service, broker = _service()
    broker.record_price(RELIANCE, Decimal("100"), BASE)
    result = service.submit_order(
        _order(),
        strategy_is_active=False,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("1000"),
        already_submitted_idempotency_keys=frozenset(),
    )
    assert result.risk_decision.outcome is RiskDecisionOutcome.REJECTED
    assert result.broker_report is None
    assert broker.get_orders() == ()


def test_max_position_size_rejection_never_reaches_the_broker() -> None:
    service, broker = _service()
    broker.record_price(RELIANCE, Decimal("100"), BASE)
    result = service.submit_order(
        _order(quantity=Decimal("150")),  # exceeds max_position_size=100
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("15000"),
        already_submitted_idempotency_keys=frozenset(),
    )
    assert result.risk_decision.outcome is RiskDecisionOutcome.REJECTED
    assert result.risk_decision.reason_code is RiskRejectionReason.MAX_POSITION_SIZE_EXCEEDED
    assert broker.get_orders() == ()


def test_risk_context_reflects_real_broker_state() -> None:
    """The service reads current exposure/positions from the REAL
    broker, not a stale/fabricated snapshot - proven by submitting a
    first order, then verifying a second order's risk context sees the
    resulting exposure."""
    service, broker = _service()
    broker.record_price(RELIANCE, Decimal("100"), BASE)
    service.submit_order(
        _order(order_id="ord-1", idempotency_key="idem-1", quantity=Decimal("60")),
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("6000"),
        already_submitted_idempotency_keys=frozenset(),
    )
    # a second order on the SAME instrument would exceed max_position_size (100)
    result = service.submit_order(
        _order(order_id="ord-2", idempotency_key="idem-2", quantity=Decimal("50")),
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("5000"),
        already_submitted_idempotency_keys=frozenset({"idem-1"}),
    )
    assert result.risk_decision.outcome is RiskDecisionOutcome.REJECTED
    assert result.risk_decision.reason_code is RiskRejectionReason.MAX_POSITION_SIZE_EXCEEDED


# --- Checkpoint 35 Part 9: instrument-level duplicate-order protection ------


def test_pending_order_on_same_instrument_blocks_a_second_order() -> None:
    """A resting LIMIT order (still PENDING, not terminal) on an
    instrument blocks a second, DIFFERENTLY-KEYED order on the SAME
    instrument - proves `instruments_with_pending_or_open_orders` is
    now correctly populated from `BrokerOrderStatusReport.instrument_id`
    (Checkpoint 34's acknowledged gap, closed this checkpoint)."""
    service, broker = _service()
    broker.record_price(RELIANCE, Decimal("105"), BASE)
    first = service.submit_order(
        _order(
            order_id="ord-1",
            idempotency_key="idem-1",
            order_type=OrderType.LIMIT,
            limit_price=Decimal("100"),
        ),
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("1000"),
        already_submitted_idempotency_keys=frozenset(),
    )
    assert first.broker_report is not None
    assert first.broker_report.status is OrderStatus.PENDING

    result = service.submit_order(
        _order(order_id="ord-2", idempotency_key="idem-2", quantity=Decimal("5")),
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("500"),
        already_submitted_idempotency_keys=frozenset({"idem-1"}),
    )
    assert result.risk_decision.outcome is RiskDecisionOutcome.REJECTED
    assert result.risk_decision.reason_code is RiskRejectionReason.DUPLICATE_ORDER
    # different idempotency key did NOT bypass the instrument-level check
    assert broker.get_orders()[-1].order_id == "ord-1"


def test_pending_order_does_not_block_a_different_instrument() -> None:
    service, broker = _service()
    tcs = make_instrument_id(Exchange.NSE, "TCS")
    broker.record_price(RELIANCE, Decimal("105"), BASE)
    broker.record_price(tcs, Decimal("50"), BASE)
    service.submit_order(
        _order(
            order_id="ord-1",
            idempotency_key="idem-1",
            order_type=OrderType.LIMIT,
            limit_price=Decimal("100"),
        ),
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("1000"),
        already_submitted_idempotency_keys=frozenset(),
    )
    result = service.submit_order(
        _order(
            order_id="ord-2", idempotency_key="idem-2", instrument_id=tcs, quantity=Decimal("5")
        ),
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("250"),
        already_submitted_idempotency_keys=frozenset({"idem-1"}),
    )
    assert result.risk_decision.outcome is RiskDecisionOutcome.APPROVED


def test_filled_order_no_longer_blocks_the_instrument() -> None:
    """A terminal order (FILLED) must NOT count as "pending or open" -
    proven via `domain.order.state_machine.is_terminal`, the single
    source of truth this service reuses rather than a second,
    hand-maintained status list."""
    service, broker = _service()
    broker.record_price(RELIANCE, Decimal("100"), BASE)
    first = service.submit_order(
        _order(order_id="ord-1", idempotency_key="idem-1", quantity=Decimal("5")),
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("500"),
        already_submitted_idempotency_keys=frozenset(),
    )
    assert first.broker_report is not None
    assert first.broker_report.status is OrderStatus.FILLED

    result = service.submit_order(
        _order(order_id="ord-2", idempotency_key="idem-2", quantity=Decimal("5")),
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("500"),
        already_submitted_idempotency_keys=frozenset({"idem-1"}),
    )
    assert result.risk_decision.outcome is RiskDecisionOutcome.APPROVED


def test_cancelled_order_no_longer_blocks_the_instrument() -> None:
    service, broker = _service()
    broker.record_price(RELIANCE, Decimal("105"), BASE)
    service.submit_order(
        _order(
            order_id="ord-1",
            idempotency_key="idem-1",
            order_type=OrderType.LIMIT,
            limit_price=Decimal("100"),
        ),
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("1000"),
        already_submitted_idempotency_keys=frozenset(),
    )
    broker.cancel_order("ord-1")

    result = service.submit_order(
        _order(order_id="ord-2", idempotency_key="idem-2", quantity=Decimal("5")),
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("500"),
        already_submitted_idempotency_keys=frozenset({"idem-1"}),
    )
    assert result.risk_decision.outcome is RiskDecisionOutcome.APPROVED
