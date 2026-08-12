# File: src/intraday/infrastructure/api/universe_views.py
#
# DRF views for the universe API resource (Checkpoint 8). Mirrors
# risk_views.py's structure and rationale.
from __future__ import annotations

import contextlib

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from intraday.application.config_schema.records import UniverseRecord
from intraday.application.contracts.errors import ApiErrorSerializer
from intraday.application.contracts.universe import UniverseResponseSerializer
from intraday.application.repositories import DuplicateVersionError
from intraday.application.services.errors import (
    InvalidActivationRequestError,
    ResourceNotFoundError,
)
from intraday.application.services.universe import UniverseService
from intraday.infrastructure.api.errors import duplicate_version, invalid_activation, not_found
from intraday.infrastructure.api.permissions import IsConfigurationOperator
from intraday.infrastructure.persistence.repositories import DjangoUniverseRepository


def _service() -> UniverseService:
    return UniverseService(DjangoUniverseRepository())


def _to_response_dict(record: UniverseRecord, *, is_active: bool) -> dict[str, object]:
    universe = record.universe
    return {
        "universe_id": universe.universe_id,
        "version": universe.version.value,
        "exchange": universe.exchange.value,
        "members": [
            {"instrument_id": str(member.instrument_id), "status": member.status.value}
            for member in universe.members
        ],
        "created_at": record.created_at,
        "is_active": is_active,
    }


@extend_schema(responses={200: UniverseResponseSerializer(many=True)})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_versions(request: Request, universe_id: str) -> Response:
    service = _service()
    versions = service.list_versions(universe_id)
    active_version: str | None
    try:
        active_version = service.get_active(universe_id).universe.version.value
    except ResourceNotFoundError:
        active_version = None
    body = [
        _to_response_dict(record, is_active=(record.universe.version.value == active_version))
        for record in versions
    ]
    return Response(body)


@extend_schema(
    responses={200: UniverseResponseSerializer, 404: OpenApiResponse(ApiErrorSerializer)}
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_active(request: Request, universe_id: str) -> Response:
    service = _service()
    try:
        record = service.get_active(universe_id)
    except ResourceNotFoundError as exc:
        return not_found(exc)
    body = _to_response_dict(record, is_active=True)
    return Response(body)


@extend_schema(
    responses={200: UniverseResponseSerializer, 404: OpenApiResponse(ApiErrorSerializer)}
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_version(request: Request, universe_id: str, version: str) -> Response:
    service = _service()
    try:
        record = service.get_version(universe_id, version)
    except ResourceNotFoundError as exc:
        return not_found(exc)
    is_active = False
    with contextlib.suppress(ResourceNotFoundError):
        is_active = service.get_active(universe_id).universe.version.value == version
    body = _to_response_dict(record, is_active=is_active)
    return Response(body)


@extend_schema(
    request=None,
    responses={
        200: UniverseResponseSerializer,
        404: OpenApiResponse(ApiErrorSerializer),
        409: OpenApiResponse(ApiErrorSerializer),
    },
)
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsConfigurationOperator])
def activate(request: Request, universe_id: str, version: str) -> Response:
    service = _service()
    try:
        record = service.activate(universe_id, version)
    except InvalidActivationRequestError as exc:
        return invalid_activation(exc)
    except DuplicateVersionError as exc:  # pragma: no cover - not reachable via activate() today
        return duplicate_version(exc)
    body = _to_response_dict(record, is_active=True)
    return Response(body)
