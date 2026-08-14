# tests/validation/__init__.py
#
# Checkpoint 30: package for the independent reference-engine validation
# suite. `reference_engine.py` is a deliberately separate, independently
# derived implementation used ONLY for comparison against
# `src/intraday/research/backtesting`'s real engine - never imported by
# any `src/intraday` module (see `test_reference_engine_isolation.py`).
from __future__ import annotations
