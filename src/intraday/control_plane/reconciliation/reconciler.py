# File: src/intraday/control_plane/reconciliation/reconciler.py
#
# Checkpoint 34 Part 13: the broker-neutral reconciliation service.
# Pure functions - detect and classify only, never mutate anything
# (Part 13's explicit "no automatic corrective action"). Takes
# "local" (this project's own persisted ledger, read via the
# application layer) and "broker" (whatever `BrokerGateway.get_orders()`
# /`get_trades()`/`get_positions()`/`get_funds()` reports) as plain,
# already-fetched collections - this module performs no I/O itself,
# exactly like `domain/market_data/aggregation.py`'s own pure-function
# discipline. `PaperBroker` is the concrete broker source this
# checkpoint (Part 13's own "for this checkpoint, PaperBroker is the
# concrete implementation... later Dhan integration will reuse the
# exact reconciliation contract" - unchanged when a real adapter
# exists, since this module only depends on the domain-neutral
# `BrokerOrderStatusReport`/`Trade`/`Position`/`Funds` shapes, never on
# `PaperBroker` itself).
from __future__ import annotations

from datetime import datetime

from intraday.control_plane.reconciliation.contracts import (
    Divergence,
    DivergenceType,
    ReconciliationReport,
)
from intraday.domain.broker.contracts import BrokerOrderStatusReport, Funds
from intraday.domain.order.contracts import OrderStatus
from intraday.domain.position.contracts import Position
from intraday.domain.shared_kernel.contracts import OrderId, TradeId
from intraday.domain.trade.contracts import Trade

_FUNDS_TOLERANCE = "0.01"  # matches this project's established 2dp rounding boundary


def reconcile_orders(
    *,
    local: dict[OrderId, OrderStatus],
    broker: tuple[BrokerOrderStatusReport, ...],
    now: datetime,
) -> tuple[Divergence, ...]:
    """`local` maps order_id -> the status this project's own ledger
    believes is current. `broker` is every order the broker currently
    reports."""
    divergences: list[Divergence] = []
    broker_by_id = {report.order_id: report for report in broker}

    for order_id, local_status in local.items():
        broker_report = broker_by_id.get(order_id)
        if broker_report is None:
            divergences.append(
                Divergence(
                    divergence_type=DivergenceType.MISSING_AT_BROKER,
                    entity_type="order",
                    entity_id=str(order_id),
                    local_value=local_status.value,
                    broker_value=None,
                    detected_at=now,
                    explanation=f"Order {order_id} exists locally but the broker has no record.",
                )
            )
            continue
        if broker_report.status is not local_status:
            divergences.append(
                Divergence(
                    divergence_type=DivergenceType.STATUS_MISMATCH,
                    entity_type="order",
                    entity_id=str(order_id),
                    local_value=local_status.value,
                    broker_value=broker_report.status.value,
                    detected_at=now,
                    explanation=(
                        f"Local status {local_status.value} does not match broker "
                        f"status {broker_report.status.value}."
                    ),
                )
            )

    for order_id, broker_report in broker_by_id.items():
        if order_id not in local:
            divergences.append(
                Divergence(
                    divergence_type=DivergenceType.MISSING_LOCALLY,
                    entity_type="order",
                    entity_id=str(order_id),
                    local_value=None,
                    broker_value=broker_report.status.value,
                    detected_at=now,
                    explanation=f"Broker reports order {order_id} but no local record exists.",
                )
            )

    return tuple(divergences)


