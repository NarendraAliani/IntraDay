# File: src/intraday/research/backtesting/mark_to_market.py
#
# Checkpoint 64.26: a standalone, pure Fill-Sequence Mark-to-Market
# Accounting Model. This module is NOT wired into `run_backtest()` or
# `run_stateful_backtest()` in this checkpoint - it is proof-in-isolation
# only, built so a FUTURE checkpoint can wire it into the real engine
# once this checkpoint's proof is reviewed. `engine.py` and
# `historical_execution.py` are UNTOUCHED by this checkpoint.
#
# ---------------------------------------------------------------------------
# DESIGN (written before implementation, per the checkpoint directive)
# ---------------------------------------------------------------------------
#
# WHAT THIS MODULE IS NOT: it does not decide when a position should
# exit. It never imports `evaluate_position_exit`, `evaluate_order_risk`,
# or any strategy/signal code. It receives FILL EVENTS - facts that have
# already happened ("this quantity, at this price, with this cost,
# belongs to this logical position, at this timestamp") - and per-bar
# mark prices, and does nothing except account for the financial
# consequence of those facts. Every exit decision fed into it in this
# checkpoint's tests is produced by the REAL, canonical
# `evaluate_position_exit()` (Checkpoint 42/64.24) - never a hand-rolled
# substitute that would bypass the real policy's own priority ordering.
#
# ZERO DEPENDENCIES beyond:
#   - `intraday.domain.shared_kernel.contracts` (Side, PositionId, ensure_utc)
#   - `intraday.research.backtesting.cost_model` (reused for computing
#     REAL transaction costs in the worked-example tests - this module
#     itself never invents its own cost formula; it only accepts a
#     `cost: Decimal` already computed by the caller)
# No Django, no database, no network, no Dhan, no strategy code, no risk
# engine, no ORM. Proven mechanically by
# `tests/unit/architecture/test_backtesting_sample_bar_boundary.py`-style
# reasoning is out of scope here (this module never touches market-data
# providers at all), and directly by `lint-imports` (this module lives in
# `intraday.research.backtesting`, permitted only to import
# `intraday.domain.*` and other `intraday.research.backtesting.*`
# modules - never `trading_engine`/`application` directly, which this
# module does not do).
#
# CORE QUANTITIES (exactly the vocabulary the checkpoint directive
# specifies):
#   starting_cash        - the ledger's initial cash balance.
#   cash                  - current cash balance, mutated only by fills
#                           (entry fills decrease it, exit fills increase
#                           it) - NEVER by an unrealized mark.
#   remaining_quantity    - per logical position: quantity not yet exited.
#   entry_price           - per logical position: the single fill price
#                           this position was opened at.
#   entry_cost            - per logical position: the TOTAL transaction
#                           cost charged on the entry fill (not per-unit -
#                           see cost-basis policy below for how it is
#                           allocated across exits).
#   exit_fill_price/exit_fill_quantity/exit_fill_cost - per exit fill,
#                           exactly what happened on that fill.
#   realized_pnl           - cumulative, ledger-wide: the sum of every
#                           exit fill's own realized P&L (see formula
#                           below). Monotonically only changes on an exit
#                           fill, never on a mark.
#   unrealized_pnl         - as of the most recent `mark_bar()` call: the
#                           mark-to-market P&L on quantity still open,
#                           summed across all open positions.
#   market_value           - as of the most recent `mark_bar()` call:
#                           `sum(remaining_quantity * current_mark_price)`
#                           across all open positions.
#   equity                 - `cash + market_value` (Checkpoint 64.26 §5's
#                           REQUIRED identity - this module computes
#                           `equity` this way BY DEFINITION, so the
#                           identity trivially and always holds; it is
#                           never computed a second, independent way that
#                           could drift out of sync).
#   total_pnl               - `realized_pnl + unrealized_pnl` (also a
#                           by-construction identity, same reasoning).
#
# COST-BASIS POLICY: quantity-weighted average cost basis.
#
# This project's strategies each produce exactly ONE entry fill per
# `TradePlan` (see `engine.py`'s own execution model docstring: "Entry
# always fills at the NEXT bar's OPEN" - a single fill, never staggered
# averaging-in entries). Under a single entry fill, "quantity-weighted
# average cost basis" and "FIFO cost basis" are mathematically IDENTICAL
# - there is only one lot, so there is nothing to average or to queue.
# This module therefore implements the single-lot case exactly (one
# `entry_price` per logical position) and does NOT implement a multi-lot
# averaging-in engine, since doing so would be speculative machinery this
# codebase never needs - a future checkpoint that adds staggered entries
# would need to extend this module, and should say so explicitly rather
# than this module silently pretending to support it today.
#
# Per-unit entry cost allocation: `entry_cost` is a single total charged
# once, at entry, for the whole original quantity. Each exit fill
# (partial or final) that removes `exit_fill_quantity` units allocates a
# PROPORTIONAL share of that total entry cost:
#
#     allocated_entry_cost_for_this_fill =
#         entry_cost * (exit_fill_quantity / original_quantity)
#
# so that after the position is fully closed, the sum of every fill's
# allocated share exactly equals the original `entry_cost` (proven by
# `test_cost_allocation_sums_exactly` below) - no double counting, no
# residual. To make this conservation EXACT under Decimal arithmetic
# (division by a non-power-of-ten quantity, e.g. 1/3, does not terminate
# exactly and must be rounded at Python's Decimal context precision), the
# ledger tracks `entry_cost` and a running `entry_cost_allocated` total
# per position; the REMAINING cost-basis share is always computed as
# `entry_cost - entry_cost_allocated` (a subtraction from the exact
# original total), never as a fresh, independently-rounded division of
# `remaining_quantity` - so the two sides of the cost-basis conservation
# invariant can never drift apart from independent rounding.
#
# Realized P&L per fill (Checkpoint 64.26 §3's exact formula):
#
#     realized_pnl_for_this_fill =
#         exit_fill_quantity * direction_sign * (exit_fill_price - entry_price)
#         - exit_fill_cost
#         - allocated_entry_cost_for_this_fill
#
# where `direction_sign` is +1 for a long (BUY) position and -1 for a
# short (SELL) position - the same sign convention `engine.py`'s own
# `signed_gross_pnl()` uses, so a single-lot single-exit trade's total
# realized P&L (summed price P&L minus BOTH legs' costs) is numerically
# identical to `engine.py`'s `SimulatedTrade.net_pnl` - proven directly,
# scenario by scenario, in `tests/unit/research/
# test_mark_to_market_regression_against_engine.py`.
#
# KNOWN, DOCUMENTED DISCREPANCY vs. `historical_execution.py`: that
# module's `Trade.realized_pnl` field is PURE PRICE P&L - it does NOT
# net transaction costs into `realized_pnl` itself; costs move through
# `_available_balance` as a separate cash flow. THIS module's
# `realized_pnl` DOES net costs in, per the checkpoint directive's
# explicit formula above. The two are therefore NOT directly comparable
# field-for-field without adjusting for this difference - documented here
# so a future integrator does not assume they mean the same thing.
#
# ---------------------------------------------------------------------------
# CHECKPOINT 64.27 CANONICAL P&L VOCABULARY (audit + reconciliation)
# ---------------------------------------------------------------------------
#
# Checkpoint 64.27 audited every real producer/consumer of
# `realized_pnl`/`unrealized_pnl`/`gross_pnl`/`net_pnl`/`total_pnl`
# across the whole `src/` tree (see `taskReport.md` 64.27 for the full
# table). Finding: the codebase genuinely contains TWO, not one,
# self-consistent-but-different conventions, and they do not agree:
#
#   1. BACKTEST-METRICS CONVENTION (cost-INCLUSIVE realized_pnl) -
#      `engine.py`'s `SimulatedTrade.gross_pnl`/`net_pnl`
#      (`net_pnl = gross_pnl - trade_costs`, both entry+exit legs) and
#      `metrics.py`'s `BacktestMetrics.net_pnl` (summed from
#      `net_pnl`). THIS module (`mark_to_market.py`) was built to
#      match this convention, and Checkpoint 64.26/64.27's regression
#      tests prove it does so EXACTLY - 10 direction-flip scenarios
#      (64.26) plus 2 ATR-TradePlan stop-loss scenarios (64.27,
#      zero-cost and real-cost), zero discrepancy in either.
#
#   2. LIVE/PAPER-BROKER CONVENTION (cost-EXCLUSIVE realized_pnl) -
#      the REAL, production `intraday.domain.position.contracts.
#      Position.realized_pnl` / `intraday.domain.trade.contracts.
#      Trade.realized_pnl`, as actually computed by
#      `intraday.infrastructure.brokers.paper.broker.PaperBroker.
#      record_fill()`: `realized = direction_sign * (fill_price -
#      existing.average_entry_price) * closing_quantity` - PURE PRICE
#      P&L, no cost term anywhere in that expression. Transaction cost
#      (`self._compute_cost(is_buy, notional)`) is applied ONLY to
#      `self._available_balance`, as a separate cash movement, never
#      folded into `realized_pnl`. `research.backtesting.
#      historical_execution.py`'s own internal `Trade.realized_pnl` /
#      `_available_balance` mirrors this exact shape (same formula,
#      same cost-via-cash-only treatment) - so `historical_execution.py`
#      is NOT an isolated backtest-only quirk, it is a faithful replica
#      of the REAL, live-trading-adjacent Paper Trading convention.
#      `application/services/paper_trading.py`'s
#      `daily_realized_pnl = sum(p.realized_pnl for p in positions)`
#      (fed into `RiskEvaluationContext.current_daily_realized_pnl`)
#      consumes this cost-EXCLUSIVE value directly for real risk
#      decisions.
#
# THESE TWO CONVENTIONS GENUINELY CONFLICT and Checkpoint 64.27
# deliberately does NOT force them to agree. `mark_to_market.py`
# matches convention (1) - `engine.py` - which is the correct choice
# for THIS module's own, already-proven purpose (matching the backtest
# engine's own trade-level P&L reporting), but it does NOT match
# convention (2) - the real, live PaperBroker's `realized_pnl` field.
# A future checkpoint attempting Paper/Backtest PARITY (not merely
# backtest-engine-internal correctness) must resolve this explicitly,
# by EITHER (a) treating `net_pnl`/`realized_pnl` as intentionally
# different-but-derivable views - `net_pnl (cost-inclusive) ==
# price_pnl (cost-exclusive) - total_cost`, so both sides can coexist
# under clearly qualified names - or (b) changing PaperBroker's
# `realized_pnl` formula to net costs in, which would be a real,
# separate, live-trading-adjacent risk change, entirely out of THIS
# checkpoint's scope (`PaperBroker`/`domain/position`/`domain/trade`
# were not modified this checkpoint).
#
# PROPOSED CANONICAL VOCABULARY (qualified names, so both existing
# conventions can be expressed unambiguously without either module
# changing its stored field's current meaning):
#
#   gross_price_pnl   - quantity * direction_sign * (exit_price -
#                       entry_price), no cost term at all. This IS
#                       exactly what `PaperBroker`/`historical_
#                       execution.py`/`domain.trade.contracts.Trade`
#                       currently store AS `realized_pnl` (an existing,
#                       real, live convention - "realized_pnl" there
#                       means "gross_price_pnl" in this vocabulary).
#   transaction_cost  - sum of entry-leg + exit-leg cost (or, for a
#                       partial exit, the allocated entry-cost share +
#                       that fill's own exit cost - this module's own
#                       `allocated_entry_cost_for_this_fill` formula).
#   net_pnl           - gross_price_pnl - transaction_cost. This IS
#                       exactly `engine.py`'s `SimulatedTrade.net_pnl`
#                       AND this module's own `realized_pnl` field
#                       (THIS module's "realized_pnl" means "net_pnl"
#                       in this vocabulary - the checkpoint directive's
#                       own formula, kept unchanged this checkpoint).
#   unrealized_pnl    - gross price P&L on the still-open remainder
#                       only (never cost-adjusted, in EITHER
#                       convention - `engine.py`'s `MarkToMarketPoint`
#                       and this module's `mark_bar()` already agree
#                       on this, undisputed).
#   total_pnl         - realized (in whichever convention is in force)
#                       + unrealized, by construction.
#
# Direction-neutral by construction: every formula above uses
# `direction_sign` (+1 long / -1 short), never a long-only assumption -
# proven for both directions by the short-position hand-worked
# reconciliation in `taskReport.md` 64.27 and by this module's own
# short-position tests (`test_trailing_stop_short_drives_ledger_via_
# real_policy`, `test_multiple_positions_isolated_and_summed_
# correctly`'s short leg).
#
# DECISION THIS CHECKPOINT: `mark_to_market.py`'s code is UNCHANGED.
# Its `realized_pnl` (== `net_pnl` in the vocabulary above) is already
# the correct, proven-exact match for its own designed oracle
# (`engine.py`), including the newly-added ATR TradePlan case. Renaming
# its own field to `net_pnl` to remove the ambiguity with convention
# (2)'s different use of the word "realized_pnl" is a real, worthwhile
# follow-up, but is a pure rename with no formula change, deliberately
# deferred rather than performed opportunistically alongside this
# checkpoint's validation-only scope.
#
# NO DOUBLE-COUNTING PROOF (Checkpoint 64.27 §9, using 64.26's own
# 12-share T1/T2/T3 hand-worked example, reused verbatim - see
# `test_hand_worked_12_share_t1_t2_t3_example` below): gross_price_pnl
# summed over all three exits = 40 + 30 + 120 = 190. total_cost =
# entry(0.51) + T1(0.28) + T2(0.15) + T3(0.46) = 1.40. gross_price_pnl
# - total_cost = 190 - 1.40 = 188.60, which EXACTLY equals this
# module's own `realized_pnl` (== net_pnl) of 188.60, proven by the
# test's own assertions. Cash and equity are NOT a second, independent
# subtraction of the same 1.40: `cash` moves by `sign * notional -
# fill.cost` PER FILL (a cash-flow view - what physically left/entered
# the account), while `realized_pnl` moves by `price_pnl - fill.cost -
# allocated_entry_cost` PER FILL (a P&L-attribution view - what that
# fill was economically worth). Both views net the SAME total cost
# exactly once each, from two different vantage points on the same
# underlying dollar amount, never twice from the trader's actual final
# wealth: `final_cash - starting_cash == 188.60 == realized_pnl` for
# this fully-closed example (proven directly by the existing test's own
# `assert ledger.cash == starting_cash + Decimal("188.6")` and
# `assert ledger.realized_pnl == Decimal("188.6")` assertions - the two
# numbers agree, they do not compound).
#
# CASH-FLOW CONVENTION (Checkpoint 64.26 §12): cash is a bookkeeping
# construct for equity reconciliation, not a broker margin simulator, but
# it IS direction-aware so that `equity == cash + market_value` reduces
# to `start_cash + net_pnl` at full close for BOTH a long and a short
# position (proven by the regression tests against `engine.py`). Let
# `sign = +1` for a long (BUY) position, `-1` for a short (SELL) position
# - the same convention `engine.py`'s own `signed_gross_pnl()` uses:
#
#   entry fill:  cash -= sign * (entry_fill_quantity * entry_fill_price)
#                        + entry_fill_cost
#   exit fill:   cash += sign * (exit_fill_quantity * exit_fill_price)
#                        - exit_fill_cost
#
# For a long, this is the familiar "pay notional+cost to buy, receive
# notional-cost to sell" shape. For a short, the signs flip: entry
# RECEIVES notional (minus cost) - a short sale - and exit PAYS notional
# (plus cost) - buying back to cover - which is why `market_value` for a
# short position (below) is carried as a NEGATIVE number (a liability,
# not an asset): `market_value = sign * remaining_quantity *
# current_mark_price`. (`engine.py` itself does not model cash/margin at
# all mid-trade - it only folds `net_pnl` into a running total AT TRADE
# CLOSE - so there is no existing convention this module could
# contradict; this module's convention is a new, self-consistent choice,
# documented rather than silently assumed.) `unrealized_pnl` NEVER
# touches `cash` directly - proven by `test_unrealized_pnl_never_touches_cash`.
#
# MARK-TO-MARKET / EQUITY CURVE: `mark_bar()` is called once per bar with
# a `{position_id: mark_price}` map for every position still open at that
# bar (closed positions need no mark - they contribute 0 to both
# `market_value` and `unrealized_pnl` by construction, since their
# `remaining_quantity` is 0). Unrealized P&L uses the SAME gross,
# no-cost-included convention `engine.py`'s own `MarkToMarketPoint`
# docstring documents ("Unrealized valuation excludes exit costs") -
# this module additionally excludes the STILL-UNALLOCATED portion of
# entry cost from `unrealized_pnl` (it stays paid-for in `cash` but
# unrecognized as a loss until the shares actually exit) - a deliberate,
# documented mirror of `engine.py`'s own choice, not an oversight.
# Peak-to-current drawdown is derived from the EQUITY curve
# (`peak_equity = running max of equity`, `drawdown = peak - equity`),
# exactly mirroring `engine.py`'s `_build_mark_to_market_curve()` formula
# shape (independently re-derived here, not imported, since this module
# may not import `engine.py`).
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from intraday.domain.shared_kernel.contracts import PositionId, Side, ensure_utc


