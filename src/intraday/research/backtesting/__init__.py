# src/intraday/research/backtesting/__init__.py
#
# Package boundary for research/backtesting. This is the ONE package
# permitted the narrow, documented exception to import
# intraday.trading_engine.strategy_execution for backtest/live code-path
# parity (Checkpoint 2 §4, Checkpoint 3 §16) - mechanically enforced by
# `.importlinter` contracts 4/5 and independently re-verified by
# tests/unit/architecture/test_narrow_dependency_exception.py.
#
# `.importlinter`'s `ignore_imports` matches the EXACT source/target
# module pair named in `.importlinter` - "intraday.research.backtesting
# -> intraday.trading_engine.strategy_execution" - not any submodule
# pair. So this `__init__` is the SOLE place in `research.backtesting`
# that imports `trading_engine.strategy_execution` directly; every other
# module in this package (`contracts.py`, `engine.py`, ...) imports the
# re-exported names from here instead. This keeps the exempted
# dependency edge singular and auditable rather than growing into a set
# of submodule-specific holes (Checkpoint 27's own audit caught an
# earlier draft doing exactly that).
from __future__ import annotations

from intraday.trading_engine import strategy_execution as _strategy_execution
from intraday.trading_engine.strategy_execution import (
    Strategy,
    StrategyConfigurationValues,
    StrategyDirection,
    StrategyRegistry,
    StrategySignal,
    build_default_registry,
)

__all__ = [
    "Strategy",
    "StrategyConfigurationValues",
    "StrategyDirection",
    "StrategyRegistry",
    "StrategySignal",
    "build_default_registry",
]

_ = _strategy_execution  # referenced to satisfy linters; the re-exports above are what matter
