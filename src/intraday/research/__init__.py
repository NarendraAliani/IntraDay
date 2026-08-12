# src/intraday/research/__init__.py
#
# Package boundary for the Quant Research Lab bounded context (Checkpoint 4
# scaffolding only). See docs/architecture/DOMAIN_BOUNDARIES.md. No
# research code exists yet. Must not import trading_engine, control_plane,
# communication, or infrastructure, except the one narrow, CI-enforced
# exception documented in .importlinter and
# tests/unit/architecture/test_narrow_dependency_exception.py:
# intraday.research.backtesting -> intraday.trading_engine.strategy_execution.