class MarkToMarketError(ValueError):
    """Raised on any fill-sequence violation this ledger detects (e.g. an
    exit fill for an unknown position, or one exceeding what remains)."""


def _direction_sign(direction: Side) -> Decimal:
    return Decimal("1") if direction is Side.BUY else Decimal("-1")


@dataclass(frozen=True, slots=True)
class EntryFill:
    """One entry fill - always exactly one per logical position in this
    project's strategies (see module docstring's cost-basis policy)."""

    position_id: PositionId
    direction: Side
    quantity: Decimal
    price: Decimal
    cost: Decimal
    timestamp: datetime

    def __post_init__(self) -> None:
        ensure_utc(self.timestamp, field_name="EntryFill.timestamp")
        if self.quantity <= 0:
            raise MarkToMarketError("EntryFill.quantity must be positive")
        if self.price <= 0:
            raise MarkToMarketError("EntryFill.price must be positive")
        if self.cost < 0:
            raise MarkToMarketError("EntryFill.cost must not be negative")


@dataclass(frozen=True, slots=True)
class ExitFill:
    """One exit fill - partial or final. Multiple `ExitFill`s may target
    the same `position_id` (T1/T2/T3, or a single full exit)."""

    position_id: PositionId
    quantity: Decimal
    price: Decimal
    cost: Decimal
    timestamp: datetime

    def __post_init__(self) -> None:
        ensure_utc(self.timestamp, field_name="ExitFill.timestamp")
        if self.quantity <= 0:
            raise MarkToMarketError("ExitFill.quantity must be positive")
        if self.price <= 0:
            raise MarkToMarketError("ExitFill.price must be positive")
        if self.cost < 0:
            raise MarkToMarketError("ExitFill.cost must not be negative")


