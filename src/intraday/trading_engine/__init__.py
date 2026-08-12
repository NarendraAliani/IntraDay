# src/intraday/trading_engine/__init__.py
#
# Package boundary for the Trading Engine bounded context (Checkpoint 4
# scaffolding only). See docs/architecture/DOMAIN_BOUNDARIES.md. No
# trading-engine code exists yet. Submodules risk_engine,
# order_management, execution_management, broker_abstraction,
# session_management, strategy_execution, strategy_registry, square_off,
# position_lifecycle, position_sizing, portfolio_management exist as empty
# packages so import-linter and the supplementary architecture test have
# real targets to enforce the narrow research.backtesting exception
# against (see .importlinter contract #5).
