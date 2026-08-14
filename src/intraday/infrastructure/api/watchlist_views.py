# File: src/intraday/infrastructure/api/watchlist_views.py
#
# DRF views for the Checkpoint 27 Part 19 research watchlist resource.
# No order/quantity/side field or endpoint exists here - this is a
# research-only named instrument list, usable as a backtest universe.
from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from intraday.application.contracts.backtesting import (
    WatchlistResponseSerializer,
    WatchlistSaveRequestSerializer,
)
from intraday.application.contracts.errors import ApiErrorSerializer
from intraday.application.services.errors import ResourceNotFoundError
from intraday.application.services.watchlist import WatchlistService
from intraday.infrastructure.api.errors import not_found
from intraday.infrastructure.persistence.repositories import DjangoWatchlistRepository


def _service() -> WatchlistService:
    return WatchlistService(repository=DjangoWatchlistRepository())


@extend_schema(responses={200: WatchlistResponseSerializer(many=True)})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_watchlists(request: Request) -> Response:
    service = _service()
    owner = request.user.get_username()
    names = service.list_for_owner(owner)
    body = [{"name": name, "instrument_ids": service.get(name, owner)} for name in names]
    return Response(body)


@extend_schema(
    request=WatchlistSaveRequestSerializer,
    responses={201: WatchlistResponseSerializer},
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def save_watchlist(request: Request) -> Response:
    request_serializer = WatchlistSaveRequestSerializer(data=request.data)
    request_serializer.is_valid(raise_exception=True)
    data = request_serializer.validated_data
    service = _service()
    owner = request.user.get_username()
    service.save(data["name"], owner, list(data["instrument_ids"]))
    return Response({"name": data["name"], "instrument_ids": data["instrument_ids"]}, status=201)


@extend_schema(
    responses={200: WatchlistResponseSerializer, 404: OpenApiResponse(ApiErrorSerializer)}
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_watchlist(request: Request, name: str) -> Response:
    service = _service()
    owner = request.user.get_username()
    try:
        instrument_ids = service.get(name, owner)
    except ResourceNotFoundError as exc:
        return not_found(exc)
    return Response({"name": name, "instrument_ids": instrument_ids})


@extend_schema(responses={204: None})
@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_watchlist(request: Request, name: str) -> Response:
    service = _service()
    owner = request.user.get_username()
    service.delete(name, owner)
    return Response(status=204)
