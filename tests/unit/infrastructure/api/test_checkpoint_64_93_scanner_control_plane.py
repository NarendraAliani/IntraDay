# tests/unit/infrastructure/api/test_checkpoint_64_93_scanner_control_plane.py
#
# Checkpoint 64.93: coverage for the additions this checkpoint made to
# the EXISTING scanner control plane (Checkpoint 64.4/64.5) - the
# notification-channel registry endpoint, the notification-channel
# field on desired/effective configuration, and the new server-side
# validation (universe consistency, notification-channel validity)
# that a client cannot bypass. Deliberately does NOT re-test what
# test_scanner_configuration_api.py already covers (auth, strategy
# validation, timeframe validation, version bump).
from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from intraday.infrastructure.api.permissions import CONFIGURATION_OPERATOR_GROUP
from tests.postgres_utils import requires_postgres

OPERATOR_USERNAME = "scanner-64-93-operator"  # noqa: S105
PASSWORD = "correct-horse-battery-staple"  # noqa: S105


def _client_as_operator() -> Client:
    user = User.objects.create_user(username=OPERATOR_USERNAME, password=PASSWORD)
    group, _ = Group.objects.get_or_create(name=CONFIGURATION_OPERATOR_GROUP)
    user.groups.add(group)
    client = Client()
    assert client.login(username=OPERATOR_USERNAME, password=PASSWORD)
    return client


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "enabled": False,
        "timeframe": "5m",
        "universe_mode": "ALL_CONFIGURED",
        "selected_instrument_ids": [],
        "selected_watchlist_name": "",
        "selected_strategy_ids": ["ema_crossover"],
        "selected_notification_channels": [],
    }
    payload.update(overrides)
    return payload


@requires_postgres
@pytest.mark.django_db
def test_notification_channel_registry_lists_telegram_and_discord() -> None:
    client = _client_as_operator()
    response = client.get("/api/v1/config/notifications/channels/")
    assert response.status_code == 200
    channel_ids = {row["channel_id"] for row in response.json()}
    assert channel_ids == {"telegram", "discord"}
    for row in response.json():
        assert set(row.keys()) == {"channel_id", "display_name", "configured", "enabled"}


@requires_postgres
@pytest.mark.django_db
def test_unknown_notification_channel_rejected() -> None:
    client = _client_as_operator()
    response = client.post(
        "/api/v1/config/market-data/scanner-config/update/",
        data=_payload(selected_notification_channels=["carrier_pigeon"]),
        content_type="application/json",
    )
    assert response.status_code == 400


@requires_postgres
@pytest.mark.django_db
def test_enabling_scanner_with_unconfigured_channel_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Fresh test DB row with no saved credentials - and this test
    # explicitly clears the env-var fallback too (this dev environment's
    # .env carries real Telegram credentials for manual testing), so
    # "configured" is genuinely False for both channels here. Selecting
    # either while enabled=True must be rejected server-side, even
    # though the frontend would never let an operator reach this state.
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHANNEL_ID", raising=False)
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    client = _client_as_operator()
    response = client.post(
        "/api/v1/config/market-data/scanner-config/update/",
        data=_payload(enabled=True, selected_notification_channels=["telegram"]),
        content_type="application/json",
    )
    assert response.status_code == 400


@requires_postgres
@pytest.mark.django_db
def test_disabled_scanner_may_stage_an_unconfigured_channel_selection() -> None:
    # A DESIRED (not-yet-enabled) draft is allowed to name an
    # unconfigured channel - the operator may be mid-setup. The
    # blocking rule only applies at the point the scanner is actually
    # turned on (enabled=True), matching Part L's "no active scan
    # without validated configuration" rather than "no draft may ever
    # be imperfect".
    client = _client_as_operator()
    response = client.post(
        "/api/v1/config/market-data/scanner-config/update/",
        data=_payload(enabled=False, selected_notification_channels=["telegram"]),
        content_type="application/json",
    )
    assert response.status_code == 200
    assert response.json()["desired"]["notification_channels"] == ["telegram"]
    assert response.json()["effective"]["notification_channels"] == []


@requires_postgres
@pytest.mark.django_db
def test_watchlist_universe_without_watchlist_name_rejected() -> None:
    client = _client_as_operator()
    response = client.post(
        "/api/v1/config/market-data/scanner-config/update/",
        data=_payload(universe_mode="WATCHLIST", selected_watchlist_name=""),
        content_type="application/json",
    )
    assert response.status_code == 400


@requires_postgres
@pytest.mark.django_db
def test_selected_universe_without_instruments_rejected() -> None:
    client = _client_as_operator()
    response = client.post(
        "/api/v1/config/market-data/scanner-config/update/",
        data=_payload(universe_mode="SELECTED", selected_instrument_ids=[]),
        content_type="application/json",
    )
    assert response.status_code == 400


@requires_postgres
@pytest.mark.django_db
def test_selected_universe_with_instruments_accepted() -> None:
    client = _client_as_operator()
    response = client.post(
        "/api/v1/config/market-data/scanner-config/update/",
        data=_payload(universe_mode="SELECTED", selected_instrument_ids=["NSE_EQ:1333"]),
        content_type="application/json",
    )
    assert response.status_code == 200
