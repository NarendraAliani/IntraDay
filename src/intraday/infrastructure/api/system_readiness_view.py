# File: src/intraday/infrastructure/api/system_readiness_view.py
#
# Checkpoint 50 Rule 10: the FIRST composed, authoritative readiness
# endpoint - `GET /api/v1/config/system/readiness/`. Gathers real facts
# from already-existing, already-tested subsystems (market-data health,
# session calendar, kill switch, emergency-square-off event state,
# database connectivity) and passes them through
# `control_plane.system_readiness.evaluator.evaluate_readiness()` (pure)
# to produce ONE answer, instead of an operator having to separately
# poll four endpoints and combine them mentally.
#
# Deliberately narrow (see `control_plane/system_readiness/__init__.py`):
# does NOT invent Celery worker/Beat heartbeat or a persistent
# market-data-worker/bar-engine health signal this checkpoint - those
# remain named, undone dependencies, never silently assumed healthy by
# this endpoint. READY here means "every signal THIS endpoint actually
# checks is healthy," not "the full operational spine is alive."
from __future__ import annotations

import datetime as dt

import structlog
from django.db import connections
from django.db.utils import Error as DjangoDatabaseError
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from intraday.application.contracts.market_data import SystemReadinessResponseSerializer
from intraday.application.services.kill_switch import KillSwitchService
from intraday.application.services.live_market_data import LiveMarketDataService
from intraday.control_plane.system_readiness.evaluator import evaluate_readiness
from intraday.domain.risk.contracts import TradingHaltStatus
from intraday.infrastructure.persistence.emergency_square_off_event_repository import (
    DjangoEmergencySquareOffEventRepository,
)
from intraday.infrastructure.persistence.kill_switch_repository import DjangoKillSwitchRepository
from intraday.infrastructure.persistence.live_market_data_repositories import (
    DjangoLiveQuoteRepository,
    DjangoMarketDataHealthRepository,
)

logger = structlog.get_logger(__name__)


def _database_ok() -> bool:
    try:
        connections["default"].ensure_connection()
        return True
    except DjangoDatabaseError:
        logger.warning("system_readiness.database_unavailable")
        return False


@extend_schema(responses={200: SystemReadinessResponseSerializer})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def system_readiness(request: Request) -> Response:
    """Read-only, no live broker call, no order/position code reachable
    from this module (mirrors `market_data_views.py`'s own absolute
    safety-boundary discipline)."""
    now = dt.datetime.now(tz=dt.UTC)

    market_data_service = LiveMarketDataService(
        quote_repository=DjangoLiveQuoteRepository(),
        health_repository=DjangoMarketDataHealthRepository(),
    )
    health = market_data_service.get_health(now=now)
    session = market_data_service.get_session(now=now)

    kill_switch_state = KillSwitchService(DjangoKillSwitchRepository()).status()
    square_off_unresolved_count = DjangoEmergencySquareOffEventRepository().count_unresolved()

    snapshot = evaluate_readiness(
        database_ok=_database_ok(),
        market_data_state=health.state,
        session_status=session.status,
        kill_switch_engaged=kill_switch_state.status is TradingHaltStatus.HALTED,
        square_off_unresolved_count=square_off_unresolved_count,
    )

    data = SystemReadinessResponseSerializer(
        {
            "state": snapshot.state.value,
            "reasons": list(snapshot.reasons),
            "database_ok": snapshot.database_ok,
            "market_data_state": snapshot.market_data_state,
            "session_status": snapshot.session_status,
            "kill_switch_engaged": snapshot.kill_switch_engaged,
            "square_off_unresolved_count": snapshot.square_off_unresolved_count,
        }
    ).data
    return Response(data)
