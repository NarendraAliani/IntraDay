# tests/unit/research/test_checkpoint_64_39_execution_fill_audit.py
#
# Checkpoint 64.39 — EXECUTION / FILL CONVERGENCE AUDIT. This checkpoint
# is deliberately AUDIT-AND-DESIGN-ONLY (see
# docs/architecture/CANONICAL_TRADE_LIFECYCLE_AND_PNL_ARCHITECTURE.md's
# "CHECKPOINT 64.39" section for the full narrative). This file adds
# ONLY small, scoped characterization tests that LOCK DOWN existing,
# already-implemented behavior discovered during the audit — it
# introduces NO new Fill/Execution/Order model, NO new production code
# path, and changes NO existing formula.
#
# Each test below cites the exact source line(s) it characterizes so a
# future reader can verify the claim without re-deriving it.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.order.contracts import OrderIntent, OrderStatus, OrderType, TimeInForce
from intraday.domain.shared_kernel.contracts import Exchange, Side
from intraday.infrastructure.brokers.paper.broker import PaperBroker

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
BASE = datetime(2026, 1, 5, 4, 0, tzinfo=UTC)


def _no_cost(is_buy: bool, notional: Decimal) -> Decimal:  # noqa: ARG001
    return Decimal("0")


def _clock_sequence(start: datetime):  # type: ignore[no-untyped-def]
    state = {"t": start}

    def _clock() -> datetime:
        state["t"] += timedelta(seconds=1)
        return state["t"]

    return _clock


def _broker(**overrides: object) -> PaperBroker:
    fields: dict[str, object] = {
        "initial_capital": Decimal("1000000"),
        "compute_cost": _no_cost,
        "clock": _clock_sequence(BASE),
    }
    fields.update(overrides)
    return PaperBroker(**fields)  # type: ignore[arg-type]


def _order(**overrides: object) -> OrderIntent:
    fields: dict[str, object] = {
        "order_id": "ord-1",
        "instrument_id": RELIANCE,
        "side": Side.BUY,
        "quantity": Decimal("10"),
        "order_type": OrderType.MARKET,
        "time_in_force": TimeInForce.DAY,
        "strategy_id": "strat-1",
        "created_at": BASE,
        "idempotency_key": "idem-1",
    }
    fields.update(overrides)
    return OrderIntent(**fields)  # type: ignore[arg-type]


class TestPaperLimitOrderSlippageClampedToLimitBoundary:
    """SUPERSEDED by the Checkpoint 64.40 fix (Finding F2). This test
    originally locked down the pre-64.40 BUG: `_attempt_fill` applied
    slippage to a crossed LIMIT order's `intent.limit_price` with no
    boundary enforcement, so a BUY LIMIT could fill WORSE than its
    stated limit — contradicting the class docstring's "never worse
    [than limit]" claim. As of 64.40, `_maybe_fill_resting_order` passes
    `limit_boundary=intent.limit_price` into `_attempt_fill`, which
    clamps the post-slippage price via `min(slipped_price, limit_price)`
    (BUY) / `max(slipped_price, limit_price)` (SELL) — see
    `test_checkpoint_64_40_execution_correctness.py` for the full F2
    test matrix. This test now asserts the FIXED (boundary-respecting)
    behavior instead of the bug."""

    def test_buy_limit_fill_price_never_worse_than_stated_limit_when_slippage_configured(
        self,
    ) -> None:
        broker = _broker(slippage_percent=Decimal("1"))  # 1% slippage
        order = _order(
            order_type=OrderType.LIMIT,
            limit_price=Decimal("100.00"),
        )
        broker.submit_order(order)
        # Price ticks down to exactly the limit -> order should cross.
        broker.record_price(RELIANCE, Decimal("100.00"), BASE + timedelta(seconds=5))

        report = broker.get_order_status(order.order_id)
        assert report.status is OrderStatus.FILLED
        # Pre-64.40: 100.00 * 1.01 = 101.00 (WORSE than stated limit).
        # Post-64.40 (F2 fix): clamped to the stated limit price itself.
        assert report.average_fill_price == Decimal("100.00")
        assert report.average_fill_price <= Decimal("100.00")


