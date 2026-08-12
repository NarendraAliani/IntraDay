# File: src/intraday/infrastructure/api/strategy_views.py
#
# DRF views for the strategy-version API resource (Checkpoint 8). Mirrors
# risk_views.py's structure and rationale. Identity is the 3-tuple
# (specification_version, code_version, configuration_version), so the
# URL path (see urls.py) carries three version segments, not one.
from __future__ import annotations

import contextlib

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from intraday.application.config_schema.records import StrategyVersionSnapshot
from intraday.application.contracts.errors import ApiErrorSerializer
from intraday.application.contracts.strategy import StrategyVersionResponseSerializer
from intraday.application.repositories import DuplicateVersionError
from intraday.application.services.errors import (
    InvalidActivationRequestError,
    ResourceNotFoundError,
)
from intraday.application.services.strategy import StrategyVersionService
from intraday.infrastructure.api.errors import duplicate_version, invalid_activation, not_found
from intraday.infrastructure.api.permissions import IsConfigurationOperator
from intraday.infrastructure.persistence.repositories import DjangoStrategyVersionRepository


def _service() -> StrategyVersionService:
    return StrategyVersionService(DjangoStrategyVersionRepository())


def _identity(snapshot: StrategyVersionSnapshot) -> tuple[str, str, str]:
    version = snapshot.strategy_version
    return (
        version.specification_version.value,
        version.code_version.value,
        version.configuration_version.value,
    )


def _to_response_dict(snapshot: StrategyVersionSnapshot, *, is_active: bool) -> dict[str, object]:
    version = snapshot.strategy_version
    return {
        "strategy_id": version.strategy_id,
        "specification_version": version.specification_version.value,
        "code_version": version.code_version.value,
        "configuration_version": version.configuration_version.value,
        "universe_version": version.universe_version.value,
        "timeframe": version.timeframe.value,
        "maturity_state": version.maturity_state.value,
        "created_at": snapshot.created_at,
        "is_active": is_active,
    }


@extend_schema(responses={200: StrategyVersionResponseSerializer(many=True)})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_versions(request: Request, strategy_id: str) -> Response:
    service = _service()
    versions = service.list_versions(strategy_id)
    active_identity: tuple[str, str, str] | None
    try:
        active_identity = _identity(service.get_active(strategy_id))
    except ResourceNotFoundError:
        active_identity = None
    body = [
        _to_response_dict(snapshot, is_active=(_identity(snapshot) == active_identity))
        for snapshot in versions
    ]
    return Response(body)


@extend_schema(
    responses={200: StrategyVersionResponseSerializer, 404: OpenApiResponse(ApiErrorSerializer)}
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_active(request: Request, strategy_id: str) -> Response:
    service = _service()
    try:
        snapshot = service.get_active(strategy_id)
    except ResourceNotFoundError as exc:
        return not_found(exc)
    body = _to_response_dict(snapshot, is_active=True)
    return Response(body)


@extend_schema(
    responses={200: StrategyVersionResponseSerializer, 404: OpenApiResponse(ApiErrorSerializer)}
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_version(
    request: Request,
    strategy_id: str,
    specification_version: str,
    code_version: str,
    configuration_version: str,
) -> Response:
    service = _service()
    try:
        snapshot = service.get_version(
            strategy_id, specification_version, code_version, configuration_version
        )
    except ResourceNotFoundError as exc:
        return not_found(exc)
    is_active = False
    with contextlib.suppress(ResourceNotFoundError):
        is_active = _identity(service.get_active(strategy_id)) == (
            specification_version,
            code_version,
            configuration_version,
        )
    body = _to_response_dict(snapshot, is_active=is_active)
    return Response(body)


@extend_schema(
    request=None,
    responses={
        200: StrategyVersionResponseSerializer,
        404: OpenApiResponse(ApiErrorSerializer),
        409: OpenApiResponse(ApiErrorSerializer),
    },
)
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsConfigurationOperator])
def activate(
    request: Request,
    strategy_id: str,
    specification_version: str,
    code_version: str,
    configuration_version: str,
) -> Response:
    service = _service()
    try:
        snapshot = service.activate(
            strategy_id, specification_version, code_version, configuration_version
        )
    except InvalidActivationRequestError as exc:
        return invalid_activation(exc)
    except DuplicateVersionError as exc:  # pragma: no cover - not reachable via activate() today
        return duplicate_version(exc)
    body = _to_response_dict(snapshot, is_active=True)
    return Response(body)
