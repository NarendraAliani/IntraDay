# File: src/intraday/infrastructure/api/reports_views.py
#
# Checkpoint 64.10: the FIRST API wiring for any of this project's
# report-builder functions (`application/reporting/*.py`). A fresh
# audit this checkpoint found `signal_pipeline_report.py` and
# `communication_delivery_report.py` were both real, tested,
# `AVAILABLE`-status pure aggregation functions with ZERO API endpoint
# anywhere - meaning no report has ever been operator-reachable through
# this whole project, despite existing since Checkpoint 37/38. This
# module closes that gap for the three reports this checkpoint could
# wire honestly: the NEW Signal Report and Daily Session Report
# (Checkpoint 64.10), and the pre-existing Communication Delivery
# Report (Checkpoint 37, reused verbatim - never rebuilt).
#
# Every view here follows the established "query real rows, project to
# the report module's plain input dataclass, call the pure builder"
# pattern - no business logic lives in this file, only the HTTP <->
# repository/report translation, mirroring every other views.py in
# this project.
from __future__ import annotations

import datetime as dt

from django.db.models import Sum
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from intraday.application.reporting.communication_delivery_report import (
    CommunicationDeliveryRow,
    build_communication_delivery_report,
)
from intraday.application.reporting.daily_session_report import (
    PaperOrderSummaryRow,
    SystemHealthSummary,
    build_daily_session_report,
)
from intraday.application.reporting.signal_report import SignalSummaryRow, build_signal_report
from intraday.infrastructure.persistence.models import (
    CommunicationLedgerRecord,
    PaperOrderRecord,
    PaperPositionRecord,
    SignalRecord,
    WorkerRuntimeStatus,
)


class SignalReportResponseSerializer(serializers.Serializer[dict[str, object]]):
    total_signals = serializers.IntegerField()
    buy_count = serializers.IntegerField()
    sell_count = serializers.IntegerField()
    neutral_count = serializers.IntegerField()
    risk_accepted = serializers.IntegerField()
    risk_rejected = serializers.IntegerField()
    by_strategy = serializers.DictField(child=serializers.IntegerField())
    by_stock = serializers.DictField(child=serializers.IntegerField())
    by_timeframe = serializers.DictField(child=serializers.IntegerField())


class CommunicationReportResponseSerializer(serializers.Serializer[dict[str, object]]):
    total_attempts = serializers.IntegerField()
    sent_count = serializers.IntegerField()
    failed_count = serializers.IntegerField()
    skipped_duplicate_count = serializers.IntegerField()
    skipped_not_configured_count = serializers.IntegerField()
    distinct_signals_communicated = serializers.IntegerField()
    by_channel = serializers.DictField(child=serializers.IntegerField())
    by_template = serializers.DictField(child=serializers.IntegerField())


class SystemHealthSummarySerializer(serializers.Serializer[dict[str, object]]):
    watchdog_state = serializers.CharField()
    reconnect_count = serializers.IntegerField()
    consecutive_failures = serializers.IntegerField()


class ChannelCommunicationSummarySerializer(serializers.Serializer[dict[str, object]]):
    """Checkpoint 64.16 §8: the per-channel counterpart to the existing
    combined `communication_sent`/`_failed`/`_skipped` fields below -
    added alongside them, never replacing them, so no existing consumer
    of the combined totals breaks."""

    sent = serializers.IntegerField()
    failed = serializers.IntegerField()
    pending = serializers.IntegerField()


class DailySessionReportResponseSerializer(serializers.Serializer[dict[str, object]]):
    session_date = serializers.DateField()
    strategies = serializers.ListField(child=serializers.CharField())
    universe = serializers.ListField(child=serializers.CharField())
    timeframes = serializers.ListField(child=serializers.CharField())
    total_signals = serializers.IntegerField()
    risk_accepted = serializers.IntegerField()
    risk_rejected = serializers.IntegerField()
    paper_orders_total = serializers.IntegerField()
    paper_orders_filled = serializers.IntegerField()
    paper_orders_rejected = serializers.IntegerField()
    communication_total = serializers.IntegerField()
    communication_sent = serializers.IntegerField()
    communication_failed = serializers.IntegerField()
    communication_skipped = serializers.IntegerField()
    telegram = ChannelCommunicationSummarySerializer()
    discord = ChannelCommunicationSummarySerializer()
    system_health = SystemHealthSummarySerializer(allow_null=True)
    realized_pnl_total = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True)


