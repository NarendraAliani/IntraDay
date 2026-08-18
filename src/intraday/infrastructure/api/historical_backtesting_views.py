# File: src/intraday/infrastructure/api/historical_backtesting_views.py
#
# Checkpoint 63.x: DRF views for the DB-first historical backtest run
# resource. `create_historical_backtest_run_view` only ever CREATES a
# `BacktestRun` row and dispatches `run_historical_backtest_run_task`
# (`.delay()`) — it never runs the orchestrator inline, so a caller
# receives a `run_id` immediately and polls
# `get_historical_backtest_run_progress` for real, incrementally-updated
# state (Phase 15). `coverage_preview_view` is the read-only Phase 21
# "data readiness" check — it NEVER fetches or persists; it only reports
# what the database already has.
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from intraday.application.contracts.backtesting import (
    CoveragePreviewRequestSerializer,
    CoveragePreviewResponseSerializer,
    HistoricalBacktestRunCreatedSerializer,
    HistoricalBacktestRunProgressSerializer,
    HistoricalBacktestRunRequestSerializer,
)
from intraday.application.contracts.errors import ApiErrorSerializer
from intraday.application.services.errors import ResourceNotFoundError
from intraday.application.services.historical_backtest_run import range_bounds
from intraday.application.services.historical_data_coverage import HistoricalDataCoverageService
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.shared_kernel.contracts import Exchange, InstrumentId, Timeframe
from intraday.infrastructure.api.errors import invalid_configuration, not_found, unexpected
from intraday.infrastructure.api.permissions import IsConfigurationOperator
from intraday.infrastructure.api.tasks import dispatch_historical_backtest_run
from intraday.infrastructure.persistence.historical_backtest_run_repository import (
    DjangoBacktestRunRepository,
)
from intraday.infrastructure.persistence.historical_bar_repository import (
    DjangoHistoricalBarRepository,
)


def _instrument_id(raw: str) -> InstrumentId:
    exchange_str, _, symbol = raw.partition(":")
    return make_instrument_id(Exchange(exchange_str), symbol)


@extend_schema(
    request=HistoricalBacktestRunRequestSerializer,
    responses={
        202: HistoricalBacktestRunCreatedSerializer,
        400: OpenApiResponse(ApiErrorSerializer),
    },
)
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsConfigurationOperator])
def create_historical_backtest_run_view(request: Request) -> Response:
    serializer = HistoricalBacktestRunRequestSerializer(data=request.data)
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
        repository = DjangoBacktestRunRepository()
        repository.create(
            run_id,
            created_by=request.user.get_username(),
            start_date=data["start_date"],
            end_date=data["end_date"],
            timeframe=data["timeframe"],
            instrument_ids=list(data["instrument_ids"]),
            strategy_id=data["strategy_id"],
            specification_version=data["specification_version"],
            code_version=data["code_version"],
            configuration_version=data["configuration_version"],
            strategy_values=dict(data["strategy_values"]),
            cost_model_name=data["cost_model_name"],
            initial_capital=data["initial_capital"],
            position_sizing_mode=data["position_sizing_mode"],
            position_size_value=data["position_size_value"],
            brokerage_percent=data["brokerage_percent"],
            slippage_percent=data["slippage_percent"],
            total_instruments=len(data["instrument_ids"]),
        )
        dispatch_historical_backtest_run(run_id)
    except Exception as exc:  # noqa: BLE001 - never let a raw, unclassified exception become an opaque
        # non-JSON Django 500 page - the frontend can only show the caller
        # something useful if the response body is the project's own
        # {error_code, message} shape (see infrastructure/api/errors.py).
        # The real exception is still logged server-side (structlog) by
        # unexpected() below.
        return unexpected(exc)
    return Response({"run_id": run_id}, status=202)


@extend_schema(
    responses={
        200: HistoricalBacktestRunProgressSerializer,
        404: OpenApiResponse(ApiErrorSerializer),
    }
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_historical_backtest_run_progress(request: Request, run_id: str) -> Response:
    try:
        snapshot = DjangoBacktestRunRepository().get(run_id)
    except Exception as exc:  # noqa: BLE001 - see create_historical_backtest_run_view's own comment
        return unexpected(exc)
    if snapshot is None:
        return not_found(ResourceNotFoundError(f"no backtest run found for {run_id!r}"))

    now = datetime.now(tz=UTC)
    elapsed_seconds = 0.0
    eta_seconds: float | None = None
    if snapshot.started_at is not None:
        reference_end = snapshot.completed_at or now
        elapsed_seconds = (reference_end - snapshot.started_at).total_seconds()
        if snapshot.completed_at is None and snapshot.progress_percent > 0:
            total_estimate = elapsed_seconds / (snapshot.progress_percent / 100)
            eta_seconds = max(total_estimate - elapsed_seconds, 0.0)

    return Response(
        {
            "run_id": snapshot.run_id,
            "status": snapshot.status,
            "phase": snapshot.phase,
            "progress_percent": snapshot.progress_percent,
            "current_instrument": snapshot.current_instrument,
            "current_strategy": snapshot.current_strategy,
            "message": snapshot.message,
            "total_instruments": snapshot.total_instruments,
            "completed_instruments": snapshot.completed_instruments,
            "total_bars": snapshot.total_bars,
            "scanned_bars": snapshot.scanned_bars,
            "signals_generated": snapshot.signals_generated,
            "cache_hits": snapshot.cache_hits,
            "cache_misses": snapshot.cache_misses,
            "api_requests": snapshot.api_requests,
            "failed_instruments": list(snapshot.failed_instruments),
            "result_backtest_ids": dict(snapshot.result_backtest_ids),
            "error_message": snapshot.error_message,
            "created_at": snapshot.created_at,
            "started_at": snapshot.started_at,
            "completed_at": snapshot.completed_at,
            "elapsed_seconds": elapsed_seconds,
            "eta_seconds": eta_seconds,
        }
    )


@extend_schema(
    request=CoveragePreviewRequestSerializer,
    responses={200: CoveragePreviewResponseSerializer, 400: OpenApiResponse(ApiErrorSerializer)},
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def coverage_preview_view(request: Request) -> Response:
    """Phase 21: read-only data-readiness preview — never fetches,
    never persists, only reports what `HistoricalBar` already has for
    each requested instrument."""
    serializer = CoveragePreviewRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    try:
        timeframe = Timeframe(data["timeframe"])
    except ValueError as exc:
        return invalid_configuration(exc)

    start, end = range_bounds(data["start_date"], data["end_date"])
    coverage_service = HistoricalDataCoverageService(repository=DjangoHistoricalBarRepository())

    entries = []
    total_expected = 0
    total_cached = 0
    try:
        for raw_id in data["instrument_ids"]:
            try:
                instrument_id = _instrument_id(raw_id)
            except (KeyError, ValueError) as exc:
                return invalid_configuration(exc)
            report = coverage_service.get_coverage(instrument_id, timeframe, start, end)
            total_expected += report.expected_bar_count
            total_cached += report.cached_bar_count
            entries.append(
                {
                    "instrument_id": raw_id,
                    "coverage_percent": report.coverage_percent,
                    "expected_bar_count": report.expected_bar_count,
                    "cached_bar_count": report.cached_bar_count,
                    "is_complete": report.is_complete,
                    "missing_range_count": len(report.missing_ranges),
                }
            )
    except Exception as exc:  # noqa: BLE001 - see create_historical_backtest_run_view's own comment
        return unexpected(exc)

    overall = round((total_cached / total_expected) * 100, 2) if total_expected else 0.0
    return Response({"instruments": entries, "overall_coverage_percent": overall})
