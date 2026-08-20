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
# Checkpoint 64.9: the Signal Operations Center needs the FULL chain
# (TradePlan + communication status), not just the bare signal - the
# response now includes both, sourced from the SAME repository's
# already-enriched `EnrichedSignal` (no second query layer, no
# duplicated join logic). A new detail endpoint exposes the full
# communication attempt history for one signal (never fetched for the
# whole list - the list view only needs "current status").
#
# RBAC: read-only, requires `configuration.read` (any authenticated
# user) - matches every other read-only market/signal endpoint in this
# project. No order-placement code path exists in this module.
from __future__ import annotations

import datetime as dt

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from intraday.infrastructure.persistence.models import CommunicationLedgerRecord
from intraday.infrastructure.persistence.signal_repository import (
    ChannelStatus,
    DjangoSignalRepository,
    EnrichedSignal,
    SignalEvidenceEnrichment,
)


class TradePlanFieldSerializer(serializers.Serializer[dict[str, object]]):
    entry_price = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True)
    stop_loss = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True)
    target_1 = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True)
    target_2 = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True)
    target_3 = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True)
    trailing_stop_loss = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True)
    calculation_method = serializers.CharField(allow_blank=True)


class ChannelStatusSerializer(serializers.Serializer[dict[str, object]]):
    status = serializers.CharField()
    attempted_at = serializers.DateTimeField(allow_null=True)
    delivered_at = serializers.DateTimeField(allow_null=True)
    retry_count = serializers.IntegerField()
    error_message = serializers.CharField(allow_blank=True)


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
    # Checkpoint 64.9: `None` (never a fabricated value) when the
    # evaluating strategy produced no TradePlan - the UI shows
    # "Not provided" for exactly this case.
    trade_plan = TradePlanFieldSerializer(allow_null=True)
    telegram = ChannelStatusSerializer(allow_null=True)
    discord = ChannelStatusSerializer(allow_null=True)
    # Checkpoint 64.18: `None` (never a fabricated value) when no
    # evidence was persisted for this signal (a strategy with no
    # registered describer, or a signal predating this checkpoint).
    # A plain `DictField`, not a nested Serializer class - a Serializer
    # attribute literally named `fields` collides with DRF's own
    # `Serializer.fields` (a `BindingDict` property) at the mypy/
    # djangorestframework-stubs level (the same class of issue
    # `ReadinessCheckSerializer` already documented for `label`,
    # Checkpoint 64.14) - the wire shape stays exactly
    # `{"schema_version": ..., "fields": [{"label": ..., "value": ...}]}`.
    evidence = serializers.DictField(allow_null=True)


class SignalListResponseSerializer(serializers.Serializer[dict[str, object]]):
    items = SignalResponseSerializer(many=True)
    total_count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()


class CommunicationAttemptSerializer(serializers.Serializer[dict[str, object]]):
    communication_id = serializers.CharField()
    channel = serializers.CharField()
    provider = serializers.CharField()
    delivery_status = serializers.CharField()
    attempted_at = serializers.DateTimeField(allow_null=True)
    retry_count = serializers.IntegerField()
    error_message = serializers.CharField(allow_blank=True)
    created_at = serializers.DateTimeField()


class SignalCommunicationHistoryResponseSerializer(serializers.Serializer[dict[str, object]]):
    signal_id = serializers.CharField()
    attempts = CommunicationAttemptSerializer(many=True)


def _channel_status_data(status: ChannelStatus | None) -> dict[str, object] | None:
    if status is None:
        return None
    return {
        "status": status.status,
        "attempted_at": status.attempted_at,
        "delivered_at": status.delivered_at,
        "retry_count": status.retry_count,
        "error_message": status.error_message,
    }


def _enriched_to_response_data(enriched: EnrichedSignal) -> dict[str, object]:
    record = enriched.record
    plan = enriched.trade_plan
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
        "trade_plan": (
            {
                "entry_price": plan.entry_price,
                "stop_loss": plan.stop_loss,
                "target_1": plan.target_1,
                "target_2": plan.target_2,
                "target_3": plan.target_3,
                "trailing_stop_loss": plan.trailing_stop_loss,
                "calculation_method": plan.calculation_method,
            }
            if plan is not None
            else None
        ),
        "telegram": _channel_status_data(enriched.telegram),
        "discord": _channel_status_data(enriched.discord),
        "evidence": _evidence_data(enriched.evidence),
    }


def _evidence_data(evidence: SignalEvidenceEnrichment | None) -> dict[str, object] | None:
    if evidence is None:
        return None
    return {
        "schema_version": evidence.schema_version,
        "fields": [{"label": label, "value": value} for label, value in evidence.fields],
    }


def _parse_datetime(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed


@extend_schema(
    responses={200: SignalListResponseSerializer},
    parameters=[
        OpenApiParameter("risk_status", str, required=False),
        OpenApiParameter("order_status", str, required=False),
        OpenApiParameter("date_from", str, required=False),
        OpenApiParameter("date_to", str, required=False),
        OpenApiParameter("telegram_status", str, required=False),
        OpenApiParameter("discord_status", str, required=False),
        OpenApiParameter("sort", str, required=False),
    ],
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_signals(request: Request) -> Response:
    """Read-only, server-side paginated list of REAL, persisted
    strategy signals - never a fabricated row. Every filter/sort maps
    to a real query parameter `DjangoSignalRepository.list_signals()`
    actually applies - never a frontend-only filter over an unbounded
    fetch. Each item is enriched with its real TradePlan (`None` when
    the strategy produced none) and current Telegram/Discord delivery
    status (`None` when no attempt exists yet)."""
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
        risk_status=request.query_params.get("risk_status") or None,
        order_status=request.query_params.get("order_status") or None,
        date_from=_parse_datetime(request.query_params.get("date_from")),
        date_to=_parse_datetime(request.query_params.get("date_to")),
        telegram_status=request.query_params.get("telegram_status") or None,
        discord_status=request.query_params.get("discord_status") or None,
        sort=request.query_params.get("sort", "newest"),
    )

    data = SignalListResponseSerializer(
        {
            "items": [_enriched_to_response_data(item) for item in result.items],
            "total_count": result.total_count,
            "page": result.page,
            "page_size": result.page_size,
        }
    ).data
    return Response(data)


@extend_schema(responses={200: SignalCommunicationHistoryResponseSerializer})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def signal_communication_history(request: Request, signal_id: str) -> Response:
    """Checkpoint 64.9: the FULL communication attempt history (every
    retry, not just the current status) for ONE signal - powers the
    signal detail screen's traceability panel. Reuses the existing
    `CommunicationLedgerRecord` table verbatim - no new persistence."""
    attempts = DjangoSignalRepository().get_signal_communication_history(signal_id)
    data = SignalCommunicationHistoryResponseSerializer(
        {
            "signal_id": signal_id,
            "attempts": [_attempt_data(a) for a in attempts],
        }
    ).data
    return Response(data)


def _attempt_data(attempt: CommunicationLedgerRecord) -> dict[str, object]:
    return {
        "communication_id": attempt.communication_id,
        "channel": attempt.channel,
        "provider": attempt.provider,
        "delivery_status": attempt.delivery_status,
        "attempted_at": attempt.attempted_at,
        "retry_count": attempt.retry_count,
        "error_message": attempt.error_message,
        "created_at": attempt.created_at,
    }
