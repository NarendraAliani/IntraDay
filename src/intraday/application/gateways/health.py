# src/intraday/application/gateways/health.py
#
# Infrastructure-only health/readiness/version endpoints (Checkpoint 4
# §11-12). Exist purely so orchestration (Docker health checks, load
# balancers, CI) can determine process liveness, readiness, and running
# version. Contain NO business logic and must not be extended with
# trading/domain concerns — those belong to control_plane's own gateways
# in a later checkpoint, once control_plane/system_health,
# control_plane/broker_health, and control_plane/market_data_health are
# actually implemented.
from __future__ import annotations

import structlog
from django.core.cache import cache
from django.db import connections
from django.db.utils import Error as DjangoDatabaseError
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

import intraday

logger = structlog.get_logger(__name__)


# Response-shape declarations for OpenAPI schema generation only (Checkpoint
# 4 §29 tooling direction: DRF -> OpenAPI -> generated TypeScript). These
# are infrastructure response shapes, not domain contracts — real domain
# serializers belong to application/contracts in a later checkpoint.
class HealthzResponseSerializer(serializers.Serializer[None]):
    status = serializers.ChoiceField(choices=["alive"])


class ReadyzResponseSerializer(serializers.Serializer[None]):
    status = serializers.ChoiceField(choices=["ready", "not_ready"])
    checks = serializers.DictField(child=serializers.CharField())


class VersionResponseSerializer(serializers.Serializer[None]):
    version = serializers.CharField()


@extend_schema(responses={200: HealthzResponseSerializer})
@api_view(["GET"])
def healthz(request: Request) -> Response:
    """Liveness: is the process alive?

    Must not depend on any external service (database, cache, broker) —
    a dependency outage must never make an otherwise-healthy process
    report itself as dead.
    """
    return Response({"status": "alive"})


@extend_schema(
    responses={
        200: ReadyzResponseSerializer,
        503: OpenApiResponse(ReadyzResponseSerializer, description="Not ready"),
    }
)
@api_view(["GET"])
def readyz(request: Request) -> Response:
    """Readiness: is this instance ready to serve its configured environment?

    Validates infrastructure connectivity (database, cache) without ever
    exposing secrets, credentials, or connection strings in the response.
    """
    checks: dict[str, str] = {}

    try:
        connections["default"].ensure_connection()
        checks["database"] = "ok"
    except DjangoDatabaseError:
        checks["database"] = "unavailable"
        logger.warning("readyz.database_unavailable")

    try:
        probe_key = "readyz:probe"
        cache.set(probe_key, "1", timeout=5)
        checks["cache"] = "ok" if cache.get(probe_key) == "1" else "unavailable"
    except Exception:  # noqa: BLE001 - cache backend errors vary by backend
        checks["cache"] = "unavailable"
        logger.warning("readyz.cache_unavailable")

    ready = all(value == "ok" for value in checks.values())
    status_code = 200 if ready else 503
    return Response(
        {"status": "ready" if ready else "not_ready", "checks": checks},
        status=status_code,
    )


@extend_schema(responses={200: VersionResponseSerializer})
@api_view(["GET"])
def version(request: Request) -> Response:
    """Returns the application version from the single authoritative source
    (package metadata derived from pyproject.toml's version field) — never
    a second, independently hardcoded value."""
    return Response({"version": intraday.__version__})
