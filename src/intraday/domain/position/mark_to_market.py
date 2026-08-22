# File: src/intraday/domain/position/mark_to_market.py
#
# Checkpoint 64.38 — PAPER TRADING MARK-TO-MARKET: pure, additive
# open-position valuation. 64.37 closed the Risk Gate's REALIZED P&L
# divergence (`domain.trade.net_pnl.compute_realized_net_pnl`). The next
# gap 64.36/64.37 both named but deliberately left untouched: Paper
# Trading `Position.unrealized_pnl` remains `Decimal("0")` at every
# construction/update site in `infrastructure.brokers.paper.broker.
# PaperBroker` — an OPEN position's financial state was never actually
# observable. THIS module closes that gap with the smallest possible
# pure, dependency-free domain utility.
#
# ZERO DEPENDENCIES beyond `intraday.domain.position.contracts` and
# `intraday.domain.shared_kernel.contracts` — no ORM, no network, no
# Dhan, no strategy/risk code, mirroring `domain/trade/net_pnl.py`'s own
# "single pure function" discipline (Checkpoint 64.37) and
# `research/backtesting/mark_to_market.py`'s own already-proven
# direction-sign convention (Checkpoint 64.26/64.27), reused here rather
# than re-derived, so this module's sign convention is NOT a new,
# competing invention — see "SIGN CONVENTION" below.
#
# WHAT THIS MODULE DOES NOT DO: it does not decide what the mark price
# IS (no market-data call, no quote lookup, no Dhan import — the caller
# supplies `mark_price` explicitly, exactly like `PaperBroker.
# record_price()`'s own existing "caller supplies inputs" discipline —
# Checkpoint 34/35). It never mutates transaction-cost accounting,
# `realized_pnl`, or `realized_net_pnl` — those fields are read, never
# written, by every function in this module.
#
# SIGN CONVENTION (identical to `research/backtesting/mark_to_market.py`
# §"CASH-FLOW CONVENTION", reused verbatim, not reinvented):
#   direction_sign = +1 for BUY (long), -1 for SELL (short).
#   unrealized_pnl = direction_sign * remaining_quantity * (mark_price -
#                     average_entry_price)
#     - Long, mark above entry:  positive (profitable).
#     - Long, mark below entry:  negative (losing).
#     - Short, mark below entry: positive (profitable).
#     - Short, mark above entry: negative (losing).
#   market_value    = direction_sign * remaining_quantity * mark_price
#     - A long position's market value is a positive asset. A short
#       position's is carried NEGATIVE (a liability) — the SAME
#       convention `research/backtesting/mark_to_market.py` already
#       established and documented, reused here so a future
#       Backtest/Paper reconciliation checkpoint does not have to
#       resolve two different short-side sign conventions.
#
# COST TREATMENT (Checkpoint directive Rule 3/13, explicit): neither
# `compute_unrealized_pnl` nor `compute_market_value` deducts any
# transaction cost. `unrealized_pnl` is PURE PRICE P&L on the remaining
# open quantity — exit transaction costs are NOT yet deducted from it,
# exactly mirroring `research/backtesting/mark_to_market.py`'s own
# already-documented choice ("Unrealized valuation excludes exit
# costs" — `engine.py`'s `MarkToMarketPoint` docstring, §"MARK-TO-MARKET
# / EQUITY CURVE" above). This is a DELIBERATE, DOCUMENTED choice, not
# an oversight: `Position.realized_net_pnl` (64.37) is the cost-
# INCLUSIVE figure for CLOSED trades; `unrealized_pnl` (this checkpoint)
# is the cost-EXCLUSIVE figure for the OPEN remainder. The two are never
# summed as if they used the same cost convention without the caller
# understanding this asymmetry — documented again in `taskReport.md`
# 64.38 and the architecture doc addendum.
from __future__ import annotations

from decimal import Decimal

from intraday.domain.position.contracts import Position, PositionStatus
from intraday.domain.shared_kernel.contracts import Side


