# File: src/intraday/infrastructure/api/live_paper_readiness_views.py
#
# Checkpoint 64.12: the ONE canonical, read-only "is it safe to start a
# Live Paper Session right now" endpoint - composes three ALREADY-REAL
# signals (Dhan credential state, live worker watchdog state, kill
# switch) via `application.services.live_paper_readiness`, never a
# fourth competing check. This view performs the real queries (the
# same repositories `settings_views.py`/`worker_runtime_status_views.py`/
# `kill_switch_views.py` already use) and translates the pure
# `LivePaperReadiness` result into a safe, secret-free HTTP response.
from __future__ import annotations

import datetime as dt

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from intraday.application.services.live_paper_readiness import evaluate_live_paper_readiness
from intraday.application.services.provider_settings import DhanSettingsService
from intraday.application.services.token_lifecycle import evaluate_dhan_token_lifecycle
from intraday.domain.risk.contracts import TradingHaltStatus
from intraday.domain.session.calendar import session_for_instant
from intraday.infrastructure.persistence.kill_switch_repository import DjangoKillSwitchRepository
from intraday.infrastructure.persistence.provider_settings_repositories import (
    DjangoDhanCredentialRepository,
)
from intraday.infrastructure.persistence.worker_runtime_status_repository import (
    DjangoWorkerRuntimeStatusRepository,
)

_DEFAULT_PROVIDER = "dhan"


class LivePaperReadinessResponseSerializer(serializers.Serializer[dict[str, object]]):
    state = serializers.CharField()
    provider = serializers.CharField()
    credential_state = serializers.CharField()
    credential_expiry = serializers.DateTimeField(allow_null=True)
    provider_state = serializers.CharField()
    watchdog_state = serializers.CharField()
    """Checkpoint 64.12: identical to `provider_state` today - this
    project's only provider-health signal IS the worker's own
    watchdog_state (Checkpoint 64.3). Both fields are exposed (matching
    the mandated response shape) rather than inventing a second,
    fabricated health signal just to make them differ."""
    market_state = serializers.CharField()
    paper_execution_state = serializers.CharField()
    real_trading_state = serializers.CharField()
    can_start = serializers.BooleanField()
    safe_reason = serializers.CharField()
    remediation = serializers.CharField()


@extend_schema(responses={200: LivePaperReadinessResponseSerializer})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def live_paper_readiness(request: Request) -> Response:
    """Checkpoint 64.12: "can real trading be enabled?" is NEVER a
    question this endpoint answers - `real_trading_state` is always
    `"DISABLED"`, a structural constant (see
    `live_paper_readiness.py`'s own docstring: `PaperBroker` is the
    only concrete broker implementation anywhere in this codebase).
    This endpoint answers only "is it safe to START a paper session,"
    never "can we place a real order" - those are permanently
    different questions in this project."""
    provider = request.query_params.get("provider", _DEFAULT_PROVIDER)
    now = dt.datetime.now(tz=dt.UTC)

    dhan_settings = DhanSettingsService(repository=DjangoDhanCredentialRepository())
    access_token = dhan_settings.effective_credentials()
    token_status = evaluate_dhan_token_lifecycle(
        access_token[1] if access_token is not None else None, now=now
    )

    worker_status = DjangoWorkerRuntimeStatusRepository().get(provider)
    watchdog_state = worker_status.watchdog_state if worker_status is not None else None

    kill_switch_state = DjangoKillSwitchRepository().get()
    kill_switch_engaged = kill_switch_state.status is TradingHaltStatus.HALTED

    market_session = session_for_instant(now)

    result = evaluate_live_paper_readiness(
        provider=provider,
        token_status=token_status,
        watchdog_state=watchdog_state,
        market_session_status=market_session.status,
        kill_switch_engaged=kill_switch_engaged,
    )

    data = LivePaperReadinessResponseSerializer(
        {
            "state": result.state.value,
            "provider": result.provider,
            "credential_state": result.credential_state.value,
            "credential_expiry": result.credential_expires_at,
            "provider_state": result.provider_state,
            "watchdog_state": result.provider_state,
            "market_state": result.market_state,
            "paper_execution_state": result.paper_execution_state,
            "real_trading_state": result.real_trading_state,
            "can_start": result.can_start,
            "safe_reason": result.safe_reason,
            "remediation": result.remediation,
        }
    ).data
    return Response(data)


__all__ = ["live_paper_readiness"]
