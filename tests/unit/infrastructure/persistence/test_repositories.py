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
    repo = DjangoRiskConfigurationRepository()
    repo.save(_risk_record("v1"))
    repo.save(_risk_record("v2"))
    repo.activate("default", "v2")
    active = repo.get_active("default")
    assert active is not None
    assert active.version.value == "v2"


@requires_postgres
@pytest.mark.django_db
def test_risk_repository_activate_unknown_version_raises() -> None:
    repo = DjangoRiskConfigurationRepository()
    with pytest.raises(ValueError, match="unknown version"):
        repo.activate("default", "nonexistent")


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
    assert fetched.contains(make_instrument_id(Exchange.NSE, "RELIANCE"))


@requires_postgres
@pytest.mark.django_db
def test_strategy_version_repository_identity_and_activation() -> None:
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
    assert fetched.maturity_state is StrategyMaturityState.IDEA

    repo.activate("example-strategy", "spec-v1", "code-v1", "cfg-v1")
    active = repo.get_active("example-strategy")
    assert active is not None
    assert active.specification_version.value == "spec-v1"
