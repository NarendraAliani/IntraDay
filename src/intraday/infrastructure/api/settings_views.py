# File: src/intraday/infrastructure/api/settings_views.py
#
# Checkpoint 22: DRF views for the operational provider-settings API
# (Dhan broker connectivity, Telegram/Discord notification channels).
# Translates HTTP <-> application/services/provider_settings.py's
# settings services. This is also the ONE place concrete infrastructure
# clients (infrastructure/brokers/dhan/client.py,
# communication/adapters/{telegram,discord}/client.py) are invoked -
# exactly `infrastructure/api`'s documented role (composes application +
# infrastructure, per Checkpoint 8's own established pattern - e.g.
# risk_views.py's `_service()` composing `DjangoRiskConfigurationRepository`
# directly).
#
# RBAC (Checkpoint 22 §33): reuses the EXISTING `IsAuthenticated`/
# `IsConfigurationOperator` two-tier model verbatim - no new capability
# token was introduced. Reading settings requires `configuration.read`
# (any authenticated user); saving credentials or testing a connection
# requires `configuration.activate` (the `configuration-operators`
# Group) - provider settings are exactly the kind of security-sensitive
# configuration change that capability already gates for risk/universe/
# strategy activation.
from __future__ import annotations

import datetime as dt
import uuid

import structlog
from django.core.cache import cache
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from intraday.application.contracts.errors import ApiErrorSerializer
from intraday.application.contracts.settings import (
    ConnectionStatusResponseSerializer,
    DhanSettingsResponseSerializer,
    DhanSettingsSaveRequestSerializer,
    DiscordSettingsResponseSerializer,
    DiscordSettingsSaveRequestSerializer,
    TelegramSettingsResponseSerializer,
    TelegramSettingsSaveRequestSerializer,
)
from intraday.application.repositories.provider_settings import ConnectionStatusRecord
from intraday.application.services.provider_settings import (
    DhanSettingsService,
    DiscordSettingsService,
    TelegramSettingsService,
)
from intraday.communication.adapters.discord.client import check_discord_connectivity
from intraday.communication.adapters.telegram.client import check_telegram_connectivity
from intraday.infrastructure.api.permissions import IsConfigurationOperator
from intraday.infrastructure.brokers.dhan.client import check_dhan_connectivity
from intraday.infrastructure.persistence.provider_settings_repositories import (
    DjangoDhanCredentialRepository,
    DjangoDiscordCredentialRepository,
    DjangoProviderConnectionStatusRepository,
    DjangoTelegramCredentialRepository,
)

logger = structlog.get_logger(__name__)

_MIN_SECONDS_BETWEEN_CHECKS = 5


def _now() -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC)


def _dhan_service() -> DhanSettingsService:
    return DhanSettingsService(repository=DjangoDhanCredentialRepository())


def _telegram_service() -> TelegramSettingsService:
    return TelegramSettingsService(repository=DjangoTelegramCredentialRepository())


def _discord_service() -> DiscordSettingsService:
    return DiscordSettingsService(repository=DjangoDiscordCredentialRepository())


def _status_repository() -> DjangoProviderConnectionStatusRepository:
    return DjangoProviderConnectionStatusRepository()


def _debounced(provider: str) -> bool:
    """Server-side debounce (Checkpoint 22 §23) distinct from the DRF
    ScopedRateThrottle applied to the view - this specifically prevents
    the exact same provider being re-tested within a few seconds (e.g. a
    double-click), independent of the per-user rate limit. Returns True
    if the caller should be blocked."""
    key = f"provider_connection_test_debounce:{provider}"
    if cache.get(key):
        return True
    cache.set(key, "1", timeout=_MIN_SECONDS_BETWEEN_CHECKS)
    return False


# --- Dhan ----------------------------------------------------------------


def _dhan_settings_response() -> Response:
    """Shared response-building helper (Checkpoint 22 bug fix, found via
    manual UX testing): a view function wrapped by `@api_view` is not a
    plain callable - it expects to be invoked by Django's URL dispatcher
    with a raw `HttpRequest`, not called directly from other Python code
    with an already-DRF-wrapped `Request` (doing so raises
    `AssertionError: The 'request' argument must be an instance of
    'django.http.HttpRequest'`). Both the GET view and the POST-save
    view below call this shared helper directly instead of one view
    function calling another."""
    view = _dhan_service().get_display()
    data = DhanSettingsResponseSerializer(
        {
            "client_id_masked": view.client_id_masked,
            "client_id_source": view.client_id_source,
            "access_token_configured": view.access_token_configured,
            "access_token_source": view.access_token_source,
            "enabled": view.enabled,
            "updated_at": view.updated_at,
            "updated_by_username": view.updated_by_username,
        }
    ).data
    return Response(data)


