# tests/unit/infrastructure/api/test_audit_api.py
#
# Checkpoint 12: append-only control-plane audit trail tests, run
# through real Django/DRF integration (Django's test `Client` against
# the actual URLconf) and, where the guarantee is about the database
# transaction itself, direct ORM access - not mocks. Gated by
# `requires_postgres` since it needs the real Django-ORM-backed
# repository and a real transactional database (SQLite-in-memory would
# not faithfully exercise `transaction.atomic()` rollback semantics the
# same way).
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Group, User
from django.db import DatabaseError
from django.test import Client

from intraday.application.config_schema.records import RiskConfigurationRecord
from intraday.domain.risk.contracts import RiskLimits
from intraday.domain.shared_kernel.contracts import Version
from intraday.infrastructure.api.permissions import CONFIGURATION_OPERATOR_GROUP
from intraday.infrastructure.persistence.models import ActiveRiskConfiguration, AuditLogEntry
from intraday.infrastructure.persistence.repositories import DjangoRiskConfigurationRepository
from tests.postgres_utils import requires_postgres

NOW = dt.datetime(2026, 1, 1, 9, 20, tzinfo=dt.UTC)
READER_USERNAME = "reader"  # noqa: S105 - test fixture username, not a secret
OPERATOR_USERNAME = "operator"  # noqa: S105 - test fixture username, not a secret
PASSWORD = "correct-horse-battery-staple"  # noqa: S105 - test-only fixture credential


def _seed(version: str = "v1") -> None:
    DjangoRiskConfigurationRepository().save(
        RiskConfigurationRecord(
            risk_configuration_id="default",
            version=Version(value=version),
            limits=RiskLimits(
                max_intraday_loss=Decimal("10000.00"),
                max_position_size=Decimal("50000.00"),
                max_per_trade_risk=Decimal("2000.00"),
            ),
            created_at=NOW,
        )
    )


def _operator() -> User:
    user = User.objects.create_user(username=OPERATOR_USERNAME, password=PASSWORD)
    group, _ = Group.objects.get_or_create(name=CONFIGURATION_OPERATOR_GROUP)
    user.groups.add(group)
    return user


def _client_as_operator() -> Client:
    _operator()
    client = Client()
    assert client.login(username=OPERATOR_USERNAME, password=PASSWORD)
    return client


def _client_as_reader() -> Client:
    User.objects.create_user(username=READER_USERNAME, password=PASSWORD)
    client = Client()
    assert client.login(username=READER_USERNAME, password=PASSWORD)
    return client


# ---------------------------------------------------------------------------
# Audit write path: actor capture, outcome semantics, integrity
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_successful_activation_creates_audit_row() -> None:
    _seed("v1")
    client = _client_as_operator()

    response = client.post("/api/v1/config/risk/default/v1/activate/")

    assert response.status_code == 200
    rows = AuditLogEntry.objects.filter(resource_type="risk_configuration", resource_id="default")
    assert rows.count() == 1
    row = rows.first()
    assert row.outcome == "activated"
    assert row.previous_version is None


@requires_postgres
@pytest.mark.django_db
def test_audit_integrity_matches_the_activation_that_produced_it() -> None:
    """Not merely 'some audit row exists' - every field must match the
    exact operation that was performed."""
    _seed("v1")
    _seed("v2")
    operator = _operator()
    client = Client()
    assert client.login(username=OPERATOR_USERNAME, password=PASSWORD)

    client.post("/api/v1/config/risk/default/v1/activate/")
    response = client.post("/api/v1/config/risk/default/v2/activate/")
    assert response.status_code == 200

    row = AuditLogEntry.objects.filter(
        resource_type="risk_configuration", resource_id="default", version_identifier="v2"
    ).get()
    assert row.actor_username == OPERATOR_USERNAME
    assert row.actor_user_id == operator.pk
    assert row.action == "configuration.activate"
    assert row.resource_type == "risk_configuration"
    assert row.resource_id == "default"
    assert row.version_identifier == "v2"
    assert row.previous_version == "v1"
    assert row.outcome == "activated"
    assert len(row.request_id) == 36  # a UUID4 string


@requires_postgres
@pytest.mark.django_db
def test_actor_identity_is_the_real_authenticated_user_never_a_placeholder() -> None:
    _seed("v1")
    operator = _operator()
    client = Client()
    assert client.login(username=OPERATOR_USERNAME, password=PASSWORD)

    client.post("/api/v1/config/risk/default/v1/activate/")

    row = AuditLogEntry.objects.get(resource_id="default")
    assert row.actor_username not in ("admin", "system", "unknown", "")
    assert row.actor_username == operator.get_username()
    assert row.actor_user_id == operator.pk


