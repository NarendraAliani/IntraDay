# File: src/intraday/infrastructure/api/live_paper_session_views.py
#
# Checkpoint 64.13: the explicit, human-triggered START/STOP endpoints
# for a Live Paper Session. NEVER trusts a frontend-supplied
# `can_start` - re-evaluates `LivePaperReadiness` (Checkpoint 64.12)
# server-side on every call, then delegates the actual mutation to the
# EXISTING `DjangoScannerConfigurationRepository` (Checkpoint 64.4) via
# `application.services.live_paper_session` - never a second
# configuration-write path. RBAC matches `update_scanner_configuration`
# exactly (`IsAuthenticated` + `IsConfigurationOperator`) - starting/
# stopping a live session is at least as sensitive as any other
# scanner-configuration write.
from __future__ import annotations

import datetime as dt
import uuid

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from intraday.application.services.live_paper_readiness import (
    LivePaperReadiness,
    evaluate_live_paper_readiness,
)
from intraday.application.services.live_paper_session import (
    start_live_paper_session,
    stop_live_paper_session,
)
from intraday.application.services.provider_settings import DhanSettingsService
from intraday.application.services.token_lifecycle import evaluate_dhan_token_lifecycle
from intraday.domain.risk.contracts import TradingHaltStatus
from intraday.domain.session.calendar import session_for_instant
from intraday.infrastructure.api.permissions import IsConfigurationOperator
from intraday.infrastructure.persistence.kill_switch_repository import DjangoKillSwitchRepository
from intraday.infrastructure.persistence.provider_settings_repositories import (
    DjangoDhanCredentialRepository,
)
from intraday.infrastructure.persistence.scanner_configuration_repository import (
    DjangoScannerConfigurationRepository,
)
from intraday.infrastructure.persistence.worker_runtime_status_repository import (
    DjangoWorkerRuntimeStatusRepository,
)

_DEFAULT_PROVIDER = "dhan"


class LivePaperSessionResponseSerializer(serializers.Serializer[dict[str, object]]):
    accepted = serializers.BooleanField()
    state = serializers.CharField()
    message = serializers.CharField()
    remediation = serializers.CharField(allow_null=True)
    configuration_version = serializers.IntegerField()
    enabled = serializers.BooleanField()


def _current_readiness(provider: str) -> LivePaperReadiness:
    now = dt.datetime.now(tz=dt.UTC)
    dhan_settings = DhanSettingsService(repository=DjangoDhanCredentialRepository())
    access_token = dhan_settings.effective_credentials()
    token_status = evaluate_dhan_token_lifecycle(
        access_token[1] if access_token is not None else None, now=now
    )
    worker_status = DjangoWorkerRuntimeStatusRepository().get(provider)
    watchdog_state = worker_status.watchdog_state if worker_status is not None else None
    kill_switch_state = DjangoKillSwitchRepository().get()
    market_session = session_for_instant(now)
    return evaluate_live_paper_readiness(
        provider=provider,
        token_status=token_status,
        watchdog_state=watchdog_state,
        market_session_status=market_session.status,
        kill_switch_engaged=kill_switch_state.status is TradingHaltStatus.HALTED,
    )


@extend_schema(
    request=None,
    responses={
        200: LivePaperSessionResponseSerializer,
        409: OpenApiResponse(LivePaperSessionResponseSerializer),
    },
)
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsConfigurationOperator])
def start_live_paper_session_view(request: Request) -> Response:
    """Checkpoint 64.13 §6/§8: the backend's OWN re-check - the
    request body is intentionally ignored (accepts no access token or
    other credential from the frontend, per §22's explicit
    instruction); every input this endpoint acts on is read server-side
    from already-configured, already-audited sources."""
    provider = _DEFAULT_PROVIDER
    assert request.user.pk is not None  # noqa: S101 - narrows for mypy; IsAuthenticated guarantees this

    readiness = _current_readiness(provider)
    result = start_live_paper_session(
        readiness=readiness,
        repository=DjangoScannerConfigurationRepository(),
        provider=provider,
        requested_by=request.user.get_username(),
        requested_by_user_id=request.user.pk,
        request_id=str(uuid.uuid4()),
    )
    data = LivePaperSessionResponseSerializer(
        {
            "accepted": result.accepted,
            "state": result.state.value,
            "message": result.message,
            "remediation": result.remediation,
            "configuration_version": result.desired.configuration_version,
            "enabled": result.desired.enabled,
        }
    ).data
    status_code = 200 if result.accepted or result.desired.enabled else 409
    return Response(data, status=status_code)


@extend_schema(request=None, responses={200: LivePaperSessionResponseSerializer})
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsConfigurationOperator])
def stop_live_paper_session_view(request: Request) -> Response:
    """Checkpoint 64.13 §11: idempotent stop - never affects historical/
    research data (only flips `ScannerConfiguration.enabled`, the same
    real, audited flag Checkpoint 64.4 already built)."""
    provider = _DEFAULT_PROVIDER
    assert request.user.pk is not None  # noqa: S101 - narrows for mypy; IsAuthenticated guarantees this

    result = stop_live_paper_session(
        repository=DjangoScannerConfigurationRepository(),
        provider=provider,
        requested_by=request.user.get_username(),
        requested_by_user_id=request.user.pk,
        request_id=str(uuid.uuid4()),
    )
    data = LivePaperSessionResponseSerializer(
        {
            "accepted": result.accepted,
            "state": result.state.value,
            "message": result.message,
            "remediation": result.remediation,
            "configuration_version": result.desired.configuration_version,
            "enabled": result.desired.enabled,
        }
    ).data
    return Response(data, status=200)


__all__ = ["start_live_paper_session_view", "stop_live_paper_session_view"]
