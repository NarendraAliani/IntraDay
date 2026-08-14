# File: src/intraday/research/backtesting/cost_model.py
#
# Checkpoint 28 Part 10/11: a provider-neutral cost-model abstraction.
# The engine (single-instrument and portfolio) never inlines a
# brokerage/slippage formula directly - it calls a `CostModel`. Today
# exactly one implementation exists (`FlatPercentageCostModel`, carried
# over unchanged from Checkpoint 27), explicitly labeled a MODEL
# ASSUMPTION - NOT a verified Indian brokerage/exchange-charge/tax
# formula (no authoritative source was available to verify against in
# either checkpoint). The Protocol exists so a future, more realistic
# model (fixed-points slippage, spread-based, volatility-aware,
# liquidity-aware, or a real Indian brokerage/STT/GST schedule) can be
# added as a second implementation WITHOUT touching the engine - Part 11
# explicitly scopes this checkpoint to "only create the abstraction
# necessary for later extension", not implement every future model now.
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from intraday.research.backtesting import StrategyDirection


class CostModel(Protocol):
    """What every cost model must answer, regardless of how it computes
    the answer internally."""

    def brokerage(self, notional: Decimal) -> Decimal:
        """Cost charged on one fill's notional value (entry or exit -
        called once per side, matching Checkpoint 27's own two-sided
        brokerage behavior)."""
        ...

    def slippage_adjusted_price(
        self, direction: StrategyDirection, price: Decimal, *, entering: bool
    ) -> Decimal:
        """Returns the actually-filled price after slippage - always
        moved AGAINST the trader (a long entry/short exit pays more, a
        short entry/long exit receives less)."""
        ...


@dataclass(frozen=True, slots=True)
class FlatPercentageCostModel:
    """MODEL ASSUMPTION (Checkpoint 27/28): brokerage is a flat
    percentage of notional; slippage is a flat percentage price
    adjustment. Carried over unchanged from Checkpoint 27's inline
    calculation - now isolated behind `CostModel` so it can be swapped
    for a more realistic model later without an engine change. NOT a
    verified Indian brokerage/STT/GST/exchange-charge schedule."""

    brokerage_percent: Decimal
    slippage_percent: Decimal

    def brokerage(self, notional: Decimal) -> Decimal:
        return notional * (self.brokerage_percent / Decimal("100"))

    def slippage_adjusted_price(
        self, direction: StrategyDirection, price: Decimal, *, entering: bool
    ) -> Decimal:
        factor = self.slippage_percent / Decimal("100")
        is_buy = (direction == StrategyDirection.BULLISH) == entering
        return price * (1 + factor) if is_buy else price * (1 - factor)
