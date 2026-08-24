# File: src/intraday/infrastructure/api/replay_paper_session_views.py
#
# Checkpoint 64.68 §19: the SMALLEST API surface the Paper Trading page
# needs - create/start/pause/resume/stop/reset/step plus one status read
# that already carries positions, trades and the P&L summary, so the UI
# never has to fan out across five endpoints to render one screen.
# Mirrors `paper_trading_views.py`'s established shape exactly (thin
# `@api_view` functions, DRF serializers, `IsConfigurationOperator` for
# mutations). NO WebSocket was added - the existing frontend convention
# is fetch-on-action + polling, and §19 explicitly says not to introduce
# websockets where that already fits.
#
# SAFETY: every endpoint here operates on the DETERMINISTIC REPLAY paper
# session only. There is no live-broker call, no Dhan connection and no
# live-order endpoint anywhere in this module or anything it composes -
# see `replay_paper_session_runtime.py`'s own safety docstring.
from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from intraday.application.services.replay_paper_session import (
    ReplayPaperSessionView,
    UnknownPaperSessionError,
)
from intraday.domain.paper_session.contracts import InvalidPaperSessionTransitionError
from intraday.domain.shared_kernel.contracts import Timeframe
from intraday.infrastructure.api.permissions import IsConfigurationOperator
from intraday.infrastructure.api.replay_paper_session_runtime import (
    DEFAULT_QUANTITY,
    DEFAULT_SESSION_ID,
    DEFAULT_STARTING_CAPITAL,
    DEFAULT_TIMEFRAME,
    available_strategy_ids,
    default_replay_date,
    get_replay_paper_session_service,
)

MODE = "PAPER_REPLAY"
"""Echoed on every response so the UI can never render this screen
without knowing, from the SERVER, that it is paper-replay mode. A
frontend label alone would be a cosmetic claim; this is the backend
asserting it."""


class PaperSessionPositionSerializer(serializers.Serializer[dict[str, object]]):
    position_id = serializers.CharField()
    instrument_id = serializers.CharField()
    direction = serializers.CharField()
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4)
    average_entry_price = serializers.DecimalField(max_digits=18, decimal_places=4)
    unrealized_pnl = serializers.DecimalField(max_digits=18, decimal_places=4)
    realized_net_pnl = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True)
    status = serializers.CharField()


class PaperSessionTradeSerializer(serializers.Serializer[dict[str, object]]):
    trade_id = serializers.CharField()
    instrument_id = serializers.CharField()
    direction = serializers.CharField()
    entry_price = serializers.DecimalField(max_digits=18, decimal_places=4)
    exit_price = serializers.DecimalField(max_digits=18, decimal_places=4)
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4)
    realized_pnl = serializers.DecimalField(max_digits=18, decimal_places=4)
    realized_net_pnl = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True)
    closed_at = serializers.DateTimeField()


class PaperSessionSignalSerializer(serializers.Serializer[dict[str, object]]):
    step = serializers.IntegerField()
    bar_timestamp = serializers.DateTimeField()
    instrument_id = serializers.CharField()
    strategy_id = serializers.CharField()
    direction = serializers.CharField(allow_null=True)
    signal_id = serializers.CharField(allow_null=True)
    skipped_reason = serializers.CharField(allow_null=True)
    risk_outcome = serializers.CharField(allow_null=True)
    risk_reason_code = serializers.CharField(allow_null=True)
    order_status = serializers.CharField(allow_null=True)


class PaperSessionAccountSerializer(serializers.Serializer[dict[str, object]]):
    starting_capital = serializers.DecimalField(max_digits=18, decimal_places=4)
    available_capital = serializers.DecimalField(max_digits=18, decimal_places=4)
    utilized_margin = serializers.DecimalField(max_digits=18, decimal_places=4)
    realized_pnl = serializers.DecimalField(max_digits=18, decimal_places=4)
    unrealized_pnl = serializers.DecimalField(max_digits=18, decimal_places=4)
    total_pnl = serializers.DecimalField(max_digits=18, decimal_places=4)
    equity = serializers.DecimalField(max_digits=18, decimal_places=4)
    peak_equity = serializers.DecimalField(max_digits=18, decimal_places=4)
    drawdown = serializers.DecimalField(max_digits=18, decimal_places=4)


class PaperSessionResponseSerializer(serializers.Serializer[dict[str, object]]):
    mode = serializers.CharField()
    exists = serializers.BooleanField()
    accepted = serializers.BooleanField()
    message = serializers.CharField()
    session_id = serializers.CharField()
    status = serializers.CharField()
    strategy_id = serializers.CharField()
    timeframe = serializers.CharField()
    instrument_ids = serializers.ListField(child=serializers.CharField())
    replay_date = serializers.DateField()
    replay_cursor = serializers.IntegerField()
    replay_total_steps = serializers.IntegerField()
    playback_speed = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4)
    available_strategy_ids = serializers.ListField(child=serializers.CharField())
    account = PaperSessionAccountSerializer()
    open_positions = PaperSessionPositionSerializer(many=True)
    closed_trades = PaperSessionTradeSerializer(many=True)
    recent_signals = PaperSessionSignalSerializer(many=True)


