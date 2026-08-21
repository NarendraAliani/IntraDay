# File: src/intraday/research/backtesting/order_intent_adapter.py
#
# Checkpoint 64.29 Target 2: standalone, UNWIRED builder proving a
# backtest entry decision (bar + TradePlan/signal + quantity) CAN
# construct a real `domain.order.contracts.OrderIntent` without
# fabricating any field. Not wired into `run_backtest()`'s actual entry
# branch this checkpoint - see `risk_gate_adapter.py`'s header docstring
# for why wiring is deferred (the same reasoning applies here: the
# entry branch's control flow is explicitly out of scope for rewriting
# this checkpoint).
#
# FIELD-BY-FIELD HONESTY CHECK (every `OrderIntent` field, confirmed
# against `domain/order/contracts.py` read in full this checkpoint):
#   order_id            - backtest can synthesize one deterministically
#                          (trade_counter/entry_index-based), same as
#                          `SimulatedTrade.trade_id` already does.
#                          Checkpoint 64.33: qualified with `instrument_id`
#                          (matching `idempotency_key`'s pre-existing
#                          convention below) - an objectively proven
#                          defect surfaced by `portfolio.py` convergence:
#                          the multi-instrument portfolio engine
#                          explicitly supports "same strategy_id assigned
#                          to multiple instruments" entering on the same
#                          shared bar index, which - WITHOUT this
#                          qualification - could produce two DIFFERENT
#                          accepted entries (different instruments) with
#                          an IDENTICAL `order_id`
#                          (`f"{strategy_id}-bt-entry-{entry_index}"`),
#                          violating the deterministic per-instrument
#                          distinct-identity requirement. Single-instrument
#                          `run_backtest()` callers are unaffected: their
#                          `order_id` is still deterministic per entry and
#                          still unique within that run (it simply also
#                          now includes the one constant `instrument_id`),
#                          and no existing test asserts an exact `order_id`
#                          string (confirmed by repo-wide search) - only
#                          type/inequality/presence checks - so this is a
#                          format widening, not a breaking change.
#   instrument_id        - `BacktestConfiguration.instrument_id`, honest.
#   side                 - derived from `StrategyDirection` (BULLISH/
#                          BEARISH map onto BUY/SELL one-to-one, no
#                          NEUTRAL ever reaches an entry decision - the
#                          engine's own loop already guards this).
#   quantity              - `quantity_for_config()`'s own real result.
#   order_type            - the engine ALWAYS fills entries at "next
#                          bar's open" (never a limit/stop price it
#                          chose) - the honest mapping is `MARKET`.
#   time_in_force          - the engine has no multi-day order concept
#                          (intraday-only, Rule 5.4) - `DAY` is honest.
#   strategy_id           - `BacktestConfiguration.strategy_id`, honest.
#   created_at            - the entry bar's own timestamp (the fill
#                          moment already the engine, itself, treats as
#                          decisive - `entry_bar.timestamp`).
#   idempotency_key       - a backtest has no retry/duplicate-submission
#                          concern (it is not resubmitting to a real
#                          broker), but the FIELD requires a non-empty
#                          string, not a full idempotency GUARANTEE - a
#                          deterministic string derived from
#                          (strategy_id, instrument_id, entry_index) is
#                          honestly unique-per-backtest-entry, not a
#                          fabricated opaque value.
#   status                 - defaults to `CREATED`, which is honestly
#                          true: a backtest constructs the intent, it
#                          never actually submits it through any broker
#                          state machine.
#   signal_id             - `StrategySignal` carries no `signal_id`
#                          field today (confirmed: `research.backtesting.
#                          StrategySignal` has no such attribute) - left
#                          `None`, which the contract's own docstring
#                          says is legitimate ("an order intent may exist
#                          without an originating signal").
#   limit_price/trigger_price - `None`, correct for a `MARKET` order
#                          (`OrderIntent.__post_init__` only requires
#                          these for LIMIT/STOP_LOSS order types).
#
# Every field above is HONESTLY supplied from real backtest state - none
# is a fabricated placeholder.
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from intraday.domain.order.contracts import OrderIntent, OrderType, TimeInForce
from intraday.domain.shared_kernel.contracts import (
    InstrumentId,
    OrderId,
    Side,
    StrategyId,
)
from intraday.research.backtesting import StrategyDirection

__all__ = ["backtest_direction_to_side", "build_backtest_entry_order_intent"]


def backtest_direction_to_side(direction: StrategyDirection) -> Side:
    """`StrategyDirection.NEUTRAL` has no `Side` equivalent - callers
    must never invoke this for a NEUTRAL direction (the engine's own
    entry branch already guards `direction != NEUTRAL` before an entry
    is ever considered, `engine.py` lines ~231-235)."""
    if direction is StrategyDirection.BULLISH:
        return Side.BUY
    if direction is StrategyDirection.BEARISH:
        return Side.SELL
    raise ValueError(
        f"StrategyDirection.NEUTRAL has no OrderIntent.side equivalent - "
        f"got {direction!r}, an entry OrderIntent must never be built for it"
    )


def build_backtest_entry_order_intent(
    *,
    strategy_id: str,
    instrument_id: str,
    direction: StrategyDirection,
    quantity: Decimal,
    entry_timestamp: datetime,
    entry_index: int,
) -> OrderIntent:
    """Builds a REAL `OrderIntent` from backtest-available entry-decision
    state - see this module's header docstring for the field-by-field
    honesty check. `entry_index` is used only to make `order_id`/
    `idempotency_key` deterministic and collision-free within one
    backtest run, mirroring `SimulatedTrade.trade_id`'s own
    `f"{strategy_id}-{trade_counter}"` convention."""
    order_id = OrderId(f"{strategy_id}-{instrument_id}-bt-entry-{entry_index}")
    idempotency_key = f"{strategy_id}:{instrument_id}:bt-entry:{entry_index}"
    return OrderIntent(
        order_id=order_id,
        instrument_id=InstrumentId(instrument_id),
        side=backtest_direction_to_side(direction),
        quantity=quantity,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        strategy_id=StrategyId(strategy_id),
        created_at=entry_timestamp,
        idempotency_key=idempotency_key,
        signal_id=None,
        limit_price=None,
        trigger_price=None,
    )
