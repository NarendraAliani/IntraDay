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
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.risk.contracts import RiskLimits
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe, Version
from intraday.domain.strategy.contracts import StrategyMaturityState, StrategyVersion
from intraday.domain.universe.contracts import Universe, UniverseMember, UniverseMembershipStatus
from intraday.infrastructure.api.permissions import CONFIGURATION_OPERATOR_GROUP
from intraday.infrastructure.persistence.models import (
    ActiveRiskConfiguration,
    ActiveStrategyVersion,
    ActiveUniverse,
    AuditLogEntry,
)
from intraday.infrastructure.persistence.repositories import (
    DjangoRiskConfigurationRepository,
    DjangoStrategyVersionRepository,
    DjangoUniverseRepository,
)
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


def _seed_universe(version: str = "v1") -> None:
    DjangoUniverseRepository().save(
        Universe(
            universe_id="example",
            version=Version(value=version),
            exchange=Exchange.NSE,
            members=(
                UniverseMember(
                    make_instrument_id(Exchange.NSE, "RELIANCE"), UniverseMembershipStatus.INCLUDED
                ),
            ),
        )
    )


STRATEGY_ACTIVATE_PATH = "/api/v1/config/strategy/example-strategy/spec-v1/code-v1/cfg-v1/activate/"


def _seed_strategy() -> None:
    DjangoStrategyVersionRepository().save(
        StrategyVersion(
            strategy_id="example-strategy",
            specification_version=Version(value="spec-v1"),
            code_version=Version(value="code-v1"),
            configuration_version=Version(value="cfg-v1"),
            universe_version=Version(value="v1"),
            timeframe=Timeframe.FIVE_MINUTE,
            maturity_state=StrategyMaturityState.IDEA,
        )
    )


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


# ---------------------------------------------------------------------------
# Universe activation audit (Checkpoint 13 - same pattern as risk config)
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_universe_successful_activation_creates_audit_row() -> None:
    _seed_universe("v1")
    client = _client_as_operator()

    response = client.post("/api/v1/config/universe/example/v1/activate/")

    assert response.status_code == 200
    rows = AuditLogEntry.objects.filter(resource_type="universe", resource_id="example")
    assert rows.count() == 1
    row = rows.first()
    assert row.outcome == "activated"
    assert row.previous_version is None
    assert row.action == "configuration.activate"


@requires_postgres
@pytest.mark.django_db
def test_universe_audit_integrity_matches_the_activation_that_produced_it() -> None:
    _seed_universe("v1")
    _seed_universe("v2")
    operator = _operator()
    client = Client()
    assert client.login(username=OPERATOR_USERNAME, password=PASSWORD)

    client.post("/api/v1/config/universe/example/v1/activate/")
    response = client.post("/api/v1/config/universe/example/v2/activate/")
    assert response.status_code == 200

    row = AuditLogEntry.objects.filter(
        resource_type="universe", resource_id="example", version_identifier="v2"
    ).get()
    assert row.actor_username == OPERATOR_USERNAME
    assert row.actor_user_id == operator.pk
    assert row.resource_id == "example"
    assert row.previous_version == "v1"
    assert row.outcome == "activated"
    assert len(row.request_id) == 36


@requires_postgres
@pytest.mark.django_db
def test_universe_already_active_activation_records_already_active() -> None:
    _seed_universe("v1")
    client = _client_as_operator()

    client.post("/api/v1/config/universe/example/v1/activate/")
    client.post("/api/v1/config/universe/example/v1/activate/")

    outcomes = list(
        AuditLogEntry.objects.filter(resource_type="universe", resource_id="example")
        .order_by("id")
        .values_list("outcome", flat=True)
    )
    assert outcomes == ["activated", "already_active"]


@requires_postgres
@pytest.mark.django_db
def test_universe_failed_activation_records_rejected() -> None:
    _seed_universe("v1")
    client = _client_as_operator()

    response = client.post("/api/v1/config/universe/example/nonexistent/activate/")

    assert response.status_code == 404
    row = AuditLogEntry.objects.get(
        resource_type="universe", resource_id="example", version_identifier="nonexistent"
    )
    assert row.outcome == "rejected"
    assert not ActiveUniverse.objects.filter(universe_id="example").exists()


