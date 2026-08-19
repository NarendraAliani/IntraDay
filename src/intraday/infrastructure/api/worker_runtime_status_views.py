# File: src/intraday/infrastructure/api/worker_runtime_status_views.py
#
# Checkpoint 64.3: DRF view for the read-only worker runtime-status
# resource - the operator-facing "is the live market-data worker
# actually healthy right now" API, the smallest architecture-consistent
# way to expose runtime state the review asked for. Read-only - the
# worker process itself is the only writer
# (`WorkerHealthTracker.persist()`).
from __future__ import annotations

import datetime as dt

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from intraday.application.contracts.worker_runtime_status import (
    WorkerRuntimeStatusResponseSerializer,
)
from intraday.infrastructure.persistence.worker_runtime_status_repository import (
    DjangoWorkerRuntimeStatusRepository,
)

_DEFAULT_PROVIDER = "dhan"


@extend_schema(responses={200: WorkerRuntimeStatusResponseSerializer})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def worker_runtime_status(request: Request) -> Response:
    provider = str(request.query_params.get("provider", _DEFAULT_PROVIDER))
    record = DjangoWorkerRuntimeStatusRepository().get(provider)

    if record is None:
        # The worker process for this provider has never run and
        # reported status at all - an honest, distinct state from
        # "ran and is now STOPPED."
        data = WorkerRuntimeStatusResponseSerializer(
            {
                "provider": provider,
                "worker_state": "STOPPED",
                "token_state": "UNCONFIGURED",
                "watchdog_state": "DISCONNECTED",
                "last_packet_at": None,
                "last_bar_at": None,
                "packet_age_seconds": None,
                "bar_age_seconds": None,
                "reconnect_count": 0,
                "consecutive_failures": 0,
                "subscribed_instrument_count": 0,
                "last_error_safe": "",
                "updated_at": None,
                "is_configured": False,
            }
        ).data
        return Response(data)

    now = dt.datetime.now(tz=dt.UTC)
    packet_age = (now - record.last_packet_at).total_seconds() if record.last_packet_at else None
    bar_age = (now - record.last_bar_at).total_seconds() if record.last_bar_at else None
    data = WorkerRuntimeStatusResponseSerializer(
        {
            "provider": record.provider,
            "worker_state": record.worker_state,
            "token_state": record.token_state,
            "watchdog_state": record.watchdog_state,
            "last_packet_at": record.last_packet_at,
            "last_bar_at": record.last_bar_at,
            "packet_age_seconds": packet_age,
            "bar_age_seconds": bar_age,
            "reconnect_count": record.reconnect_count,
            "consecutive_failures": record.consecutive_failures,
            "subscribed_instrument_count": record.subscribed_instrument_count,
            "last_error_safe": record.last_error_safe,
            "updated_at": record.updated_at,
            "is_configured": True,
        }
    ).data
    return Response(data)


__all__ = ["worker_runtime_status"]
