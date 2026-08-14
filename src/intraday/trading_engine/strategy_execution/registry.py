# File: src/intraday/trading_engine/strategy_execution/registry.py
#
# Checkpoint 26 Part 8: authoritative strategy registry. In-memory,
# process-local (mirrors nothing needing a database - registration is a
# code-deployment-time fact, not user data; per-configuration VALUES are
# what get persisted, in `application/repositories/strategy_configuration.py`).
from __future__ import annotations

from dataclasses import dataclass, field

from intraday.trading_engine.strategy_execution.contracts import (
    StrategyConfigurationValues,
    validate_configuration,
)
from intraday.trading_engine.strategy_execution.errors import (
    DuplicateStrategyRegistrationError,
    UnknownStrategyError,
)
from intraday.trading_engine.strategy_execution.strategy import Strategy


@dataclass
class StrategyRegistry:
    _strategies: dict[str, Strategy] = field(default_factory=dict)
    _active: set[str] = field(default_factory=set)

    def register(self, strategy: Strategy) -> None:
        if strategy.strategy_id in self._strategies:
            raise DuplicateStrategyRegistrationError(
                f"strategy_id {strategy.strategy_id!r} is already registered"
            )
        self._strategies[strategy.strategy_id] = strategy

    def get(self, strategy_id: str) -> Strategy:
        try:
            return self._strategies[strategy_id]
        except KeyError as exc:
            raise UnknownStrategyError(f"unknown strategy_id {strategy_id!r}") from exc

    def list(self) -> tuple[Strategy, ...]:
        """Deterministic order - insertion order, matching
        `field_registry.list_fields()`'s own precedent."""
        return tuple(self._strategies.values())

    def activate(self, strategy_id: str) -> None:
        self.get(strategy_id)  # raises UnknownStrategyError if absent
        self._active.add(strategy_id)

    def deactivate(self, strategy_id: str) -> None:
        self.get(strategy_id)
        self._active.discard(strategy_id)

    def get_active(self) -> tuple[Strategy, ...]:
        return tuple(s for s in self._strategies.values() if s.strategy_id in self._active)

    def is_active(self, strategy_id: str) -> bool:
        return strategy_id in self._active

    def validate_configuration(
        self,
        strategy_id: str,
        config: StrategyConfigurationValues,
        *,
        known_field_ids: frozenset[str],
    ) -> None:
        strategy = self.get(strategy_id)
        schema = strategy.parameter_schema()
        validate_configuration(schema, config.values, known_field_ids=known_field_ids)


def build_default_registry() -> StrategyRegistry:
    """Builds a registry pre-populated with the checkpoint's initial
    strategy suite. The single place that knows the concrete strategy
    classes - callers (application services, tests) never import the
    individual strategy modules directly, preventing accidental
    duplicate/ad-hoc registration elsewhere."""
    from intraday.trading_engine.strategy_execution.strategies.atr_volatility_breakout import (
        AtrVolatilityBreakoutStrategy,
    )
    from intraday.trading_engine.strategy_execution.strategies.ema_crossover import (
        EmaCrossoverStrategy,
    )
    from intraday.trading_engine.strategy_execution.strategies.sma_trend_filter import (
        SmaTrendFilterStrategy,
    )

    registry = StrategyRegistry()
    registry.register(EmaCrossoverStrategy())
    registry.register(SmaTrendFilterStrategy())
    registry.register(AtrVolatilityBreakoutStrategy())
    return registry
