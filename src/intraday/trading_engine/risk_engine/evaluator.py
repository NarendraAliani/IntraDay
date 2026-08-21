# File: src/intraday/trading_engine/risk_engine/evaluator.py
#
# Checkpoint 64.24: `RiskEvaluationContext`/`evaluate_order_risk()`
# were relocated to `intraday.domain.risk.policy` (the one layer every
# part of this codebase - trading_engine, application, AND research -
# is permitted to import; this is what allowed
# `research/backtesting/historical_execution.py` to stop maintaining a
# separate "verified port" of this same logic, Checkpoint 64.23). This
# module is now a thin backward-compatibility re-export shim, kept
# (rather than deleted) so any import path this refactor's own grep
# audit might have missed still resolves correctly. Prefer importing
# directly from `intraday.domain.risk.policy` in new code.
from __future__ import annotations

from intraday.domain.risk.policy import (
    RiskEvaluationContext as RiskEvaluationContext,
)
from intraday.domain.risk.policy import (
    evaluate_order_risk as evaluate_order_risk,
)

__all__ = ["RiskEvaluationContext", "evaluate_order_risk"]
