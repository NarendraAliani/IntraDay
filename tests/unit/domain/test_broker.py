# tests/unit/domain/test_broker.py
#
# Unit tests for the BrokerGateway Protocol and BrokerOrderStatusReport
# (Checkpoint 5). Verifies the contract is structural-only: no network
# access, no broker SDK, no credentials anywhere in this module or its
# tests.
from __future__ import annotations

import inspect
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from intraday.domain.broker.contracts import BrokerGateway, BrokerOrderStatusReport
from intraday.domain.order.contracts import OrderStatus

NOW = datetime(2026, 1, 1, 9, 20, tzinfo=UTC)


def test_order_status_report_rejects_negative_fill_quantity() -> None:
    with pytest.raises(ValueError):
        BrokerOrderStatusReport(
            order_id="ord-1",
            status=OrderStatus.FILLED,
            filled_quantity=Decimal("-1"),
            average_fill_price=Decimal("100"),
            reported_at=NOW,
        )


def test_order_status_report_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError):
        BrokerOrderStatusReport(
            order_id="ord-1",
            status=OrderStatus.PENDING,
            filled_quantity=Decimal("0"),
            average_fill_price=None,
            reported_at=datetime(2026, 1, 1, 9, 20),
        )


def test_broker_gateway_is_structural_only() -> None:
    """Every BrokerGateway method must be a stub (`...` body) — no
    implementation, no network call, no broker SDK import exists in this
    Protocol (Checkpoint 5 Section 18/22)."""
    for name, member in inspect.getmembers(BrokerGateway):
        if name.startswith("_"):
            continue
        if inspect.isfunction(member):
            source = inspect.getsource(member)
            assert "..." in source, f"BrokerGateway.{name} must be a stub, not implemented"
