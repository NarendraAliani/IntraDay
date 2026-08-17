# File: src/intraday/infrastructure/api/signal_views.py
#
# Checkpoint 62.x: the FIRST read-only API for real, persisted
# strategy signals (`SignalRecord`, `infrastructure/persistence/
# signal_repository.py`) - closes a gap a fresh audit this checkpoint
# found: no signal-listing endpoint existed anywhere in this project,
# which would have forced an "active signal monitor" UI to either
# fabricate rows or go unbuilt. Mirrors `paper_trading_views.py`'s own
# established shape (thin view, translates HTTP <-> repository).
#
# RBAC: read-only, requires `configuration.read` (any authenticated
# user) - matches every other read-only market/signal endpoint in this
# project. No order-placement code path exists in this module.
from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from intraday.infrastructure.persistence.models import SignalRecord
from intraday.infrastructure.persistence.signal_repository import DjangoSignalRepository


class SignalResponseSerializer(serializers.Serializer[dict[str, object]]):
    signal_id = serializers.CharField()
    strategy_id = serializers.CharField()
    instrument_id = serializers.CharField()
    direction = serializers.CharField()
    price = serializers.DecimalField(max_digits=18, decimal_places=4)
    timeframe = serializers.CharField()
    signal_timestamp = serializers.DateTimeField()
    risk_status = serializers.CharField()
    risk_reason = serializers.CharField(allow_blank=True)
    order_status = serializers.CharField(allow_blank=True)
    created_at = serializers.DateTimeField()


class SignalListResponseSerializer(serializers.Serializer[dict[str, object]]):
    items = SignalResponseSerializer(many=True)
    total_count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()


def _record_to_response_data(record: SignalRecord) -> dict[str, object]:
    return {
        "signal_id": record.signal_id,
        "strategy_id": record.strategy_id,
        "instrument_id": record.instrument_id,
        "direction": record.direction,
        "price": record.price,
        "timeframe": record.timeframe,
        "signal_timestamp": record.signal_timestamp,
        "risk_status": record.risk_status,
        "risk_reason": record.risk_reason,
        "order_status": record.order_status,
        "created_at": record.created_at,
    }


@extend_schema(responses={200: SignalListResponseSerializer})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_signals(request: Request) -> Response:
    """Read-only, server-side paginated list of REAL, persisted
    strategy signals - never a fabricated row. Query params:
    `page` (default 1), `page_size` (default 25, max 200),
    `strategy_id`, `instrument_id`, `timeframe`, `direction`
    (all optional filters - the Active Signal Monitor UI's controls
    bind directly to these, never a frontend-only filter over an
    unbounded fetch)."""
    try:
        page = int(request.query_params.get("page", "1"))
    except ValueError:
        page = 1
    try:
        page_size = int(request.query_params.get("page_size", "25"))
    except ValueError:
        page_size = 25

    result = DjangoSignalRepository().list_signals(
        page=page,
        page_size=page_size,
        strategy_id=request.query_params.get("strategy_id") or None,
        instrument_id=request.query_params.get("instrument_id") or None,
        timeframe=request.query_params.get("timeframe") or None,
        direction=request.query_params.get("direction") or None,
    )

    data = SignalListResponseSerializer(
        {
            "items": [_record_to_response_data(record) for record in result.items],
            "total_count": result.total_count,
            "page": result.page,
            "page_size": result.page_size,
        }
    ).data
    return Response(data)
