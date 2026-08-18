# tests/unit/infrastructure/api/test_market_data_sync_api.py
#
# API-level coverage for the manual historical-market-data-sync
# resource (the Settings page's "fetch real Dhan data into the
# database" trigger). `CELERY_TASK_ALWAYS_EAGER=True` (settings/
# testing.py) makes `run_market_data_sync_run_task.delay()` execute
# synchronously in-process here, mirroring `test_historical_backtesting_
# api.py`'s own established pattern for the analogous `BacktestRun`
# resource.
from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from intraday.application.services.provider_settings import DhanSettingsService
from intraday.infrastructure.api.permissions import CONFIGURATION_OPERATOR_GROUP
from tests.postgres_utils import requires_postgres

OPERATOR_USERNAME = "market-data-sync-operator"  # noqa: S105
READER_USERNAME = "market-data-sync-reader"  # noqa: S105
PASSWORD = "correct-horse-battery-staple"  # noqa: S105


@pytest.fixture(autouse=True)
def _no_real_dhan_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same discipline `test_historical_backtesting_api.py`'s own fixture
    documents: this dev environment's `.env` genuinely carries a real
    Dhan access token, so every test here must explicitly force "no
    credentials configured" unless it is specifically testing the
    credentials-configured path - never rely on a real network call."""
    monkeypatch.setattr(DhanSettingsService, "effective_credentials", lambda self: None)


def _client_as_operator() -> Client:
    user = User.objects.create_user(username=OPERATOR_USERNAME, password=PASSWORD)
    group, _ = Group.objects.get_or_create(name=CONFIGURATION_OPERATOR_GROUP)
    user.groups.add(group)
    client = Client()
    assert client.login(username=OPERATOR_USERNAME, password=PASSWORD)
    return client


def _client_as_reader() -> Client:
    User.objects.create_user(username=READER_USERNAME, password=PASSWORD)
    client = Client()
    assert client.login(username=READER_USERNAME, password=PASSWORD)
    return client


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "instrument_ids": ["NSE:RELIANCE"],
        "timeframes": ["5m"],
        "start_date": "2026-01-05",
        "end_date": "2026-01-05",
    }
    payload.update(overrides)
    return payload


@requires_postgres
@pytest.mark.django_db
def test_create_run_requires_operator_role() -> None:
    client = _client_as_reader()
    response = client.post(
        "/api/v1/config/market-data/sync-runs/", data=_payload(), content_type="application/json"
    )
    assert response.status_code == 403


@requires_postgres
@pytest.mark.django_db
def test_create_run_returns_202_with_a_run_id() -> None:
    client = _client_as_operator()
    response = client.post(
        "/api/v1/config/market-data/sync-runs/", data=_payload(), content_type="application/json"
    )
    assert response.status_code == 202
    assert "run_id" in response.json()


@requires_postgres
@pytest.mark.django_db
def test_a_run_completes_and_persists_real_bars_via_the_synthetic_fallback() -> None:
    """No live Dhan credentials configured (this file's own autouse
    fixture) -> `_select_historical_bar_provider()` falls back to the
    synthetic provider, exactly like the historical-backtest-run tests -
    proves the full create -> dispatch -> orchestrate -> persist ->
    poll pipeline end to end through the real HTTP API."""
    client = _client_as_operator()
    create_response = client.post(
        "/api/v1/config/market-data/sync-runs/", data=_payload(), content_type="application/json"
    )
    run_id = create_response.json()["run_id"]

    progress = client.get(f"/api/v1/config/market-data/sync-runs/{run_id}/progress/").json()

    assert progress["status"] == "COMPLETED"
    assert progress["progress_percent"] == 100.0
    assert progress["total_combinations"] == 1
    assert progress["completed_combinations"] == 1
    assert progress["bars_fetched"] > 0
    assert progress["bars_persisted"] > 0
    assert progress["api_requests"] > 0
    assert not progress["failed_combinations"]


@requires_postgres
@pytest.mark.django_db
def test_a_repeat_run_over_the_same_range_hits_the_cache() -> None:
    client = _client_as_operator()
    first = client.post(
        "/api/v1/config/market-data/sync-runs/", data=_payload(), content_type="application/json"
    )
    first_run_id = first.json()["run_id"]
    first_progress = client.get(
        f"/api/v1/config/market-data/sync-runs/{first_run_id}/progress/"
    ).json()
    assert first_progress["api_requests"] > 0

    second = client.post(
        "/api/v1/config/market-data/sync-runs/", data=_payload(), content_type="application/json"
    )
    second_run_id = second.json()["run_id"]
    second_progress = client.get(
        f"/api/v1/config/market-data/sync-runs/{second_run_id}/progress/"
    ).json()

    assert second_progress["status"] == "COMPLETED"
    assert second_progress["api_requests"] == 0
    assert second_progress["cache_hits"] > 0


@requires_postgres
@pytest.mark.django_db
def test_progress_for_unknown_run_id_returns_404() -> None:
    client = _client_as_operator()
    response = client.get("/api/v1/config/market-data/sync-runs/does-not-exist/progress/")
    assert response.status_code == 404


@requires_postgres
@pytest.mark.django_db
def test_an_unknown_timeframe_is_rejected_with_a_400() -> None:
    client = _client_as_operator()
    response = client.post(
        "/api/v1/config/market-data/sync-runs/",
        data=_payload(timeframes=["not-a-real-timeframe"]),
        content_type="application/json",
    )
    assert response.status_code == 400


@requires_postgres
@pytest.mark.django_db
def test_multiple_selected_timeframes_are_all_fetched_in_one_run() -> None:
    """The approved UI decision: checking several timeframes fetches all
    of them in one run, with one combined progress bar counting
    instrument x timeframe combinations, not just instruments."""
    client = _client_as_operator()
    response = client.post(
        "/api/v1/config/market-data/sync-runs/",
        data=_payload(timeframes=["1d", "5m", "1h"]),
        content_type="application/json",
    )
    run_id = response.json()["run_id"]

    progress = client.get(f"/api/v1/config/market-data/sync-runs/{run_id}/progress/").json()

    assert progress["status"] == "COMPLETED"
    assert progress["total_combinations"] == 3  # 1 instrument x 3 timeframes
    assert progress["completed_combinations"] == 3
    assert not progress["failed_combinations"]
