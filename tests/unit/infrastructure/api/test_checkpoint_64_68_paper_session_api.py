# tests/unit/infrastructure/api/test_checkpoint_64_68_paper_session_api.py
#
# Checkpoint 64.68 §18/§19: the REAL database + HTTP proofs.
#   §18 persistence: a session's state survives a FRESH service
#        instance (a new repository object, a new service object, a new
#        broker) - the "after a service restart" requirement, proven
#        against the real PostgreSQL-backed repository, not a stub.
#   §19 frontend/backend contract: every endpoint the Paper Trading page
#        calls, including RBAC and the idempotency/invalid-transition
#        HTTP-status distinction.
#
# NO live Dhan connection, NO live-order endpoint, NO network I/O.
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from intraday.application.repositories.paper_session import PaperSessionRecord
from intraday.domain.paper_session.contracts import PaperSessionStatus
from intraday.infrastructure.api.permissions import CONFIGURATION_OPERATOR_GROUP
from intraday.infrastructure.api.replay_paper_session_runtime import (
    DEFAULT_SESSION_ID,
    default_replay_date,
    get_replay_paper_session_service,
    load_replay_bars,
)
from intraday.infrastructure.persistence.paper_session_repository import (
    DjangoPaperSessionRepository,
)
from tests.postgres_utils import requires_postgres

PASSWORD = "correct-horse-battery-staple"  # noqa: S105
REPLAY_DATE = dt.date(2026, 1, 5)  # a Monday; not in NSE_HOLIDAYS_2026
INSTRUMENT = "NSE:RELIANCE"
BASE = "/api/v1/config/paper-trading/session/"


def _operator_client() -> Client:
    user = User.objects.create_user(username="paper-operator", password=PASSWORD)
    group, _ = Group.objects.get_or_create(name=CONFIGURATION_OPERATOR_GROUP)
    user.groups.add(group)
    client = Client()
    assert client.login(username="paper-operator", password=PASSWORD)
    return client


def _reader_client() -> Client:
    User.objects.create_user(username="paper-reader", password=PASSWORD)
    client = Client()
    assert client.login(username="paper-reader", password=PASSWORD)
    return client


def _configure(client: Client, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "strategy_id": "ema_crossover",
        "instrument_ids": [INSTRUMENT],
        "timeframe": "5m",
        "starting_capital": "1000000.0000",
        "quantity": "10.0000",
        "replay_date": REPLAY_DATE.isoformat(),
        "playback_speed": 5,
    }
    payload.update(overrides)
    response = client.post(f"{BASE}configure/", payload, content_type="application/json")
    assert response.status_code == 200, response.content
    body: dict[str, object] = response.json()
    return body


def _record(**overrides: object) -> PaperSessionRecord:
    values: dict[str, object] = {
        "session_id": DEFAULT_SESSION_ID,
        "status": PaperSessionStatus.STOPPED.value,
        "strategy_id": "ema_crossover",
        "timeframe": "5m",
        "instrument_ids": (INSTRUMENT,),
        "starting_capital": Decimal("1000000"),
        "quantity": Decimal("10"),
        "replay_date": REPLAY_DATE,
        "replay_cursor": 0,
        "replay_total_steps": 0,
        "playback_speed": 1,
        "created_at": None,
        "updated_at": None,
        "last_error": "",
    }
    values.update(overrides)
    return PaperSessionRecord(**values)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# §5 deterministic replay data - real, and genuinely offline
# --------------------------------------------------------------------------


def test_replay_bars_are_deterministic_and_session_aligned() -> None:
    """No database and no network needed - proving the replay bar loader
    is a pure function of the record, and that it produces a real
    intraday NSE session grid rather than an empty or arbitrary series."""
    record = _record()
    first = load_replay_bars(record)
    second = load_replay_bars(record)

    assert first == second
    assert len(first) > 20, "a 5m NSE session should yield a substantial bar series"
    assert all(bar.timeframe.value == "5m" for bar in first)
    assert all(bar.timestamp.tzinfo is not None for bar in first)
    assert list(first) == sorted(first, key=lambda b: b.timestamp)


def test_default_replay_date_is_a_real_trading_day() -> None:
    from intraday.domain.session.calendar import is_trading_day

    # A Saturday - the helper must walk back to the preceding Friday.
    assert default_replay_date(dt.date(2026, 1, 10)) == dt.date(2026, 1, 9)
    assert is_trading_day(default_replay_date(dt.date(2026, 1, 10)))


