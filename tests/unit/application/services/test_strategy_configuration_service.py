# tests/unit/application/services/test_strategy_configuration_service.py
#
# Checkpoint 26: application-service tests, using an in-memory fake
# repository (mirrors every other application-service test in this
# codebase - no Django/Postgres dependency needed here).
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from intraday.application.config_schema.records import StrategyConfigurationSnapshot
from intraday.application.repositories import DuplicateVersionError
from intraday.application.services.errors import ResourceNotFoundError
from intraday.application.services.strategy_configuration import StrategyConfigurationService
from intraday.trading_engine.strategy_execution.errors import (
    InvalidParameterValueError,
    UnknownStrategyError,
)
from intraday.trading_engine.strategy_execution.registry import build_default_registry


@dataclass
class _FakeRepository:
    _rows: dict[tuple[str, str, str, str], StrategyConfigurationSnapshot] = field(
        default_factory=dict
    )

    def save(self, snapshot: StrategyConfigurationSnapshot) -> None:
        key = (
            snapshot.strategy_id,
            snapshot.specification_version,
            snapshot.code_version,
            snapshot.configuration_version,
        )
        if key in self._rows:
            raise DuplicateVersionError(f"duplicate {key!r}")
        self._rows[key] = snapshot

    def get(self, strategy_id, specification_version, code_version, configuration_version):
        return self._rows.get(
            (strategy_id, specification_version, code_version, configuration_version)
        )

    def list_for_strategy(self, strategy_id: str) -> tuple[StrategyConfigurationSnapshot, ...]:
        return tuple(row for key, row in self._rows.items() if key[0] == strategy_id)


def _service() -> StrategyConfigurationService:
    return StrategyConfigurationService(
        repository=_FakeRepository(), registry=build_default_registry()
    )


def test_save_configuration_validates_and_persists() -> None:
    service = _service()
    snapshot = service.save_configuration(
        "ema_crossover",
        "v1",
        "v1",
        "cfg-v1",
        {"fast_lookback": 5, "slow_lookback": 10},
        created_by="tester",
    )
    assert snapshot.parameter_values == {"fast_lookback": 5, "slow_lookback": 10}


def test_save_configuration_rejects_invalid_values() -> None:
    service = _service()
    with pytest.raises(InvalidParameterValueError):
        service.save_configuration(
            "ema_crossover",
            "v1",
            "v1",
            "cfg-v1",
            {"fast_lookback": "bad", "slow_lookback": 10},
            created_by="tester",
        )


def test_save_configuration_rejects_unknown_strategy() -> None:
    service = _service()
    with pytest.raises(UnknownStrategyError):
        service.save_configuration("nonexistent", "v1", "v1", "cfg-v1", {}, created_by="tester")


def test_get_configuration_raises_resource_not_found() -> None:
    service = _service()
    with pytest.raises(ResourceNotFoundError):
        service.get_configuration("ema_crossover", "v1", "v1", "nonexistent")


def test_list_configurations_for_unknown_strategy_raises() -> None:
    service = _service()
    with pytest.raises(UnknownStrategyError):
        service.list_configurations("nonexistent")