@extend_schema(responses={200: DhanSettingsResponseSerializer})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def dhan_settings(request: Request) -> Response:
    return _dhan_settings_response()


@extend_schema(
    request=DhanSettingsSaveRequestSerializer, responses={200: DhanSettingsResponseSerializer}
)
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsConfigurationOperator])
def dhan_settings_save(request: Request) -> Response:
    serializer = DhanSettingsSaveRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    validated = serializer.validated_data
    assert request.user.pk is not None  # noqa: S101 - narrows for mypy; IsAuthenticated guarantees this
    _dhan_service().save(
        client_id=_blank_to_none(validated.get("client_id")),
        access_token=_blank_to_none(validated.get("access_token")),
        enabled=validated.get("enabled"),
        actor=request.user.get_username(),
        actor_user_id=request.user.pk,
        request_id=str(uuid.uuid4()),
    )
    return _dhan_settings_response()


@extend_schema(
    request=None,
    responses={200: ConnectionStatusResponseSerializer, 429: OpenApiResponse(ApiErrorSerializer)},
)
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsConfigurationOperator])
@throttle_classes([ScopedRateThrottle])
def dhan_test_connection(request: Request) -> Response:
    if _debounced("dhan"):
        return _rate_limited_response()

    credentials = _dhan_service().effective_credentials()
    status_repo = _status_repository()
    if credentials is None:
        status_repo.record_check(
            "dhan",
            status="NOT_CONFIGURED",
            checked_at=_now(),
            success=False,
            failure_reason_safe="Dhan is not configured.",
            latency_ms=None,
        )
        return _status_response(status_repo.get("dhan"))

    result = check_dhan_connectivity(*credentials)
    logger.info("settings.provider_connection_test", provider="dhan", success=result.success)
    status_repo.record_check(
        "dhan",
        status=result.status,
        checked_at=_now(),
        success=result.success,
        failure_reason_safe=result.safe_error,
        latency_ms=result.latency_ms,
    )
    return _status_response(status_repo.get("dhan"))


# --- Telegram --------------------------------------------------------------


def _telegram_settings_response() -> Response:
    view = _telegram_service().get_display()
    data = TelegramSettingsResponseSerializer(
        {
            "channel_id_masked": view.channel_id_masked,
            "channel_id_source": view.channel_id_source,
            "bot_token_configured": view.bot_token_configured,
            "bot_token_source": view.bot_token_source,
            "enabled": view.enabled,
            "updated_at": view.updated_at,
            "updated_by_username": view.updated_by_username,
        }
    ).data
    return Response(data)


@extend_schema(responses={200: TelegramSettingsResponseSerializer})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def telegram_settings(request: Request) -> Response:
    return _telegram_settings_response()


@extend_schema(
    request=TelegramSettingsSaveRequestSerializer,
    responses={200: TelegramSettingsResponseSerializer},
)
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsConfigurationOperator])
def telegram_settings_save(request: Request) -> Response:
    serializer = TelegramSettingsSaveRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    validated = serializer.validated_data
    assert request.user.pk is not None  # noqa: S101
    _telegram_service().save(
        bot_token=_blank_to_none(validated.get("bot_token")),
        channel_id=_blank_to_none(validated.get("channel_id")),
        enabled=validated.get("enabled"),
        actor=request.user.get_username(),
        actor_user_id=request.user.pk,
        request_id=str(uuid.uuid4()),
    )
    return _telegram_settings_response()


@extend_schema(
    request=None,
    responses={200: ConnectionStatusResponseSerializer, 429: OpenApiResponse(ApiErrorSerializer)},
)
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsConfigurationOperator])
@throttle_classes([ScopedRateThrottle])
def telegram_test_connection(request: Request) -> Response:
    if _debounced("telegram"):
        return _rate_limited_response()

    credentials = _telegram_service().effective_credentials()
    status_repo = _status_repository()
    if credentials is None:
        status_repo.record_check(
            "telegram",
            status="NOT_CONFIGURED",
            checked_at=_now(),
            success=False,
            failure_reason_safe="Telegram is not configured.",
            latency_ms=None,
        )
        return _status_response(status_repo.get("telegram"))

    bot_token, _channel_id = credentials
    result = check_telegram_connectivity(bot_token)
    logger.info("settings.provider_connection_test", provider="telegram", success=result.success)
    status_repo.record_check(
        "telegram",
        status=result.status,
        checked_at=_now(),
        success=result.success,
        failure_reason_safe=result.safe_error,
        latency_ms=result.latency_ms,
    )
    return _status_response(status_repo.get("telegram"))


