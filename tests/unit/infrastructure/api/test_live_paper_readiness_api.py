# tests/unit/infrastructure/api/test_live_paper_readiness_api.py
#
# Checkpoint 64.12: vertical-slice coverage for the Live Paper
# Readiness gate endpoint - real Django test Client against the real
# URLconf and real repositories. Per §13, no real production JWT value
# is used anywhere - `_fake_jwt()` builds a deterministic, unsigned
# token shape only.
from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest
from django.contrib.auth.models import User
from django.test import Client

from intraday.infrastructure.persistence.provider_settings_repositories import (
    DjangoDhanCredentialRepository,
)
from tests.postgres_utils import requires_postgres

READER_USERNAME = "readiness_reader"  # noqa: S105
PASSWORD = "correct-horse-battery-staple"  # noqa: S105


def _client() -> Client:
    User.objects.create_user(username=READER_USERNAME, password=PASSWORD)
    client = Client()
    assert client.login(username=READER_USERNAME, password=PASSWORD)
    return client


def _fake_jwt(*, exp: datetime) -> str:
    """Deterministic, LOCALLY GENERATED token shape - never a real
    Dhan credential, never a hardcoded real production JWT value."""

    def _segment(payload: dict[str, object]) -> str:
        raw = json.dumps(payload).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    header = _segment({"alg": "HS512", "typ": "JWT"})
    payload = _segment({"exp": int(exp.timestamp())})
    return f"{header}.{payload}.fake-signature-not-a-real-credential"


def _save_credential(*, client_id: str | None, access_token: str | None) -> None:
    DjangoDhanCredentialRepository().save(
        client_id=client_id,
        access_token=access_token,
        enabled=True,
        actor="tester",
        actor_user_id=1,
        request_id="11111111-1111-1111-1111-111111111111",
    )


@requires_postgres
@pytest.mark.django_db
def test_readiness_endpoint_requires_authentication() -> None:
    response = Client().get("/api/v1/config/market-data/live-paper-readiness/")
    assert response.status_code in (401, 403)


