# File: src/intraday/infrastructure/api/paper_trading_views.py
#
# Checkpoint 35 Part 4-6: authenticated read-only APIs for paper
# orders/trades/positions/funds, plus the ONE order-submission
# endpoint. Mirrors `settings_views.py`'s established shape - thin
# views translating HTTP <-> `application/services/paper_trading*.py`.
#
# RBAC: reads require `configuration.read` (any authenticated user);
# submitting a paper order requires `configuration.activate`
# (`IsConfigurationOperator`) - the same capability that already gates
# every other high-consequence action in this project (kill switch,
# risk/universe/strategy activation, provider credentials). No new
# capability token introduced.
#
# SAFETY: this endpoint submits a PAPER order only - it calls
# `PaperTradingService.submit_order()`, which itself never reaches a
# real broker (`infrastructure.brokers.paper.PaperBroker` performs no
# network I/O at all - proven by `test_paper_broker_never_performs_network_io`,
# Checkpoint 34). There is no LIVE order endpoint anywhere in this
# codebase.
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from intraday.domain.order.contracts import OrderIntent, OrderType, TimeInForce
from intraday.domain.shared_kernel.contracts import Side
from intraday.infrastructure.api.paper_trading_runtime import (
    expire_end_of_session,
    get_paper_trading_service,
)
from intraday.infrastructure.api.permissions import IsConfigurationOperator
from intraday.infrastructure.persistence.models import (
    PaperFundsRecord,
    PaperOrderRecord,
    PaperPositionRecord,
    PaperTradeRecord,
)


class PaperOrderResponseSerializer(serializers.Serializer[dict[str, object]]):
    order_id = serializers.CharField()
    idempotency_key = serializers.CharField()
    correlation_id = serializers.CharField()
    instrument_id = serializers.CharField()
    strategy_id = serializers.CharField()
    side = serializers.CharField()
    order_type = serializers.CharField()
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4)
    filled_quantity = serializers.DecimalField(max_digits=18, decimal_places=4)
    limit_price = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True)
    trigger_price = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True)
    status = serializers.CharField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    state_history = serializers.ListField(child=serializers.DictField())


class PaperTradeResponseSerializer(serializers.Serializer[dict[str, object]]):
    trade_id = serializers.CharField()
    strategy_id = serializers.CharField()
    instrument_id = serializers.CharField()
    direction = serializers.CharField()
    order_ids = serializers.ListField(child=serializers.CharField())
    entry_price = serializers.DecimalField(max_digits=18, decimal_places=4)
    exit_price = serializers.DecimalField(max_digits=18, decimal_places=4)
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4)
    realized_pnl = serializers.DecimalField(max_digits=18, decimal_places=4)
    opened_at = serializers.DateTimeField()
    closed_at = serializers.DateTimeField()


class PaperPositionResponseSerializer(serializers.Serializer[dict[str, object]]):
    position_id = serializers.CharField()
    instrument_id = serializers.CharField()
    direction = serializers.CharField()
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4)
    average_entry_price = serializers.DecimalField(max_digits=18, decimal_places=4)
    realized_pnl = serializers.DecimalField(max_digits=18, decimal_places=4)
    unrealized_pnl = serializers.DecimalField(max_digits=18, decimal_places=4)
    opened_at = serializers.DateTimeField()
    closed_at = serializers.DateTimeField(allow_null=True)
    status = serializers.CharField()


class PaperFundsResponseSerializer(serializers.Serializer[dict[str, object]]):
    available_balance = serializers.DecimalField(max_digits=18, decimal_places=4)
    utilized_margin = serializers.DecimalField(max_digits=18, decimal_places=4)
    updated_at = serializers.DateTimeField()


class PaperOrderSubmitRequestSerializer(serializers.Serializer[dict[str, object]]):
    instrument_id = serializers.CharField()
    side = serializers.ChoiceField(choices=[side.value for side in Side])
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4)
    order_type = serializers.ChoiceField(choices=[t.value for t in OrderType])
    strategy_id = serializers.CharField()
    limit_price = serializers.DecimalField(
        max_digits=18, decimal_places=4, required=False, allow_null=True
    )
    trigger_price = serializers.DecimalField(
        max_digits=18, decimal_places=4, required=False, allow_null=True
    )


class PaperOrderSubmitResponseSerializer(serializers.Serializer[dict[str, object]]):
    risk_outcome = serializers.ChoiceField(choices=["APPROVED", "REJECTED"])
    risk_reason_code = serializers.CharField(allow_null=True)
    risk_explanation = serializers.CharField()
    order_status = serializers.CharField(allow_null=True)