class TestPaperMarketOrderFillsAtLatestObservedPrice:
    """`broker.py::submit_order` (~line 202-211): a MARKET order fills
    immediately against `self._latest_prices.get(order.instrument_id)`
    — the most recent `record_price()` observation — never a price the
    strategy could not yet have known (no look-ahead)."""

    def test_market_order_fills_at_last_recorded_price_not_a_future_price(self) -> None:
        broker = _broker()
        broker.record_price(RELIANCE, Decimal("250.00"), BASE)
        order = _order(order_type=OrderType.MARKET)
        broker.submit_order(order)

        report = broker.get_order_status(order.order_id)
        assert report.status is OrderStatus.FILLED
        assert report.average_fill_price == Decimal("250.00")


class TestPaperMarketOrderWithNoRecordedPriceIsRejectedNeverFabricated:
    """`broker.py::submit_order` (~line 202-210): a MARKET order with no
    prior `record_price()` call for its instrument is REJECTED, never
    filled at a fabricated/zero price."""

    def test_market_order_rejected_when_no_reference_price(self) -> None:
        broker = _broker()
        order = _order(order_type=OrderType.MARKET)
        broker.submit_order(order)

        report = broker.get_order_status(order.order_id)
        assert report.status is OrderStatus.REJECTED
        assert report.filled_quantity == Decimal("0")


class TestPaperPartialFillRatioProducesPartiallyFilledStateAndRemainingQuantity:
    """`broker.py::_attempt_fill` (~line 437-462): when `partial_fill_
    ratio < 1`, `fill_quantity = round(remaining * ratio)` — strictly
    less than the order's full quantity — producing `OrderStatus.
    PARTIALLY_FILLED` and a nonzero remaining quantity on the resting
    order. This is a structural capability of `PaperBroker` that
    `research.backtesting.engine` (single-fill, all-or-nothing
    entry/exit sizing) has no equivalent for. NOTE (see the second test
    in this class): as of Checkpoint 64.40 (Finding F1 fix), a
    partially-filled MARKET order now DOES complete on the next valid
    `record_price()` observation - see that test's docstring."""

    def test_market_order_with_half_partial_fill_ratio_leaves_remaining_quantity(self) -> None:
        broker = _broker(partial_fill_ratio=Decimal("0.5"))
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        order = _order(order_type=OrderType.MARKET, quantity=Decimal("10"))
        broker.submit_order(order)

        report = broker.get_order_status(order.order_id)
        assert report.status is OrderStatus.PARTIALLY_FILLED
        assert report.filled_quantity == Decimal("5")
        assert order.quantity - report.filled_quantity == Decimal("5")

        # SUPERSEDED by the Checkpoint 64.40 fix (Finding F1).
        # `_maybe_fill_resting_order` (broker.py) now has an
        # `OrderType.MARKET` branch: when the order is PARTIALLY_FILLED,
        # the next `record_price()` observation completes the ENTIRE
        # remaining quantity (bypassing `partial_fill_ratio` a second
        # time, which was already applied once at initial submission) -
        # see `test_checkpoint_64_40_execution_correctness.py` for the
        # full F1 multi-fill test matrix.
        broker.record_price(RELIANCE, Decimal("100.00"), BASE + timedelta(seconds=2))
        report2 = broker.get_order_status(order.order_id)
        assert report2.status is OrderStatus.FILLED
        assert report2.filled_quantity == Decimal("10.00")
        assert order.quantity - report2.filled_quantity == Decimal("0.00")


class TestPaperStopLossMarketTriggersAndFillsImmediatelyAtTriggerPrice:
    """`broker.py::_maybe_fill_resting_order` (~line 414-420): a
    STOP_LOSS_MARKET order stays PENDING until `record_price()` crosses
    `trigger_price`, then fills IMMEDIATELY at that observed price (not
    at the trigger price itself, if they differ)."""

    def test_sell_stop_loss_market_fills_at_the_crossing_price(self) -> None:
        broker = _broker()
        broker.record_price(RELIANCE, Decimal("100.00"), BASE)
        order = _order(
            side=Side.SELL,
            order_type=OrderType.STOP_LOSS_MARKET,
            trigger_price=Decimal("95.00"),
        )
        broker.submit_order(order)
        report_before = broker.get_order_status(order.order_id)
        assert report_before.status is OrderStatus.PENDING

        # Price gaps down through the trigger to 93.00 (worse than trigger).
        broker.record_price(RELIANCE, Decimal("93.00"), BASE + timedelta(seconds=3))
        report_after = broker.get_order_status(order.order_id)
        assert report_after.status is OrderStatus.FILLED
        assert report_after.average_fill_price == Decimal("93.00")
