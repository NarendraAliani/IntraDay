# File: src/intraday/infrastructure/api/market_data_views.py
#
# Checkpoint 23: DRF views for the read-only live market-data API.
# Translates HTTP <-> application/services/live_market_data.py's
# orchestration. This is also the ONE place the concrete Dhan market-
# data client (infrastructure/market_data_providers/dhan/client.py) is
# invoked and where Dhan-shaped data is converted into the canonical
# domain `Quote` - exactly `infrastructure/api`'s documented role
# (composes application + infrastructure), matching Checkpoint 22
# decision 105's precedent for `settings_views.py`'s Test Connection
# views.
#
# RBAC: reuses the existing `IsAuthenticated`/`IsConfigurationOperator`
# two-tier model verbatim, no new capability token (Checkpoint 23 does
# not introduce or need one) - reading session/health/quotes requires
# `configuration.read` (any authenticated user); triggering a live
# refresh requires `configuration.activate`, the same capability that
# already gates Checkpoint 22's provider-connection tests.
#
# ABSOLUTE SAFETY BOUNDARY (Checkpoint 23 §2): this module calls exactly
# one external endpoint - `infrastructure.market_data_providers.dhan.
# client.fetch_quotes()`, itself scoped to `POST /v2/marketfeed/quote`
# only. No order/position/trading endpoint is imported, referenced, or
# reachable from this file.
from __future__ import annotations

import datetime as dt

import structlog
from django.core.cache import cache
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from intraday.application.contracts.errors import ApiErrorSerializer
from intraday.application.contracts.market_data import (
    MarketDataHealthResponseSerializer,
    QuoteResponseSerializer,
    SessionResponseSerializer,
)
from intraday.application.services.live_market_data import LiveMarketDataService
from intraday.application.services.provider_settings import DhanSettingsService
from intraday.control_plane.market_data_health.contracts import MarketDataHealthSnapshot
from intraday.control_plane.market_data_health.evaluator import FRESHNESS_THRESHOLD_SECONDS
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Quote
from intraday.domain.shared_kernel.contracts import Exchange
from intraday.infrastructure.api.permissions import IsConfigurationOperator
from intraday.infrastructure.market_data_providers.dhan.client import (
    DhanAuthenticationError,
    DhanConnectionError,
    DhanMalformedResponseError,
    DhanQuoteObservation,
    fetch_quotes,
)
from intraday.infrastructure.market_data_providers.dhan.instruments import observation_universe
from intraday.infrastructure.persistence.live_market_data_repositories import (
    DjangoLiveQuoteRepository,
    DjangoMarketDataHealthRepository,
)
from intraday.infrastructure.persistence.provider_settings_repositories import (
    DjangoDhanCredentialRepository,
)

logger = structlog.get_logger(__name__)

_MIN_SECONDS_BETWEEN_REFRESHES = 5


def _now() -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC)


def _service() -> LiveMarketDataService:
    return LiveMarketDataService(
        quote_repository=DjangoLiveQuoteRepository(),
        health_repository=DjangoMarketDataHealthRepository(),
    )


def _dhan_service() -> DhanSettingsService:
    return DhanSettingsService(repository=DjangoDhanCredentialRepository())


@extend_schema(responses={200: SessionResponseSerializer})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def session_status(request: Request) -> Response:
    """Current NSE cash-equity trading session - computed live, no
    persistence, no external call (Checkpoint 23 §8)."""
    session = _service().get_session(now=_now())
    data = SessionResponseSerializer(
        {
            "session_date": session.session_date,
            "exchange": session.exchange.value,
            "market_open": session.market_open,
            "market_close": session.market_close,
            "square_off_deadline": session.square_off_deadline,
            "status": session.status.value,
        }
    ).data
    return Response(data)


@extend_schema(responses={200: MarketDataHealthResponseSerializer})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def health_status(request: Request) -> Response:
    """Last-recorded live-market-data health - NEVER performs a live
    fetch itself (Checkpoint 23 §22's read-vs-refresh separation,
    matching Checkpoint 22's `provider_status` precedent exactly)."""
    snapshot = _service().get_health(now=_now())
    return Response(_health_response_data(snapshot))


@extend_schema(responses={200: QuoteResponseSerializer(many=True)})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def current_quotes(request: Request) -> Response:
    """The latest observed quote per configured instrument - reads
    already-persisted data only, never triggers a live fetch."""
    now = _now()
    quotes = _service().get_quotes()
    body = [
        dict(QuoteResponseSerializer(_quote_response_data(quote, now=now)).data) for quote in quotes
    ]
    return Response(body)


