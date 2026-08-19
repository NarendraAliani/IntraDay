# File: src/intraday/infrastructure/api/scanner_configuration_views.py
#
# Checkpoint 64.4: DRF views for the live scanner control plane -
# DESIRED configuration write (`POST`), combined desired+effective read
# (`GET`). Validates against the EXISTING `StrategyRegistry`/`Timeframe`
# vocabulary and `AuditLogEntry`-backed audit trail (Checkpoint 12) -
# never a duplicated strategy schema or a second audit mechanism.
from __future__ import annotations

import uuid

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from intraday.application.contracts.errors import ApiErrorSerializer
from intraday.application.contracts.scanner_configuration import (
    ScannerConfigurationResponseSerializer,
    ScannerConfigurationUpdateRequestSerializer,
)
from intraday.domain.shared_kernel.contracts import Timeframe
from intraday.infrastructure.api.errors import invalid_configuration
from intraday.infrastructure.api.permissions import IsConfigurationOperator
from intraday.infrastructure.persistence.scanner_configuration_repository import (
    DjangoScannerConfigurationRepository,
)
from intraday.infrastructure.persistence.worker_runtime_status_repository import (
    DjangoWorkerRuntimeStatusRepository,
)
from intraday.trading_engine.strategy_execution.errors import UnknownStrategyError
from intraday.trading_engine.strategy_execution.registry import build_default_registry

_DEFAULT_PROVIDER = "dhan"
_registry = build_default_registry()


def _compose_response(provider: str) -> Response:
    desired = DjangoScannerConfigurationRepository().get(provider)
    effective_row = DjangoWorkerRuntimeStatusRepository().get(provider)

    if effective_row is None:
        effective = {
            "timeframe": "",
            "universe_requested_count": 0,
            "universe_subscribed_count": 0,
            "strategy_ids": [],
            "configuration_version": 0,
        }
        status = "APPLYING" if desired.enabled else "STOPPED"
    else:
        effective = {
            "timeframe": effective_row.effective_timeframe,
            "universe_requested_count": effective_row.effective_universe_requested_count,
            "universe_subscribed_count": effective_row.effective_universe_subscribed_count,
            "strategy_ids": list(effective_row.effective_strategy_ids),
            "configuration_version": effective_row.effective_configuration_version,
        }
        if not desired.enabled:
            status = "STOPPED"
        elif effective_row.effective_configuration_version != desired.configuration_version:
            status = "APPLYING"
        elif (
            effective_row.effective_universe_subscribed_count
            < effective_row.effective_universe_requested_count
        ):
            status = "DEGRADED"
        else:
            status = "EFFECTIVE"

    data = ScannerConfigurationResponseSerializer(
        {
            "provider": provider,
            "desired": {
                "timeframe": desired.timeframe,
                "universe_mode": desired.universe_mode,
                "universe_requested_count": len(desired.selected_instrument_ids)
                if desired.universe_mode == "SELECTED"
                else 0,
                "universe_subscribed_count": 0,
                "strategy_ids": list(desired.selected_strategy_ids),
                "configuration_version": desired.configuration_version,
                "enabled": desired.enabled,
            },
            "effective": effective,
            "status": status,
            "requested_by": desired.requested_by,
            "requested_at": desired.requested_at,
        }
    ).data
    return Response(data)


@extend_schema(responses={200: ScannerConfigurationResponseSerializer})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_scanner_configuration(request: Request) -> Response:
    provider = str(request.query_params.get("provider", _DEFAULT_PROVIDER))
    return _compose_response(provider)


@extend_schema(
    request=ScannerConfigurationUpdateRequestSerializer,
    responses={
        200: ScannerConfigurationResponseSerializer,
        400: OpenApiResponse(ApiErrorSerializer),
    },
)
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsConfigurationOperator])
def update_scanner_configuration(request: Request) -> Response:
    """Checkpoint 64.4 §3/§11: writes the DESIRED configuration -
    version-bumped and audited by the repository (never a separate,
    un-audited path). The worker reconciles against this on its own
    next cycle - this view never touches the worker process directly
    (they communicate ONLY through this durable row, per this
    checkpoint's own architecture decision: a separate OS process
    cannot be reached synchronously from an HTTP request)."""
    serializer = ScannerConfigurationUpdateRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    try:
        Timeframe(data["timeframe"])
    except ValueError as exc:
        return invalid_configuration(exc)

    for strategy_id in data.get("selected_strategy_ids", []):
        try:
            _registry.get(strategy_id)
        except UnknownStrategyError as exc:
            return invalid_configuration(exc)

    provider = _DEFAULT_PROVIDER
    DjangoScannerConfigurationRepository().save(
        provider,
        enabled=data["enabled"],
        timeframe=data["timeframe"],
        universe_mode=data["universe_mode"],
        selected_instrument_ids=list(data.get("selected_instrument_ids", [])),
        selected_watchlist_name=data.get("selected_watchlist_name", ""),
        selected_strategy_ids=list(data.get("selected_strategy_ids", [])),
        requested_by=request.user.get_username(),
        requested_by_user_id=request.user.pk or 0,
        request_id=str(uuid.uuid4()),
    )
    return _compose_response(provider)


__all__ = ["get_scanner_configuration", "update_scanner_configuration"]