# --------------------------------------------------------------------------
# §18 DATABASE PERSISTENCE
# --------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_session_round_trips_through_the_real_repository() -> None:
    repository = DjangoPaperSessionRepository()
    saved = repository.save(_record(replay_cursor=7, replay_total_steps=40, playback_speed=3))

    # A genuinely FRESH repository object - nothing carried in memory.
    reloaded = DjangoPaperSessionRepository().get(DEFAULT_SESSION_ID)

    assert reloaded is not None
    assert reloaded.replay_cursor == 7
    assert reloaded.replay_total_steps == 40
    assert reloaded.playback_speed == 3
    assert reloaded.instrument_ids == (INSTRUMENT,)
    assert reloaded.starting_capital == Decimal("1000000")
    assert reloaded.replay_date == REPLAY_DATE
    assert reloaded.created_at is not None
    assert saved.session_id == reloaded.session_id


@requires_postgres
@pytest.mark.django_db
def test_session_state_survives_a_fresh_service_instance() -> None:
    """§18's actual acceptance criterion: after a simulated restart (a
    brand-new service, repository AND PaperBroker), the session's
    positions, trades and P&L are reconstructed IDENTICALLY from the
    persisted row alone."""
    first_service = get_replay_paper_session_service()
    first_service.create(
        session_id=DEFAULT_SESSION_ID,
        strategy_id="ema_crossover",
        instrument_ids=[INSTRUMENT],
        timeframe=__import__(
            "intraday.domain.shared_kernel.contracts", fromlist=["Timeframe"]
        ).Timeframe("5m"),
        starting_capital=Decimal("1000000"),
        quantity=Decimal("10"),
        replay_date=REPLAY_DATE,
    )
    first_service.start(DEFAULT_SESSION_ID)
    before = first_service.step(DEFAULT_SESSION_ID, steps=30).view

    # RESTART: every object below is newly constructed. Nothing from the
    # run above is reachable except the persisted database row.
    restarted_service = get_replay_paper_session_service()
    after = restarted_service.get(DEFAULT_SESSION_ID)

    assert after is not None
    assert after.status is before.status
    assert after.record.replay_cursor == before.record.replay_cursor
    assert after.signals == before.signals
    assert after.closed_trades == before.closed_trades
    assert after.open_positions == before.open_positions
    assert after.account == before.account
    assert after.account.equity == before.account.equity


# --------------------------------------------------------------------------
# §19 FRONTEND/BACKEND CONTRACT + §10 LIVE SAFETY
# --------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_status_endpoint_reports_no_session_without_erroring() -> None:
    response = _reader_client().get(BASE)
    assert response.status_code == 200
    body = response.json()
    assert body["exists"] is False
    assert body["mode"] == "PAPER_REPLAY"
    assert body["status"] == "STOPPED"
    assert "ema_crossover" in body["available_strategy_ids"]


@requires_postgres
@pytest.mark.django_db
def test_backend_asserts_paper_replay_mode_on_every_response() -> None:
    """§10: the "this is PAPER, not LIVE" claim is made by the SERVER, so
    the UI label is backed by a real backend fact rather than being a
    cosmetic string in the frontend only."""
    client = _operator_client()
    assert _configure(client)["mode"] == "PAPER_REPLAY"
    for action in ("start/", "pause/", "resume/", "stop/", "reset/"):
        response = client.post(f"{BASE}{action}")
        assert response.status_code in (200, 409)
        if response.status_code == 200:
            assert response.json()["mode"] == "PAPER_REPLAY"


@requires_postgres
@pytest.mark.django_db
def test_full_lifecycle_over_http() -> None:
    client = _operator_client()
    created = _configure(client)
    assert created["status"] == "STOPPED"
    assert int(str(created["replay_total_steps"])) > 0

    started = client.post(f"{BASE}start/").json()
    assert started["status"] == "RUNNING"
    assert started["accepted"] is True

    stepped = client.post(f"{BASE}step/").json()
    assert stepped["replay_cursor"] == 5  # playback_speed=5

    paused = client.post(f"{BASE}pause/").json()
    assert paused["status"] == "PAUSED"

    blocked = client.post(f"{BASE}step/").json()
    assert blocked["accepted"] is False
    assert blocked["replay_cursor"] == 5

    resumed = client.post(f"{BASE}resume/").json()
    assert resumed["status"] == "RUNNING"

    stopped = client.post(f"{BASE}stop/").json()
    assert stopped["status"] == "STOPPED"

    reset = client.post(f"{BASE}reset/").json()
    assert reset["status"] == "STOPPED"
    assert reset["replay_cursor"] == 0
    assert reset["closed_trades"] == []


