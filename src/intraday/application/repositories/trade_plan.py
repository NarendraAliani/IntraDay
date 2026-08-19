# File: src/intraday/application/repositories/trade_plan.py
#
# Checkpoint 64.7: the Protocol for the ONE persisted copy of a
# strategy-produced TradePlan (see `trading_engine.strategy_execution.
# contracts.TradePlan`'s own docstring for the architecture decision).
# `signal_id` is supplied by the caller (not carried on `TradePlan`
# itself) because a `TradePlan` is built by the strategy layer before
# the deterministic `signal_id` is derived downstream
# (`application.services.paper_signal_execution.derive_signal_id`).
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from intraday.trading_engine.strategy_execution.contracts import TradePlan


@dataclass(frozen=True, slots=True)
class TradePlanRecordView:
    signal_id: str
    strategy_id: str
    code_version: str
    calculation_method: str
    entry_price: Decimal | None
    stop_loss: Decimal | None
    target_1: Decimal | None
    target_2: Decimal | None
    target_3: Decimal | None
    trailing_stop_loss: Decimal | None
    generated_at: datetime


class TradePlanRepository(Protocol):
    def save(self, signal_id: str, plan: TradePlan) -> TradePlanRecordView: ...

    def get_by_signal_id(self, signal_id: str) -> TradePlanRecordView | None: ...


__all__ = ["TradePlanRecordView", "TradePlanRepository"]
