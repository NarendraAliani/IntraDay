# tests/unit/application/config_schema/test_strategy.py
#
# Unit tests for the StrategyVersion config loader (Checkpoint 6).
from __future__ import annotations

import pytest

from intraday.application.config_schema.errors import ConfigValidationError
from intraday.application.config_schema.strategy import load_strategy_version
from intraday.domain.strategy.contracts import StrategyMaturityState

VALID_RAW = {
    "strategy_id": "example-strategy",
    "specification_version": "spec-v1",
    "code_version": "unversioned",
    "configuration_version": "cfg-v1",
    "universe_version": "v1",
    "timeframe": "5m",
    "maturity_state": "IDEA",
}


def test_valid_raw_dict_loads_into_strategy_version() -> None:
    version = load_strategy_version(VALID_RAW)
    assert version.maturity_state is StrategyMaturityState.IDEA


def test_invalid_maturity_state_raises_config_validation_error() -> None:
    raw = {**VALID_RAW, "maturity_state": "NOT_A_STATE"}
    with pytest.raises(ConfigValidationError):
        load_strategy_version(raw)


def test_invalid_timeframe_raises_config_validation_error() -> None:
    raw = {**VALID_RAW, "timeframe": "7m"}
    with pytest.raises(ConfigValidationError):
        load_strategy_version(raw)


def test_missing_field_raises_config_validation_error() -> None:
    raw = dict(VALID_RAW)
    del raw["code_version"]
    with pytest.raises(ConfigValidationError):
        load_strategy_version(raw)
