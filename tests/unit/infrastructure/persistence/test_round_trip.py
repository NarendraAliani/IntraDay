# tests/unit/infrastructure/persistence/test_round_trip.py
#
# Full persistence round-trip tests (Checkpoint 7 §17):
#
#     config/*.yaml source
#         -> application/config_schema validated domain/application object
#         -> repository.save()
#         -> PostgreSQL
#         -> repository.get_version()
#         -> reconstructed domain/application object
#
# Verifies semantic (value) equality against the originally loaded
# object, not merely that a database row exists. All gated by
# requires_postgres.
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from intraday.application.config_schema.loader import load_yaml_config
from intraday.application.config_schema.records import RiskConfigurationRecord
from intraday.application.config_schema.risk import load_risk_limits
from intraday.application.config_schema.strategy import load_strategy_version
from intraday.application.config_schema.universe import load_universe
from intraday.domain.shared_kernel.contracts import Version
from intraday.infrastructure.persistence.repositories import (
    DjangoRiskConfigurationRepository,
    DjangoStrategyVersionRepository,
    DjangoUniverseRepository,
)
from tests.postgres_utils import requires_postgres

REPO_ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2026, 1, 1, 9, 20, tzinfo=UTC)


@requires_postgres
@pytest.mark.django_db
def test_risk_configuration_round_trip_from_example_yaml() -> None:
    raw = load_yaml_config(REPO_ROOT / "config" / "risk" / "default.yaml")
    limits = load_risk_limits(raw, source="config/risk/default.yaml")
    record = RiskConfigurationRecord(
        risk_configuration_id="default", version=Version(value="v1"), limits=limits, created_at=NOW
    )

    repo = DjangoRiskConfigurationRepository()
    repo.save(record)
    reconstructed = repo.get_version("default", "v1")

    assert reconstructed is not None
    assert reconstructed.limits == limits  # semantic equality, not just row existence
    assert reconstructed.version == record.version


@requires_postgres
@pytest.mark.django_db
def test_universe_round_trip_from_example_yaml() -> None:
    raw = load_yaml_config(REPO_ROOT / "config" / "universe" / "example.yaml")
    universe = load_universe(raw, source="config/universe/example.yaml")

    repo = DjangoUniverseRepository()
    repo.save(universe)
    reconstructed = repo.get_version(universe.universe_id, universe.version.value)

    assert reconstructed is not None
    assert reconstructed.universe_id == universe.universe_id
    assert reconstructed.version == universe.version
    assert reconstructed.exchange == universe.exchange
    assert set(reconstructed.members) == set(universe.members)


@requires_postgres
@pytest.mark.django_db
def test_strategy_version_round_trip_from_example_yaml() -> None:
    raw = load_yaml_config(REPO_ROOT / "config" / "strategies" / "example.yaml")
    strategy_version = load_strategy_version(raw, source="config/strategies/example.yaml")

    repo = DjangoStrategyVersionRepository()
    repo.save(strategy_version)
    reconstructed = repo.get_version(
        strategy_version.strategy_id,
        strategy_version.specification_version.value,
        strategy_version.code_version.value,
        strategy_version.configuration_version.value,
    )

    assert reconstructed == strategy_version  # full dataclass equality