@requires_postgres
@pytest.mark.django_db
def test_double_start_returns_200_not_accepted_and_double_stop_is_safe() -> None:
    """§15 over HTTP: an idempotent no-op is a 200 with accepted=false -
    NOT an error, and NOT a second session."""
    client = _operator_client()
    _configure(client)
    assert client.post(f"{BASE}start/").json()["accepted"] is True

    second = client.post(f"{BASE}start/")
    assert second.status_code == 200
    assert second.json()["accepted"] is False
    assert len(DjangoPaperSessionRepository().list_all()) == 1

    client.post(f"{BASE}stop/")
    first_stop_state = client.get(BASE).json()
    second_stop = client.post(f"{BASE}stop/")
    assert second_stop.status_code == 200
    assert second_stop.json()["accepted"] is False
    assert second_stop.json()["replay_cursor"] == first_stop_state["replay_cursor"]


@requires_postgres
@pytest.mark.django_db
def test_reset_while_running_is_rejected_with_conflict() -> None:
    """§15's documented semantics, over HTTP: an INVALID transition is a
    409, clearly distinguishable from an idempotent no-op's 200."""
    client = _operator_client()
    _configure(client)
    client.post(f"{BASE}start/")

    response = client.post(f"{BASE}reset/")
    assert response.status_code == 409
    assert "RESET is EXPLICITLY REJECTED" in response.json()["detail"]
    assert client.get(BASE).json()["status"] == "RUNNING"


@requires_postgres
@pytest.mark.django_db
def test_commands_on_an_unspecified_session_are_a_clean_400() -> None:
    client = _operator_client()
    response = client.post(f"{BASE}start/")
    assert response.status_code == 400
    assert DjangoPaperSessionRepository().list_all() == ()


@requires_postgres
@pytest.mark.django_db
def test_unregistered_strategy_is_refused() -> None:
    """§11: Gainz is NOT in the default registry and therefore cannot be
    selected here - proven, not asserted."""
    client = _operator_client()
    response = client.post(
        f"{BASE}configure/",
        {
            "strategy_id": "gainz_compatible_research",
            "instrument_ids": [INSTRUMENT],
        },
        content_type="application/json",
    )
    assert response.status_code == 400
    assert "unknown or unavailable strategy" in response.json()["detail"]


@requires_postgres
@pytest.mark.django_db
def test_mutations_require_the_configuration_operator_capability() -> None:
    reader = _reader_client()
    assert reader.get(BASE).status_code == 200
    for action in ("configure/", "start/", "pause/", "resume/", "stop/", "reset/", "step/"):
        assert reader.post(f"{BASE}{action}").status_code == 403, action


@requires_postgres
@pytest.mark.django_db
def test_anonymous_access_is_denied() -> None:
    client = Client()
    assert client.get(BASE).status_code in (401, 403)
    assert client.post(f"{BASE}start/").status_code in (401, 403)


@requires_postgres
@pytest.mark.django_db
def test_status_payload_carries_every_field_the_paper_trading_page_renders() -> None:
    """§9's required UI fields must all be genuinely served - a missing
    one would mean the page fabricates or omits it."""
    client = _operator_client()
    _configure(client)
    client.post(f"{BASE}start/")
    client.post(f"{BASE}step/")
    body = client.get(BASE).json()

    for key in (
        "status",
        "strategy_id",
        "instrument_ids",
        "timeframe",
        "replay_cursor",
        "replay_total_steps",
        "open_positions",
        "closed_trades",
        "recent_signals",
    ):
        assert key in body, key
    for key in (
        "starting_capital",
        "available_capital",
        "equity",
        "realized_pnl",
        "unrealized_pnl",
        "total_pnl",
        "drawdown",
    ):
        assert key in body["account"], key
