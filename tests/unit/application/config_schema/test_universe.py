# tests/unit/application/config_schema/test_universe.py
#
# Unit tests for the Universe config loader (Checkpoint 6).
from __future__ import annotations

import pytest

from intraday.application.config_schema.errors import ConfigValidationError
from intraday.application.config_schema.universe import load_universe
from intraday.domain.shared_kernel.contracts import Exchange


def test_valid_raw_dict_loads_into_universe() -> None:
    universe = load_universe(
        {
            "universe_id": "example",
            "version": "v1",
            "exchange": "NSE",
            "members": [{"symbol": "RELIANCE", "status": "INCLUDED"}],
        }
    )
    assert universe.exchange is Exchange.NSE
    assert len(universe.members) == 1


def test_member_status_defaults_to_included() -> None:
    universe = load_universe(
        {
            "universe_id": "example",
            "version": "v1",
            "exchange": "NSE",
            "members": [{"symbol": "TCS"}],
        }
    )
    assert universe.members[0].status.name == "INCLUDED"


def test_invalid_exchange_raises_config_validation_error() -> None:
    with pytest.raises(ConfigValidationError):
        load_universe({"universe_id": "x", "version": "v1", "exchange": "NASDAQ"})


def test_missing_universe_id_raises_config_validation_error() -> None:
    with pytest.raises(ConfigValidationError):
        load_universe({"version": "v1", "exchange": "NSE"})
