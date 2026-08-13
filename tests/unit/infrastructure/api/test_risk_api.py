# tests/unit/infrastructure/api/test_risk_api.py
#
# The single most important test in Checkpoint 8 (§19): a full vertical
# slice — persisted RiskConfiguration -> repository -> application
# service -> DRF endpoint -> HTTP response -> stable JSON contract —
# exercised through real Django/DRF integration (Django's test Client
# against the actual URLconf), not mocks. Gated by requires_postgres
# since it needs the real Django-ORM-backed repository.
#
# Checkpoint 12 fix: every endpoint here has required `IsAuthenticated`
# (and, for `activate`, `IsConfigurationOperator`) since Checkpoint 11 -
# but because these tests are always `requires_postgres`-skipped in
# every sandbox this project has been validated in, that regression was
# never actually exercised and caught until now. Every test that hits a
# protected endpoint now logs in first (`client.login()` - Django's
# direct auth-backend login, not an HTTP round-trip to /api/v1/auth/
# login/, which is what test_auth_api.py exists to test).
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from intraday.application.config_schema.records import RiskConfigurationRecord
from intraday.domain.risk.contracts import RiskLimits
from intraday.domain.shared_kernel.contracts import Version
from intraday.infrastructure.api.permissions import CONFIGURATION_OPERATOR_GROUP
from intraday.infrastructure.persistence.repositories import DjangoRiskConfigurationRepository
from tests.postgres_utils import requires_postgres

NOW = datetime(2026, 1, 1, 9, 20, tzinfo=UTC)
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
def test_full_vertical_slice_get_version() -> None:
    """persisted -> repository -> service -> endpoint -> stable JSON."""
    _seed("v1")
    client = _client_as_reader()

    response = client.get("/api/v1/config/risk/default/v1/")

    assert response.status_code == 200
    body = response.json()
    assert body["risk_configuration_id"] == "default"
    assert body["version"] == "v1"
    # Decimal values serialize as strings (DRF DecimalField default) —
    # exact precision preserved, never float rounding.
    assert body["limits"]["max_intraday_loss"] == "10000.00"
    assert body["limits"]["max_position_size"] == "50000.00"
    assert body["limits"]["max_per_trade_risk"] == "2000.00"
    # Timestamp serializes as ISO-8601 UTC.
    assert body["created_at"].startswith("2026-01-01T09:20:00")
    assert body["is_active"] is False


@requires_postgres
@pytest.mark.django_db
def test_list_versions_returns_all_saved_versions() -> None:
    _seed("v1")
    _seed("v2")
    client = _client_as_reader()

    response = client.get("/api/v1/config/risk/default/")

    assert response.status_code == 200
    versions = {entry["version"] for entry in response.json()}
    assert versions == {"v1", "v2"}


@requires_postgres
@pytest.mark.django_db
def test_get_active_returns_404_when_nothing_activated() -> None:
    _seed("v1")
    client = _client_as_reader()

    response = client.get("/api/v1/config/risk/default/active/")

    assert response.status_code == 404
    body = response.json()
    assert body["error_code"] == "not_found"
    assert "message" in body
    # No internal details leaked.
    serialized = str(body).lower()
    for forbidden in ("traceback", "django.db", "select ", "integrityerror"):
        assert forbidden not in serialized


@requires_postgres
@pytest.mark.django_db
def test_unknown_configuration_id_returns_404() -> None:
    client = _client_as_reader()

    response = client.get("/api/v1/config/risk/does-not-exist/v1/")

    assert response.status_code == 404
    assert response.json()["error_code"] == "not_found"


@requires_postgres
@pytest.mark.django_db
def test_activate_then_get_active_reflects_new_active_version() -> None:
    _seed("v1")
    _seed("v2")
    client = _client_as_operator()

    activate_response = client.post("/api/v1/config/risk/default/v2/activate/")
    assert activate_response.status_code == 200
    assert activate_response.json()["is_active"] is True

    active_response = client.get("/api/v1/config/risk/default/active/")
    assert active_response.status_code == 200
    assert active_response.json()["version"] == "v2"

    # Historical version remains unchanged and still fetchable.
    v1_response = client.get("/api/v1/config/risk/default/v1/")
    assert v1_response.status_code == 200
    assert v1_response.json()["is_active"] is False


@requires_postgres
@pytest.mark.django_db
def test_activate_is_idempotent() -> None:
    _seed("v1")
    client = _client_as_operator()

    first = client.post("/api/v1/config/risk/default/v1/activate/")
    second = client.post("/api/v1/config/risk/default/v1/activate/")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()


@requires_postgres
@pytest.mark.django_db
def test_activate_unknown_version_returns_404() -> None:
    _seed("v1")
    client = _client_as_operator()

    response = client.post("/api/v1/config/risk/default/nonexistent/activate/")

    assert response.status_code == 404
    assert response.json()["error_code"] == "invalid_activation"
