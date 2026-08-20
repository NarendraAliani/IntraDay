# tests/unit/infrastructure/api/test_live_paper_session_api.py
#
# Checkpoint 64.13: vertical-slice coverage for the explicit START/STOP
# endpoints - real Django test Client against the real URLconf, real
# repositories. Per §23, no real Dhan token is used anywhere -
# `_fake_jwt()` builds a deterministic, unsigned token shape only.
from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from intraday.infrastructure.api.permissions import CONFIGURATION_OPERATOR_GROUP
from intraday.infrastructure.persistence.kill_switch_repository import DjangoKillSwitchRepository
from intraday.infrastructure.persistence.provider_settings_repositories import (
    DjangoDhanCredentialRepository,
)
from tests.postgres_utils import requires_postgres

OPERATOR_USERNAME = "session_operator"  # noqa: S105
READER_USERNAME = "session_reader"  # noqa: S105
PASSWORD = "correct-horse-battery-staple"  # noqa: S105

START_URL = "/api/v1/config/market-data/live-paper-session/start/"
STOP_URL = "/api/v1/config/market-data/live-paper-session/stop/"


def _operator_client() -> Client:
    user = User.objects.create_user(username=OPERATOR_USERNAME, password=PASSWORD)
    group, _ = Group.objects.get_or_create(name=CONFIGURATION_OPERATOR_GROUP)
    user.groups.add(group)
    client = Client()
    assert client.login(username=OPERATOR_USERNAME, password=PASSWORD)
    return client


def _reader_client() -> Client:
    User.objects.create_user(username=READER_USERNAME, password=PASSWORD)
    client = Client()
    assert client.login(username=READER_USERNAME, password=PASSWORD)
    return client


def _fake_jwt(*, exp: datetime) -> str:
    def _segment(payload: dict[str, object]) -> str:
        raw = json.dumps(payload).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    header = _segment({"alg": "HS512", "typ": "JWT"})
    payload = _segment({"exp": int(exp.timestamp())})
    return f"{header}.{payload}.fake-signature-not-a-real-credential"


def _save_credential(*, access_token: str | None) -> None:
    DjangoDhanCredentialRepository().save(
        client_id="test-client",
        access_token=access_token,
        enabled=True,
        actor="tester",
        actor_user_id=1,
        request_id="11111111-1111-1111-1111-111111111111",
    )


@requires_postgres
@pytest.mark.django_db
def test_start_requires_authentication() -> None:
    response = Client().post(START_URL)
    assert response.status_code in (401, 403)


@requires_postgres
@pytest.mark.django_db
def test_start_requires_the_operator_role() -> None:
    client = _reader_client()

    response = client.post(START_URL)

    assert response.status_code == 403


@requires_postgres
@pytest.mark.django_db
def test_start_is_refused_with_an_expired_credential() -> None:
    """The actual expired token this environment has is used here
    indirectly - no DB override means the real .env fallback applies,
    exactly like the readiness gate itself (Checkpoint 64.12)."""
    client = _operator_client()

    response = client.post(START_URL)

    assert response.status_code == 409
    body = response.json()
    assert body["accepted"] is False
    assert body["state"] == "NOT_READY"
    assert body["remediation"] is not None
    assert body["enabled"] is False


@requires_postgres
@pytest.mark.django_db
def test_start_succeeds_with_a_valid_synthetic_token_and_a_healthy_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from intraday.infrastructure.persistence.models import WorkerRuntimeStatus

    valid_token = _fake_jwt(exp=datetime.now(tz=UTC) + timedelta(hours=12))
    _save_credential(access_token=valid_token)
    WorkerRuntimeStatus.objects.update_or_create(
        provider="dhan", defaults={"watchdog_state": "HEALTHY"}
    )
    client = _operator_client()

    response = client.post(START_URL)

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["enabled"] is True
    assert body["state"] == "STARTING"