@requires_postgres
@pytest.mark.django_db
def test_universe_unauthorized_activation_rejected_and_not_audited() -> None:
    _seed_universe("v1")
    reader_client = _client_as_reader()

    response = reader_client.post("/api/v1/config/universe/example/v1/activate/")

    assert response.status_code == 403
    assert not AuditLogEntry.objects.filter(resource_type="universe").exists()


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_universe_activation_rolls_back_if_audit_write_fails() -> None:
    _seed_universe("v1")
    operator = _operator()

    with (
        patch(
            "intraday.infrastructure.persistence.repositories.AuditLogEntry.objects.create",
            side_effect=DatabaseError("simulated audit write failure"),
        ),
        pytest.raises(DatabaseError),
    ):
        DjangoUniverseRepository().activate(
            "example",
            "v1",
            actor=operator.get_username(),
            actor_user_id=operator.pk,
            request_id="22222222-2222-2222-2222-222222222222",
        )

    assert not ActiveUniverse.objects.filter(universe_id="example").exists()
    assert not AuditLogEntry.objects.filter(resource_type="universe").exists()


@requires_postgres
@pytest.mark.django_db
def test_universe_audit_read_requires_operator_capability() -> None:
    _seed_universe("v1")
    operator_client = _client_as_operator()
    operator_client.post("/api/v1/config/universe/example/v1/activate/")

    reader_client = _client_as_reader()
    response = reader_client.get("/api/v1/audit/universe/example/")

    assert response.status_code == 403


@requires_postgres
@pytest.mark.django_db
def test_universe_audit_read_accessible_to_operator() -> None:
    _seed_universe("v1")
    client = _client_as_operator()
    client.post("/api/v1/config/universe/example/v1/activate/")

    response = client.get("/api/v1/audit/universe/example/")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["resource_type"] == "universe"
    assert body[0]["resource_id"] == "example"
    assert body[0]["version"] == "v1"
    assert body[0]["outcome"] == "activated"


# ---------------------------------------------------------------------------
# Strategy-version activation audit (Checkpoint 13 - same pattern, with the
# 3-tuple identity flattened into a single audit `version_identifier`)
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_strategy_successful_activation_creates_audit_row() -> None:
    _seed_strategy()
    client = _client_as_operator()

    response = client.post(STRATEGY_ACTIVATE_PATH)

    assert response.status_code == 200
    rows = AuditLogEntry.objects.filter(
        resource_type="strategy_version", resource_id="example-strategy"
    )
    assert rows.count() == 1
    row = rows.first()
    assert row.outcome == "activated"
    assert row.version_identifier == "spec-v1:code-v1:cfg-v1"
    assert row.previous_version is None


@requires_postgres
@pytest.mark.django_db
def test_strategy_audit_integrity_preserves_exact_version_identity() -> None:
    """Verifies the exact StrategyVersion identity (the 3-tuple) is
    preserved in the audit row's flattened `version_identifier`, not
    simplified/lost."""
    _seed_strategy()
    operator = _operator()
    client = Client()
    assert client.login(username=OPERATOR_USERNAME, password=PASSWORD)

    response = client.post(STRATEGY_ACTIVATE_PATH)
    assert response.status_code == 200

    row = AuditLogEntry.objects.get(
        resource_type="strategy_version", resource_id="example-strategy"
    )
    assert row.actor_username == OPERATOR_USERNAME
    assert row.actor_user_id == operator.pk
    assert row.action == "configuration.activate"
    assert row.resource_id == "example-strategy"
    assert row.version_identifier == "spec-v1:code-v1:cfg-v1"
    assert len(row.request_id) == 36


@requires_postgres
@pytest.mark.django_db
def test_strategy_already_active_activation_records_already_active() -> None:
    _seed_strategy()
    client = _client_as_operator()

    client.post(STRATEGY_ACTIVATE_PATH)
    client.post(STRATEGY_ACTIVATE_PATH)

    outcomes = list(
        AuditLogEntry.objects.filter(resource_type="strategy_version")
        .order_by("id")
        .values_list("outcome", flat=True)
    )
    assert outcomes == ["activated", "already_active"]


