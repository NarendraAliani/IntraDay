# src/intraday/research/backtesting/__init__.py
#
# Package boundary for research/backtesting (Checkpoint 4 scaffolding
# only). This is the ONE package permitted the narrow, documented exception
# to import intraday.trading_engine.strategy_execution's implementation
# module for backtest/live code-path parity (Checkpoint 2 §4, Checkpoint 3
# §16). It must never import any other trading_engine submodule
# (risk_engine, order_management, execution_management, broker_abstraction,
# session_management) — mechanically enforced by .importlinter contract #5
# and independently re-verified by
# tests/unit/architecture/test_narrow_dependency_exception.py. No backtest
# engine code exists yet.
