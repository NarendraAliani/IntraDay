# tests/unit/infrastructure/api/test_kill_switch_api.py
#
# Checkpoint 34 Part 11/18/19: full vertical slice for the kill switch -
# real Django ORM + DRF + RBAC, mirroring test_risk_api.py's own
# established pattern exactly.
from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from intraday.infrastructure.api.permissions import CONFIGURATION_OPERATOR_GROUP
from intraday.infrastructure.persistence.models import AuditLogEntry
from tests.postgres_utils import requires_postgres

READER_USERNAME = "ks-reader"  # noqa: S105 - test fixture username, not a secret
OPERATOR_USERNAME = "ks-operator"  # noqa: S105 - test fixture username, not a secret
PASSWORD = "correct-horse-battery-staple"  # noqa: S105 - test-only fixture credential


def _client_as_reader() -> Client:
    User.objects.create_user(username=READER_USERNAME, password=PASSWORD)
    client = Client()
    assert client.login(username=READER_USERNAME, password=PASSWORD)
    return client


def _client_as_operator() -> Client:
    user = User.objects.create_user(username=OPERATOR_USERNAME, password=PASSWORD)
    group, _ = Group.objects.get_or_create(name=CONFIGURATION_OPERATOR_GROUP)
    user.groups.add(group)
    client = Client()
    assert client.login(username=OPERATOR_USERNAME, password=PASSWORD)
    return client


@requires_postgres
@pytest.mark.django_db
def test_default_status_is_active() -> None:
    response = _client_as_reader().get("/api/v1/config/kill-switch/")
    assert response.status_code == 200
    assert response.json()["status"] == "ACTIVE"


@requires_postgres
@pytest.mark.django_db
def test_reader_cannot_engage() -> None:
    response = _client_as_reader().post(
        "/api/v1/config/kill-switch/engage/", {"reason": "test halt"}
    )
    assert response.status_code == 403


@requires_postgres
@pytest.mark.django_db
def test_operator_can_engage_and_reset() -> None:
    client = _client_as_operator()
    engage_response = client.post(
        "/api/v1/config/kill-switch/engage/",
        {"reason": "manual halt for testing"},
        content_type="application/json",
    )
    assert engage_response.status_code == 200
    assert engage_response.json()["status"] == "HALTED"
    assert engage_response.json()["reason"] == "manual halt for testing"

    status_response = _client_as_reader().get("/api/v1/config/kill-switch/")
    assert status_response.json()["status"] == "HALTED"

    reset_response = client.post("/api/v1/config/kill-switch/reset/")
    assert reset_response.status_code == 200
    assert reset_response.json()["status"] == "ACTIVE"


@requires_postgres
@pytest.mark.django_db
def test_engage_without_reason_is_rejected() -> None:
    client = _client_as_operator()
    response = client.post(
        "/api/v1/config/kill-switch/engage/", {}, content_type="application/json"
    )
    assert response.status_code == 400


@requires_postgres
@pytest.mark.django_db
def test_engage_and_reset_are_both_audited() -> None:
    client = _client_as_operator()
    client.post(
        "/api/v1/config/kill-switch/engage/",
        {"reason": "audited halt"},
        content_type="application/json",
    )
    client.post("/api/v1/config/kill-switch/reset/")

    actions = list(
        AuditLogEntry.objects.filter(resource_type="kill_switch").values_list("action", flat=True)
    )
    assert "kill_switch.engaged" in actions
    assert "kill_switch.reset" in actions


@requires_postgres
@pytest.mark.django_db
def test_anonymous_cannot_read_status() -> None:
    response = Client().get("/api/v1/config/kill-switch/")
    assert response.status_code in (401, 403)