class PaperSessionCreateRequestSerializer(serializers.Serializer[dict[str, object]]):
    strategy_id = serializers.CharField()
    instrument_ids = serializers.ListField(child=serializers.CharField(), allow_empty=False)
    timeframe = serializers.ChoiceField(
        choices=[t.value for t in Timeframe], required=False, default=DEFAULT_TIMEFRAME.value
    )
    starting_capital = serializers.DecimalField(
        max_digits=18, decimal_places=4, required=False, default=DEFAULT_STARTING_CAPITAL
    )
    quantity = serializers.DecimalField(
        max_digits=18, decimal_places=4, required=False, default=DEFAULT_QUANTITY
    )
    replay_date = serializers.DateField(required=False, allow_null=True)
    playback_speed = serializers.IntegerField(required=False, default=1, min_value=1)


def _serialize(view: ReplayPaperSessionView | None, *, accepted: bool, message: str) -> Response:
    if view is None:
        return Response(
            PaperSessionResponseSerializer(
                {
                    "mode": MODE,
                    "exists": False,
                    "accepted": accepted,
                    "message": message,
                    "session_id": DEFAULT_SESSION_ID,
                    "status": "STOPPED",
                    "strategy_id": "",
                    "timeframe": DEFAULT_TIMEFRAME.value,
                    "instrument_ids": [],
                    "replay_date": default_replay_date(),
                    "replay_cursor": 0,
                    "replay_total_steps": 0,
                    "playback_speed": 1,
                    "quantity": DEFAULT_QUANTITY,
                    "available_strategy_ids": list(available_strategy_ids()),
                    "account": {
                        "starting_capital": Decimal("0"),
                        "available_capital": Decimal("0"),
                        "utilized_margin": Decimal("0"),
                        "realized_pnl": Decimal("0"),
                        "unrealized_pnl": Decimal("0"),
                        "total_pnl": Decimal("0"),
                        "equity": Decimal("0"),
                        "peak_equity": Decimal("0"),
                        "drawdown": Decimal("0"),
                    },
                    "open_positions": [],
                    "closed_trades": [],
                    "recent_signals": [],
                }
            ).data
        )

    record = view.record
    account = view.account
    return Response(
        PaperSessionResponseSerializer(
            {
                "mode": MODE,
                "exists": True,
                "accepted": accepted,
                "message": message,
                "session_id": record.session_id,
                "status": view.status.value,
                "strategy_id": record.strategy_id,
                "timeframe": record.timeframe,
                "instrument_ids": list(record.instrument_ids),
                "replay_date": record.replay_date,
                "replay_cursor": record.replay_cursor,
                "replay_total_steps": record.replay_total_steps,
                "playback_speed": record.playback_speed,
                "quantity": record.quantity,
                "available_strategy_ids": list(available_strategy_ids()),
                "account": {
                    "starting_capital": account.starting_capital,
                    "available_capital": account.available_capital,
                    "utilized_margin": account.utilized_margin,
                    "realized_pnl": account.realized_pnl,
                    "unrealized_pnl": account.unrealized_pnl,
                    "total_pnl": account.total_pnl,
                    "equity": account.equity,
                    "peak_equity": account.peak_equity,
                    "drawdown": account.drawdown,
                },
                "open_positions": [
                    {
                        "position_id": str(p.position_id),
                        "instrument_id": str(p.instrument_id),
                        "direction": p.direction.value,
                        "quantity": p.quantity,
                        "average_entry_price": p.average_entry_price,
                        "unrealized_pnl": p.unrealized_pnl,
                        "realized_net_pnl": p.realized_net_pnl,
                        "status": p.status.value,
                    }
                    for p in view.open_positions
                ],
                "closed_trades": [
                    {
                        "trade_id": str(t.trade_id),
                        "instrument_id": str(t.instrument_id),
                        "direction": t.direction.value,
                        "entry_price": t.entry_price,
                        "exit_price": t.exit_price,
                        "quantity": t.quantity,
                        "realized_pnl": t.realized_pnl,
                        "realized_net_pnl": t.realized_net_pnl,
                        "closed_at": t.closed_at,
                    }
                    for t in view.closed_trades
                ],
                "recent_signals": [
                    {
                        "step": s.step,
                        "bar_timestamp": s.bar_timestamp,
                        "instrument_id": s.instrument_id,
                        "strategy_id": s.strategy_id,
                        "direction": s.direction,
                        "signal_id": s.signal_id,
                        "skipped_reason": s.skipped_reason,
                        "risk_outcome": s.risk_outcome,
                        "risk_reason_code": s.risk_reason_code,
                        "order_status": s.order_status,
                    }
                    # Newest first, bounded - the UI shows a recent-activity
                    # feed, never the whole replay history.
                    for s in reversed(view.signals[-50:])
                ],
            }
        ).data
    )