# --- Discord -----------------------------------------------------------------


def _discord_settings_response() -> Response:
    view = _discord_service().get_display()
    data = DiscordSettingsResponseSerializer(
        {
            "webhook_configured": view.webhook_configured,
            "webhook_source": view.webhook_source,
            "enabled": view.enabled,
            "updated_at": view.updated_at,
            "updated_by_username": view.updated_by_username,
        }
    ).data
    return Response(data)


@extend_schema(responses={200: DiscordSettingsResponseSerializer})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def discord_settings(request: Request) -> Response:
    return _discord_settings_response()


@extend_schema(
    request=DiscordSettingsSaveRequestSerializer,
    responses={200: DiscordSettingsResponseSerializer},
)
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsConfigurationOperator])
def discord_settings_save(request: Request) -> Response:
    serializer = DiscordSettingsSaveRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    validated = serializer.validated_data
    assert request.user.pk is not None  # noqa: S101
    _discord_service().save(
        webhook_url=_blank_to_none(validated.get("webhook_url")),
        enabled=validated.get("enabled"),
        actor=request.user.get_username(),
        actor_user_id=request.user.pk,
        request_id=str(uuid.uuid4()),
    )
    return _discord_settings_response()


@extend_schema(
    request=None,
    responses={200: ConnectionStatusResponseSerializer, 429: OpenApiResponse(ApiErrorSerializer)},
)
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsConfigurationOperator])
@throttle_classes([ScopedRateThrottle])
def discord_test_connection(request: Request) -> Response:
    if _debounced("discord"):
        return _rate_limited_response()

    webhook_url = _discord_service().effective_webhook_url()
    status_repo = _status_repository()
    if not webhook_url:
        status_repo.record_check(
            "discord",
            status="NOT_CONFIGURED",
            checked_at=_now(),
            success=False,
            failure_reason_safe="Discord is not configured.",
            latency_ms=None,
        )
        return _status_response(status_repo.get("discord"))

    result = check_discord_connectivity(webhook_url)
    logger.info("settings.provider_connection_test", provider="discord", success=result.success)
    status_repo.record_check(
        "discord",
        status=result.status,
        checked_at=_now(),
        success=result.success,
        failure_reason_safe=result.safe_error,
        latency_ms=result.latency_ms,
    )
    return _status_response(status_repo.get("discord"))


# --- Status (read-only, no test performed) ------------------------------


@extend_schema(responses={200: ConnectionStatusResponseSerializer})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def provider_status(request: Request, provider: str) -> Response:
    """Returns the LAST RECORDED status - never performs a live check
    itself (Checkpoint 22 §22's explicit separation of "save settings"/
    "test connection"/"read status" as three distinct operations; also
    satisfies §23's "do not automatically test every provider every time
    the Settings page loads")."""
    record = _status_repository().get(provider)
    return _status_response(record)


def _status_response(record: ConnectionStatusRecord) -> Response:
    data = ConnectionStatusResponseSerializer(
        {
            "provider": record.provider,
            "status": record.status,
            "last_checked_at": record.last_checked_at,
            "last_success_at": record.last_success_at,
            "last_failure_at": record.last_failure_at,
            "failure_reason_safe": record.failure_reason_safe,
            "latency_ms": record.latency_ms,
        }
    ).data
    return Response(data)


def _rate_limited_response() -> Response:
    return Response(
        {
            "error_code": "rate_limited",
            "message": "Please wait a few seconds before testing this connection again.",
        },
        status=429,
    )


def _blank_to_none(value: str | None) -> str | None:
    """Write-only replacement pattern (Checkpoint 22 §21): an omitted or
    blank field means "leave unchanged" - only a genuinely non-blank
    value is treated as a real replacement."""
    if not value:
        return None
    return value


# Checkpoint 22 §23: rate limiting (DRF's ScopedRateThrottle, same
# mechanism/cache backend as the existing login throttle - Checkpoint
# 11) - assigned on `.cls` exactly like `auth_views.py`'s own
# `login_view.cls.throttle_scope = "login"` precedent, since DRF's
# ScopedRateThrottle reads `view.throttle_scope` from the wrapped
# view class, not from the request.
dhan_test_connection.cls.throttle_scope = "provider_connection_test"  # type: ignore[attr-defined]
telegram_test_connection.cls.throttle_scope = "provider_connection_test"  # type: ignore[attr-defined]
discord_test_connection.cls.throttle_scope = "provider_connection_test"  # type: ignore[attr-defined]
