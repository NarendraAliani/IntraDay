# src/intraday/domain/__init__.py
#
# Package boundary for the shared kernel (Checkpoint 4 scaffolding only).
# Holds the 14 canonical, technology-neutral contracts approved at
# Checkpoints 1-2 (shared_kernel, market_data, instrument, universe,
# feature, strategy, signal, risk, portfolio, order, position, trade,
# broker, session) — see docs/architecture/DOMAIN_BOUNDARIES.md. No
# contract is implemented yet; that begins at Checkpoint 5. This file
# exists only so import-linter has a real package to enforce dependency
# rules against, and must remain free of any import from research,
# signal_intelligence, trading_engine, control_plane, communication,
# application, or infrastructure.
