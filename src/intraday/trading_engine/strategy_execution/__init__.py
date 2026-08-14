# src/intraday/trading_engine/strategy_execution/__init__.py
#
# Package boundary for trading_engine/strategy_execution. Per Checkpoint
# 2 §4, this is the SOLE canonical home for strategy implementation
# (executable code satisfying domain.strategy) - used identically by
# live execution and, via the one narrow documented exception, by
# research.backtesting.
#
# Checkpoint 27: this package's PUBLIC surface (re-exported below) is
# what `research.backtesting` is permitted to depend on
# (`.importlinter` contracts 4/5's narrow exception). `research.backtesting`
# imports ONLY from this `__init__` - never a submodule path like
# `trading_engine.strategy_execution.contracts` directly - so the
# exempted dependency edge stays exactly the single, auditable one named
# in `.importlinter` ("research.backtesting -> trading_engine.
# strategy_execution"), not a growing set of submodule-specific holes.
from __future__ import annotations

from intraday.trading_engine.strategy_execution.contracts import (
    ParameterDefinition,
    ParameterType,
    StrategyConfigurationValues,
    StrategyDirection,
    StrategyParameterSchema,
    StrategySignal,
    validate_configuration,
)
from intraday.trading_engine.strategy_execution.registry import (
    StrategyRegistry,
    build_default_registry,
)
from intraday.trading_engine.strategy_execution.strategy import Strategy

__all__ = [
    "ParameterDefinition",
    "ParameterType",
    "Strategy",
    "StrategyConfigurationValues",
    "StrategyDirection",
    "StrategyParameterSchema",
    "StrategyRegistry",
    "StrategySignal",
    "build_default_registry",
    "validate_configuration",
]
