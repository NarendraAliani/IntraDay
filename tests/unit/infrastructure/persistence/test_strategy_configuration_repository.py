# tests/unit/infrastructure/persistence/test_strategy_configuration_repository.py
#
# Checkpoint 26 Part 11/12: persistence and identity tests for
# `DjangoStrategyConfigurationRepository`. Gated by `requires_postgres`,
# matching every other Django-ORM repository test in this codebase.
from __future__ import annotations

import datetime as _dt

import pytest

from intraday.application.config_schema.records import StrategyConfigurationSnapshot
from intraday.application.repositories import DuplicateVersionError
from intraday.infrastructure.persistence.repositories import DjangoStrategyConfigurationRepository
from tests.postgres_utils import requires_postgres


def _snapshot(
    *,
    configuration_version: str = "cfg-v1",
    values: dict[str, object] | None = None,
) -> StrategyConfigurationSnapshot:
    return StrategyConfigurationSnapshot(
        strategy_id="ema_crossover",
        specification_version="spec-v1",
        code_version="code-v1",
        configuration_version=configuration_version,
        parameter_values=values or {"fast_lookback": 5, "slow_lookback": 10},
        created_at=_dt.datetime.now(tz=_dt.UTC),
        created_by="tester",
    )


@requires_postgres
@pytest.mark.django_db
def test_save_and_get_round_trips_values() -> None:
    repo = DjangoStrategyConfigurationRepository()
    repo.save(_snapshot())
    result = repo.get("ema_crossover", "spec-v1", "code-v1", "cfg-v1")
    assert result is not None
    assert result.parameter_values == {"fast_lookback": 5, "slow_lookback": 10}
    assert result.created_by == "tester"


@requires_postgres
@pytest.mark.django_db
def test_get_missing_configuration_returns_none() -> None:
    repo = DjangoStrategyConfigurationRepository()
    assert repo.get("ema_crossover", "spec-v1", "code-v1", "nonexistent") is None


@requires_postgres
@pytest.mark.django_db
def test_list_for_strategy_returns_chronological_order() -> None:
    repo = DjangoStrategyConfigurationRepository()
    repo.save(_snapshot(configuration_version="cfg-v1"))
    repo.save(_snapshot(configuration_version="cfg-v2"))
    results = repo.list_for_strategy("ema_crossover")
    assert [r.configuration_version for r in results] == ["cfg-v1", "cfg-v2"]


@requires_postgres
@pytest.mark.django_db
def test_saving_same_identity_twice_raises_duplicate_version_error() -> None:
    """Part 11: configurations are immutable once saved - identical
    identity is rejected, never silently overwritten."""
    repo = DjangoStrategyConfigurationRepository()
    repo.save(_snapshot(configuration_version="cfg-v1"))
    with pytest.raises(DuplicateVersionError):
        repo.save(_snapshot(configuration_version="cfg-v1", values={"fast_lookback": 99}))


@requires_postgres
@pytest.mark.django_db
def test_same_strategy_same_parameters_share_identity_only_if_same_configuration_version() -> None:
    """Part 12: identity is the 4-tuple, not the parameter values
    themselves - two DIFFERENT configuration_version labels never
    collide even with identical values."""
    repo = DjangoStrategyConfigurationRepository()
    repo.save(_snapshot(configuration_version="cfg-v1", values={"fast_lookback": 5}))
    repo.save(_snapshot(configuration_version="cfg-v2", values={"fast_lookback": 5}))
    results = repo.list_for_strategy("ema_crossover")
    assert len(results) == 2


@requires_postgres
@pytest.mark.django_db
def test_different_code_version_is_a_different_identity() -> None:
    repo = DjangoStrategyConfigurationRepository()
    repo.save(_snapshot(configuration_version="cfg-v1"))
    other = StrategyConfigurationSnapshot(
        strategy_id="ema_crossover",
        specification_version="spec-v1",
        code_version="code-v2",  # different code_version
        configuration_version="cfg-v1",
        parameter_values={"fast_lookback": 5, "slow_lookback": 10},
        created_at=_dt.datetime.now(tz=_dt.UTC),
        created_by="tester",
    )
    repo.save(other)  # must not raise DuplicateVersionError
    assert len(repo.list_for_strategy("ema_crossover")) == 2


@requires_postgres
@pytest.mark.django_db
def test_different_specification_version_is_a_different_identity() -> None:
    repo = DjangoStrategyConfigurationRepository()
    repo.save(_snapshot(configuration_version="cfg-v1"))
    other = StrategyConfigurationSnapshot(
        strategy_id="ema_crossover",
        specification_version="spec-v2",  # different specification_version
        code_version="code-v1",
        configuration_version="cfg-v1",
        parameter_values={"fast_lookback": 5, "slow_lookback": 10},
        created_at=_dt.datetime.now(tz=_dt.UTC),
        created_by="tester",
    )
    repo.save(other)  # must not raise DuplicateVersionError
    assert len(repo.list_for_strategy("ema_crossover")) == 2
