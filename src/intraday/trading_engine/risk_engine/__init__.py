# src/intraday/trading_engine/risk_engine/__init__.py
#
# Package boundary for trading_engine/risk_engine (Checkpoint 4 scaffolding
# only). Per Checkpoint 1 Rule 5.2, every signal must pass through this
# package before becoming an order; no strategy or research code may
# import it except via the risk-gated order flow in later checkpoints.
# research.backtesting is explicitly forbidden from importing this module
# (.importlinter contract #5) — no risk logic exists yet.
