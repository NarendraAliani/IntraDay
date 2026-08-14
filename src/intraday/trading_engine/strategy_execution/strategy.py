# File: src/intraday/trading_engine/strategy_execution/strategy.py
#
# Checkpoint 26: the `Strategy` Protocol every executable strategy
# implements. Deliberately minimal - a strategy declares its own
# parameter schema and required features, and evaluates one bar at a
# time given already-computed feature values; it never reads Django,
# env vars, the frontend, YAML, or the ORM directly (Part 3), and never
# calls another strategy (Part 9).
from __future__ import annotations

from typing import Protocol

from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.trading_engine.strategy_execution.contracts import (
    StrategyConfigurationValues,
    StrategyParameterSchema,
    StrategySignal,
)


class Strategy(Protocol):
    strategy_id: str
    display_name: str
    specification_version: str
    code_version: str

    def parameter_schema(self) -> StrategyParameterSchema: ...

    def required_features(self, config: StrategyConfigurationValues) -> tuple[str, ...]:
        """Returns the field_ids (from the canonical field registry) this
        strategy needs computed for the given configuration - lets the
        coordinator compute shared features once, not per-strategy."""
        ...

    def evaluate(
        self,
        bar: Bar,
        feature_values: dict[str, FeatureValue],
        config: StrategyConfigurationValues,
    ) -> StrategySignal | None:
        """Returns a `StrategySignal` for this bar, or `None` if the
        strategy has no opinion (e.g. insufficient warm-up data) -
        mirrors `generate_directional_indications`' own policy of never
        fabricating a signal for missing data."""
        ...
