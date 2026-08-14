# src/intraday/control_plane/market_data_health/__init__.py
#
# Package boundary for control_plane/market_data_health (previously an
# architecture placeholder — see market_data_health/README.md at the
# repo root: "Detects stale/missing/anomalous market data feeds").
# Checkpoint 23 gives this its first real content: `contracts.py`
# (state vocabulary) and `evaluator.py` (pure classification function).
# Supervisory only, per this context's own README — it observes and
# classifies data health, it never generates a signal or makes a
# trading decision (Checkpoint 2 §10's binary/supervisory authority
# boundary, same rule `control_plane/kill_switch` documents for itself).
