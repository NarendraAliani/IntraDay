# File: src/intraday/trading_engine/risk_engine/contracts.py
#
# Checkpoint 64.24: `RiskRejectionReason`/`OrderRiskDecision` were
# relocated to `intraday.domain.risk.contracts` (the one layer every
# part of this codebase - trading_engine, application, AND research -
# is permitted to import). This module is now a thin backward-
# compatibility re-export shim, kept (rather than deleted) so any
# import path this refactor's own grep audit might have missed still
# resolves correctly. Prefer importing directly from
# `intraday.domain.risk.contracts` in new code.
from __future__ import annotations

from intraday.domain.risk.contracts import (
    OrderRiskDecision as OrderRiskDecision,
)
from intraday.domain.risk.contracts import (
    RiskRejectionReason as RiskRejectionReason,
)

__all__ = ["OrderRiskDecision", "RiskRejectionReason"]
