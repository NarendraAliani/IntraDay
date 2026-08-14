# File: src/intraday/infrastructure/api/kill_switch_views.py
#
# Checkpoint 34 Part 11: DRF views for the kill switch. Mirrors
# `settings_views.py`'s established shape (thin views translating
# HTTP <-> `application/services/kill_switch.py`).
#
# RBAC: reading status requires `configuration.read` (any authenticated
# user - an operator monitoring the system must be able to see kill-
# switch state without also being able to change it); engaging/
# resetting requires `configuration.activate` (`IsConfigurationOperator`)
# - the same capability already gates every other high-consequence
# state change in this project (risk/universe/strategy activation,
# provider credentials). No new capability token was introduced
# (Part 11's "role/capability protection", satisfied by reuse, not a
# new mechanism).
from __future__ import annotations

import uuid

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from intraday.application.services.kill_switch import EmptyKillSwitchReasonError, KillSwitchService
from intraday.domain.risk.contracts import TradingHaltState
from intraday.infrastructure.api.permissions import IsConfigurationOperator
from intraday.infrastructure.persistence.kill_switch_repository import DjangoKillSwitchRepository


class KillSwitchStatusResponseSerializer(serializers.Serializer[dict[str, object]]):
    status = serializers.ChoiceField(choices=["ACTIVE", "HALTED"])
    reason = serializers.CharField(allow_null=True)
    changed_at = serializers.DateTimeField(allow_null=True)


class KillSwitchEngageRequestSerializer(serializers.Serializer[dict[str, object]]):
    reason = serializers.CharField(max_length=500)


def _service() -> KillSwitchService:
    return KillSwitchService(DjangoKillSwitchRepository())


def _response(status_obj: TradingHaltState) -> Response:
    return Response(
        KillSwitchStatusResponseSerializer(
            {
                "status": status_obj.status.value,
                "reason": status_obj.reason,
                "changed_at": status_obj.changed_at,
            }
        ).data
    )


@extend_schema(responses={200: KillSwitchStatusResponseSerializer})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def kill_switch_status(request: Request) -> Response:
    return _response(_service().status())


@extend_schema(
    request=KillSwitchEngageRequestSerializer,
    responses={
        200: KillSwitchStatusResponseSerializer,
        400: OpenApiResponse(description="Missing/empty reason"),
    },
)
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsConfigurationOperator])
def kill_switch_engage(request: Request) -> Response:
    serializer = KillSwitchEngageRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    assert request.user.pk is not None  # noqa: S101 - narrows for mypy; IsAuthenticated guarantees this
    try:
        result = _service().engage(
            reason=serializer.validated_data["reason"],
            actor=request.user.get_username(),
            actor_user_id=request.user.pk,
            request_id=str(uuid.uuid4()),
        )
    except EmptyKillSwitchReasonError as exc:
        return Response({"detail": str(exc)}, status=400)
    return _response(result)


@extend_schema(request=None, responses={200: KillSwitchStatusResponseSerializer})
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsConfigurationOperator])
def kill_switch_reset(request: Request) -> Response:
    assert request.user.pk is not None  # noqa: S101 - narrows for mypy; IsAuthenticated guarantees this
    result = _service().reset(
        actor=request.user.get_username(),
        actor_user_id=request.user.pk,
        request_id=str(uuid.uuid4()),
    )
    return _response(result)
