# tests/unit/infrastructure/persistence/test_repositories.py
#
# Repository-level tests (Checkpoint 7 §22): create, read, version
# resolution, immutability (no update path exists), missing records,
# duplicate-version rejection. All gated by requires_postgres.
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from intraday.application.config_schema.records import RiskConfigurationRecord
from intraday.application.repositories import DuplicateVersionError
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.risk.contracts import RiskLimits
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe, Version
from intraday.domain.strategy.contracts import StrategyMaturityState, StrategyVersion
from intraday.domain.universe.contracts import Universe, UniverseMember, UniverseMembershipStatus
from intraday.infrastructure.persistence.models import AuditLogEntry
from intraday.infrastructure.persistence.repositories import (
    DjangoRiskConfigurationRepository,
    DjangoStrategyVersionRepository,
    DjangoUniverseRepository,
)
from tests.postgres_utils import requires_postgres

NOW = datetime(2026, 1, 1, 9, 20, tzinfo=UTC)


def _risk_record(version: str = "v1") -> RiskConfigurationRecord:
    return RiskConfigurationRecord(
        risk_configuration_id="default",
        version=Version(value=version),
        limits=RiskLimits(
            max_intraday_loss=Decimal("10000.00"),
            max_position_size=Decimal("50000.00"),
            max_per_trade_risk=Decimal("2000.00"),
        ),
        created_at=NOW,
    )


@requires_postgres
@pytest.mark.django_db
def test_risk_repository_save_and_get_version() -> None:
    repo = DjangoRiskConfigurationRepository()
    repo.save(_risk_record())
    fetched = repo.get_version("default", "v1")
    assert fetched is not None
    assert fetched.limits.max_intraday_loss == Decimal("10000.00")


@requires_postgres
@pytest.mark.django_db
def test_risk_repository_missing_version_returns_none() -> None:
    repo = DjangoRiskConfigurationRepository()
    assert repo.get_version("default", "does-not-exist") is None
    assert repo.get_active("default") is None


@requires_postgres
@pytest.mark.django_db
def test_risk_repository_duplicate_save_raises_duplicate_version_error() -> None:
    repo = DjangoRiskConfigurationRepository()
    repo.save(_risk_record())
    with pytest.raises(DuplicateVersionError):
        repo.save(_risk_record())


@requires_postgres
@pytest.mark.django_db
def test_risk_repository_activate_then_get_active() -> None:
    """Checkpoint 17.2: `activate()` gained keyword-only `actor`/
    `actor_user_id`/`request_id` at Checkpoint 12 (the append-only audit
    trail - see docs/architecture/AUDITABILITY.md) - this test was never
    updated to pass them and was silently never running (PostgreSQL was
    unreachable in every prior checkpoint's sandbox). Fixed to supply
    them AND to verify the actual intended behavior those parameters
    exist for: a matching, correctly-populated `AuditLogEntry` row is
    created in the same transaction as the activation - not just that
    the call no longer raises `TypeError`."""
    repo = DjangoRiskConfigurationRepository()
    repo.save(_risk_record("v1"))
    repo.save(_risk_record("v2"))

    repo.activate("default", "v2", actor="ux_test_operator", actor_user_id=7, request_id="req-1")

    active = repo.get_active("default")
    assert active is not None
    assert active.version.value == "v2"

    entry = AuditLogEntry.objects.get(resource_id="default", version_identifier="v2")
    assert entry.actor_username == "ux_test_operator"
    assert entry.actor_user_id == 7
    assert entry.request_id == "req-1"
    assert entry.action == "configuration.activate"
    assert entry.resource_type == "risk_configuration"
    assert entry.outcome == "activated"


@requires_postgres
@pytest.mark.django_db
def test_risk_repository_activate_unknown_version_raises() -> None:
    """Checkpoint 17.2: same signature fix as above, plus verification
    that a REJECTED activation attempt is still durably recorded
    (Checkpoint 12 §9: a failed attempt must not be silently unrecorded)."""
    repo = DjangoRiskConfigurationRepository()

    with pytest.raises(ValueError, match="unknown version"):
        repo.activate(
            "default", "nonexistent", actor="ux_test_operator", actor_user_id=7, request_id="req-2"
        )

    entry = AuditLogEntry.objects.get(resource_id="default", version_identifier="nonexistent")
    assert entry.outcome == "rejected"
    assert entry.request_id == "req-2"


@requires_postgres
@pytest.mark.django_db
def test_risk_repository_list_versions_preserves_all_history() -> None:
    repo = DjangoRiskConfigurationRepository()
    repo.save(_risk_record("v1"))
    repo.save(_risk_record("v2"))
    versions = repo.list_versions("default")
    assert {record.version.value for record in versions} == {"v1", "v2"}


@requires_postgres
@pytest.mark.django_db
def test_universe_repository_round_trips_members() -> None:
    repo = DjangoUniverseRepository()
    universe = Universe(
        universe_id="example",
        version=Version(value="v1"),
        exchange=Exchange.NSE,
        members=(
            UniverseMember(
                make_instrument_id(Exchange.NSE, "RELIANCE"), UniverseMembershipStatus.INCLUDED
            ),
        ),
    )
    repo.save(universe)
    fetched = repo.get_version("example", "v1")
    assert fetched is not None
    assert fetched.universe.contains(make_instrument_id(Exchange.NSE, "RELIANCE"))
    assert fetched.created_at is not None


@requires_postgres
@pytest.mark.django_db
def test_strategy_version_repository_identity_and_activation() -> None:
    """Checkpoint 17.2: same stale-signature fix as the risk repository
    tests above - `activate()` gained `actor`/`actor_user_id`/
    `request_id` at Checkpoint 13, never reflected here."""
    repo = DjangoStrategyVersionRepository()
    version = StrategyVersion(
        strategy_id="example-strategy",
        specification_version=Version(value="spec-v1"),
        code_version=Version(value="code-v1"),
        configuration_version=Version(value="cfg-v1"),
        universe_version=Version(value="v1"),
        timeframe=Timeframe.FIVE_MINUTE,
        maturity_state=StrategyMaturityState.IDEA,
    )
    repo.save(version)
    fetched = repo.get_version("example-strategy", "spec-v1", "code-v1", "cfg-v1")
    assert fetched is not None
    assert fetched.strategy_version.maturity_state is StrategyMaturityState.IDEA

    repo.activate(
        "example-strategy",
        "spec-v1",
        "code-v1",
        "cfg-v1",
        actor="ux_test_operator",
        actor_user_id=7,
        request_id="req-3",
    )
    active = repo.get_active("example-strategy")
    assert active is not None
    assert active.strategy_version.specification_version.value == "spec-v1"

    entry = AuditLogEntry.objects.get(
        resource_id="example-strategy", version_identifier="spec-v1:code-v1:cfg-v1"
    )
    assert entry.actor_username == "ux_test_operator"
    assert entry.resource_type == "strategy_version"
    assert entry.outcome == "activated"