@extend_schema(responses={200: PaperSessionResponseSerializer})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def paper_session_status(request: Request) -> Response:
    """The ONE read the Paper Trading page polls. `exists=false` means no
    paper session has been specified yet - never a 404, so the page can
    render its empty state without treating it as an error."""
    view = get_replay_paper_session_service().get(DEFAULT_SESSION_ID)
    return _serialize(
        view,
        accepted=True,
        message="" if view is not None else "No paper session has been specified yet.",
    )


@extend_schema(
    request=PaperSessionCreateRequestSerializer,
    responses={
        200: PaperSessionResponseSerializer,
        400: OpenApiResponse(description="Invalid paper session specification"),
    },
)
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsConfigurationOperator])
def paper_session_create(request: Request) -> Response:
    serializer = PaperSessionCreateRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    validated = serializer.validated_data

    strategy_id = validated["strategy_id"]
    if strategy_id not in available_strategy_ids():
        # §11: only strategies the EXISTING registry contains. A strategy
        # that is not registered is refused here, explicitly.
        return Response({"detail": f"unknown or unavailable strategy {strategy_id!r}"}, status=400)

    replay_date: dt.date = validated.get("replay_date") or default_replay_date()
    try:
        result = get_replay_paper_session_service().create(
            session_id=DEFAULT_SESSION_ID,
            strategy_id=strategy_id,
            instrument_ids=list(validated["instrument_ids"]),
            timeframe=Timeframe(validated["timeframe"]),
            starting_capital=validated["starting_capital"],
            quantity=validated["quantity"],
            replay_date=replay_date,
            playback_speed=validated["playback_speed"],
        )
    except (ValueError, InvalidOperation) as exc:
        return Response({"detail": str(exc)}, status=400)
    return _serialize(result.view, accepted=result.accepted, message=result.message)


def _run_command(request: Request, command: str) -> Response:
    service = get_replay_paper_session_service()
    try:
        if command == "start":
            result = service.start(DEFAULT_SESSION_ID)
        elif command == "pause":
            result = service.pause(DEFAULT_SESSION_ID)
        elif command == "resume":
            result = service.resume(DEFAULT_SESSION_ID)
        elif command == "stop":
            result = service.stop(DEFAULT_SESSION_ID)
        elif command == "reset":
            result = service.reset(DEFAULT_SESSION_ID)
        elif command == "step":
            result = service.tick(DEFAULT_SESSION_ID)
        else:  # pragma: no cover - unreachable, the URLconf fixes the set
            return Response({"detail": f"unknown command {command!r}"}, status=400)
    except UnknownPaperSessionError:
        return Response(
            {"detail": "No paper session has been specified yet - configure one first."},
            status=400,
        )
    except InvalidPaperSessionTransitionError as exc:
        # An INVALID transition (e.g. reset-while-running) is a client
        # error and says so. An IDEMPOTENT no-op (double-start,
        # double-stop) is NOT an error and returns 200 with
        # `accepted=false` - the two are deliberately distinguishable.
        return Response({"detail": str(exc)}, status=409)
    return _serialize(result.view, accepted=result.accepted, message=result.message)


@extend_schema(request=None, responses={200: PaperSessionResponseSerializer})
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsConfigurationOperator])
def paper_session_start(request: Request) -> Response:
    """Starts PAPER trading on a deterministic replay. This is not, and
    cannot become, a live-order action - see this module's docstring."""
    return _run_command(request, "start")


@extend_schema(request=None, responses={200: PaperSessionResponseSerializer})
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsConfigurationOperator])
def paper_session_pause(request: Request) -> Response:
    return _run_command(request, "pause")


@extend_schema(request=None, responses={200: PaperSessionResponseSerializer})
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsConfigurationOperator])
def paper_session_resume(request: Request) -> Response:
    return _run_command(request, "resume")


@extend_schema(request=None, responses={200: PaperSessionResponseSerializer})
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsConfigurationOperator])
def paper_session_stop(request: Request) -> Response:
    return _run_command(request, "stop")


@extend_schema(request=None, responses={200: PaperSessionResponseSerializer})
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsConfigurationOperator])
def paper_session_reset(request: Request) -> Response:
    return _run_command(request, "reset")


@extend_schema(request=None, responses={200: PaperSessionResponseSerializer})
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsConfigurationOperator])
def paper_session_step(request: Request) -> Response:
    """Advances the replay by the session's own `playback_speed`."""
    return _run_command(request, "step")