@requires_postgres
@pytest.mark.django_db
def test_start_and_stop_write_distinguishable_audit_action_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Checkpoint 64.14 §10/§11: proves the audit trail can tell a
    live-paper-session start/stop apart from a generic scanner-config
    update - never a second audit table, the SAME AuditLogEntry model
    (Checkpoint 12), just a real, non-generic `action` label. Also
    confirms no secret is ever logged."""
    from intraday.infrastructure.persistence.models import AuditLogEntry, WorkerRuntimeStatus

    valid_token = _fake_jwt(exp=datetime.now(tz=UTC) + timedelta(hours=12))
    _save_credential(access_token=valid_token)
    WorkerRuntimeStatus.objects.update_or_create(
        provider="dhan", defaults={"watchdog_state": "HEALTHY"}
    )
    client = _operator_client()

    client.post(START_URL)
    client.post(STOP_URL)

    start_entry = AuditLogEntry.objects.filter(action="live_paper_session.start").latest("id")
    stop_entry = AuditLogEntry.objects.filter(action="live_paper_session.stop").latest("id")
    assert start_entry.resource_type == "scanner_configuration"
    assert start_entry.actor_username == OPERATOR_USERNAME
    assert stop_entry.actor_username == OPERATOR_USERNAME
    assert valid_token not in start_entry.request_id
    assert valid_token not in (start_entry.previous_version or "")


@requires_postgres
@pytest.mark.django_db
def test_start_is_idempotent_and_does_not_bump_the_version_twice() -> None:
    from intraday.infrastructure.persistence.models import WorkerRuntimeStatus

    valid_token = _fake_jwt(exp=datetime.now(tz=UTC) + timedelta(hours=12))
    _save_credential(access_token=valid_token)
    WorkerRuntimeStatus.objects.update_or_create(
        provider="dhan", defaults={"watchdog_state": "HEALTHY"}
    )
    client = _operator_client()

    first = client.post(START_URL)
    second = client.post(START_URL)

    assert first.status_code == 200
    assert first.json()["accepted"] is True
    assert second.status_code == 200
    assert second.json()["accepted"] is False
    assert second.json()["configuration_version"] == first.json()["configuration_version"]


@requires_postgres
@pytest.mark.django_db
def test_kill_switch_blocks_start_even_with_a_valid_token() -> None:
    from intraday.infrastructure.persistence.models import WorkerRuntimeStatus

    valid_token = _fake_jwt(exp=datetime.now(tz=UTC) + timedelta(hours=12))
    _save_credential(access_token=valid_token)
    WorkerRuntimeStatus.objects.update_or_create(
        provider="dhan", defaults={"watchdog_state": "HEALTHY"}
    )
    DjangoKillSwitchRepository().engage(
        reason="test halt", actor="tester", actor_user_id=1, request_id="req-halt"
    )
    client = _operator_client()

    response = client.post(START_URL)

    assert response.status_code == 409
    assert response.json()["accepted"] is False


@requires_postgres
@pytest.mark.django_db
def test_stop_is_idempotent_on_an_already_stopped_session() -> None:
    client = _operator_client()

    response = client.post(STOP_URL)

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is False
    assert "already stopped" in body["message"].lower()


@requires_postgres
@pytest.mark.django_db
def test_stop_succeeds_on_a_running_session_and_never_bypasses_rbac() -> None:
    unauthenticated = Client().post(STOP_URL)
    assert unauthenticated.status_code in (401, 403)

    reader_response = _reader_client().post(STOP_URL)
    assert reader_response.status_code == 403


@requires_postgres
@pytest.mark.django_db
def test_start_endpoint_never_exposes_the_configured_token_value() -> None:
    valid_token = _fake_jwt(exp=datetime.now(tz=UTC) + timedelta(hours=12))
    _save_credential(access_token=valid_token)
    client = _operator_client()

    response = client.post(START_URL)

    assert valid_token not in response.content.decode()


@requires_postgres
@pytest.mark.django_db
def test_start_and_stop_do_not_break_historical_reports() -> None:
    """Checkpoint 64.13 §18: starting/stopping the live session must
    not break historical/research surfaces."""
    client = _operator_client()
    client.post(START_URL)  # refused (no ready credential) - still must not break reports
    client.post(STOP_URL)

    response = client.get("/api/v1/config/reports/signals/")
    assert response.status_code == 200
    assert response.json()["total_signals"] == 0


@requires_postgres
@pytest.mark.django_db
def test_scanner_configuration_get_still_works_after_a_refused_start() -> None:
    client = _operator_client()
    client.post(START_URL)

    response = client.get("/api/v1/config/market-data/scanner-config/")
    assert response.status_code == 200
    assert response.json()["desired"]["enabled"] is False