def _parse_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    return dt.date.fromisoformat(value)


@extend_schema(
    responses={200: SignalReportResponseSerializer},
    parameters=[
        OpenApiParameter("date_from", str, required=False),
        OpenApiParameter("date_to", str, required=False),
        OpenApiParameter("strategy_id", str, required=False),
        OpenApiParameter("instrument_id", str, required=False),
        OpenApiParameter("timeframe", str, required=False),
        OpenApiParameter("direction", str, required=False),
        OpenApiParameter("risk_status", str, required=False),
    ],
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def signal_report(request: Request) -> Response:
    """Checkpoint 64.10 Report 1: real aggregation over `SignalRecord`
    - the SAME table the Signal Operations Center (Checkpoint 64.9)
    reads, never a second query implementation. Filters mirror
    `GET /signals/`'s own vocabulary exactly."""
    queryset = SignalRecord.objects.all()
    date_from = _parse_date(request.query_params.get("date_from"))
    date_to = _parse_date(request.query_params.get("date_to"))
    if date_from:
        queryset = queryset.filter(signal_timestamp__date__gte=date_from)
    if date_to:
        queryset = queryset.filter(signal_timestamp__date__lte=date_to)
    if request.query_params.get("strategy_id"):
        queryset = queryset.filter(strategy_id=request.query_params["strategy_id"])
    if request.query_params.get("instrument_id"):
        queryset = queryset.filter(instrument_id=request.query_params["instrument_id"])
    if request.query_params.get("timeframe"):
        queryset = queryset.filter(timeframe=request.query_params["timeframe"])
    if request.query_params.get("direction"):
        queryset = queryset.filter(direction=request.query_params["direction"])
    if request.query_params.get("risk_status"):
        queryset = queryset.filter(risk_status=request.query_params["risk_status"])

    rows = tuple(
        SignalSummaryRow(
            strategy_id=r.strategy_id,
            instrument_id=r.instrument_id,
            timeframe=r.timeframe,
            direction=r.direction,
            risk_status=r.risk_status,
        )
        for r in queryset
    )
    report = build_signal_report(rows=rows, generated_by=request.user.get_username())
    data = SignalReportResponseSerializer(
        {
            "total_signals": report.total_signals,
            "buy_count": report.buy_count,
            "sell_count": report.sell_count,
            "neutral_count": report.neutral_count,
            "risk_accepted": report.risk_accepted,
            "risk_rejected": report.risk_rejected,
            "by_strategy": report.by_strategy,
            "by_stock": report.by_stock,
            "by_timeframe": report.by_timeframe,
        }
    ).data
    return Response(data)


@extend_schema(responses={200: CommunicationReportResponseSerializer})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def communication_report(request: Request) -> Response:
    """Checkpoint 64.10 Report 4: wires the pre-existing (Checkpoint 37
    Part 8), previously-unwired `build_communication_delivery_report()`
    to a real endpoint for the first time - reused verbatim, never
    rebuilt."""
    rows = tuple(
        CommunicationDeliveryRow(
            signal_id=r.signal_id,
            channel=r.channel,
            provider=r.provider,
            template_id=r.template_id,
            delivery_status=r.delivery_status,
            created_at=r.created_at,
        )
        for r in CommunicationLedgerRecord.objects.all()
    )
    report = build_communication_delivery_report(
        rows=rows, generated_by=request.user.get_username()
    )
    data = CommunicationReportResponseSerializer(
        {
            "total_attempts": report.total_attempts,
            "sent_count": report.sent_count,
            "failed_count": report.failed_count,
            "skipped_duplicate_count": report.skipped_duplicate_count,
            "skipped_not_configured_count": report.skipped_not_configured_count,
            "distinct_signals_communicated": report.distinct_signals_communicated,
            "by_channel": report.by_channel,
            "by_template": report.by_template,
        }
    ).data
    return Response(data)


@extend_schema(
    responses={200: DailySessionReportResponseSerializer},
    parameters=[OpenApiParameter("date", str, required=False)],
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def daily_session_report(request: Request) -> Response:
    """Checkpoint 64.10 Report 5 - "the MOST IMPORTANT report." A
    "session" is identified by calendar date (disclosed limitation - no
    dedicated Session persistence row exists, see this report's own
    `ReportCatalogueEntry`). Defaults to today (server clock, UTC)."""
    session_date = (
        _parse_date(request.query_params.get("date")) or dt.datetime.now(tz=dt.UTC).date()
    )

    signal_rows = tuple(
        SignalSummaryRow(
            strategy_id=r.strategy_id,
            instrument_id=r.instrument_id,
            timeframe=r.timeframe,
            direction=r.direction,
            risk_status=r.risk_status,
        )
        for r in SignalRecord.objects.filter(signal_timestamp__date=session_date)
    )
    paper_order_rows = tuple(
        PaperOrderSummaryRow(status=r.status)
        for r in PaperOrderRecord.objects.filter(created_at__date=session_date)
    )
    communication_rows = tuple(
        CommunicationDeliveryRow(
            signal_id=r.signal_id,
            channel=r.channel,
            provider=r.provider,
            template_id=r.template_id,
            delivery_status=r.delivery_status,
            created_at=r.created_at,
        )
        for r in CommunicationLedgerRecord.objects.filter(created_at__date=session_date)
    )

    worker_row = WorkerRuntimeStatus.objects.filter(provider="dhan").first()
    system_health = (
        SystemHealthSummary(
            watchdog_state=worker_row.watchdog_state,
            reconnect_count=worker_row.reconnect_count,
            consecutive_failures=worker_row.consecutive_failures,
        )
        if worker_row is not None
        else None
    )

    positions_today = PaperPositionRecord.objects.filter(opened_at__date=session_date)
    pnl_aggregate = positions_today.aggregate(total=Sum("realized_pnl"))
    realized_pnl_total = pnl_aggregate["total"]  # `None` when no positions opened this session

    report = build_daily_session_report(
        session_date=session_date,
        signal_rows=signal_rows,
        paper_order_rows=paper_order_rows,
        communication_rows=communication_rows,
        system_health=system_health,
        realized_pnl_total=realized_pnl_total,
        generated_by=request.user.get_username(),
    )
    data = DailySessionReportResponseSerializer(
        {
            "session_date": report.session_date,
            "strategies": list(report.strategies),
            "universe": list(report.universe),
            "timeframes": list(report.timeframes),
            "total_signals": report.total_signals,
            "risk_accepted": report.risk_accepted,
            "risk_rejected": report.risk_rejected,
            "paper_orders_total": report.paper_orders_total,
            "paper_orders_filled": report.paper_orders_filled,
            "paper_orders_rejected": report.paper_orders_rejected,
            "communication_total": report.communication_total,
            "communication_sent": report.communication_sent,
            "communication_failed": report.communication_failed,
            "communication_skipped": report.communication_skipped,
            "telegram": {
                "sent": report.telegram.sent,
                "failed": report.telegram.failed,
                "pending": report.telegram.pending,
            },
            "discord": {
                "sent": report.discord.sent,
                "failed": report.discord.failed,
                "pending": report.discord.pending,
            },
            "system_health": (
                {
                    "watchdog_state": report.system_health.watchdog_state,
                    "reconnect_count": report.system_health.reconnect_count,
                    "consecutive_failures": report.system_health.consecutive_failures,
                }
                if report.system_health is not None
                else None
            ),
            "realized_pnl_total": report.realized_pnl_total,
        }
    ).data
    return Response(data)


__all__ = ["communication_report", "daily_session_report", "signal_report"]