@requires_postgres
@pytest.mark.django_db
def test_no_credential_configured_reports_not_configured_and_blocks_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A REAL finding this checkpoint: `DhanSettingsService.effective_
    credentials()` (Checkpoint 22) falls back to `DHAN_CLIENT_ID`/
    `DHAN_ACCESS_TOKEN` env vars when nothing is saved in the DB - this
    dev environment's own `.env` sets both (with the real, expired
    token from Checkpoint 64.11's investigation), so "nothing in the
    DB" alone does not mean "nothing configured at all." This test
    isolates the truly-unconfigured case explicitly, matching the
    real precedence rule rather than assuming a clean environment."""
    monkeypatch.delenv("DHAN_CLIENT_ID", raising=False)
    monkeypatch.delenv("DHAN_ACCESS_TOKEN", raising=False)
    client = _client()

    response = client.get("/api/v1/config/market-data/live-paper-readiness/")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "NOT_CONFIGURED"
    assert body["can_start"] is False
    assert body["real_trading_state"] == "DISABLED"


@requires_postgres
@pytest.mark.django_db
def test_expired_credential_reports_credential_expired_and_blocks_start() -> None:
    expired_token = _fake_jwt(exp=datetime.now(tz=UTC) - timedelta(days=1))
    _save_credential(client_id="test-client", access_token=expired_token)
    client = _client()

    response = client.get("/api/v1/config/market-data/live-paper-readiness/")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "CREDENTIAL_EXPIRED"
    assert body["can_start"] is False
    assert "renew" in body["remediation"].lower()
    assert body["credential_expiry"] is not None


@requires_postgres
@pytest.mark.django_db
def test_malformed_credential_reports_credential_invalid() -> None:
    _save_credential(client_id="test-client", access_token="not-a-real-jwt")
    client = _client()

    response = client.get("/api/v1/config/market-data/live-paper-readiness/")

    assert response.status_code == 200
    assert response.json()["state"] == "CREDENTIAL_INVALID"


@requires_postgres
@pytest.mark.django_db
def test_valid_credential_with_no_worker_report_blocks_on_provider_unavailable() -> None:
    valid_token = _fake_jwt(exp=datetime.now(tz=UTC) + timedelta(hours=12))
    _save_credential(client_id="test-client", access_token=valid_token)
    client = _client()

    response = client.get("/api/v1/config/market-data/live-paper-readiness/")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "PROVIDER_UNAVAILABLE"
    assert body["can_start"] is False
    assert body["provider_state"] == "NEVER_REPORTED"


@requires_postgres
@pytest.mark.django_db
def test_response_never_contains_the_configured_token_value() -> None:
    valid_token = _fake_jwt(exp=datetime.now(tz=UTC) + timedelta(hours=12))
    _save_credential(client_id="test-client", access_token=valid_token)
    client = _client()

    response = client.get("/api/v1/config/market-data/live-paper-readiness/")

    assert valid_token not in response.content.decode()
    assert "test-client" not in response.content.decode()


@requires_postgres
@pytest.mark.django_db
def test_expired_credential_does_not_break_the_signal_report_endpoint() -> None:
    """Checkpoint 64.12 §8/§12: an expired Dhan credential must NOT
    break historical/research surfaces - the Signal Report (Checkpoint
    64.10) reads only `SignalRecord`, never the Dhan credential."""
    expired_token = _fake_jwt(exp=datetime.now(tz=UTC) - timedelta(days=1))
    _save_credential(client_id="test-client", access_token=expired_token)
    client = _client()

    response = client.get("/api/v1/config/reports/signals/")

    assert response.status_code == 200
    assert response.json()["total_signals"] == 0


@requires_postgres
@pytest.mark.django_db
def test_the_actual_configured_environment_credential_reports_expired_honestly() -> None:
    """No DB credential saved, no monkeypatch - this exercises the gate
    against THIS environment's real `.env` `DHAN_ACCESS_TOKEN` (the
    same one Checkpoint 64.11 decoded and found expired). If a human
    operator later renews it, this exact test's assertion would need
    updating - that is the intended, honest behavior, not a bug."""
    client = _client()

    response = client.get("/api/v1/config/market-data/live-paper-readiness/")

    assert response.status_code == 200
    body = response.json()
    # Confirmed via manage.py shell this checkpoint: this environment's
    # real .env DHAN_ACCESS_TOKEN's own `exp` claim is still in the past.
    assert body["state"] == "CREDENTIAL_EXPIRED"
    assert body["can_start"] is False
    assert body["real_trading_state"] == "DISABLED"


@requires_postgres
@pytest.mark.django_db
def test_expired_credential_does_not_break_the_daily_session_report_endpoint() -> None:
    expired_token = _fake_jwt(exp=datetime.now(tz=UTC) - timedelta(days=1))
    _save_credential(client_id="test-client", access_token=expired_token)
    client = _client()

    response = client.get("/api/v1/config/reports/daily-session/")

    assert response.status_code == 200
    assert response.json()["total_signals"] == 0


# --- Checkpoint 64.14: the Pre-Session Readiness Workbench endpoint -----


@requires_postgres
@pytest.mark.django_db
def test_workbench_requires_authentication() -> None:
    response = Client().get("/api/v1/config/market-data/live-paper-workbench/")
    assert response.status_code in (401, 403)


@requires_postgres
@pytest.mark.django_db
def test_workbench_returns_all_ten_checklist_items_in_order() -> None:
    client = _client()

    response = client.get("/api/v1/config/market-data/live-paper-workbench/")

    assert response.status_code == 200
    body = response.json()
    assert [item["label"] for item in body["checklist"]] == [
        "Dhan Credential",
        "Provider Connectivity",
        "Token Validity",
        "Watchdog",
        "Market State",
        "Universe",
        "Timeframe",
        "Strategy Selection",
        "Paper Execution",
        "Real Trading Safety",
    ]
    for item in body["checklist"]:
        assert item["state"] in ("READY", "WARNING", "BLOCKED", "UNKNOWN")


@requires_postgres
@pytest.mark.django_db
def test_workbench_reports_a_real_session_state_and_no_drift_when_never_started() -> None:
    client = _client()

    response = client.get("/api/v1/config/market-data/live-paper-workbench/")

    assert response.status_code == 200
    body = response.json()
    assert body["session_state"] in ("NOT_READY", "READY")
    config = body["effective_session_configuration"]
    assert config["effective_configuration_version"] == 0
    assert config["drift"] is True  # never reconciled at all (desired=1, effective=0)


@requires_postgres
@pytest.mark.django_db
def test_workbench_shows_no_drift_once_desired_and_effective_versions_match() -> None:
    from intraday.infrastructure.persistence.models import WorkerRuntimeStatus

    WorkerRuntimeStatus.objects.update_or_create(
        provider="dhan",
        defaults={
            "watchdog_state": "HEALTHY",
            "effective_configuration_version": 1,
            "effective_timeframe": "1m",
            "effective_strategy_ids": [],
        },
    )
    client = _client()

    response = client.get("/api/v1/config/market-data/live-paper-workbench/")

    assert response.status_code == 200
    config = response.json()["effective_session_configuration"]
    assert config["drift"] is False
    assert config["effective_configuration_version"] == config["desired_configuration_version"]


@requires_postgres
@pytest.mark.django_db
def test_workbench_reports_failed_session_state_on_a_real_worker_failure() -> None:
    from intraday.infrastructure.persistence.models import WorkerRuntimeStatus

    WorkerRuntimeStatus.objects.update_or_create(
        provider="dhan",
        defaults={"worker_state": "TOKEN_EXPIRED", "watchdog_state": "DISCONNECTED"},
    )
    client = _client()

    response = client.get("/api/v1/config/market-data/live-paper-workbench/")

    assert response.status_code == 200
    assert response.json()["session_state"] == "FAILED"