@requires_postgres
@pytest.mark.django_db
def test_strategy_failed_activation_records_rejected() -> None:
    client = _client_as_operator()  # no seed - target identity does not exist

    response = client.post(STRATEGY_ACTIVATE_PATH)

    assert response.status_code == 404
    row = AuditLogEntry.objects.get(resource_type="strategy_version")
    assert row.outcome == "rejected"


@requires_postgres
@pytest.mark.django_db
def test_strategy_unauthorized_activation_rejected_and_not_audited() -> None:
    _seed_strategy()
    reader_client = _client_as_reader()

    response = reader_client.post(STRATEGY_ACTIVATE_PATH)

    assert response.status_code == 403
    assert not AuditLogEntry.objects.filter(resource_type="strategy_version").exists()


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_strategy_activation_rolls_back_if_audit_write_fails() -> None:
    _seed_strategy()
    operator = _operator()

    with (
        patch(
            "intraday.infrastructure.persistence.repositories.AuditLogEntry.objects.create",
            side_effect=DatabaseError("simulated audit write failure"),
        ),
        pytest.raises(DatabaseError),
    ):
        DjangoStrategyVersionRepository().activate(
            "example-strategy",
            "spec-v1",
            "code-v1",
            "cfg-v1",
            actor=operator.get_username(),
            actor_user_id=operator.pk,
            request_id="33333333-3333-3333-3333-333333333333",
        )

    assert not ActiveStrategyVersion.objects.filter(strategy_id="example-strategy").exists()
    assert not AuditLogEntry.objects.filter(resource_type="strategy_version").exists()


@requires_postgres
@pytest.mark.django_db
def test_strategy_audit_read_requires_operator_capability() -> None:
    _seed_strategy()
    operator_client = _client_as_operator()
    operator_client.post(STRATEGY_ACTIVATE_PATH)

    reader_client = _client_as_reader()
    response = reader_client.get("/api/v1/audit/strategy/example-strategy/")

    assert response.status_code == 403


@requires_postgres
@pytest.mark.django_db
def test_strategy_audit_read_accessible_to_operator() -> None:
    _seed_strategy()
    client = _client_as_operator()
    client.post(STRATEGY_ACTIVATE_PATH)

    response = client.get("/api/v1/audit/strategy/example-strategy/")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["resource_type"] == "strategy_version"
    assert body[0]["resource_id"] == "example-strategy"
    assert body[0]["version"] == "spec-v1:code-v1:cfg-v1"
    assert body[0]["outcome"] == "activated"


# ---------------------------------------------------------------------------
# Cross-resource consistency (Checkpoint 13 §16)
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_same_audit_vocabulary_used_across_all_three_resource_types() -> None:
    """Proves risk_configuration/universe/strategy_version audit records
    are all instances of the SAME AuditLogEntry schema/vocabulary,
    differing only by resource identity - not three independently
    evolved audit architectures. Guards against future architectural
    drift."""
    _seed("v1")
    _seed_universe("v1")
    _seed_strategy()
    client = _client_as_operator()

    client.post("/api/v1/config/risk/default/v1/activate/")
    client.post("/api/v1/config/universe/example/v1/activate/")
    client.post(STRATEGY_ACTIVATE_PATH)

    rows = AuditLogEntry.objects.order_by("resource_type")
    assert rows.count() == 3

    resource_types = {row.resource_type for row in rows}
    assert resource_types == {"risk_configuration", "universe", "strategy_version"}

    # Every row - regardless of resource type - populates exactly the same
    # field set with real, non-empty values. No resource type has its own
    # parallel schema or a differently-shaped record.
    for row in rows:
        assert row.action == "configuration.activate"
        assert row.actor_username == OPERATOR_USERNAME
        assert row.outcome == "activated"
        assert row.previous_version is None
        assert len(row.request_id) == 36
        assert row.occurred_at is not None

    # The read API surfaces the same field set for every resource type too.
    risk_audit = client.get("/api/v1/audit/risk-configuration/default/").json()
    universe_audit = client.get("/api/v1/audit/universe/example/").json()
    strategy_audit = client.get("/api/v1/audit/strategy/example-strategy/").json()
    for body in (risk_audit, universe_audit, strategy_audit):
        assert set(body[0].keys()) == {
            "actor",
            "action",
            "resource_type",
            "resource_id",
            "version",
            "previous_version",
            "outcome",
            "occurred_at",
            "request_id",
        }
