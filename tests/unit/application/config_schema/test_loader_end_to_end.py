# tests/unit/application/config_schema/test_loader_end_to_end.py
#
# End-to-end tests (Checkpoint 6): proves the full
# config/*.yaml -> loader -> domain-contract pipeline works against the
# actual example files committed under config/, not just synthetic dicts.
from __future__ import annotations

from pathlib import Path

from intraday.application.config_schema.loader import load_yaml_config
from intraday.application.config_schema.risk import load_risk_limits
from intraday.application.config_schema.strategy import load_strategy_version
from intraday.application.config_schema.universe import load_universe

REPO_ROOT = Path(__file__).resolve().parents[4]


def test_example_risk_config_loads_end_to_end() -> None:
    path = REPO_ROOT / "config" / "risk" / "default.yaml"
    raw = load_yaml_config(path)
    limits = load_risk_limits(raw, source=str(path))
    assert limits.max_intraday_loss > 0


def test_example_universe_config_loads_end_to_end() -> None:
    path = REPO_ROOT / "config" / "universe" / "example.yaml"
    raw = load_yaml_config(path)
    universe = load_universe(raw, source=str(path))
    assert len(universe.members) == 2


def test_example_strategy_config_loads_end_to_end() -> None:
    path = REPO_ROOT / "config" / "strategies" / "example.yaml"
    raw = load_yaml_config(path)
    version = load_strategy_version(raw, source=str(path))
    assert version.strategy_id == "example-strategy"
