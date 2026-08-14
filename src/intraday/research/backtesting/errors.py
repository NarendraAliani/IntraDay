# File: src/intraday/research/backtesting/errors.py
#
# Checkpoint 27: backtest-specific error types. Kept in this bounded
# context (not `domain/`), mirroring
# `trading_engine.strategy_execution.errors`'s own precedent.
from __future__ import annotations


class InvalidBacktestConfigurationError(ValueError):
    """Raised when a `BacktestConfiguration` fails validation (e.g. end
    date before start date, non-positive initial capital)."""


class InsufficientHistoricalDataError(ValueError):
    """Raised when the requested instrument/timeframe/date-range has no
    bars available at all - a backtest cannot run on zero bars."""