def _direction_sign(direction: Side) -> Decimal:
    return Decimal("1") if direction is Side.BUY else Decimal("-1")


def compute_unrealized_pnl(
    *,
    direction: Side,
    average_entry_price: Decimal,
    remaining_quantity: Decimal,
    mark_price: Decimal,
) -> Decimal:
    """Pure price-P&L on the still-open remainder only. Uses
    `remaining_quantity` (the position's CURRENT open quantity, already
    reduced by any prior partial exit — see `Position.quantity`'s own
    existing meaning for an OPEN position in
    `infrastructure/brokers/paper/broker.py::_apply_to_position`), never
    the position's original entry quantity — so a partially-closed
    position's unrealized P&L is automatically correct (Rule 11), no
    separate "original_quantity" bookkeeping needed here."""
    if mark_price <= 0:
        raise ValueError("mark_price must be positive")
    if remaining_quantity < 0:
        raise ValueError("remaining_quantity must not be negative")
    sign = _direction_sign(direction)
    return sign * remaining_quantity * (mark_price - average_entry_price)


def compute_market_value(
    *, direction: Side, remaining_quantity: Decimal, mark_price: Decimal
) -> Decimal:
    """Signed market value of the still-open remainder — see module
    docstring's "SIGN CONVENTION" (identical to `research/backtesting/
    mark_to_market.py`'s own established, already-tested convention)."""
    if mark_price <= 0:
        raise ValueError("mark_price must be positive")
    if remaining_quantity < 0:
        raise ValueError("remaining_quantity must not be negative")
    sign = _direction_sign(direction)
    return sign * remaining_quantity * mark_price


def mark_position(position: Position, mark_price: Decimal) -> Position:
    """Returns a NEW `Position` (this contract is `frozen=True` — a
    value snapshot, per its own docstring) with `unrealized_pnl`
    recomputed against `mark_price`. Every OTHER field — including
    `realized_pnl` and 64.37's `realized_net_pnl` — is carried through
    UNCHANGED (this function reads them, never writes them).

    A CLOSED position is returned completely unchanged (not even a new
    object) — a closed position's remaining exposure is, by
    construction, zero (`PaperBroker._apply_to_position` already sets
    `unrealized_pnl=Decimal("0")` at the moment a position closes), so
    marking it again would be a meaningless no-op at best and a silent
    masking of a caller bug (marking a position that should no longer
    be in anyone's "open positions" list) at worst — this function
    refuses to paper over that by returning early rather than
    recomputing on a zero/undefined remaining quantity."""
    if position.status is PositionStatus.CLOSED:
        return position
    unrealized = compute_unrealized_pnl(
        direction=position.direction,
        average_entry_price=position.average_entry_price,
        remaining_quantity=position.quantity,
        mark_price=mark_price,
    )
    from dataclasses import replace

    return replace(position, unrealized_pnl=unrealized)


def position_market_value(position: Position) -> Decimal:
    """Derives the CURRENT market value of `position` from its OWN
    already-marked `unrealized_pnl` field, without needing the mark
    price threaded through a second time. By definition (identical
    algebra for both directions, since `unrealized_pnl` already carries
    `direction_sign`):

        market_value = direction_sign * quantity * average_entry_price
                        + unrealized_pnl

    (`direction_sign * quantity * average_entry_price` is the position's
    signed BOOK value; adding the already-computed `unrealized_pnl`
    yields exactly `direction_sign * quantity * mark_price` —
    `compute_market_value`'s own formula — without a second Decimal
    division/multiplication by a re-supplied mark price that could, in
    principle, drift from the one `unrealized_pnl` was actually computed
    against.) For a position never yet marked (`unrealized_pnl ==
    Decimal("0")`, e.g. immediately after entry, before the first
    `mark_position()` call), this correctly reduces to the position's
    own book value — never a fabricated "no mark = zero value" answer
    (Rule 5)."""
    sign = _direction_sign(position.direction)
    return sign * position.quantity * position.average_entry_price + position.unrealized_pnl