@dataclass(frozen=True, slots=True)
class PositionAccountingState:
    """A read-only snapshot of one logical position's accounting state -
    exposed so invariant proofs can inspect it directly without reaching
    into the ledger's private mutable bookkeeping."""

    position_id: PositionId
    direction: Side
    original_quantity: Decimal
    remaining_quantity: Decimal
    cumulative_exited_quantity: Decimal
    entry_price: Decimal
    entry_cost: Decimal
    entry_cost_allocated: Decimal
    """Sum of every exit fill's allocated share of `entry_cost` so far."""
    realized_pnl: Decimal
    """Cumulative realized P&L from this position's exit fills only."""

    @property
    def is_closed(self) -> bool:
        """`remaining_quantity == 0` - the ONLY genuine terminal state
        (mirrors `PositionLifecycleStatus.is_terminal()`, which is True
        only for `CLOSED` - Checkpoint 64.26 §5)."""
        return self.remaining_quantity == 0

    @property
    def remaining_entry_basis(self) -> Decimal:
        """`remaining_quantity * entry_price + (entry_cost -
        entry_cost_allocated)` - the unrecovered cost basis still sitting
        in the open remainder. Cost-basis conservation:
        `original_quantity * entry_price + entry_cost ==
        (cumulative_exited_quantity * entry_price + entry_cost_allocated)
        + remaining_entry_basis` holds EXACTLY (subtraction-based, no
        independent rounding - see module docstring)."""
        return self.remaining_quantity * self.entry_price + (
            self.entry_cost - self.entry_cost_allocated
        )


