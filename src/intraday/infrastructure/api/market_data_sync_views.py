# File: src/intraday/infrastructure/api/market_data_sync_views.py
#
# DRF views for the manual historical-market-data-sync resource - the
# Settings page's "fetch real Dhan data into the database" trigger.
# Mirrors `historical_backtesting_views.py`'s create/poll shape exactly
# (create returns 202 + run_id immediately, dispatched asynchronously;
# progress is polled separately) - deliberately the SAME pattern, not a
# new one, for a genuinely analogous long-running job.
from __future__ import annotations

import traceback
import uuid

import structlog
from django.conf import settings
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from intraday.application.contracts.errors import ApiErrorSerializer
from intraday.application.contracts.market_data_sync import (
    MarketDataSyncRunCreatedSerializer,
    MarketDataSyncRunProgressSerializer,
    MarketDataSyncRunRequestSerializer,
)
from intraday.application.services.errors import ResourceNotFoundError
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.shared_kernel.contracts import Exchange, InstrumentId, Timeframe
from intraday.infrastructure.api.errors import invalid_configuration, not_found, unexpected
from intraday.infrastructure.api.permissions import IsConfigurationOperator
from intraday.infrastructure.api.tasks import dispatch_market_data_sync_run
from intraday.infrastructure.persistence.market_data_sync_run_repository import (
    DjangoMarketDataSyncRunRepository,
)

logger = structlog.get_logger(__name__)


def _instrument_id(raw: str) -> InstrumentId:
    exchange_str, _, symbol = raw.partition(":")
    return make_instrument_id(Exchange(exchange_str), symbol)


def _unexpected(exc: Exception) -> Response:
    """Same `DEBUG`-only diagnostic-detail wrapper `historical_
    backtesting_views.py`'s own `_unexpected()` uses - never the shared
    `unexpected()` helper's behavior itself."""
    response = unexpected(exc)
    if settings.DEBUG:
        response.data["debug_detail"] = {
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "traceback": traceback.format_exc(),
        }
    logger.error("market_data_sync.unexpected_error", traceback=traceback.format_exc())
    return response


@extend_schema(
    request=MarketDataSyncRunRequestSerializer,
    responses={
        202: MarketDataSyncRunCreatedSerializer,
        400: OpenApiResponse(ApiErrorSerializer),
    },
)
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsConfigurationOperator])
def create_market_data_sync_run_view(request: Request) -> Response:
    serializer = MarketDataSyncRunRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    try:
        Timeframe(data["timeframe"])
    except ValueError as exc:
        return invalid_configuration(exc)
    for raw_id in data["instrument_ids"]:
        try:
            _instrument_id(raw_id)
        except (KeyError, ValueError) as exc:
            return invalid_configuration(exc)

    run_id = str(uuid.uuid4())
    try:
        repository = DjangoMarketDataSyncRunRepository()
        repository.create(
            run_id,
            created_by=request.user.get_username(),
            start_date=data["start_date"],
            end_date=data["end_date"],
            timeframe=data["timeframe"],
            instrument_ids=list(data["instrument_ids"]),
            total_instruments=len(data["instrument_ids"]),
        )
        dispatch_market_data_sync_run(run_id)
    except Exception as exc:  # noqa: BLE001 - never let a raw exception become an opaque non-JSON 500
        return _unexpected(exc)
    return Response({"run_id": run_id}, status=202)


@extend_schema(
    responses={
        200: MarketDataSyncRunProgressSerializer,
        404: OpenApiResponse(ApiErrorSerializer),
    }
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_market_data_sync_run_progress(request: Request, run_id: str) -> Response:
    try:
        snapshot = DjangoMarketDataSyncRunRepository().get(run_id)
    except Exception as exc:  # noqa: BLE001 - see create_market_data_sync_run_view's own comment
        return _unexpected(exc)
    if snapshot is None:
        return not_found(ResourceNotFoundError(f"no market data sync run found for {run_id!r}"))

    return Response(
        {
            "run_id": snapshot.run_id,
            "status": snapshot.status,
            "progress_percent": snapshot.progress_percent,
            "current_instrument": snapshot.current_instrument,
            "message": snapshot.message,
            "total_instruments": snapshot.total_instruments,
            "completed_instruments": snapshot.completed_instruments,
            "bars_fetched": snapshot.bars_fetched,
            "bars_persisted": snapshot.bars_persisted,
            "cache_hits": snapshot.cache_hits,
            "api_requests": snapshot.api_requests,
            "failed_instruments": list(snapshot.failed_instruments),
            "created_at": snapshot.created_at,
            "started_at": snapshot.started_at,
            "completed_at": snapshot.completed_at,
        }
    )


__all__ = ["create_market_data_sync_run_view", "get_market_data_sync_run_progress"]
