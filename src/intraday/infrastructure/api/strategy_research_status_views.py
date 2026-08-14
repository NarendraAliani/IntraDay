# File: src/intraday/infrastructure/api/strategy_research_status_views.py
#
# DRF views for the Checkpoint 27 Part 20 strategy research-monitor
# pause/resume resource. Explicitly NOT a live-trading control - see
# `application.services.strategy_research_status`'s own docstring.
from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from intraday.application.contracts.backtesting import (
    ResearchStatusResponseSerializer,
    ResearchStatusUpdateRequestSerializer,
)
from intraday.application.contracts.errors import ApiErrorSerializer
from intraday.application.services.strategy_research_status import StrategyResearchStatusService
from intraday.infrastructure.api.errors import invalid_configuration, unknown_strategy
from intraday.infrastructure.api.permissions import IsConfigurationOperator
from intraday.infrastructure.persistence.repositories import DjangoStrategyResearchStatusRepository
from intraday.trading_engine.strategy_execution.errors import UnknownStrategyError
from intraday.trading_engine.strategy_execution.registry import build_default_registry

_REGISTRY = build_default_registry()


def _service() -> StrategyResearchStatusService:
    return StrategyResearchStatusService(
        repository=DjangoStrategyResearchStatusRepository(), registry=_REGISTRY
    )


@extend_schema(responses={200: ResearchStatusResponseSerializer(many=True)})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_research_statuses(request: Request) -> Response:
    service = _service()
    body = [
        {"strategy_id": strategy_id, "status": status}
        for strategy_id, status in service.list_all().items()
    ]
    return Response(body)


@extend_schema(
    responses={200: ResearchStatusResponseSerializer, 404: OpenApiResponse(ApiErrorSerializer)}
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_research_status(request: Request, strategy_id: str) -> Response:
    service = _service()
    try:
        status = service.get_status(strategy_id)
    except UnknownStrategyError as exc:
        return unknown_strategy(exc)
    return Response({"strategy_id": strategy_id, "status": status})


@extend_schema(
    request=ResearchStatusUpdateRequestSerializer,
    responses={200: ResearchStatusResponseSerializer, 400: OpenApiResponse(ApiErrorSerializer)},
)
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsConfigurationOperator])
def set_research_status(request: Request, strategy_id: str) -> Response:
    request_serializer = ResearchStatusUpdateRequestSerializer(data=request.data)
    request_serializer.is_valid(raise_exception=True)
    service = _service()
    try:
        status = service.set_status(
            strategy_id,
            request_serializer.validated_data["status"],
            updated_by=request.user.get_username(),
        )
    except UnknownStrategyError as exc:
        return unknown_strategy(exc)
    except ValueError as exc:
        return invalid_configuration(exc)
    return Response({"strategy_id": strategy_id, "status": status})