@dataclass(frozen=True, slots=True)
class MarkToMarketSnapshot:
    """One per-bar accounting snapshot (Checkpoint 64.26 §13)."""

    timestamp: datetime
    cash: Decimal
    market_value: Decimal
    equity: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_pnl: Decimal
    peak_equity: Decimal
    drawdown: Decimal
    drawdown_percent: Decimal


@dataclass(frozen=True, slots=True)
class AccountingResult:
    """Checkpoint 64.26 §15: a minimal, standalone result type - NOT
    `BacktestResult`/`ResultValidationSummary`, never touches those."""

    starting_cash: Decimal
    final_cash: Decimal
    final_equity: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_pnl: Decimal
    equity_curve: tuple[MarkToMarketSnapshot, ...]
    drawdown_curve: tuple[Decimal, ...]


@dataclass(slots=True)
class _PositionAccount:
    direction: Side
    original_quantity: Decimal
    remaining_quantity: Decimal
    entry_price: Decimal
    entry_cost: Decimal
    entry_cost_allocated: Decimal = field(default_factory=lambda: Decimal("0"))
    cumulative_exited_quantity: Decimal = field(default_factory=lambda: Decimal("0"))
    realized_pnl: Decimal = field(default_factory=lambda: Decimal("0"))


class MarkToMarketLedger:
    """Pure, dependency-free fill-sequence accounting engine. See the
    module docstring for the full design. Zero ORM/database/network
    calls anywhere in this class (Checkpoint 64.26 §16) - every method
    below is plain Decimal arithmetic and dict/list bookkeeping."""

    def __init__(self, starting_cash: Decimal) -> None:
        self._starting_cash = starting_cash
        self._cash = starting_cash
        self._positions: dict[PositionId, _PositionAccount] = {}
        self._realized_pnl_total = Decimal("0")
        self._peak_equity = starting_cash
        self._snapshots: list[MarkToMarketSnapshot] = []

    @property
    def cash(self) -> Decimal:
        return self._cash

    @property
    def realized_pnl(self) -> Decimal:
        return self._realized_pnl_total

    def position_state(self, position_id: PositionId) -> PositionAccountingState:
        account = self._positions.get(position_id)
        if account is None:
            raise MarkToMarketError(f"unknown position_id {position_id!r}")
        return PositionAccountingState(
            position_id=position_id,
            direction=account.direction,
            original_quantity=account.original_quantity,
            remaining_quantity=account.remaining_quantity,
            cumulative_exited_quantity=account.cumulative_exited_quantity,
            entry_price=account.entry_price,
            entry_cost=account.entry_cost,
            entry_cost_allocated=account.entry_cost_allocated,
            realized_pnl=account.realized_pnl,
        )

    def open_position_ids(self) -> tuple[PositionId, ...]:
        return tuple(pid for pid, acc in self._positions.items() if acc.remaining_quantity > 0)

    def apply_entry_fill(self, fill: EntryFill) -> None:
        """Accounts for one entry fill. Never decides to enter - the
        caller has already decided this fill happened."""
        if fill.position_id in self._positions:
            raise MarkToMarketError(
                f"position {fill.position_id!r} already has an entry fill - this ledger "
                "models exactly one entry fill per logical position (see module docstring's "
                "cost-basis policy); a second entry fill for the same position_id is rejected "
                "rather than silently treated as an averaging-in entry."
            )
        notional = fill.quantity * fill.price
        sign = _direction_sign(fill.direction)
        self._cash -= sign * notional + fill.cost
        self._positions[fill.position_id] = _PositionAccount(
            direction=fill.direction,
            original_quantity=fill.quantity,
            remaining_quantity=fill.quantity,
            entry_price=fill.price,
            entry_cost=fill.cost,
        )

    def apply_exit_fill(self, fill: ExitFill) -> None:
        """Accounts for one exit fill (partial or final). Never decides
        to exit, and never re-derives WHY - the caller (in this
        checkpoint's tests, the real `evaluate_position_exit()`) has
        already decided this fill happened."""
        account = self._positions.get(fill.position_id)
        if account is None:
            raise MarkToMarketError(f"exit fill for unknown position_id {fill.position_id!r}")
        if fill.quantity > account.remaining_quantity:
            raise MarkToMarketError(
                f"exit fill quantity {fill.quantity} exceeds remaining quantity "
                f"{account.remaining_quantity} for position {fill.position_id!r}"
            )

        sign = _direction_sign(account.direction)
        price_pnl = fill.quantity * sign * (fill.price - account.entry_price)
        allocated_entry_cost = account.entry_cost * (fill.quantity / account.original_quantity)
        realized = price_pnl - fill.cost - allocated_entry_cost

        notional = fill.quantity * fill.price
        self._cash += sign * notional - fill.cost

        account.remaining_quantity -= fill.quantity
        account.cumulative_exited_quantity += fill.quantity
        account.entry_cost_allocated += allocated_entry_cost
        account.realized_pnl += realized
        self._realized_pnl_total += realized

    def mark_bar(
        self, timestamp: datetime, mark_prices: dict[PositionId, Decimal]
    ) -> MarkToMarketSnapshot:
        """One call per bar. `mark_prices` need only contain entries for
        positions still open at this bar (Checkpoint 64.26 §13: "closed
        contributes zero" - achieved here by construction, since a
        closed position's `remaining_quantity` is 0 regardless of
        whether a mark price was supplied for it)."""
        ensure_utc(timestamp, field_name="mark_bar timestamp")
        market_value = Decimal("0")
        unrealized = Decimal("0")
        for position_id, account in self._positions.items():
            if account.remaining_quantity <= 0:
                continue
            mark_price = mark_prices.get(position_id)
            if mark_price is None:
                continue
            sign = _direction_sign(account.direction)
            market_value += sign * account.remaining_quantity * mark_price
            unrealized += account.remaining_quantity * sign * (mark_price - account.entry_price)

        equity = self._cash + market_value
        total_pnl = self._realized_pnl_total + unrealized
        self._peak_equity = max(self._peak_equity, equity)
        drawdown = self._peak_equity - equity
        drawdown_percent = (
            (drawdown / self._peak_equity * 100) if self._peak_equity > 0 else Decimal("0")
        )
        snapshot = MarkToMarketSnapshot(
            timestamp=timestamp,
            cash=self._cash,
            market_value=market_value,
            equity=equity,
            realized_pnl=self._realized_pnl_total,
            unrealized_pnl=unrealized,
            total_pnl=total_pnl,
            peak_equity=self._peak_equity,
            drawdown=drawdown,
            drawdown_percent=drawdown_percent,
        )
        self._snapshots.append(snapshot)
        return snapshot

    def finalize(self) -> AccountingResult:
        last = self._snapshots[-1] if self._snapshots else None
        final_equity = last.equity if last is not None else self._cash
        unrealized = last.unrealized_pnl if last is not None else Decimal("0")
        return AccountingResult(
            starting_cash=self._starting_cash,
            final_cash=self._cash,
            final_equity=final_equity,
            realized_pnl=self._realized_pnl_total,
            unrealized_pnl=unrealized,
            total_pnl=self._realized_pnl_total + unrealized,
            equity_curve=tuple(self._snapshots),
            drawdown_curve=tuple(s.drawdown for s in self._snapshots),
        )
