# File: src/intraday/domain/shared_kernel/slippage.py
#
# Checkpoint 64.40: the ONE shared, pure slippage-adjustment formula.
# Before this checkpoint, `research.backtesting.cost_model` (both
# `FlatPercentageCostModel.slippage_adjusted_price()` and
# `IndianCashEquityIntradayCostModel.slippage_adjusted_price()`) and
# `infrastructure.brokers.paper.broker.PaperBroker._attempt_fill()` each
# independently implemented the identical flat-percentage-against-the-
# trader formula (64.39's audit, "Slippage Semantics" finding). This
# module extracts that ONE formula so both callers compute the same
# number the same way, never two competing implementations that could
# silently drift apart.
#
# Deliberately placed in `domain.shared_kernel` (not
# `research.backtesting`, not `infrastructure`): it is a pure numeric
# function with no dependency on either bounded context, and
# `domain` is importable from both `research` and `infrastructure`
# (`.importlinter` contract 1/2 - domain is the innermost layer, nothing
# above it may be imported BY domain, but domain itself may be imported
# BY anything above it). This is the SAME placement pattern already used
# for `domain/trade/net_pnl.py` (64.37) and
# `domain/position/mark_to_market.py` (64.38) - one pure shared function,
# reused by both engines, never reimplemented.
#
# This module does NOT introduce a `Fill` contract, a slippage "engine",
# or any execution abstraction - it is exactly one function, matching
# the checkpoint 64.40 directive's explicit "prefer one pure function,
# not a SlippageEngine/SlippageManager" instruction.
from __future__ import annotations

from decimal import Decimal


def apply_flat_percentage_slippage(
    *, is_buy: bool, price: Decimal, slippage_percent: Decimal
) -> Decimal:
    """Returns `price` adjusted by a flat-percentage slippage model,
    ALWAYS moved against the trader - a BUY pays MORE
    (`price * (1 + slippage_percent/100)`), a SELL receives LESS
    (`price * (1 - slippage_percent/100)`). Never rounds (rounding
    policy is each caller's own responsibility - Backtest's
    `CostModel.slippage_adjusted_price()` has historically returned an
    UNROUNDED Decimal, and this extraction must not change that
    existing, verified numerical behavior; Paper rounds the result
    itself, exactly as it did before this extraction, via its own
    `_round()` helper applied AFTER calling this function).

    `slippage_percent` is a plain percentage (e.g. `Decimal("0.05")` for
    a 0.05% adjustment), matching both pre-existing call sites' own
    convention - never a fraction (0.0005) or a basis-point value.

    This is the ONE place the flat-percentage slippage FORMULA is
    written down (Checkpoint 64.40) - `research.backtesting.cost_model`
    and `infrastructure.brokers.paper.broker.PaperBroker` both call this
    function rather than each computing `price * (1 +/- factor)`
    independently.
    """
    if price <= 0:
        raise ValueError("price must be positive")
    if slippage_percent < 0:
        raise ValueError("slippage_percent must not be negative")
    factor = slippage_percent / Decimal("100")
    return price * (Decimal("1") + factor) if is_buy else price * (Decimal("1") - factor)
