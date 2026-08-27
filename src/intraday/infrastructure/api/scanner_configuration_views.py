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
    NotificationChannelSerializer,
    ScannerConfigurationResponseSerializer,
    ScannerConfigurationUpdateRequestSerializer,
)
from intraday.application.services.provider_settings import (
    DiscordSettingsService,
    TelegramSettingsService,
)
from intraday.domain.shared_kernel.contracts import Timeframe
from intraday.infrastructure.api.errors import invalid_configuration
from intraday.infrastructure.api.permissions import IsConfigurationOperator
from intraday.infrastructure.persistence.provider_settings_repositories import (
    DjangoDiscordCredentialRepository,
    DjangoTelegramCredentialRepository,
)
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


def _notification_channel_registry() -> list[dict[str, object]]:
    """Checkpoint 64.93 Part D: the SAME registry the
    `/notifications/channels/` view returns - kept as one function so
    the update view's server-side validation and the read view's
    listing can never drift apart. Reuses the existing Telegram/Discord
    settings services (Checkpoint 22) - no duplicated channel model."""
    telegram = TelegramSettingsService(repository=DjangoTelegramCredentialRepository()).get_display()
    discord = DiscordSettingsService(repository=DjangoDiscordCredentialRepository()).get_display()
    return [
        {
            "channel_id": "telegram",
            "display_name": "Telegram",
            "configured": telegram.bot_token_configured and bool(telegram.channel_id_masked),
            "enabled": telegram.enabled,
        },
        {
            "channel_id": "discord",
            "display_name": "Discord",
            "configured": discord.webhook_configured,
            "enabled": discord.enabled,
        },
    ]


@extend_schema(responses={200: NotificationChannelSerializer(many=True)})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_notification_channels(request: Request) -> Response:
    """Checkpoint 64.93 Part D: the notification-channel registry the
    frontend renders its multi-select from - never a hardcoded
    Telegram/Discord pair in markup. Adding a future channel here (and
    to `_notification_channel_registry()` above) is the only change a
    new channel would require on the backend side."""
    return Response(_notification_channel_registry())


def effective_notification_channel_ids(selected_notification_channels: list[str]) -> list[str]:
    """Checkpoint 64.93/64.94: THE single computation of "effective"
    notification-channel selection - selected by the operator AND
    genuinely configured AND enabled in the real Telegram/Discord
    settings right now. Read-time only, never a stored second copy.
    Shared by this view's own `_compose_response()` (what the UI
    displays) and `run_market_data_worker.py`'s scanner reconciliation
    cycle (what actually controls notification fan-out, Checkpoint
    64.94) - kept as ONE function so display and enforcement can never
    drift apart."""
    channel_registry = {row["channel_id"]: row for row in _notification_channel_registry()}
    return [
        channel_id
        for channel_id in selected_notification_channels
        if channel_registry.get(channel_id, {}).get("configured")
        and channel_registry.get(channel_id, {}).get("enabled")
    ]


def _compose_response(provider: str) -> Response:
    desired = DjangoScannerConfigurationRepository().get(provider)
    effective_row = DjangoWorkerRuntimeStatusRepository().get(provider)

    effective_notification_channels = effective_notification_channel_ids(
        desired.selected_notification_channels
    )

    if effective_row is None:
        effective = {
            "timeframe": "",
            "universe_requested_count": 0,
            "universe_subscribed_count": 0,
            "strategy_ids": [],
            "configuration_version": 0,
            "notification_channels": effective_notification_channels,
        }
        status = "APPLYING" if desired.enabled else "STOPPED"
    else:
        effective = {
            "timeframe": effective_row.effective_timeframe,
            "universe_requested_count": effective_row.effective_universe_requested_count,
            "universe_subscribed_count": effective_row.effective_universe_subscribed_count,
            "strategy_ids": list(effective_row.effective_strategy_ids),
            "configuration_version": effective_row.effective_configuration_version,
            "notification_channels": effective_notification_channels,
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
                "notification_channels": list(desired.selected_notification_channels),
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

    # Checkpoint 64.93 Part L: SERVER-SIDE validation of universe and
    # notification-channel selection - the frontend's own validation
    # (Part E) is UX only, this is the actual enforcement. A client
    # cannot bypass the frontend and activate an invalid configuration
    # directly through this endpoint.
    universe_mode = data["universe_mode"]
    if universe_mode == "WATCHLIST" and not data.get("selected_watchlist_name", ""):
        return invalid_configuration(
            ValueError("universe_mode=WATCHLIST requires selected_watchlist_name")
        )
    if universe_mode == "SELECTED" and not data.get("selected_instrument_ids", []):
        return invalid_configuration(
            ValueError("universe_mode=SELECTED requires at least one selected_instrument_id")
        )

    channel_registry = {row["channel_id"]: row for row in _notification_channel_registry()}
    for channel_id in data.get("selected_notification_channels", []):
        row = channel_registry.get(channel_id)
        if row is None:
            return invalid_configuration(ValueError(f"unknown notification channel {channel_id!r}"))
        if data["enabled"] and not row["configured"]:
            return invalid_configuration(
                ValueError(f"notification channel {channel_id!r} is not configured")
            )

    assert request.user.pk is not None  # noqa: S101 - narrows for mypy; IsAuthenticated guarantees this

    provider = _DEFAULT_PROVIDER
    DjangoScannerConfigurationRepository().save(
        provider,
        enabled=data["enabled"],
        timeframe=data["timeframe"],
        universe_mode=universe_mode,
        selected_instrument_ids=list(data.get("selected_instrument_ids", [])),
        selected_watchlist_name=data.get("selected_watchlist_name", ""),
        selected_strategy_ids=list(data.get("selected_strategy_ids", [])),
        selected_notification_channels=list(data.get("selected_notification_channels", [])),
        requested_by=request.user.get_username(),
        requested_by_user_id=request.user.pk,
        request_id=str(uuid.uuid4()),
    )
    return _compose_response(provider)


__all__ = [
    "get_scanner_configuration",
    "update_scanner_configuration",
    "list_notification_channels",
]