@extend_schema(responses={200: PaperOrderResponseSerializer(many=True)})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def paper_orders(request: Request) -> Response:
    rows = PaperOrderRecord.objects.order_by("-created_at")[:200]
    return Response(PaperOrderResponseSerializer(rows, many=True).data)  # type: ignore[arg-type]


@extend_schema(responses={200: PaperTradeResponseSerializer(many=True)})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def paper_trades(request: Request) -> Response:
    rows = PaperTradeRecord.objects.order_by("-closed_at")[:200]
    return Response(PaperTradeResponseSerializer(rows, many=True).data)  # type: ignore[arg-type]


@extend_schema(responses={200: PaperPositionResponseSerializer(many=True)})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def paper_positions(request: Request) -> Response:
    rows = PaperPositionRecord.objects.order_by("-opened_at")[:200]
    return Response(PaperPositionResponseSerializer(rows, many=True).data)  # type: ignore[arg-type]


@extend_schema(responses={200: PaperFundsResponseSerializer})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def paper_funds(request: Request) -> Response:
    row, _created = PaperFundsRecord.objects.get_or_create(
        pk=1, defaults={"available_balance": 0, "utilized_margin": 0}
    )
    return Response(PaperFundsResponseSerializer(row).data)  # type: ignore[arg-type]


@extend_schema(
    request=PaperOrderSubmitRequestSerializer,
    responses={
        200: PaperOrderSubmitResponseSerializer,
        400: OpenApiResponse(description="Invalid order parameters"),
    },
)
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsConfigurationOperator])
def paper_order_submit(request: Request) -> Response:
    """Submits ONE PAPER order (never a real broker order - see this
    module's own docstring). Risk-gated by
    `PaperTradingService.submit_order()` - a REJECTED risk decision is
    still an HTTP 200 (the request was handled correctly; the ORDER
    was rejected, which is a normal, expected, fully-informative
    outcome, not a request error)."""
    serializer = PaperOrderSubmitRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    validated = serializer.validated_data

    order_type = OrderType(validated["order_type"])
    limit_price = validated.get("limit_price")
    trigger_price = validated.get("trigger_price")

    try:
        order = OrderIntent(
            order_id=str(uuid.uuid4()),  # type: ignore[arg-type]
            instrument_id=validated["instrument_id"],
            side=Side(validated["side"]),
            quantity=validated["quantity"],
            order_type=order_type,
            time_in_force=TimeInForce.DAY,
            strategy_id=validated["strategy_id"],
            created_at=datetime.now(tz=UTC),
            idempotency_key=str(uuid.uuid4()),
            limit_price=limit_price,
            trigger_price=trigger_price,
        )
    except (ValueError, InvalidOperation) as exc:
        return Response({"detail": str(exc)}, status=400)

    service = get_paper_trading_service()
    broker = service.broker
    already_submitted = set(PaperOrderRecord.objects.values_list("idempotency_key", flat=True))
    result = service.submit_order(
        order,
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=(
            order.quantity * (order.limit_price or _latest_price_or_zero(broker, order))
        ),
        already_submitted_idempotency_keys=frozenset(already_submitted),
    )

    return Response(
        PaperOrderSubmitResponseSerializer(
            {
                "risk_outcome": result.risk_decision.outcome.value,
                "risk_reason_code": (
                    result.risk_decision.reason_code.value
                    if result.risk_decision.reason_code
                    else None
                ),
                "risk_explanation": result.risk_decision.explanation,
                "order_status": (
                    result.broker_report.status.value if result.broker_report else None
                ),
            }
        ).data
    )


class PaperExpireSessionResponseSerializer(serializers.Serializer[dict[str, object]]):
    expired_order_ids = serializers.ListField(child=serializers.CharField())


@extend_schema(request=None, responses={200: PaperExpireSessionResponseSerializer})
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsConfigurationOperator])
def paper_expire_session(request: Request) -> Response:
    """Checkpoint 35 Part 7: manually triggers end-of-session expiry -
    see `expire_end_of_session()`'s own docstring for the honest,
    disclosed limitation that this is not yet invoked automatically by
    a scheduler."""
    expired_order_ids = expire_end_of_session()
    return Response(
        PaperExpireSessionResponseSerializer({"expired_order_ids": list(expired_order_ids)}).data
    )


def _latest_price_or_zero(broker: object, order: OrderIntent) -> Decimal:
    get_latest_price = getattr(broker, "get_latest_price", None)
    if get_latest_price is None:
        return Decimal("0")
    price = get_latest_price(order.instrument_id)
    return price if price is not None else Decimal("0")
