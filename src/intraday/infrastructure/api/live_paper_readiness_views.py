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
#
# Checkpoint 64.14: extended to also carry the 10-item readiness
# checklist (`live_paper_readiness_checklist.py`) and the real session
# state (`live_paper_session.derive_live_paper_session_state()`) in
# the SAME response - one call gives the frontend everything the
# Pre-Session Readiness Workbench (§2-4) and the session-state display
# (§9) need, reusing every existing signal, never a second aggregate
# decision (`can_start` remains the sole authority - the checklist only
# explains it).
from __future__ import annotations

import datetime as dt

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from intraday.application.repositories.scanner_configuration import ScannerConfigurationRecord
from intraday.application.repositories.worker_runtime_status import WorkerRuntimeStatusRecord
from intraday.application.services.live_paper_readiness import (
    LivePaperReadiness,
    evaluate_live_paper_readiness,
)
from intraday.application.services.live_paper_readiness_checklist import build_readiness_checklist
from intraday.application.services.live_paper_session import derive_live_paper_session_state
from intraday.application.services.provider_settings import DhanSettingsService
from intraday.application.services.token_lifecycle import evaluate_dhan_token_lifecycle
from intraday.domain.risk.contracts import TradingHaltStatus
from intraday.domain.session.calendar import session_for_instant
from intraday.domain.session.contracts import TradingSession
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


class ReadinessCheckSerializer(serializers.Serializer[dict[str, object]]):
    """NOT used as a nested nested-serializer field below - a plain
    `label = serializers.CharField()` class attribute here collides
    with DRF's own `Field.label` attribute at the type-checker level
    (djangorestframework-stubs), even though it is fine at runtime.
    Kept only as a documented, real shape (used by `extend_schema`);
    the response itself builds each checklist item as a plain dict via
    `serializers.DictField()` below, sidestepping the collision without
    changing the wire contract's `"label"` key at all."""

    key = serializers.CharField()
    state = serializers.CharField()
    explanation = serializers.CharField()
    remediation = serializers.CharField(allow_null=True)


class EffectiveSessionConfigurationSerializer(serializers.Serializer[dict[str, object]]):
    """Checkpoint 64.14 §5: DESIRED and EFFECTIVE are always two
    distinct sub-objects here, never blurred into one - `drift` is
    `true` exactly when the worker has not yet reconciled the desired
    version (an honest, real comparison, never inferred)."""

    desired_configuration_version = serializers.IntegerField()
    desired_universe_mode = serializers.CharField()
    desired_timeframe = serializers.CharField()
    desired_strategy_ids = serializers.ListField(child=serializers.CharField())
    desired_requested_by = serializers.CharField()
    effective_configuration_version = serializers.IntegerField()
    effective_timeframe = serializers.CharField()
    effective_strategy_ids = serializers.ListField(child=serializers.CharField())
    effective_stock_count = serializers.IntegerField()
    effective_requested_stock_count = serializers.IntegerField()
    drift = serializers.BooleanField()


class LivePaperWorkbenchResponseSerializer(serializers.Serializer[dict[str, object]]):
    readiness = LivePaperReadinessResponseSerializer()
    checklist = serializers.ListField(child=serializers.DictField())
    session_state = serializers.CharField()
    effective_session_configuration = EffectiveSessionConfigurationSerializer()


def _build_readiness_and_context(
    provider: str,
) -> tuple[
    LivePaperReadiness, TradingSession, ScannerConfigurationRecord, WorkerRuntimeStatusRecord | None
]:
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

    readiness = evaluate_live_paper_readiness(
        provider=provider,
        token_status=token_status,
        watchdog_state=watchdog_state,
        market_session_status=market_session.status,
        kill_switch_engaged=kill_switch_engaged,
    )
    desired = DjangoScannerConfigurationRepository().get(provider)
    return readiness, market_session, desired, worker_status


def _readiness_data(readiness: LivePaperReadiness) -> dict[str, object]:
    return {
        "state": readiness.state.value,
        "provider": readiness.provider,
        "credential_state": readiness.credential_state.value,
        "credential_expiry": readiness.credential_expires_at,
        "provider_state": readiness.provider_state,
        "watchdog_state": readiness.provider_state,
        "market_state": readiness.market_state,
        "paper_execution_state": readiness.paper_execution_state,
        "real_trading_state": readiness.real_trading_state,
        "can_start": readiness.can_start,
        "safe_reason": readiness.safe_reason,
        "remediation": readiness.remediation,
    }


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
    readiness, _market_session, _desired, _worker_status = _build_readiness_and_context(provider)
    data = LivePaperReadinessResponseSerializer(_readiness_data(readiness)).data
    return Response(data)


@extend_schema(responses={200: LivePaperWorkbenchResponseSerializer})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def live_paper_workbench(request: Request) -> Response:
    """Checkpoint 64.14: the Pre-Session Readiness Workbench's single
    data source - the aggregate `readiness` (authoritative, unchanged),
    the 10-item `checklist` (explains it), `session_state` (the real
    NOT_READY/READY/STARTING/RUNNING/STOPPING/STOPPED/FAILED value,
    Checkpoint 64.13/64.14), and the `effective_session_configuration`
    (desired vs effective, never blurred)."""
    provider = request.query_params.get("provider", _DEFAULT_PROVIDER)
    readiness, _market_session, desired, worker_status = _build_readiness_and_context(provider)

    checklist = build_readiness_checklist(
        readiness=readiness,
        market_session_status=_market_session.status,
        desired=desired,
        effective=worker_status,
    )
    session_state = derive_live_paper_session_state(
        desired=desired, effective=worker_status, readiness=readiness
    )

    effective_configuration_version = (
        worker_status.effective_configuration_version if worker_status is not None else 0
    )
    effective_timeframe = worker_status.effective_timeframe if worker_status is not None else ""
    effective_strategy_ids = (
        list(worker_status.effective_strategy_ids) if worker_status is not None else []
    )
    effective_stock_count = (
        worker_status.effective_universe_subscribed_count if worker_status is not None else 0
    )
    effective_requested_stock_count = (
        worker_status.effective_universe_requested_count if worker_status is not None else 0
    )

    data = LivePaperWorkbenchResponseSerializer(
        {
            "readiness": _readiness_data(readiness),
            "checklist": [
                {
                    "key": c.key,
                    "label": c.label,
                    "state": c.state.value,
                    "explanation": c.explanation,
                    "remediation": c.remediation,
                }
                for c in checklist
            ],
            "session_state": session_state.value,
            "effective_session_configuration": {
                "desired_configuration_version": desired.configuration_version,
                "desired_universe_mode": desired.universe_mode,
                "desired_timeframe": desired.timeframe,
                "desired_strategy_ids": list(desired.selected_strategy_ids),
                "desired_requested_by": desired.requested_by,
                "effective_configuration_version": effective_configuration_version,
                "effective_timeframe": effective_timeframe,
                "effective_strategy_ids": effective_strategy_ids,
                "effective_stock_count": effective_stock_count,
                "effective_requested_stock_count": effective_requested_stock_count,
                "drift": effective_configuration_version != desired.configuration_version,
            },
        }
    ).data
    return Response(data)


__all__ = ["live_paper_readiness", "live_paper_workbench"]
