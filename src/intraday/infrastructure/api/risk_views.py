# File: src/intraday/infrastructure/api/risk_views.py
#
# DRF views for the risk-configuration API resource (Checkpoint 8).
# Translate HTTP <-> application/services/risk.py's RiskConfigurationService.
# No Django model, QuerySet, or persistence logic appears here — only
# request/response translation and error mapping (Checkpoint 8 §2, §16).
from __future__ import annotations

import contextlib
import uuid

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from intraday.application.config_schema.records import RiskConfigurationRecord
from intraday.application.contracts.errors import ApiErrorSerializer
from intraday.application.contracts.risk import RiskConfigurationResponseSerializer
from intraday.application.repositories import DuplicateVersionError
from intraday.application.services.errors import (
    InvalidActivationRequestError,
    ResourceNotFoundError,
)
from intraday.application.services.risk import RiskConfigurationService
from intraday.infrastructure.api.errors import duplicate_version, invalid_activation, not_found
from intraday.infrastructure.api.permissions import IsConfigurationOperator
from intraday.infrastructure.persistence.repositories import DjangoRiskConfigurationRepository


def _service() -> RiskConfigurationService:
    """Composition point: the only place a concrete (Django-backed)
    repository is constructed for this resource. See
    infrastructure/api/__init__.py for why this composition lives here,
    not in application/."""
    return RiskConfigurationService(DjangoRiskConfigurationRepository())


def _to_response_dict(record: RiskConfigurationRecord, *, is_active: bool) -> dict[str, object]:
    return {
        "risk_configuration_id": record.risk_configuration_id,
        "version": record.version.value,
        "limits": {
            "max_intraday_loss": record.limits.max_intraday_loss,
            "max_position_size": record.limits.max_position_size,
            "max_per_trade_risk": record.limits.max_per_trade_risk,
        },
        "created_at": record.created_at,
        "is_active": is_active,
    }


@extend_schema(responses={200: RiskConfigurationResponseSerializer(many=True)})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_versions(request: Request, configuration_id: str) -> Response:
    service = _service()
    versions = service.list_versions(configuration_id)
    active_version: str | None
    try:
        active_version = service.get_active(configuration_id).version.value
    except ResourceNotFoundError:
        active_version = None
    body = [
        _to_response_dict(record, is_active=(record.version.value == active_version))
        for record in versions
    ]
    return Response(body)


@extend_schema(
    responses={200: RiskConfigurationResponseSerializer, 404: OpenApiResponse(ApiErrorSerializer)}
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_active(request: Request, configuration_id: str) -> Response:
    service = _service()
    try:
        record = service.get_active(configuration_id)
    except ResourceNotFoundError as exc:
        return not_found(exc)
    return Response(_to_response_dict(record, is_active=True))


@extend_schema(
    responses={200: RiskConfigurationResponseSerializer, 404: OpenApiResponse(ApiErrorSerializer)}
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_version(request: Request, configuration_id: str, version: str) -> Response:
    service = _service()
    try:
        record = service.get_version(configuration_id, version)
    except ResourceNotFoundError as exc:
        return not_found(exc)
    is_active = False
    with contextlib.suppress(ResourceNotFoundError):
        is_active = service.get_active(configuration_id).version.value == version
    return Response(_to_response_dict(record, is_active=is_active))


@extend_schema(
    request=None,
    responses={
        200: RiskConfigurationResponseSerializer,
        404: OpenApiResponse(ApiErrorSerializer),
        409: OpenApiResponse(ApiErrorSerializer),
    },
)
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsConfigurationOperator])
def activate(request: Request, configuration_id: str, version: str) -> Response:
    service = _service()
    # Checkpoint 12: the authenticated actor and a per-request UUID are
    # minted here, at the one HTTP boundary that knows both - the actor
    # from `IsAuthenticated`/`IsConfigurationOperator` having already
    # guaranteed `request.user` is a real, identified account, and the
    # request id fresh per call (no pre-existing request/correlation-id
    # infrastructure exists in this codebase - see
    # docs/architecture/AUDITABILITY.md).
    request_id = str(uuid.uuid4())
    # `IsAuthenticated` already guarantees a real, persisted user - `pk`
    # is only optionally-typed because Django's base `Model.pk` is `Any`
    # for an unsaved instance, which can never be the case for
    # `request.user` once authentication has succeeded.
    assert request.user.pk is not None  # noqa: S101 - narrows for mypy, not a runtime guard
    try:
        record = service.activate(
            configuration_id,
            version,
            actor=request.user.get_username(),
            actor_user_id=request.user.pk,
            request_id=request_id,
        )
    except InvalidActivationRequestError as exc:
        return invalid_activation(exc)
    except DuplicateVersionError as exc:  # pragma: no cover - not reachable via activate() today
        return duplicate_version(exc)
    return Response(_to_response_dict(record, is_active=True))