def reconcile_trades(
    *, local: dict[TradeId, Trade], broker: tuple[Trade, ...], now: datetime
) -> tuple[Divergence, ...]:
    divergences: list[Divergence] = []
    broker_by_id = {trade.trade_id: trade for trade in broker}

    for trade_id, local_trade in local.items():
        broker_trade = broker_by_id.get(trade_id)
        if broker_trade is None:
            divergences.append(
                Divergence(
                    divergence_type=DivergenceType.MISSING_AT_BROKER,
                    entity_type="trade",
                    entity_id=str(trade_id),
                    local_value=str(local_trade.quantity),
                    broker_value=None,
                    detected_at=now,
                    explanation=f"Trade {trade_id} exists locally but not at the broker.",
                )
            )
            continue
        if local_trade.quantity != broker_trade.quantity:
            divergences.append(
                Divergence(
                    divergence_type=DivergenceType.QUANTITY_MISMATCH,
                    entity_type="trade",
                    entity_id=str(trade_id),
                    local_value=str(local_trade.quantity),
                    broker_value=str(broker_trade.quantity),
                    detected_at=now,
                    explanation="Local and broker-reported trade quantity differ.",
                )
            )
        if local_trade.exit_price != broker_trade.exit_price:
            divergences.append(
                Divergence(
                    divergence_type=DivergenceType.PRICE_MISMATCH,
                    entity_type="trade",
                    entity_id=str(trade_id),
                    local_value=str(local_trade.exit_price),
                    broker_value=str(broker_trade.exit_price),
                    detected_at=now,
                    explanation="Local and broker-reported exit price differ.",
                )
            )

    for trade_id in broker_by_id:
        if trade_id not in local:
            divergences.append(
                Divergence(
                    divergence_type=DivergenceType.MISSING_LOCALLY,
                    entity_type="trade",
                    entity_id=str(trade_id),
                    local_value=None,
                    broker_value=str(broker_by_id[trade_id].quantity),
                    detected_at=now,
                    explanation=f"Broker reports trade {trade_id} but no local record exists.",
                )
            )

    return tuple(divergences)


def reconcile_positions(
    *, local: dict[str, Position], broker: tuple[Position, ...], now: datetime
) -> tuple[Divergence, ...]:
    divergences: list[Divergence] = []
    broker_by_instrument = {str(position.instrument_id): position for position in broker}

    for instrument_id, local_position in local.items():
        broker_position = broker_by_instrument.get(instrument_id)
        if broker_position is None:
            divergences.append(
                Divergence(
                    divergence_type=DivergenceType.MISSING_AT_BROKER,
                    entity_type="position",
                    entity_id=instrument_id,
                    local_value=str(local_position.quantity),
                    broker_value=None,
                    detected_at=now,
                    explanation=f"Local position in {instrument_id} has no broker-side match.",
                )
            )
            continue
        if local_position.quantity != broker_position.quantity:
            divergences.append(
                Divergence(
                    divergence_type=DivergenceType.POSITION_MISMATCH,
                    entity_type="position",
                    entity_id=instrument_id,
                    local_value=str(local_position.quantity),
                    broker_value=str(broker_position.quantity),
                    detected_at=now,
                    explanation="Local and broker-reported position quantity differ.",
                )
            )

    for instrument_id in broker_by_instrument:
        if instrument_id not in local:
            divergences.append(
                Divergence(
                    divergence_type=DivergenceType.MISSING_LOCALLY,
                    entity_type="position",
                    entity_id=instrument_id,
                    local_value=None,
                    broker_value=str(broker_by_instrument[instrument_id].quantity),
                    detected_at=now,
                    explanation=f"Broker reports {instrument_id} but no local record exists.",
                )
            )

    return tuple(divergences)


def reconcile_funds(*, local: Funds, broker: Funds, now: datetime) -> tuple[Divergence, ...]:
    if abs(local.available_balance - broker.available_balance) <= 0:
        return ()
    return (
        Divergence(
            divergence_type=DivergenceType.FUNDS_MISMATCH,
            entity_type="funds",
            entity_id="available_balance",
            local_value=str(local.available_balance),
            broker_value=str(broker.available_balance),
            detected_at=now,
            explanation="Local and broker-reported available balance differ.",
        ),
    )


def build_reconciliation_report(
    *,
    order_divergences: tuple[Divergence, ...],
    trade_divergences: tuple[Divergence, ...],
    position_divergences: tuple[Divergence, ...],
    funds_divergences: tuple[Divergence, ...],
    now: datetime,
) -> ReconciliationReport:
    return ReconciliationReport(
        generated_at=now,
        order_divergences=order_divergences,
        trade_divergences=trade_divergences,
        position_divergences=position_divergences,
        funds_divergences=funds_divergences,
    )