@extend_schema(
    request=None,
    responses={
        200: MarketDataHealthResponseSerializer,
        429: OpenApiResponse(ApiErrorSerializer),
    },
)
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsConfigurationOperator])
@throttle_classes([ScopedRateThrottle])
def refresh(request: Request) -> Response:
    """Performs exactly ONE live `POST /v2/marketfeed/quote` call
    against the configured observation universe (Checkpoint 23 §6/§7),
    persists the result, and returns the freshly-recomputed health
    snapshot. Rate-limited and debounced identically to Checkpoint 22's
    `dhan_test_connection` (same mechanism, a distinct throttle scope).

    No order, position, or trading endpoint is called anywhere in this
    function (Checkpoint 23 §2's absolute safety boundary) - the only
    external call is `fetch_quotes()`, itself scoped to the documented
    read-only Market Quote endpoint."""
    if _debounced():
        return _rate_limited_response()

    service = _service()
    credentials = _dhan_service().effective_credentials()
    if credentials is None:
        # Not configured is not the same thing as "attempted and
        # failed" (Checkpoint 22's own Configured != Connected
        # distinction, applied here) - no attempt was made at all, so
        # no failure is recorded; the health snapshot honestly reflects
        # whatever it already was (DISCONNECTED if truly never used).
        logger.info("market_data.refresh_skipped", reason="not_configured")
        return Response(_health_response_data(service.get_health(now=_now())))

    client_id, access_token = credentials
    try:
        result = fetch_quotes(
            client_id=client_id,
            access_token=access_token,
            instruments=observation_universe(),
        )
    except DhanAuthenticationError as exc:
        service.record_refresh_failure(checked_at=_now(), error_safe=str(exc))
        logger.info("market_data.refresh_failed", reason="authentication")
        return Response(_health_response_data(service.get_health(now=_now())))
    except (DhanConnectionError, DhanMalformedResponseError) as exc:
        service.record_refresh_failure(checked_at=_now(), error_safe=str(exc))
        logger.info("market_data.refresh_failed", reason="connection_or_malformed")
        return Response(_health_response_data(service.get_health(now=_now())))

    quotes = tuple(_observation_to_quote(observation) for observation in result.observations)
    service.record_refresh_success(quotes, fetched_at=result.fetched_at)
    logger.info("market_data.refresh_succeeded", instrument_count=len(quotes))
    return Response(_health_response_data(service.get_health(now=_now())))


def _observation_to_quote(observation: DhanQuoteObservation) -> Quote:
    """The ONE place a Dhan-shaped `DhanQuoteObservation` is converted
    into the canonical domain `Quote` - Dhan's security_id never
    appears past this boundary."""
    return Quote(
        instrument_id=make_instrument_id(Exchange.NSE, observation.instrument.symbol),
        timestamp=observation.source_timestamp,
        last_price=observation.last_price,
    )


def _health_response_data(snapshot: MarketDataHealthSnapshot) -> dict[str, object]:
    return dict(
        MarketDataHealthResponseSerializer(
            {
                "state": snapshot.state.value,
                "last_success_at": snapshot.last_success_at,
                "last_failure_at": snapshot.last_failure_at,
                "last_error_safe": snapshot.last_error_safe,
                "freshness_age_seconds": snapshot.freshness_age_seconds,
                "consecutive_failures": snapshot.consecutive_failures,
                "reconnect_count": snapshot.reconnect_count,
                "subscription_active": snapshot.subscription_active,
            }
        ).data
    )


def _quote_response_data(quote: Quote, *, now: dt.datetime) -> dict[str, object]:
    age_seconds = (now - quote.timestamp).total_seconds()
    symbol = str(quote.instrument_id).split(":", maxsplit=1)[-1]
    return {
        "symbol": symbol,
        "exchange": Exchange.NSE.value,
        "last_price": quote.last_price,
        "source_timestamp": quote.timestamp,
        "freshness_age_seconds": age_seconds,
        "is_stale": age_seconds > FRESHNESS_THRESHOLD_SECONDS,
    }


def _debounced() -> bool:
    """Mirrors Checkpoint 22's `_debounced()` in settings_views.py -
    same 5-second per-action debounce, independent of the per-user rate
    limit, guarding specifically against a double-click re-triggering a
    real outbound Dhan call within the same second."""
    key = "market_data_refresh_debounce"
    if cache.get(key):
        return True
    cache.set(key, "1", timeout=_MIN_SECONDS_BETWEEN_REFRESHES)
    return False


def _rate_limited_response() -> Response:
    return Response(
        {
            "error_code": "rate_limited",
            "message": "Please wait a few seconds before refreshing market data again.",
        },
        status=429,
    )


refresh.cls.throttle_scope = "market_data_refresh"  # type: ignore[attr-defined]