@requires_postgres
@pytest.mark.django_db
def test_already_active_activation_records_already_active_not_activated() -> None:
    _seed("v1")
    client = _client_as_operator()

    client.post("/api/v1/config/risk/default/v1/activate/")
    client.post("/api/v1/config/risk/default/v1/activate/")

    rows = list(
        AuditLogEntry.objects.filter(resource_id="default")
        .order_by("id")
        .values_list("outcome", flat=True)
    )
    assert rows == ["activated", "already_active"]


@requires_postgres
@pytest.mark.django_db
def test_failed_activation_records_rejected_not_success() -> None:
    """The system must not claim success when activation failed - and
    must not silently drop the record of the attempt either."""
    _seed("v1")
    client = _client_as_operator()

    response = client.post("/api/v1/config/risk/default/nonexistent/activate/")

    assert response.status_code == 404
    row = AuditLogEntry.objects.get(resource_id="default", version_identifier="nonexistent")
    assert row.outcome == "rejected"
    # No pointer was actually created.
    assert not ActiveRiskConfiguration.objects.filter(risk_configuration_id="default").exists()


# ---------------------------------------------------------------------------
# Transactional coupling - the critical guarantee
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_activation_rolls_back_if_audit_write_fails() -> None:
    """Exercises the REAL transaction boundary (`transaction.atomic()` in
    DjangoRiskConfigurationRepository.activate()), not a mocked service.
    Forces the audit INSERT to fail after the ActiveRiskConfiguration
    write has already happened inside the same atomic block, and proves
    the whole transaction - including the state change - rolled back."""
    _seed("v1")
    operator = _operator()

    with (
        patch(
            "intraday.infrastructure.persistence.repositories.AuditLogEntry.objects.create",
            side_effect=DatabaseError("simulated audit write failure"),
        ),
        pytest.raises(DatabaseError),
    ):
        DjangoRiskConfigurationRepository().activate(
            "default",
            "v1",
            actor=operator.get_username(),
            actor_user_id=operator.pk,
            request_id="11111111-1111-1111-1111-111111111111",
        )

    # The activation must not have survived the rollback: no active
    # pointer, no audit row - a successful state change cannot exist
    # without its required audit record.
    assert not ActiveRiskConfiguration.objects.filter(risk_configuration_id="default").exists()
    assert not AuditLogEntry.objects.filter(resource_id="default").exists()


# ---------------------------------------------------------------------------
# Append-only enforcement
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_audit_record_cannot_be_updated_through_normal_api() -> None:
    _seed("v1")
    client = _client_as_operator()
    client.post("/api/v1/config/risk/default/v1/activate/")
    row = AuditLogEntry.objects.get(resource_id="default")

    row.outcome = "rejected"
    with pytest.raises(RuntimeError, match="append-only"):
        row.save()


@requires_postgres
@pytest.mark.django_db
def test_audit_record_cannot_be_deleted_through_normal_api() -> None:
    _seed("v1")
    client = _client_as_operator()
    client.post("/api/v1/config/risk/default/v1/activate/")
    row = AuditLogEntry.objects.get(resource_id="default")

    with pytest.raises(RuntimeError, match="cannot be deleted"):
        row.delete()

    assert AuditLogEntry.objects.filter(pk=row.pk).exists()


# ---------------------------------------------------------------------------
# Audit read API
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_audit_read_requires_operator_capability_not_plain_read() -> None:
    _seed("v1")
    operator_client = _client_as_operator()
    operator_client.post("/api/v1/config/risk/default/v1/activate/")

    reader_client = _client_as_reader()
    response = reader_client.get("/api/v1/audit/risk-configuration/default/")

    assert response.status_code == 403


@requires_postgres
@pytest.mark.django_db
def test_audit_read_accessible_to_operator_and_reflects_recorded_events() -> None:
    _seed("v1")
    client = _client_as_operator()
    client.post("/api/v1/config/risk/default/v1/activate/")

    response = client.get("/api/v1/audit/risk-configuration/default/")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["resource_id"] == "default"
    assert body[0]["version"] == "v1"
    assert body[0]["outcome"] == "activated"
    assert body[0]["actor"] == OPERATOR_USERNAME


@requires_postgres
@pytest.mark.django_db
def test_audit_read_rejects_anonymous() -> None:
    response = Client().get("/api/v1/audit/risk-configuration/default/")
    assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Sensitive data
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_audit_response_never_contains_sensitive_fields() -> None:
    _seed("v1")
    client = _client_as_operator()
    client.post("/api/v1/config/risk/default/v1/activate/")

    response = client.get("/api/v1/audit/risk-configuration/default/")

    serialized = str(response.content).lower()
    for forbidden in ("password", "csrftoken", "sessionid", "secret", "authorization"):
        assert forbidden not in serialized
