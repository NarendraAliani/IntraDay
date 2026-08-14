# File: src/intraday/infrastructure/api/backtesting_views.py
#
# DRF views for the Checkpoint 27 backtesting API resource. The ONLY
# view in this codebase that runs a backtest - always against the
# fixture/historical repository (`FixtureHistoricalMarketDataRepository`),
# never live market data (SAMPLE_BAR safety gate - see
# `application.services.backtesting`'s own docstring and
# `tests/unit/architecture/test_backtesting_sample_bar_boundary.py`).
from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from intraday.application.contracts.backtesting import (
    BacktestResultSerializer,
    BacktestRunRequestSerializer,
)
from intraday.application.contracts.errors import ApiErrorSerializer
from intraday.application.services.backtesting import BacktestingService
from intraday.application.services.errors import ResourceNotFoundError
from intraday.application.services.market_data import HistoricalMarketDataService
from intraday.domain.shared_kernel.contracts import Timeframe
from intraday.infrastructure.api.errors import invalid_configuration, not_found, unknown_strategy
from intraday.infrastructure.api.permissions import IsConfigurationOperator
from intraday.infrastructure.market_data_providers.fixtures import (
    FixtureHistoricalMarketDataRepository,
)
from intraday.infrastructure.persistence.repositories import DjangoBacktestResultRepository
from intraday.research.backtesting.contracts import BacktestConfiguration, PositionSizingMode
from intraday.research.backtesting.errors import (
    InsufficientHistoricalDataError,
    InvalidBacktestConfigurationError,
)
from intraday.research.backtesting.serialization import to_json_dict
from intraday.trading_engine.strategy_execution.errors import (
    InvalidParameterValueError,
    MissingRequiredParameterError,
    UnknownFieldReferenceError,
    UnknownParameterError,
    UnknownStrategyError,
)
from intraday.trading_engine.strategy_execution.registry import build_default_registry

_REGISTRY = build_default_registry()


def _service() -> BacktestingService:
    return BacktestingService(
        market_data=HistoricalMarketDataService(repository=FixtureHistoricalMarketDataRepository()),
        registry=_REGISTRY,
        repository=DjangoBacktestResultRepository(),
    )


@extend_schema(
    request=BacktestRunRequestSerializer,
    responses={
        200: BacktestResultSerializer,
        400: OpenApiResponse(ApiErrorSerializer),
        404: OpenApiResponse(ApiErrorSerializer),
    },
)
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsConfigurationOperator])
def run_backtest_view(request: Request) -> Response:
    request_serializer = BacktestRunRequestSerializer(data=request.data)
    request_serializer.is_valid(raise_exception=True)
    data = request_serializer.validated_data

    try:
        timeframe = Timeframe(data["timeframe"])
    except ValueError as exc:
        return invalid_configuration(exc)

    try:
        config = BacktestConfiguration(
            instrument_id=data["instrument_id"],
            timeframe=timeframe,
            start=data["start"],
            end=data["end"],
            strategy_id=data["strategy_id"],
            specification_version=data["specification_version"],
            code_version=data["code_version"],
            configuration_version=data["configuration_version"],
            initial_capital=data["initial_capital"],
            position_sizing_mode=PositionSizingMode(data["position_sizing_mode"]),
            position_size_value=data["position_size_value"],
            brokerage_percent=data["brokerage_percent"],
            slippage_percent=data["slippage_percent"],
        )
    except InvalidBacktestConfigurationError as exc:
        return invalid_configuration(exc)

    service = _service()
    try:
        result = service.run(
            config, dict(data["strategy_values"]), created_by=request.user.get_username()
        )
    except UnknownStrategyError as exc:
        return unknown_strategy(exc)
    except (
        InvalidParameterValueError,
        MissingRequiredParameterError,
        UnknownParameterError,
        UnknownFieldReferenceError,
        InsufficientHistoricalDataError,
    ) as exc:
        return invalid_configuration(exc)

    return Response(to_json_dict(result))


@extend_schema(responses={200: BacktestResultSerializer, 404: OpenApiResponse(ApiErrorSerializer)})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_backtest_result(request: Request, backtest_id: str) -> Response:
    service = _service()
    try:
        payload = service.get_result(backtest_id)
    except ResourceNotFoundError as exc:
        return not_found(exc)
    return Response(payload)


@extend_schema(responses={200: BacktestResultSerializer(many=True)})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_backtest_results(request: Request, strategy_id: str) -> Response:
    service = _service()
    try:
        payloads = service.list_results(strategy_id)
    except UnknownStrategyError as exc:
        return unknown_strategy(exc)
    return Response(list(payloads))
