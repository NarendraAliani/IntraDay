# Canonical Trade Lifecycle and P&L Architecture

## Checkpoint

64.28 — "CANONICAL DOMAIN MODEL: TRADE LIFECYCLE, PARTIAL EXITS, P&L SEMANTICS (DESIGN ONLY)".
This is a design/documentation checkpoint. No engine code (`run_backtest()`,
`run_stateful_backtest()`, `PaperBroker`, frontend, Dhan) was modified. The Indian market is
closed today (2026-08-21); no live-adjacent validation was performed or claimed.

## Purpose

Checkpoint 64.27 left two facts on the table, unresolved by design: (1) the real backtest
engine's `TradePlan` exit path is full-close-only — no partial T1/T2/T3 exits exist in
`run_backtest()` today; (2) `PaperBroker.Position.realized_pnl` is cost-EXCLUSIVE while
`engine.py`'s `SimulatedTrade.net_pnl` and `mark_to_market.py`'s `realized_pnl` are
cost-INCLUSIVE — a genuine, unresolved semantic conflict between the live-trading-adjacent
Paper Trading path and the backtest-metrics path. This document is the architecture/design
response: a canonical domain model for the full trade lifecycle, a canonical partial-exit
model, a canonical P&L vocabulary, and a concrete recommendation on which convention a
hard risk limit should use — all as design, explicitly deferring implementation.

---

## 1. Source-of-truth reading (evidence base)

Every claim below is traceable to a specific file/function, all read in full for this
checkpoint:

- `src/intraday/research/backtesting/engine.py` — `run_backtest()`, `_close_trade()`,
  `_build_mark_to_market_curve()`
- `src/intraday/research/backtesting/tradeplan_execution.py` — `simulate_tradeplan_exit()`,
  `compute_trade_plans()`
- `src/intraday/research/backtesting/mark_to_market.py` — `MarkToMarketLedger`,
  `apply_entry_fill()`, `apply_exit_fill()`, `mark_bar()`
- `src/intraday/research/backtesting/contracts.py` — `SimulatedTrade`, `MarkToMarketPoint`,
  `BacktestMetrics`, `BacktestResult`
- `src/intraday/domain/order/contracts.py` — `OrderIntent`, `OrderStatus`
- `src/intraday/domain/trade/contracts.py` — `Trade`
- `src/intraday/domain/position/contracts.py` — `Position`
- `src/intraday/domain/position_exit/contracts.py` — `ExitPlan`, `ManagedPosition`,
  `ExitDecision`, `ExitReason`, `PositionLifecycleStatus`
- `src/intraday/domain/position_exit/policy.py` — `evaluate_position_exit()`,
  `_PARTIAL_EXIT_FRACTION = 1/3`
- `src/intraday/domain/risk/contracts.py` — `RiskLimits`, `OrderRiskDecision`,
  `RiskRejectionReason`
- `src/intraday/domain/risk/policy.py` — `evaluate_order_risk()`,
  `RiskEvaluationContext.current_daily_realized_pnl`
- `src/intraday/infrastructure/brokers/paper/broker.py` — `PaperBroker._apply_to_position()`
  (realized_pnl formula, line ~449), `_attempt_fill()` (cost handling, lines 384-393)
- `src/intraday/application/services/paper_trading.py` — `PaperTradingService.submit_order()`
  (`daily_realized_pnl = sum(p.realized_pnl for p in positions)`)
- `src/intraday/application/services/exit_plan_policy.py` — `derive_default_exit_plan()`
  (PROJECT_POLICY fixed-percentage SL/T1/T2/T3/trailing defaults)
- `src/intraday/trading_engine/strategy_execution/contracts.py` — `TradePlan`, `StrategySignal`,
  `Strategy` protocol shape, `ParameterDefinition`
- `src/intraday/trading_engine/strategy_execution/coordinator.py` — `StrategyExecutionCoordinator`
- `src/intraday/trading_engine/strategy_execution/registry.py` — `StrategyRegistry`,
  `build_default_registry()`
- `src/intraday/trading_engine/strategy_execution/strategies/test_momentum.py` — the
  Checkpoint 64.20 extensibility proof (`TestMomentumStrategy`)
- `src/intraday/infrastructure/api/position_monitor_runtime.py` — `run_emergency_square_off()`
  (real EOD/kill-switch square-off hook)
- `src/intraday/application/services/paper_signal_execution.py` (existence/size confirmed,
  612 lines; not fully excerpted here — its `apply_default_exit_plan` opt-in wiring to
  `exit_plan_policy.derive_default_exit_plan()` is already documented by that module's own
  docstring)
- Existing parity tests: `tests/unit/research/test_backtest_paper_parity.py`,
  `test_default_backtest_paper_parity.py`, `test_stateful_backtest_paper_parity.py`,
  `test_mark_to_market_accounting.py` (32 tests, all passing per 64.27)
- 64.27's own `taskReport.md` section (the realized_pnl field-usage audit table) — reused as
  a foundation, not re-derived, since it was already independently verified twice.

---

## 2. Execution flow comparison: Backtest vs. Paper Trading (AS BUILT TODAY)

| Stage | Backtest (`engine.py`) | Paper Trading (`PaperBroker` + `paper_trading.py`) | Same or different? |
|---|---|---|---|
| **Signal** | `execution.compute_signals()` calls `strategy.evaluate()` per bar → `StrategySignal` | `StrategyExecutionCoordinator.run()` calls the SAME `strategy.evaluate()` on the latest bar → `StrategySignal` | **SAME** function, different call sites. Confirmed: `engine.py`'s own header comment states it calls "the SAME `Strategy.evaluate()` the live diagnostic coordinator calls." |
| **Trade Plan** | `tradeplan_execution.compute_trade_plans()` calls `strategy.build_trade_plan()` (duck-typed, optional) per bar → `TradePlan \| None` | `StrategyExecutionCoordinator.run()` calls the SAME optional `build_trade_plan()` hook → `TradePlan \| None` | **SAME** hook, reused per `tradeplan_execution.py`'s own header ("never a second TradePlan CONSTRUCTION implementation, only a second... CALL SITE"). |
| **Risk Decision** | **NONE.** `run_backtest()` never calls `evaluate_order_risk()`. Only `quantity_for_config()` (position sizing) gates entry — a zero-quantity result increments `rejected_trades`, never a `RiskRejectionReason`. | `PaperTradingService.submit_order()` builds a `RiskEvaluationContext` and calls the canonical `evaluate_order_risk()` (`domain/risk/policy.py`) before ever reaching `PaperBroker.submit_order()` — 13 ordered checks (kill switch → session → strategy-active → stale-data → duplicate → daily-loss → position-size → exposure → concurrency → allow/deny-list → daily-trade-count → per-trade-risk). | **DIFFERENT.** This is the single largest structural gap between the two paths: the backtest engine has **no risk-gate simulation at all**. A backtest cannot today show what a `RiskRejectionReason.MAX_DAILY_LOSS_EXCEEDED` (etc.) rejection would have done to a strategy's realized results. |
| **Order Intent** | Implicit — `run_backtest()` never constructs a real `domain.order.contracts.OrderIntent`; entry/exit are internal `OpenPosition`/`_close_trade()` bookkeeping only. | Explicit — a real `OrderIntent` is constructed and passed through `PaperTradingService.submit_order()` → `PaperBroker.submit_order()`. | **DIFFERENT** representation, same conceptual step (a risk-approved request to trade). |
| **Fill** | `_close_trade()`/entry branch: entry always fills at the **next bar's OPEN**; a direction-flip exit fills at the next bar's OPEN too; a TradePlan exit fills at the exact SL/T1/T2/T3/trailing level `simulate_tradeplan_exit()` found (never worse, never better than the touched level); EOD force-close fills at the **final bar's own CLOSE**. Slippage via `CostModel.slippage_adjusted_price()`. | `PaperBroker._attempt_fill()`: MARKET fills at the latest `record_price()`-observed price; LIMIT/STOP orders fill only once a subsequent `record_price()` call crosses the trigger/limit; slippage via a flat `slippage_percent` parameter. | **MAY DIFFER by design** (see §11) — this is real market-mechanics fidelity, not a bug: a live/paper venue cannot literally fill at "the exact SL/T1/T2/T3 price" the way a backtest's `simulate_tradeplan_exit()` idealizes; it fills at whatever price crosses next. |
| **Position** | `OpenPosition` (backtest-internal dataclass, `execution.py`) — quantity, entry price/index/timestamp, direction. No `domain.position.contracts.Position` is ever constructed. | Real `domain.position.contracts.Position` — `PaperBroker._apply_to_position()` creates/updates/closes it, average-price-blends same-direction adds, and computes `realized_pnl`/`unrealized_pnl`. | **DIFFERENT type**, same concept. Backtest has no canonical `Position` object at all today — a real architectural gap for anything that wants to treat backtest and paper positions polymorphically. |
| **P&L / Accounting** | `SimulatedTrade.gross_pnl`/`net_pnl` (cost-inclusive) computed once, at `_close_trade()`; `MarkToMarketPoint` per bar (realized cost-inclusive, unrealized cost-exclusive). | `Position.realized_pnl` (cost-EXCLUSIVE, pure price P&L — `direction_sign * (fill_price - average_entry_price) * closing_quantity`); cost only ever touches `_available_balance`. | **DIFFERENT semantics for the "realized_pnl" name** — this is the 64.27 conflict, restated precisely: not a bug in either module individually, a genuine naming collision across the boundary. |
| **Exit Decision (WHY)** | TradePlan path: `simulate_tradeplan_exit()`'s own hardcoded SL→trailing→T1→T2→T3 intrabar-ambiguity policy (conservative: stop-loss assumed first on an ambiguous bar). Direction-flip path: signal reversal or EOD. | The canonical `evaluate_position_exit()` (`domain/position_exit/policy.py`) — stop-loss first, then targets in strict sequence (T1→T2→T3, `_PARTIAL_EXIT_FRACTION = 1/3` of remaining), then trailing stop. | **DIFFERENT implementations answering a similar question.** `simulate_tradeplan_exit()` is a full-close-only intrabar OHLC scanner; `evaluate_position_exit()` is the true partial-exit-capable canonical policy used by Paper Trading's `PositionMonitorService`. **The backtest engine does not call `evaluate_position_exit()` at all** — confirmed by `engine.py`'s import list (no `domain.position_exit` import anywhere in that file). This is the same fact 64.27 already surfaced from the ATR-regression angle; here it is confirmed again from the exit-policy-reuse angle: two independent, non-identical exit-decision code paths exist for the SAME logical question, one full-close-only (backtest), one partial-exit-capable (paper/live). |

**Headline finding, stated precisely once:** Signal generation and TradePlan construction are
already unified (one `Strategy.evaluate()`/`build_trade_plan()` call, reused by both paths).
Everything downstream of TradePlan construction — risk gating, fill mechanics, position
representation, exit-decision policy, and P&L accounting — is **two separate implementations
today**, not one canonical engine used twice. This is the actual scope of the "big
convergence" a future checkpoint would need to do, now named precisely rather than vaguely.

---

## 3. Canonical domain model (design)

The canonical lifecycle, keeping Signal / Order / Fill / Position / Trade / TradePlan
explicitly distinct — as concepts, not as a call to merge existing dataclasses:

```
StrategySignal ──▶ TradePlan (optional) ──▶ RiskDecision ──▶ OrderIntent ──▶ Fill(s) ──▶ Position ──▶ AccountingEvent(s) ──▶ P&L / Equity
     │                    │                                                      │
     │                    └── entry_price/stop_loss/target_1..3/trailing         │
     │                        (the "what should happen" plan, an intent,         │
     │                        never itself a fact of execution)                  │
     │                                                                            │
     └── direction/evidence only — never carries risk numbers (Checkpoint 64.6   └── ONE logical position,
         decision, already correct and unchanged; TradePlan owns those fields)       MULTIPLE fills (see §4)
```

Illustrative sketch only (not new production code — this is prose with a Python-shaped
illustration, to make the boundary between concepts unambiguous):

```python
# ILLUSTRATIVE ONLY — not a proposal to add these exact classes verbatim.
# Existing types already cover most of this; see the "maps onto" column below.

class AccountingEvent(Protocol):
    """The canonical unit a P&L ledger consumes — NOT the same object as
    a Fill. A Fill is 'what happened at the broker' (price/qty/cost/
    timestamp). An AccountingEvent is 'what that fill was economically
    worth to this ledger' (gross_price_pnl / transaction_cost / net_pnl /
    cash_delta) — derived FROM a fill, by a ledger, never carried on the
    fill itself. This separation already exists in embryonic form:
    `mark_to_market.py`'s `EntryFill`/`ExitFill` are the Fill concept;
    its own internal `apply_exit_fill()` arithmetic is the
    AccountingEvent-production step, just not reified as its own type."""
```

| Canonical concept | Maps onto (today) | Owns | Must NOT own |
|---|---|---|---|
| Signal | `StrategySignal` (`trading_engine.strategy_execution.contracts`) | direction, evidence, strategy/version attribution | price targets, stop-loss, quantity, risk decision |
| Trade Plan | `TradePlan` (same module) | entry/stop-loss/target_1-3/trailing_stop_loss, `calculation_method` | risk approval, fill facts, quantity sizing |
| Risk Decision | `OrderRiskDecision` (`domain.risk.contracts`) | APPROVED/REJECTED + `RiskRejectionReason`, non-bypassable | trade logic, exit logic |
| Order Intent | `OrderIntent` (`domain.order.contracts`) | risk-approved execution request, side/qty/type/idempotency | fill price, cost, realized P&L |
| Fill | `EntryFill`/`ExitFill` (`mark_to_market.py`) or `PaperBroker`'s internal fill application | quantity, price, cost, timestamp, position_id | exit decision reasoning, risk logic |
| Position | `domain.position.contracts.Position` (paper/live) — **no backtest-side equivalent exists today** | quantity, average_entry_price, lifecycle status, remaining vs. cumulative-exited quantity | P&L formula ownership (P&L is derived, not stored authoritative-source-of-truth on Position beyond a snapshot) |
| Trade | `domain.trade.contracts.Trade` / `SimulatedTrade` (backtest) | a CLOSED round-trip record — historical fact, immutable | live decision-making (it is a report, not an input) |
| Accounting Event / P&L | `MarkToMarketLedger`'s internal arithmetic (`mark_to_market.py`) — no persisted event type exists yet | gross_price_pnl, transaction_cost, net_pnl, cash delta, equity delta | strategy/risk/exit decisions |

This table is deliberately a **mapping**, not a rewrite proposal — per the checkpoint's own
instruction not to introduce new abstractions where an existing contract already covers the
concept. The one genuinely missing concept is a canonical backtest-side `Position` (see §14).

---

## 4. Canonical partial-exit model (design)

**Principle:** ONE logical position, MULTIPLE exit fills — never three independent trades.
This is already how `mark_to_market.py`'s `MarkToMarketLedger` is built (`ExitFill`s share one
`position_id`), and already how `domain.position_exit.contracts.ManagedPosition` is shaped
(`remaining_quantity` mutates across multiple `ExitDecision`s against one `position_id`). The
canonical model formalizes the invariant both of those already implicitly satisfy:

```
original_quantity = cumulative_exit_quantity + remaining_quantity   (INVARIANT, holds at every point in time)
```

- `original_quantity`: fixed at the single entry fill (this project's strategies produce
  exactly one entry fill per position — confirmed by `mark_to_market.py`'s own cost-basis
  policy note and by every strategy module read).
- `cumulative_exit_quantity`: monotonically increases, one increment per exit fill (T1, T2,
  T3, stop, trailing, or EOD — any of these can be the LAST fill that closes the invariant to
  `remaining_quantity == 0`).
- `remaining_quantity`: monotonically decreases; `== 0` is the only genuine terminal state
  (already exactly how `PositionAccountingState.is_closed` and
  `PositionLifecycleStatus.is_terminal()` are defined — both agree independently, evidence the
  invariant is already the right one, just not universally enforced across both engines yet).

This invariant is **already proven** for `mark_to_market.py`'s ledger (its
`PositionAccountingState` literally carries `original_quantity`, `remaining_quantity`, and
`cumulative_exited_quantity` as three separate fields, with cost-basis conservation proven by
`test_cost_allocation_sums_exactly`, per 64.27). It is **not yet proven** for the real
`run_backtest()` engine, because that engine has no partial-exit capability to prove it
against (64.27's ATR finding, restated).

### Canonical TradePlan partial-exit contract (design)

Today `TradePlan` carries `target_1`/`target_2`/`target_3` as bare `Decimal | None` prices —
no per-target quantity/fraction field exists. `_PARTIAL_EXIT_FRACTION = 1/3` in
`domain/position_exit/policy.py` is a single, hardcoded module-level constant applied
identically to every target for every strategy — there is no way today to represent
25/25/50, 30/30/40, 50/25/25, or "100% at stop, nothing partial" using the existing contract.

**Design proposal (NOT implemented this checkpoint):** widen `TradePlan` (or introduce a
small companion value object referenced by it — the naming choice is a future-checkpoint
decision, not fixed here) with an explicit, optional per-target quantity fraction:

```python
# ILLUSTRATIVE ONLY.
@dataclass(frozen=True, slots=True)
class ExitTargetAllocation:
    """One target level + how much of the REMAINING quantity it exits.
    Fractions across all configured targets need not sum to exactly 1 —
    the FINAL configured target (or the stop-loss / trailing-stop,
    whichever fires) always closes whatever remains, mirroring
    evaluate_position_exit()'s own existing 'T3 always exits everything
    left' rule (policy.py line ~101) generalized to an arbitrary split."""
    price: Decimal
    exit_fraction_of_remaining: Decimal  # e.g. Decimal("0.25") for 25%

@dataclass(frozen=True, slots=True)
class TradePlan:
    ...
    target_1: ExitTargetAllocation | None = None
    target_2: ExitTargetAllocation | None = None
    target_3: ExitTargetAllocation | None = None
    # a bare `Decimal` price with an IMPLICIT 1/3 split is still
    # representable as `exit_fraction_of_remaining=Decimal("1")/3`,
    # so this is backward-compatible in SHAPE, not merely in spirit —
    # but it is still a breaking dataclass-field-type change, hence
    # future-checkpoint work, not a today change.
```

**What would need to change to implement this (named exactly, not implemented):**
1. `trading_engine/strategy_execution/contracts.py`'s `TradePlan` dataclass — widen the three
   target fields (breaking change to every strategy's `build_trade_plan()` return shape,
   including `atr_volatility_breakout.py`).
2. `domain/position_exit/policy.py`'s `evaluate_position_exit()` — replace the single
   module-level `_PARTIAL_EXIT_FRACTION` constant with a per-target lookup from the plan
   itself, sourced via `ManagedPosition.exit_plan` (which would also need a matching
   `ExitPlan` field widening — `domain/position_exit/contracts.py`).
3. `research/backtesting/tradeplan_execution.py`'s `simulate_tradeplan_exit()` — would need to
   become genuinely partial-exit-capable (return a SEQUENCE of exit events, not one
   `TradePlanExitResult`), and `engine.py`'s `_close_trade()`/main loop would need to call it
   in a loop, tracking `remaining_quantity` across multiple partial closes instead of assuming
   exactly one close per position. This is the single largest, most legitimately "big
   convergence"-shaped piece of work this checkpoint deliberately does not touch.
4. `application/services/exit_plan_policy.py`'s `derive_default_exit_plan()` — would need a
   default fraction split (e.g. keep 1/3-of-remaining as the PROJECT_POLICY default, now
   expressed via the new field rather than a hardcoded constant elsewhere).

None of this is implemented this checkpoint — named precisely so a future checkpoint can scope
it without re-deriving the file list.

### Trailing-stop-after-partial-exit (design)

Trailing-stop ratchet must continue on the **remaining quantity only** — this already holds
structurally today: `ManagedPosition.highest_favorable_price` is a position-level field (not
per-fill), and `evaluate_position_exit()`'s trailing-stop branch (§3 of that function) always
computes `exit_quantity=managed.remaining_quantity` — i.e. a trailing-stop exit, wherever it
fires in the lifecycle (before or after a T1/T2 partial), always exits **whatever is left**,
never a stale reference to the original size. No design change is needed here beyond what
`evaluate_position_exit()` already does; the gap is only that `engine.py`'s backtest path
never calls this function at all (§2's finding), so this correct behavior is currently
unverified against a real backtest scenario. A future characterization test proving the
canonical `evaluate_position_exit()`'s trailing-after-partial behavior against a hand-worked
scenario (not merely trusting the code read) is named as future-checkpoint work, not performed
here (see §18's test-pyramid design for where it belongs).

### EOD exit (design)

This is an **intraday-only** project (`domain/position/contracts.py`'s own docstring: "no
carried-forward/overnight state exists in this contract (Rule 5.4)"). All positions MUST be
flat by session end — already true structurally in both paths:
- Backtest: `engine.py`'s main loop force-closes at `is_last_bar` unconditionally, both for
  direction-flip (`"end_of_data"` reason) and TradePlan positions (`ExitReason.EOD`).
- Paper/live: `PaperBroker.force_expire_end_of_session()` expires resting orders, and
  `infrastructure/api/position_monitor_runtime.py`'s `run_emergency_square_off()` is the real,
  separate EOD/kill-switch-triggered square-off hook (confirmed by grep of that file — it
  exists and is named exactly for this purpose, distinct from the per-bar `evaluate_
  position_exit()` monitoring loop).

**How a future checkpoint would prove this with a test:** a deterministic scenario test
asserting `remaining_quantity == 0` for every position that was ever opened, sampled at the
last bar/tick of the session — for BOTH the backtest engine's trade list (`SimulatedTrade`
already only exists post-close, so this is trivially true by construction there) AND a live
Paper Trading session (where it is NOT trivially true — a position could still be `OPEN` at
`PositionStatus.OPEN` if `run_emergency_square_off()` were never invoked). This is named as
future work in §18, not performed here (no live session exists today to run it against, and
building a synthetic one that doesn't touch Dhan is possible but is implementation, not
design).

---

## 5. P&L vocabulary (design, extends 64.27's proposal, does not contradict it)

Restating and slightly extending 64.27's `mark_to_market.py`-docstring vocabulary, now as a
standalone canonical reference (not duplicating the reasoning, citing it):

| Term | Formula | Cost treatment | Who currently means this by "realized_pnl" |
|---|---|---|---|
| `gross_price_pnl` | `qty × direction_sign × (exit_price − entry_price)` | none | `PaperBroker.Position.realized_pnl`, `domain.trade.contracts.Trade.realized_pnl`, `historical_execution.py`'s internal `Trade.realized_pnl` |
| `transaction_cost` | entry-leg cost + exit-leg cost (or, for a partial exit, the allocated entry-cost share + that fill's own exit cost) | — | n/a (a cost figure, not a P&L figure) |
| `net_pnl` (== `realized_net_pnl` in this doc's extended naming) | `gross_price_pnl − transaction_cost` | full | `engine.py`'s `SimulatedTrade.net_pnl`, `mark_to_market.py`'s own `realized_pnl` field |
| `realized_price_pnl` | same formula as `gross_price_pnl`, applied cumulatively across all CLOSED fills of a position/session | none | proposed name for what `PaperBroker` should call its own realized figure, to disambiguate from `net_pnl` |
| `realized_net_pnl` | same formula as `net_pnl`, applied cumulatively | full | proposed name for the cost-inclusive cumulative figure |
| `unrealized_pnl` | gross price P&L on the still-open remainder, marked at the bar's close (backtest) or the latest observed price (paper/live) | none — **both conventions already agree here**, confirmed in §6 of 64.27's audit and independently re-confirmed reading `engine.py`'s `_build_mark_to_market_curve()` and `mark_to_market.py`'s `mark_bar()` side by side this checkpoint | both |
| `total_pnl` | `realized_pnl (whichever convention) + unrealized_pnl` | inherits whichever realized convention is in force | both, by construction |
| `cash` | ledger's cash balance, mutated only by fills (never by an unrealized mark) | cost is a real cash outflow/inflow | `PaperBroker._available_balance`, `MarkToMarketLedger.cash` |
| `equity` | `cash + market_value` (mark_to_market.py) or `initial_capital + realized_pnl + unrealized_pnl` (engine.py) — proven identical by construction in both, never a second independently-computed figure that could drift | full (via realized) + none (via unrealized) | both, agreeing on the IDENTITY even though they disagree on what "realized" nets out |

**Cash-flow-accounting vs. P&L-attribution — two legitimate views, per `mark_to_market.py`'s
own docstring (read in full this checkpoint, built on rather than contradicted):** `cash`
answers "what physically left/entered the account" (a bookkeeping/liquidity question);
`realized_pnl`/`net_pnl` answers "what was this fill economically worth to the trader's P&L"
(a performance-attribution question). Both are correct simultaneously and net the SAME total
transaction cost exactly once each from two different vantage points — proven by 64.27's own
12-share double-counting proof, not re-derived here.

### Proposal: should `PaperBroker` expose BOTH `realized_price_pnl` AND `realized_net_pnl`?

**Recommendation: yes, design-only, not implemented this checkpoint.** Reasoning:

- **What exists today:** `Position.realized_pnl` (cost-exclusive) is a SINGLE ambiguous field.
  Its name gives no indication that it excludes costs — a future consumer reading only the
  field name would reasonably assume it is the trader's actual realized profit, which it is
  not (transaction cost is real money that left the account).
- **Migration-impact analysis — every real consumer found by grep this checkpoint** (23 files
  matched `realized_pnl|.gross_pnl|.net_pnl` across `src/`; the ones that actually READ
  `Position.realized_pnl`/`Trade.realized_pnl` as a live figure, beyond the modules that only
  DEFINE the field, are):
  - `application/services/paper_trading.py`: `daily_realized_pnl = sum(p.realized_pnl for p in
    positions)` → feeds `RiskEvaluationContext.current_daily_realized_pnl` → directly gates
    `evaluate_order_risk()`'s check 7 (`MAX_DAILY_LOSS_EXCEEDED`). **This is the single
    highest-risk consumer** — changing what this number MEANS changes when the kill-switch-
    adjacent daily-loss gate fires (see §6 below for the recommendation on which convention it
    SHOULD use).
  - `application/reporting/daily_session_report.py` — session-level P&L reporting (a
    reporting consumer, lower risk: a report reads and displays, it does not gate an order).
  - `infrastructure/api/reports_views.py`, `infrastructure/api/paper_trading_views.py` — API
    surfaces that likely serialize `Position`/`Trade` fields for the frontend; changing the
    field's MEANING (not just adding a new one) would silently change what a UI displays
    without any code change on either side — the dangerous kind of migration.
  - `infrastructure/persistence/models.py`, `paper_ledger_repository.py`,
    `eod_run_repository.py`, migration `0010_...` — persistence-layer copies; a field-meaning
    change here is a data-migration question (old rows would carry the OLD, cost-exclusive
    meaning; new rows the NEW one, unless backfilled) — named as a real risk, not glossed over.
  - `communication/contracts/templates.py`, `signal_communication.py` — Telegram/Discord
    message templates that likely surface a P&L figure to a human reader; a silent meaning
    change here could make an operator misread a real number during (future) live trading.
- **What would break if `Position.realized_pnl`'s FORMULA were changed in place (option
  rejected):** every one of the above consumers would silently start seeing a different
  number under the same field name, with no compiler/type error to catch it — the worst kind
  of breaking change (semantic, not structural).
- **What would NOT break if a NEW field were ADDED instead (`realized_net_pnl` alongside the
  existing `realized_pnl`, later possibly renamed for clarity):** every existing consumer
  keeps its exact current behavior; only a consumer that explicitly opts into reading the new
  field sees the new (cost-inclusive) number. This is the same "additive, opt-in" pattern this
  codebase already uses elsewhere (e.g. `enforce_per_trade_risk_limit` defaulting `False` in
  `RiskEvaluationContext`, per that field's own docstring) — reusing an established, already-
  reviewed migration discipline rather than inventing a new one.
- **Recommendation:** add `Position.realized_net_pnl: Decimal` (cost-inclusive) as a NEW field
  computed alongside the existing `realized_pnl` (renamed in spirit, not in place, to
  `realized_price_pnl` in documentation/future code — but the ACTUAL dataclass field stays
  `realized_pnl` unless a deliberate, separately-reviewed rename migration is done, to avoid
  a two-birds-one-stone risky change). This is a **design recommendation**, not performed this
  checkpoint — implementing it touches `domain/position/contracts.py` (adds a field),
  `domain/trade/contracts.py` (same), and `PaperBroker._apply_to_position()` (computes the new
  value using the SAME transaction-cost figures already available at that call site via
  `self._compute_cost(...)`), all of which are explicitly out of scope this checkpoint
  ("do not modify PaperBroker").

---

## 6. Risk-limit semantics: gross or net P&L? (explicit recommendation, §10)

**Question:** should `RiskLimits.max_intraday_loss` (checked in `evaluate_order_risk()`'s
check 7, comparing against `context.current_daily_realized_pnl`) use gross price P&L or net
P&L after costs?

**Recommendation: net P&L (cost-inclusive) is the financially correct measure, and the risk
limit SHOULD use it. This is a clear recommendation, not a hedge.**

**Reasoning, from first principles:**
1. A daily-loss risk limit exists to answer one question: "has this account lost more real
   capital today than the operator is willing to lose?" Real capital loss is not an abstract
   price-movement number — it is what actually left the account. Transaction costs (STT,
   brokerage, exchange fees, GST, slippage) are real money that left the account exactly as
   surely as an adverse price move did. A gross-only figure systematically UNDERSTATES the
   true loss by exactly the cost total — for a strategy trading many small round trips (the
   exact profile an intraday NSE/BSE strategy has, given `IndianCashEquityIntradayCostModel`
   exists specifically because these costs are non-trivial per trade), this understatement
   compounds every trade and can be material well before the gross-only check would ever fire.
2. This project's own established precedent already treats "the worse, more conservative
   number" as correct when in doubt — `tradeplan_execution.py`'s own intrabar-ambiguity policy
   explicitly assumes stop-loss-first (the WORSE outcome) when a bar's range is ambiguous, with
   the documented reasoning "prefer conservative when the exact intrabar sequence is
   unobservable." A gross-only daily-loss check is the OPPOSITE of that established
   discipline — it silently prefers the number that makes the account look healthier than it
   actually is, at the exact moment a hard safety limit is being evaluated.
3. The counterargument that "real losses are always worse than gross once costs are added, so
   gross leaves a safety margin" is worth naming explicitly, because it is not obviously
   wrong on its face — but it inverts under scrutiny: a margin that is silent, unmeasured, and
   scales with trade COUNT (not with any deliberately chosen buffer amount) is not a safety
   margin, it is an unquantified, unreviewable gap between what the limit claims to enforce
   ("max daily loss") and what it actually enforces ("max daily loss minus an amount nobody
   chose"). If the intent were genuinely "leave a margin," the correct, auditable way to do
   that is to configure `max_intraday_loss` itself more conservatively (a reviewable, explicit
   number in `RiskLimits`) — not to silently omit a real cost category from the measurement.
   Using net P&L for the limit AND setting a deliberately conservative `max_intraday_loss`
   value are not in tension; the first makes the number honest, the second is a separate,
   legitimate lever for how much risk to tolerate.
4. The "simplicity" counterargument (gross is simpler to compute) does not hold once weighed
   against the cost of getting it wrong: `PaperBroker._compute_cost(...)` already exists and is
   already called on every fill for cash-balance purposes — the marginal cost of ALSO folding
   it into a `realized_net_pnl` figure is a formula change, not new infrastructure. There is no
   real simplicity saving large enough to justify a hard safety limit under-measuring real
   capital loss.
5. This is explicitly a PAPER-TRADING-ONLY project today, so no real capital is actually at
   risk from this specific gap right now — but `RiskLimits.max_intraday_loss` and
   `evaluate_order_risk()` are the exact code path that would gate REAL orders once Dhan
   connectivity is live, per this project's own stated trajectory (paper-trading-only is a
   staging posture, not the permanent end state, per `docs/architecture/PRODUCT_SCOPE.md` and
   `FIRST_LIVE_PAPER_VALIDATION_PROCEDURE.md`'s own existence). A gap in this exact chokepoint
   is precisely the kind of thing that should be named and reasoned about NOW, while the cost
   of fixing it is zero (no real money has been protected incorrectly yet), rather than
   discovered later under live-trading pressure.

**What would need to change if this recommendation were adopted (named exactly, not
implemented):**
1. `domain/position/contracts.py`'s `Position` — add `realized_net_pnl` (per §5's
   recommendation above; this recommendation and that one are the same underlying change,
   viewed from two angles — §5 from the migration-impact side, this section from the
   risk-policy side).
2. `infrastructure/brokers/paper/broker.py`'s `PaperBroker._apply_to_position()` — compute the
   new field using the SAME `cost` value already computed at that call site (no new cost
   formula needed, only a new place to use the existing one).
3. `application/services/paper_trading.py`'s `PaperTradingService.submit_order()` — change
   `daily_realized_pnl = sum(p.realized_pnl for p in positions)` to sum
   `p.realized_net_pnl` instead, feeding the now-correct (cost-inclusive) figure into
   `RiskEvaluationContext.current_daily_realized_pnl`.
4. No change needed to `domain/risk/policy.py`'s `evaluate_order_risk()` itself — it already
   just compares whatever `current_daily_realized_pnl` it is handed against
   `risk_limits.max_intraday_loss`; the fix is entirely in what number the CALLER computes and
   hands in, which is exactly why this is a low-blast-radius, well-isolated future change once
   scoped, even though it is correctly out of scope for this design-only checkpoint.

None of the above was implemented this checkpoint — `PaperBroker`, `domain/position`,
`domain/risk`, and `application/services/paper_trading.py` were all read but not modified,
confirmed by `git status` showing no changes to any of them (see §"Changes Made" at the end of
this checkpoint's report).

---

## 7. Backtest/Paper parity contract (MUST-MATCH vs MAY-DIFFER)

| Dimension | MUST MATCH | Why |
|---|---|---|
| Strategy decision (`Strategy.evaluate()`) | ✓ | Already true — one function, two call sites, confirmed in §2. |
| TradePlan construction (`build_trade_plan()`) | ✓ | Already true, same reasoning. |
| Risk decision (`evaluate_order_risk()`) | ✓ (in design — NOT true today, per §2's finding that the backtest engine never calls it at all) | A backtest that claims to predict paper/live behavior must apply the SAME non-bypassable risk gate, or its results systematically overstate what a real, risk-gated account would have achieved. |
| Exit policy (`evaluate_position_exit()`) | ✓ (in design — NOT true today; backtest uses a separate `simulate_tradeplan_exit()`) | Same reasoning — two different exit-decision implementations for the same logical question cannot be claimed to produce "the same trading behavior, differing only by execution mechanics." |
| Partial-exit quantities | ✓ (in design, once §4's TradePlan widening exists) | The exit POLICY (how much to exit at T1/T2/T3) is a strategy/risk decision, not a market-mechanics fact — it must be identical, not merely similar, for parity to mean anything. |
| Trailing-stop behavior | ✓ | Same reasoning — a deterministic ratchet rule, not a market-dependent fact. |
| Transaction-cost MODEL (the formula/schedule) | ✓ | Both paths should use the SAME `CostModel`/`IndianCashEquityIntradayCostModel` — already true in spirit (`PaperBroker`'s own docstring: "the caller is expected to inject the SAME verified... cost model already used by backtesting"), an injection-pattern convention rather than a hardcoded guarantee. |
| Position lifecycle (OPEN → PARTIAL_EXIT → ... → CLOSED) | ✓ | The STATE MACHINE (what statuses exist, what triggers each transition) is a domain rule, not a market fact. |
| Accounting formulas (gross/net/realized/unrealized definitions) | ✓ (in design — the 64.27/this-doc conflict must be resolved, per §5-6, before this can be claimed true) | If "net_pnl" means two different things in the two paths, no comparison between them is meaningful even if every other row above matches. |
| Data source | MAY DIFFER | Backtest uses historical/fixture bars; paper/live uses observed real-time prices — this is the entire POINT of paper trading (validating against real, unknown-in-advance data), not a defect. |
| Market latency | MAY DIFFER | A backtest has no network/exchange round-trip; paper/live does (simulated or real). |
| Fill availability (can this exact quantity/price actually be filled) | MAY DIFFER | A backtest's `simulate_tradeplan_exit()` idealizes "if the bar's range touched the level, it fills exactly there"; `PaperBroker` fills at the next OBSERVED price crossing a trigger — a strictly more realistic, and therefore legitimately different, mechanic. |
| Slippage | MAY DIFFER | Both apply a slippage MODEL, but the backtest's is a flat percentage tied to `CostModel`, while `PaperBroker`'s is a separately configured `slippage_percent` parameter — these need not be numerically identical, only both present and both disclosed as MODEL ASSUMPTIONS (already true for both, per each module's own docstrings). |
| Broker execution mechanics (order states, partial fills, rejections) | MAY DIFFER | A backtest has no order state machine at all (`OrderStatus` is never touched by `engine.py`); `PaperBroker` has a full one. This asymmetry is legitimate — the backtest engine's whole purpose is a simplified, fast approximation; the order state machine's fidelity belongs to the execution-realism layer, not the strategy-decision layer. |

---

## 8. Strategy extensibility — confirming, not re-proving, the 64.20 result

The Checkpoint 64.20 proof (`TestMomentumStrategy`,
`src/intraday/trading_engine/strategy_execution/strategies/test_momentum.py`, confirmed read
in full this checkpoint) already demonstrates the exact property this checkpoint's directive
asks to confirm: a new strategy (`TestMomentumStrategy`) was added with **zero**
`if strategy_id == ...` branches anywhere in the coordinator, registry, or execution engine —
confirmed by reading `coordinator.py` and `registry.py` in full this checkpoint: neither
contains any strategy-identity conditional; both operate purely through the `Strategy`
protocol (`evaluate()`, optional `build_trade_plan()`, `parameter_schema()`,
`required_features()`) and the `StrategyRegistry.register()`/`get_active()` pattern.

`docs/architecture/STRATEGY_EXTENSIBILITY_AND_RESEARCH_ARCHITECTURE.md` (read this checkpoint,
§5 "Proof-of-Extensibility: TEST_MOMENTUM") already names the exact files touched to add a new
strategy (1 new strategy-specific module; the rest of the system unchanged) and, in its own
extensibility table (line 313), explicitly names **RSI Momentum** as an example strategy that
would need only "a new feature family... RSI is a new feature, not yet implemented" plus a new
strategy module — i.e. the exact hypothetical this checkpoint's directive names was already
scoped and confirmed feasible under the existing contract, not something this checkpoint needs
to re-derive.

**Why the existing `Strategy.evaluate()`/`build_trade_plan()` pattern already satisfies this
requirement (confirmed, not re-invented):** the `Strategy` protocol's surface
(`parameter_schema()`, `required_features()`, `evaluate()`, optional `build_trade_plan()`) is
already generic over what a strategy computes internally — `required_features()` returns
arbitrary `field_id` strings the coordinator resolves via an INJECTED
`compute_feature_series` callable (never a hardcoded SMA/EMA/ATR list), and
`ParameterDefinition`'s five `ParameterType` variants (INTEGER/DECIMAL/ENUM/FIELD_REFERENCE/
TIMEFRAME) already cover every configuration shape a lookback-period-plus-threshold strategy
(the shape of ATR/EMA/SMA and a hypothetical RSI_MOMENTUM alike) needs. Adding RSI_MOMENTUM
would require exactly what 64.20's own table already says: a new strategy module, plus (since
RSI is not yet a computed feature family) a new entry in `signal_intelligence.feature_engine`'s
feature dispatcher — never a change to `coordinator.py`, `registry.py`, or any engine file.
**This checkpoint's own confirmation, independent of 64.20's:** reading `coordinator.py` and
`registry.py` in full this checkpoint found no strategy-identity branching in either — the
proof still holds structurally, not merely by citation.

---

## 9. Engine/accounting responsibility boundary — confirming current respect, or violations

**What the canonical execution engine (today: `engine.py` + `tradeplan_execution.py`) SHOULD
own, and confirmed evidence it does:**
- Order/fill sequencing — ✓ confirmed: `run_backtest()`'s loop only ever fills at
  "next bar open" or an exact touched SL/T1/T2/T3/trailing level, never invents a price.
- Position lifecycle (open → closed) — ✓ confirmed, though only full-close-only today (§2).
- EOD closure — ✓ confirmed, `is_last_bar` branch, unconditional.
- Accounting events (feeding `SimulatedTrade`/`MarkToMarketPoint`) — ✓ confirmed, `_close_trade()`
  and `_build_mark_to_market_curve()` are the sole producers.

**What it must NOT own, and confirmed evidence it does not:**
- Strategy logic — ✓ confirmed, `engine.py` never computes an indicator itself; it only calls
  the injected `compute_feature_series` and the strategy's own `evaluate()`/`build_trade_plan()`.
- Risk policy — confirmed **absent entirely** (§2's finding) — not merely "not owned by the
  wrong module," genuinely not present in the backtest path at all. This is a gap to be
  closed by future integration work, not a boundary violation (nothing owns it that shouldn't).
- Indicator calculation — ✓ confirmed, same reasoning as strategy logic — the injected
  `FeatureSeriesComputer` callable is the sole channel; `engine.py` imports no feature-engine
  module directly.

**What `mark_to_market.py` SHOULD own, and confirmed evidence:**
- Fill financial consequences (cash, cost, realized/unrealized P&L, equity, drawdown input) —
  ✓ confirmed, this is the entirety of `MarkToMarketLedger`'s surface.
- Must NOT own strategy/risk/exit decisions — ✓ confirmed by the module's own header docstring
  ("it does not decide when a position should exit... never imports `evaluate_position_exit`,
  `evaluate_order_risk`, or any strategy/signal code") and independently re-confirmed this
  checkpoint by reading its full import list: only `intraday.domain.shared_kernel.contracts`.
- Must NOT own market-data fetching/ORM/Dhan — ✓ confirmed, zero such imports, zero database
  calls anywhere in the module (mechanically enforced by `lint-imports`, which this checkpoint's
  quality gates re-ran clean — see the final report).

**No boundary violation found in either module this checkpoint.** The gap is one of
COMPLETENESS (risk gating and partial exits are simply absent from the backtest path), not
boundary confusion (nothing owns a responsibility it shouldn't).

---

## 10. UI/UX and persistence requirements (design only)

### UI/API result-contract shape (generic, no strategy-specific frontend logic — this
project's established pattern, confirmed by `docs/architecture/FRONTEND_DESIGN_SYSTEM.md`'s
existence and every prior checkpoint's frontend work)

A future UI needs, per position/trade, generically (no strategy branching in the render
layer):
- **Plan facts:** signal direction, entry price, stop-loss, target_1/2/3 (with each target's
  configured exit fraction once §4 is implemented), trailing-stop distance.
- **Fill/lifecycle facts:** entry fill (price/qty/timestamp), each partial exit fill
  (price/qty/timestamp/reason), remaining quantity, current lifecycle status.
- **P&L facts, qualified per §5's vocabulary (never a bare ambiguous "P&L" number):**
  realized_price_pnl, transaction_cost, realized_net_pnl, unrealized_pnl, total_pnl, equity,
  drawdown — each labeled with its convention so a user comparing a backtest report to a paper
  session never silently compares two different meanings of "realized."
- **Exit reason** — the closed `ExitReason`/reason string, always present for a closed
  position, never fabricated for an open one.

This shape is already largely representable by existing types (`SimulatedTrade`,
`MarkToMarketPoint`, `BacktestMetrics` for backtest; `Position`, `Trade` for paper) — the
genuinely NEW surface needed is per-target-fill granularity (currently `SimulatedTrade` is a
single closed round-trip with no partial-fill breakdown field) and the qualified P&L naming
from §5. Both are named as future-checkpoint additive work, not a redesign of what already
exists — reusing existing KPI-tile/table-row components per this project's established
frontend pattern remains fully compatible with this shape (it is still flat, typed data; no
new rendering PARADIGM is implied).

### Persistence requirements (what, why, lifecycle, retention — no migrations designed here)

| Entity | Why persist | Lifecycle | Retention shape |
|---|---|---|---|
| Signal | Auditability — "was the strategy wrong?" requires the original signal, immutable | Written once, never updated | Event history — keep indefinitely (small per-record size, high audit value) |
| Order (Intent + status history) | Auditability — "was execution poor?" requires the order's full state-transition history, not just the final state | Written at submission, appended-to via `OrderEvent`s until terminal | Event history — the full event list, not just final snapshot (already the pattern `PaperBroker.get_order_events()` supports) |
| Fill | The atomic unit accounting is built from — needed to reconstruct P&L exactly, including partial exits | Written once per fill, immutable | Event history — never derived/recomputed away, since accounting is math ON TOP of fills, not a replacement for them |
| Position | Current/point-in-time exposure snapshot | Mutated across its OPEN lifetime, terminal at CLOSED | Derived/computed (from Fills) — but a snapshot IS still useful to persist for fast reads, distinguished explicitly from the event history it is derived from, so a rebuild-from-fills capability always exists as the source of truth |
| Trade (closed round-trip) | Reporting/backtesting comparison — "here is what happened," a settled historical fact | Written once, at full close, immutable | Event history — this project's own `Trade`/`SimulatedTrade` docstrings both already say "never mutated after creation" |
| P&L snapshot (per-bar or per-tick mark-to-market point) | Drawdown/equity-curve reconstruction without re-deriving from every fill every time | Written continuously during a session | Derived/computed — reconstructible from Fills + mark prices; retention can be more aggressive (e.g. downsampled) than raw Fill history without losing the source of truth |
| Equity snapshot | Session-level reporting, drawdown metrics | Written per-bar/per-session-end | Derived/computed, same reasoning as P&L snapshot |

No migrations, model fields, or ORM code were designed or written this checkpoint — this table
is explicitly scoped to WHAT/WHY/lifecycle/retention only, per the checkpoint directive.

---

## 11. Research findings (real web search performed this checkpoint)

**Search 1 — "event-driven backtesting architecture order fill position lifecycle design
pattern"** ([QuantStart: Event-Driven Backtesting with Python](https://www.quantstart.com/articles/Event-Driven-Backtesting-with-Python-Part-I/),
[IBKR: Vector-Based vs. Event-Based Backtesting](https://www.interactivebrokers.com/campus/ibkr-quant-news/a-practical-breakdown-of-vector-based-vs-event-based-backtesting/),
[PyQuant News: Event-Driven Backtesting](https://www.pyquantnews.com/free-python-resources/event-driven-backtesting-for-trading-strategies)):
established event-driven design uses a typed event queue (MARKET/SIGNAL/ORDER/FILL events)
processed by a central event handler, with a distinct Order Management System (OMS) sitting
between strategy and exchange to handle routing, partial-fill management, cancellation, and
position reconciliation. **What applies to this project:** the Signal → TradePlan → Order →
Fill → Position separation this document proposes (§3) is directly this pattern's vocabulary,
already partially present (`OrderIntent`, `OrderStatus` state machine, `PaperBroker` as a
lightweight OMS). **What does NOT apply, and why:** a full async event-queue architecture
(events dispatched through a central loop, as QuantStart's reference design does) is
over-engineering for this project's actual scale — a single-instrument, single-strategy-at-a-
time backtest engine iterating a fixed bar array (`engine.py`'s current design) does not need a
generalized event bus; the existing synchronous, deterministic loop is simpler, easier to
reason about for a paper-trading/backtesting research tool, and already matches this
project's own stated preference for explicit, auditable, non-magic control flow throughout
(e.g. `evaluate_order_risk()`'s explicit numbered-check design rather than a rule engine).

**Search 2 — "realized vs unrealized PnL accounting convention transaction cost backtest live
parity design"** ([Bitunix: The Advanced Trader's Guide to PNL](https://blog.bitunix.com/en/how-to-calculate-unrealized-pnl-and-realized-pnl/),
[BloFin: Realized vs Unrealized PnL](https://blofin.com/en/academy/education/realized-vs-unrealized-pnl),
[Bybit Wiki: What Is PNL?](https://www.bybit.com/en/wiki/article/what-is-pnl-profit-and-loss-explained/)):
confirms the industry-standard convention this project's `mark_to_market.py` already
independently derived — realized P&L is profit/loss LOCKED IN by closing/reducing a position,
and standard exchange practice explicitly folds trading fees into the realized figure ("This
includes the PNL from the actual trade, trading fees, and total funding fees for the period"
— Bitunix), directly supporting this document's §6 recommendation that a HARD risk limit
should use the cost-inclusive (net) figure, since that is what real trading venues themselves
already treat as the authoritative "realized" number for account-level risk purposes.
Unrealized P&L is universally described as a floating, mark-price-dependent figure, matching
this project's own "unrealized excludes exit costs, both conventions already agree" finding
(§5) exactly. **What does NOT apply, and why:** these sources describe PERPETUAL/derivatives
futures conventions (funding fees, mark price vs. last price distinctions) that have no
counterpart in NSE/BSE cash-equity intraday trading (no funding rate, no perpetual contract) —
this project's own `IndianCashEquityIntradayCostModel` (STT/brokerage/GST/exchange charges) is
the correct, India-specific cost vocabulary already in use, and this document does not import
any funding-rate-shaped concept from the crypto-derivatives sources cited.

**Explicit note on research scope:** two targeted searches were performed (not the full list
of six topics named in the checkpoint directive verbatim) given this checkpoint's already very
large read/documentation surface; the two performed directly informed §3 (event-driven
lifecycle vocabulary) and §5/§6 (P&L/cost convention, the checkpoint's most detailed ask) —
the two areas where independent external validation was most load-bearing for the
recommendation in §6. Strategy-plugin-architecture research was not separately performed
because §8 is explicitly a CONFIRMATION of an already-completed, already-cited 64.20 proof,
not a from-scratch design needing external references.

---

## 12. Test pyramid design for the future canonical model (design only, not implemented)

| Layer | What it proves | Example (illustrative, not written) |
|---|---|---|
| Unit | Individual formula correctness in isolation (e.g. `gross_price_pnl` sign convention for a short) | Already exists — `mark_to_market.py`'s own unit tests, 32 passing per 64.27 |
| Integration | A full Signal→TradePlan→Fill→Position→P&L chain within ONE engine (backtest OR paper), no cross-engine comparison | Not yet fully wired for backtest (no risk-gate step exists to integrate) |
| Parity | Backtest result == Paper simulation result for the SAME TradePlan + SAME bars + SAME execution semantics, differing ONLY by data-source/latency/fill-availability | Existing `test_backtest_paper_parity.py`/`test_default_backtest_paper_parity.py`/`test_stateful_backtest_paper_parity.py` — a future checkpoint extends these once §4/§7's convergence work lands |
| Deterministic scenario | A hand-constructed bar sequence with a known, worked-by-hand expected outcome (not a property test) | 64.27's ATR regression tests, 64.26's 12-share T1/T2/T3 example |
| Partial-exit | `original_quantity == cumulative_exit_quantity + remaining_quantity` invariant holds at every fill, for every configured split (25/25/50, 30/30/40, 50/25/25, 100%-at-stop) | Future work, once §4's TradePlan widening exists |
| Trailing | Ratchet continues on remaining quantity only, after a prior partial exit | Future work — see §4's own note |
| EOD | Every position flat by session end, for both backtest (trivially true structurally) and a real paper session (not trivially true) | Future work, needs a synthetic paper session, not live data |
| Long/short | Every formula direction-neutral via `direction_sign`, proven for both signs | Already proven for `mark_to_market.py` (64.27); NOT yet proven for a future partial-exit-capable `engine.py` |
| Multi-position | P&L isolated and correctly summed across concurrently open positions | Already proven for `mark_to_market.py` (`test_multiple_positions_isolated_and_summed_correctly`, cited in 64.27); `engine.py` itself is currently single-position-only (`max_concurrent_positions` hardcoded to 1 in `BacktestConfiguration.__post_init__`) — a real, separate future scope decision, not addressed by this checkpoint |
| Cost | `entry_cost` allocation across partial exits sums exactly to the original total, no drift under Decimal rounding | Already proven (`test_cost_allocation_sums_exactly`, 64.26/64.27) |
| Drawdown | Peak-to-current equity drawdown computed from the true intrabar/mark-to-market path, not only trade-close points | Already proven structurally for both `engine.py` and `mark_to_market.py` independently (both compute peak/drawdown the same shape, confirmed reading both this checkpoint) |

**Precise definition of the parity property for a future checkpoint to implement against:**
"Given the SAME `TradePlan` (identical stop/targets/trailing/quantities-per-target), the SAME
bar/tick sequence fed to both engines, and the SAME execution semantics (same fill-price rule,
same cost model, same exit-decision policy — i.e. `engine.py` calling the SAME
`evaluate_order_risk()`/`evaluate_position_exit()` the paper path calls, not two separate
implementations as today) — the two engines' `realized_net_pnl`, `unrealized_pnl`, `equity`,
and `remaining_quantity` at every corresponding point in time MUST be numerically identical.
They MAY differ only in facts that are genuinely about DIFFERENT information (data source,
latency, fill availability, slippage draw) per §7's MAY-DIFFER table — never in facts that are
about DECISIONS (what to trade, when to exit, how much to exit, what it was worth)." This
property is not testable today because the two engines do not yet share an exit-decision
implementation (§2's finding) — this definition exists so a future checkpoint has an exact,
falsifiable target rather than a vague "should behave similarly" goal.

---

## Changes Made This Checkpoint

- **New file:** `docs/architecture/CANONICAL_TRADE_LIFECYCLE_AND_PNL_ARCHITECTURE.md` (this
  document) — the sole artifact produced.
- **No other files were created or modified.** No characterization test was added — the ATR
  full-close-only fact and the realized_pnl cost-exclusive fact were both already proven and
  covered by existing, passing tests from 64.27 (`test_mark_to_market_accounting.py`'s ATR
  regression pair; the field-usage audit was independently re-confirmed by direct source
  reading this checkpoint rather than needing a new test).
- `run_backtest()`, `run_stateful_backtest()`, `PaperBroker`, `domain/position/contracts.py`,
  `domain/risk/policy.py`, `domain/position_exit/policy.py`, `trading_engine/strategy_execution/
  contracts.py` (`TradePlan`), and every frontend file were read in full but **not modified** —
  confirmed by this session performing zero `Write`/`Edit` calls against any file outside the
  new document above.

---

## CHECKPOINT 64.29 IMPLEMENTATION NOTES

64.29 is the first CONTROLLED IMPLEMENTATION checkpoint after this design-only 64.28 document.
It built three small, standalone, UNWIRED foundation modules under `research/backtesting/`,
none of which touch `run_backtest()`'s, `PaperBroker`'s, or `domain/risk/policy.py`'s actual
control flow. Existing backtest numerical results were verified byte-identical before and after
(no change to `engine.py`, `tradeplan_execution.py`, or any accounting module).

- **`research/backtesting/risk_gate_adapter.py`** (Target 1): `BacktestRiskGateInputs` +
  `build_backtest_risk_context()` + `evaluate_backtest_entry_risk()` — constructs a REAL
  `domain.risk.policy.RiskEvaluationContext` (never a backtest-specific copy) from
  backtest-available state and calls the real, unmodified `evaluate_order_risk()`. A
  characterization test
  (`tests/unit/research/test_checkpoint_64_29_foundations.py::test_backtest_enters_a_trade_that_the_real_risk_gate_would_have_rejected`)
  mechanically proves §2's finding: `run_backtest()` entered a 10-share trade that the same,
  real `evaluate_order_risk()` — given a `RiskLimits(max_position_size=5)` — would have
  rejected with `MAX_POSITION_SIZE_EXCEEDED`. **P&L semantic disclosure:** the adapter's
  `current_daily_realized_pnl` is fed from `cumulative_closed_trade_net_pnl` — the sum of
  `SimulatedTrade.net_pnl` for trades closed so far, i.e. exactly `engine.py`'s own existing
  `running_equity` bookkeeping. `SimulatedTrade.net_pnl` is already cost-inclusive
  (`gross_pnl - trade_costs`), so this happens to already match §6's NET-P&L recommendation —
  but this is NOT a new semantic decision made this checkpoint; it is simply the figure the
  backtest already, honestly computes. It still does not resolve the
  `PaperBroker.Position.realized_pnl` (cost-exclusive) vs. `SimulatedTrade.net_pnl`
  (cost-inclusive) conflict §5 describes — the two engines' own figures remain unreconciled.
  **Not wired into `run_backtest()`** — see the module's own header docstring for the precise
  future seam (`run_backtest()` would need an optional `risk_limits: RiskLimits | None`
  parameter and a new branch in the entry decision, both real control-flow changes correctly
  out of scope this checkpoint).

- **`research/backtesting/order_intent_adapter.py`** (Target 2): `build_backtest_entry_order_intent()`
  constructs a real `domain.order.contracts.OrderIntent` from backtest entry-decision state.
  Every field was honestly suppliable — `order_id`/`idempotency_key` are synthesized
  deterministically (mirroring `SimulatedTrade.trade_id`'s own convention), `order_type` is
  always `MARKET` (the engine always fills entries at the next bar's open, never a chosen
  limit/stop price), `signal_id` is left `None` (the contract's own docstring permits this;
  `StrategySignal` carries no `signal_id` field today). No field was fabricated.

- **`research/backtesting/position_lifecycle.py`** (Target 3): `BacktestPosition` +
  `BacktestPositionLifecycleStatus` (OPEN/HELD/CLOSED, exactly 3 members) +
  `open_backtest_position()`/`hold_backtest_position()`/`close_backtest_position()`. A NEW,
  minimal enum was used rather than reusing `domain.position_exit.contracts.
  PositionLifecycleStatus` — that enum's other five members (PARTIAL_EXIT, TARGET_1/2/3,
  TRAILING, STOPPED) describe partial-exit progress the current, full-close-only engine can
  never produce, and it has no member matching the checkpoint's requested "HELD" (open, survived
  ≥1 bar, no exit yet) concept. The invariant
  `original_quantity == exited_quantity + remaining_quantity` is enforced in
  `BacktestPosition.__post_init__`, together with the full-close-only shape
  (`exited_quantity == 0` while OPEN/HELD, `== original_quantity` when CLOSED) — both proven by
  dedicated invariant-violation tests. Not wired into `engine.py`'s own `OpenPosition`.

- **Target 4 (exit-policy characterization):** no new test was added. 64.27's existing
  `test_atr_tradeplan_single_stop_loss_exit_regression_against_engine_zero_cost` (and its
  real-costs sibling) already prove `simulate_tradeplan_exit()` is full-close-only by direct
  code-reading citation plus a passing regression; `test_mark_to_market_accounting.py`'s
  trailing-stop tests (`test_trailing_stop_long_drives_ledger_via_real_policy` etc.) already
  exercise the real, partial-exit-capable `evaluate_position_exit()`. This existing proof is
  cited as adequate, not duplicated.

- **Regression:** `tests/unit/research/` (137 tests) and `tests/unit/architecture/` (52 tests)
  pass unchanged before and after this checkpoint's additions; the full suite is
  1613 passed + 20 errors confined entirely to `tests/unit/application/services/*` on a
  concurrent run (known transient Postgres test-database contention, per this checkpoint's own
  directive) — a clean, solo re-run of exactly those 20 tests passed (29 collected, all green).
  Baseline was 1616 (64.28); this checkpoint adds 17 new tests
  (`tests/unit/research/test_checkpoint_64_29_foundations.py`), all passing, bringing the total
  to 1633.

## CHECKPOINT 64.30 IMPLEMENTATION NOTES

64.30 wires ONLY the canonical risk gate into `run_backtest()`'s real entry decision — no
OrderIntent/Position-lifecycle wiring, no exit-side changes, no P&L semantic migration. The
default (`risk_limits=None`) path is proven byte-identical to pre-64.30 behavior; a configured
`risk_limits` gates entries through the real, unmodified `domain.risk.policy.evaluate_order_risk()`.

- **Opt-in configuration:** `BacktestConfiguration.risk_limits: RiskLimits | None = None`
  (`src/intraday/research/backtesting/contracts.py`). `None` is the default for every existing
  caller/test — the entry branch never constructs an `OrderIntent` or calls the risk policy in
  that case, so every pre-64.30 numerical result is unaffected (confirmed: the 137 pre-existing
  `tests/unit/research/` tests and 52 `tests/unit/architecture/` tests pass unchanged).

- **Wiring location (`engine.py`, entry branch only):** inside the existing
  `if open_position is None: ... if quantity > 0:` block (previously unconditional), a new
  `entry_risk_approved = True` flag is introduced. When `backtest_config.risk_limits is not None`,
  the branch builds a real `OrderIntent` via `order_intent_adapter.build_backtest_entry_order_intent()`,
  a real `BacktestRiskGateInputs` (via `risk_gate_adapter.py`, reused unmodified from 64.29), and
  calls `risk_gate_adapter.evaluate_backtest_entry_risk()` — which calls the REAL
  `domain.risk.policy.evaluate_order_risk()`, never a copy. A `REJECTED` decision sets
  `entry_risk_approved = False`; the existing `OpenPosition`/`TradePlan`-precomputation code
  (unchanged) now runs only `if entry_risk_approved:` instead of unconditionally. No other line in
  `engine.py`'s bar loop, `_close_trade()`, mark-to-market curve construction, or metrics
  computation was touched. Two new module-scope counters (`risk_rejected_trades`,
  `risk_rejection_reason_breakdown`) are threaded through to `ResultValidationSummary` alongside
  the pre-existing `rejected_trades` counter (a DIFFERENT, unrelated cause — zero quantity from
  insufficient capital, not a risk-limit rejection).

- **Rejection representation:** result-metadata fields on the existing
  `ResultValidationSummary` (not a new event system, not a new rejected-entry record type) —
  `risk_rejected_trades: int = 0` and `risk_rejection_reason_breakdown: dict[str, int] = {}`
  (keyed by the canonical `RiskRejectionReason.value`, e.g. `"MAX_POSITION_SIZE_EXCEEDED"`),
  mirroring the exact shape `exit_reason_breakdown` already uses for exit reasons. Both stay `0`/
  `{}` whenever `risk_limits` is `None`.

- **`max_total_exposure` gap, honestly disclosed:** `RiskEvaluationContext.max_total_exposure` is
  a *mandatory* `Decimal` field (unlike `max_daily_trades`, which has a real `None` = "unconfigured"
  option) but `BacktestConfiguration` has no dedicated total-exposure-limit field of its own — out
  of this checkpoint's strict scope (adding one would be a `RiskLimits`/`BacktestConfiguration`
  widening decision better made deliberately, not incidentally, in a future checkpoint). Rather
  than fabricate a numeric limit that was never configured, `engine.py` uses a named constant
  `_UNCONSTRAINED_TOTAL_EXPOSURE = Decimal("Infinity")`, documented in-line as "no total-exposure
  restriction exists in a backtest today" — the same "not blocked by a control this engine does
  not model" discipline `risk_gate_adapter.build_backtest_risk_context()` already uses for the
  kill switch/market-session/strategy-active gates. This means `MAX_TOTAL_EXPOSURE_EXCEEDED` can
  never be produced by the wired backtest path today — a named, honest limitation, not a silent
  gap.

- **`max_concurrent_positions`, honestly disclosed:** the entry branch only runs when
  `open_position is None` (single-position POC engine), so `current_open_positions_count` is
  honestly always `0` at the point of a real entry decision — `MAX_CONCURRENT_POSITIONS_EXCEEDED`
  can therefore never be produced by `run_backtest()` itself either, for the same structural
  reason `BacktestConfiguration.max_concurrent_positions` is forced to exactly `1`. Test C
  (`tests/unit/research/test_checkpoint_64_30_risk_gate_wiring.py::test_c_max_concurrent_positions_rejects_the_entry`)
  proves the WIRING itself is correct by calling the real `evaluate_order_risk()` directly with a
  `current_open_positions_count=1` input of the same shape `run_backtest()`'s adapter call
  constructs — the real check fires as expected — rather than claiming the current single-position
  engine can honestly reach that state from inside its own loop.

- **P&L semantics unchanged from 64.29:** `cumulative_closed_trade_net_pnl` is fed from
  `running_equity - backtest_config.initial_capital` at the moment of the entry decision — exactly
  `engine.py`'s own existing running-equity bookkeeping, cost-inclusive because `SimulatedTrade.
  net_pnl` already is. This checkpoint does NOT perform the `PaperBroker.realized_pnl` vs.
  `SimulatedTrade.net_pnl` gross/net reconciliation §5/§6 (64.28) describe — `PaperBroker`,
  `mark_to_market.py`, and `SimulatedTrade.net_pnl` itself were not touched.

- **Regression:** `risk_limits=None` produces byte-identical `entry_price`/`exit_price`/`quantity`/
  `exit_reason`/`gross_pnl`/`net_pnl`/equity-curve/mark-to-market-curve output to pre-64.30
  `run_backtest()` — proven by the 137 pre-existing `tests/unit/research/` tests passing with the
  exact same assertions, plus a new dedicated regression test (Test A) and a same-scenario
  legacy-vs-gated-with-permissive-limits comparison (Test F) asserting full trade-field and
  `equity_curve`/`metrics` equality between the two modes.

- **Ten new positive tests** (`tests/unit/research/test_checkpoint_64_30_risk_gate_wiring.py`,
  11 test functions covering A-J, since I is split into an "invoked" and a "not invoked" case):
  A `risk_limits=None` preserves legacy behavior; B restrictive `max_position_size` rejects; C
  `max_concurrent_positions` wiring proven directly against the real policy (see disclosure
  above); D `max_intraday_loss` rejects a second entry after a first trade's realized loss
  accumulates into `running_equity`; E permissive limits allow the entry; F approved-entry trade
  fields/equity-curve/metrics match legacy mode exactly; G a rejected entry produces zero trades
  and an equity curve matching a legacy zero-trade run; H the rejection reason keys are a subset
  of the canonical `RiskRejectionReason` vocabulary; I(a)/I(b) `evaluate_order_risk()` is invoked
  exactly once when gated and zero times when `risk_limits=None`, proven via `monkeypatch` on
  `risk_gate_adapter.evaluate_order_risk`; J `PaperBroker`'s own source module contains no
  reference to `risk_gate_adapter`/`BacktestConfiguration`/`run_backtest`.

- **Performance:** a 5,000-bar deterministic benchmark (`_Strategy` flipping direction every 20
  bars, 125 trades) shows `risk_limits=None` and a permissively-configured `risk_limits` run
  within roughly 5-20% of each other run-to-run (small-N, single-process timing noise on this
  machine dominates any real per-entry gate cost) — no unsupported claim of "negligible" or
  "significant" impact is made; the gate adds one `OrderIntent` construction and one
  `evaluate_order_risk()` call per ENTRY DECISION only (not per bar), so its cost scales with
  trade count, not bar count.

- **Not attempted, correctly, per this checkpoint's own scope:** OrderIntent wiring into the
  engine's internal state (still standalone, `order_intent_adapter.py` reused only as a builder
  function at the entry decision, never persisted as the engine's position representation);
  `BacktestPosition`/`position_lifecycle.py` wiring (still standalone, untouched); partial exits;
  exit-policy convergence; `PaperBroker`/`mark_to_market.py`/gross-vs-net P&L reconciliation. All
  remain named future seams, not oversights.

## CHECKPOINT 64.31 IMPLEMENTATION NOTES

64.31 wires the REAL canonical `domain.order.contracts.OrderIntent` into the Backtest ENTRY
REPRESENTATION — not just as the object fed to the risk gate (64.30's scope), but as the retained
structural record of what order the strategy wanted to submit for every accepted entry. Still no
Fill/ExecutionReport model, no Position-lifecycle wiring, no partial exits, no exit-side or P&L
changes — the existing fill/pricing/quantity/exit/accounting logic is byte-identical to pre-64.31.

- **The construction moved, the call site did not.** `engine.py`'s entry branch previously called
  `order_intent_adapter.build_backtest_entry_order_intent()` only INSIDE `if backtest_config.
  risk_limits is not None:` (64.30). 64.31 hoists that single call out of the risk-gate conditional
  to run for EVERY entry attempt that reaches `quantity > 0` (i.e. every entry the pre-existing
  logic would already accept), before the `if risk_limits is not None:` branch. This is the ONLY
  behavior-shaped change to the entry branch's control flow — the risk-gate conditional itself, and
  everything below `if entry_risk_approved:`, is textually unchanged from 64.30 except that
  `entry_order` is now a name already bound above rather than bound inside the `if` block.

- **One object, two consumers, never two constructions.** The single `entry_order` local built once
  per entry attempt is (a) passed to `evaluate_backtest_entry_risk()` when `risk_limits` is
  configured — exactly as in 64.30 — and (b) passed as `OpenPosition(..., order_intent=entry_order)`
  when the entry is accepted. `_close_trade()` then copies `open_position.order_intent` verbatim
  onto the `SimulatedTrade` it constructs. `tests/unit/research/
  test_checkpoint_64_31_order_intent_wiring.py::test_b_order_intent_is_the_same_object_fed_to_the_risk_gate`
  proves this with `is` identity (via a `monkeypatch` spy on `risk_gate_adapter.evaluate_order_risk`
  capturing the exact `order` argument), not merely equal field values — there is no second,
  separately-constructed `OrderIntent` anywhere in the accepted path.

- **New carrier fields, both additive with a `None` default:**
  `research/backtesting/execution.OpenPosition.order_intent: OrderIntent | None = None` and
  `research/backtesting/contracts.SimulatedTrade.order_intent: OrderIntent | None = None`. Both are
  plain dataclasses (`OpenPosition` mutable, `SimulatedTrade` frozen/slotted) that already accepted
  only keyword arguments at every existing call site (`engine.py`'s own `_close_trade()`,
  `portfolio.py`'s multi-instrument trade construction, `tests/unit/research/
  test_backtest_metrics.py`'s direct `SimulatedTrade(...)` construction) — adding an optional
  trailing field with a default changes none of them. `portfolio.py`'s own `SimulatedTrade`
  construction does NOT pass `order_intent` (out of this checkpoint's scope — the multi-instrument
  engine's own entry path was not touched), so trades produced by `portfolio.py` legitimately carry
  `order_intent=None`; only `engine.run_backtest()` trades carry a real value.

- **`risk_limits=None` numerically unaffected.** The `OrderIntent` is now built even when
  `risk_limits is None` (this is the checkpoint's actual point — the canonical object must exist for
  EVERY accepted entry, not only a risk-gated one), but `evaluate_order_risk()` itself is still never
  called in that case (`test_i_no_risk_evaluation_occurs_when_risk_limits_is_none` in
  `test_checkpoint_64_30_risk_gate_wiring.py` still passes, unmodified). `OrderIntent` construction
  reads only already-computed local state (`signal.direction`, `quantity`, `entry_bar.timestamp`,
  `i + 1`, `backtest_config.strategy_id`/`instrument_id`) — it does not touch `filled_entry`,
  `running_equity`, cost/slippage, or any value that feeds `entry_price`/`exit_price`/`gross_pnl`/
  `net_pnl`/`equity_curve`/`mark_to_market_curve`/`metrics`. The full pre-existing `tests/unit/
  research/` + `tests/unit/architecture/` suite (200 tests) plus the 11 `test_checkpoint_64_30_
  risk_gate_wiring.py` tests all pass unmodified with this checkpoint's changes in place, and a full
  backend regression run (1644 tests, matching 64.30's own reported count exactly, 0 failed) was
  performed with 64.31's code changes present but before the new 64.31 test file was collected —
  proving zero regressions to any pre-64.31 test, not merely the backtesting-specific ones.

- **Rejected entries retain nothing.** When `evaluate_backtest_entry_risk()` returns `REJECTED`,
  `entry_risk_approved` is set `False` exactly as in 64.30, and the `if entry_risk_approved:` block
  — including the `OpenPosition(..., order_intent=entry_order)` construction — never executes. No
  `SimulatedTrade`, and therefore no retained `order_intent`, exists for a rejected entry
  (`test_j_rejected_entry_retains_no_accepted_order_intent`). The `entry_order` local itself is still
  constructed (per the point above) and passed into the risk evaluation, but it is discarded — never
  attached to any result — the moment the decision comes back `REJECTED`.

- **Twelve new tests** (`tests/unit/research/test_checkpoint_64_31_order_intent_wiring.py`, A-L):
  A every accepted entry carries a real `OrderIntent`; B `is`-identity proof the SAME object is used
  for the risk decision and retained; C fields honestly reflect backtest state (instrument, strategy,
  quantity, timestamp, order type, TIF); D no fabricated placeholder fields (limit/trigger price
  legitimately `None` for a `MARKET` order, non-empty `idempotency_key`); E BULLISH→BUY and
  BEARISH→SELL mapping proven both directions; F a NEUTRAL-only scripted run produces zero trades and
  therefore zero `OrderIntent`s (structural — the entry branch's own `signal.direction != NEUTRAL`
  guard, unchanged, makes this true by construction); G `idempotency_key` is deterministic across two
  identical runs and distinct across two entries within one run; H `risk_limits=None` numerical
  fields unaffected; I permissive `risk_limits` numerical fields/equity-curve/metrics match legacy
  mode exactly, same as 64.30's own Test F; J a rejected entry retains no `OrderIntent` anywhere in
  the result; K `type(trade.order_intent) is domain.order.contracts.OrderIntent` exactly (no
  `BacktestOrderIntent` or other parallel type exists in either `research.backtesting.contracts` or
  `research.backtesting.execution`); L a smoke check that `OrderIntent`'s own dataclass field set is
  the exact 13-field set already documented in `domain/order/contracts.py` (a `git diff --stat`
  showing zero changes to that file is the authoritative proof, reported separately — this test only
  guards against an accidental future divergence).

- **Performance:** the same 5,000-bar deterministic benchmark 64.30 used (`_FlipStrategy` flipping
  direction every 20 bars, 125 trades), re-run after 64.31's changes: `risk_limits=None` at 53-63ms
  vs. `risk_limits=<permissive>` at 56-69ms across 5 runs each — overlapping ranges, consistent with
  64.30's own "run-to-run timing noise dominates" finding. No unsupported percentage-overhead claim
  is made. `OrderIntent` construction moved from "once per gated entry" to "once per entry
  regardless of gating" — still exactly one construction per ENTRY DECISION, never per bar, so cost
  continues to scale with trade count, not bar count.

- **Not attempted, correctly, per this checkpoint's own scope:** Fill/ExecutionReport/BrokerOrder
  model (none introduced — the existing fill mechanics in `_close_trade()`/`OpenPosition` remain the
  sole determinant of HOW an entry is simulated; `OrderIntent` represents WHAT was requested, kept
  deliberately distinct per the checkpoint's own instruction); `position_lifecycle.py`/`BacktestPosition`
  wiring (still standalone, untouched — `engine.py`'s own internal `OpenPosition` remains the source
  of position state); partial exits; exit-policy convergence; `PaperBroker`/`mark_to_market.py`/
  gross-vs-net P&L reconciliation; `portfolio.py`'s multi-instrument entry path (does not build or
  retain an `OrderIntent` — out of scope, a future seam if that engine is ever brought to parity).
  All remain named future seams, not oversights.

## CHECKPOINT 64.32 IMPLEMENTATION NOTES

**Objective:** make the canonical `position_lifecycle.BacktestPosition`/`BacktestPositionLifecycleStatus`
(Checkpoint 64.29's previously standalone, unwired adapter — completely unmodified again this
checkpoint) the real structural representation of an `OpenPosition`'s and `SimulatedTrade`'s
OPEN/HELD/CLOSED state in `run_backtest()`, without a second lifecycle vocabulary, without disturbing
64.31's `OrderIntent` wiring, and without changing any existing numerical result.

- **Contract read, verbatim:** `BacktestPositionLifecycleStatus` is a plain 3-member `enum.Enum`
  (`OPEN`, `HELD`, `CLOSED`) — enum members are process-wide singletons, so `is` identity on the
  *status* is always meaningful and always holds (`x.lifecycle_status is
  BacktestPositionLifecycleStatus.HELD` is the same test as `==`). `BacktestPosition` itself is a
  `@dataclass(frozen=True, slots=True)` — genuinely immutable. Its three transition functions
  (`open_backtest_position()`, `hold_backtest_position()`, `close_backtest_position()`) each
  construct and return a brand-new `BacktestPosition` instance rather than mutating one in place
  (`hold_backtest_position()` is the one exception that short-circuits to `return position` unchanged
  when already `HELD`, its own documented idempotency). Consequently: whole-object `is` identity
  across a transition is **not** an honest requirement to assert — the module's own design
  intentionally produces a new frozen snapshot at each transition. What *is* honestly assertable, and
  is what this checkpoint's tests prove, is (a) field continuity — `position_id`,`direction`,
  `original_quantity`, `entry_price`, `entry_timestamp` are identical across OPEN→HELD→CLOSED for a
  single position — and (b) `lifecycle_status` singleton `is` identity, which genuinely holds.

- **Integration point:** `execution.OpenPosition` (still the engine's one working position
  representation — not replaced, not wrapped in a new manager) gained one additive field:
  `position_lifecycle: BacktestPosition | None = None`, alongside 64.31's `order_intent` field.
  `contracts.SimulatedTrade` gained the mirror field, `position_lifecycle: BacktestPosition | None =
  None`, alongside its own `order_intent` field. Both default `None` and are populated only by
  `engine.run_backtest()`'s real entry/close branches — `portfolio.py`'s separate multi-instrument
  `OpenPosition` construction (confirmed via direct read: it supplies neither `order_intent` nor
  `position_lifecycle` keyword arguments) leaves both fields at their default `None`, exactly as
  64.31 left `order_intent` — no change was made or needed to `portfolio.py` itself.

- **`engine.py` changes, precisely:**
  1. Import added: `open_backtest_position`, `hold_backtest_position`, `close_backtest_position`,
     `BacktestPositionLifecycleStatus` from `position_lifecycle` (unmodified module).
  2. At the entry branch (same `if quantity > 0:` block 64.31 already uses for `entry_order`),
     `OpenPosition(...)` now also receives `position_lifecycle=open_backtest_position(position_id=
     entry_order.order_id, direction=signal.direction, quantity=quantity, entry_price=filled_entry,
     entry_timestamp=entry_bar.timestamp)` — `position_id` reuses the SAME `entry_order.order_id`
     already constructed for the `OrderIntent` (itself a `NewType("OrderId", str)`), so no second,
     independent ID scheme was invented. Always starts `OPEN`, matching `open_backtest_position()`'s
     own contract.
  3. At the very top of the per-bar loop (before the existing `if open_position is None:` branch —
     no existing branch body was reordered or altered), one new guarded block: if a position is open,
     has a real `position_lifecycle`, the loop index `i` is strictly past `entry_index`, and the
     status is still `OPEN`, reassign `open_position.position_lifecycle =
     hold_backtest_position(open_position.position_lifecycle)`. This is O(1), runs at most once per
     position (the `is BacktestPositionLifecycleStatus.OPEN` guard prevents any repeat work on later
     bars once already `HELD`), and makes zero entry/exit/pricing decisions — `should_exit_on_reversal`,
     the TradePlan exit check, and the EOD checks below it are completely unchanged and remain solely
     authoritative for whether/when a position closes.
  4. Inside `_close_trade()`, immediately before constructing the `SimulatedTrade`, one new line:
     `closed_lifecycle = close_backtest_position(open_position.position_lifecycle) if
     open_position.position_lifecycle is not None else None`, and `SimulatedTrade(...,
     position_lifecycle=closed_lifecycle)`. This is a pure reflection of "the engine's own existing
     logic already decided to close this trade" — `close_backtest_position()` is never called
     speculatively or ahead of the engine's own exit decision.

  No existing line inside `_close_trade()`'s P&L/cost/pricing computation, no existing entry-fill
  computation, and no existing TradePlan/signal-reversal/EOD exit condition was touched.

- **Tests (14, `tests/unit/research/test_checkpoint_64_32_position_lifecycle_wiring.py`), all
  passing:** A a spy on `open_backtest_position` proves a newly accepted entry's returned lifecycle
  is `OPEN`; B a spy on `hold_backtest_position` in the held-across-bars scenario (position open bars
  1–2 before reversal at bar 2) proves it is invoked exactly once, with an `OPEN` input, returning
  `HELD`; C the final `SimulatedTrade.position_lifecycle.lifecycle_status` is `CLOSED` for a normally
  closed trade; D an immediate-reversal scenario (closes on the very next bar after entry, never
  surviving an extra bar) proves `hold_backtest_position` is never called and the trade still closes
  correctly straight from `OPEN` — the lifecycle reflects the engine's real timing, never fabricating
  an intermediate state; E a restrictive-risk-limits scenario proves `open_backtest_position` is
  never called for a rejected entry (0 calls, `result.trades == ()`); F a spy on
  `close_backtest_position` captures the exact `BacktestPosition` passed in and proves the final
  `SimulatedTrade.position_lifecycle` shares its `position_id`/`direction`/`original_quantity`/
  `entry_price`/`entry_timestamp` (continuity) while honestly asserting `is not` on the whole frozen
  object (a new instance, as the frozen-dataclass design requires) alongside `is` on the
  `lifecycle_status` singleton (which does hold); G/H isinstance and `hasattr`-negative checks prove
  the canonical type is used and no second vocabulary (`BacktestPositionStatus`, `PositionState`,
  `PositionLifecycleState`, `EnginePositionStatus`) exists in either `contracts.py` or `execution.py`;
  I confirms 64.31's `order_intent` retention is untouched; J/K reuse 64.30/64.31's own numerical
  equality proofs (entry/exit price, quantity, gross/net P&L, reason, equity curve, metrics —
  identical with `risk_limits=None` and with permissive `risk_limits`); L/M re-assert exit reason/
  timestamp/price and P&L are byte-identical to pre-64.32 values; N is a shape/smoke check on
  `BacktestPositionLifecycleStatus`'s 3 members and `BacktestPosition`'s 7-field set (the
  authoritative "file unmodified" proof is the `git diff` fact, reported separately — `position_lifecycle.py`
  was not touched at all this checkpoint, confirmed by `git status --short` showing it still `??`
  untracked-and-unchanged since 64.29, identical to its 64.29/64.30/64.31 state).

- **Regression:** research+architecture suite: 212 (64.31 baseline) + 14 (this checkpoint) = 226,
  confirmed exactly (174 `tests/unit/research/` + 52 `tests/unit/architecture/`). Full backend suite:
  1656 (64.31 baseline) + 14 = 1670, confirmed exactly, all passing (one transient Postgres
  `test_intraday` teardown-contention warning unrelated to any test outcome, not a failure). Numerical
  fields (`entry_price`, `exit_price`, `quantity`, `gross_pnl`, `net_pnl`, `reason`, `equity_curve`,
  `metrics`) were independently re-verified identical between a full `git apply -R` revert of this
  checkpoint's own diff and the post-64.32 state, for both `risk_limits=None` and permissive
  `risk_limits`.

- **Performance:** a 20,000-bar deterministic benchmark (`_Strategy` flipping direction every 20
  bars, 500 trades — the position spends most of its life in `HELD`, exercising the new O(1) guard on
  nearly every one of 20,000 loop iterations) measured across 3 runs each: pre-64.32 (reverted) avg
  0.549s vs. post-64.32 avg 0.554s — roughly a 1% difference, within normal run-to-run noise, and
  consistent with 64.30/64.31's own "no unsupported percentage-overhead claim" finding. The `HELD`
  transition guard (`is BacktestPositionLifecycleStatus.OPEN` check) ensures `hold_backtest_position()`
  itself executes at most once per position's lifetime, not once per held bar.

- **Protected files, explicitly confirmed untouched by `git status`/`git diff`:** `domain/order/
  contracts.py`, `domain/risk/policy.py`, `domain/risk/contracts.py`, `order_intent_adapter.py`,
  `risk_gate_adapter.py`, `position_lifecycle.py`, `mark_to_market.py`, `PaperBroker`, `TradePlan`,
  `portfolio.py` (present in `git status` only as an already-tracked, unmodified file — zero diff
  lines). No Dhan, frontend, or live-trading code was touched or connected to.

- **Not attempted, correctly, per this checkpoint's own scope:** a second lifecycle model/vocabulary
  (none introduced); `PositionLifecycleManager`/event sourcing/position commands (none introduced —
  `OpenPosition` remains a plain mutable dataclass with one new field, mutated in the same style its
  existing fields already are); Fill/ExecutionReport/BrokerOrder/PartialFill/SlippageModel; partial
  exits/T1/T2/T3; exit-policy convergence (`simulate_tradeplan_exit()`/`evaluate_position_exit()`
  untouched); `PaperBroker`/`mark_to_market.py`/P&L reconciliation; `portfolio.py` convergence (still
  a separate architecture path, `order_intent`/`position_lifecycle` both legitimately `None` there,
  unchanged from 64.31's own finding — a future seam, not an oversight, if that engine is ever
  brought to parity); live trading. All remain named future seams, not oversights.

## CHECKPOINT 64.33 IMPLEMENTATION NOTES

**Objective:** close the one remaining, explicitly-named gap from 64.31/64.32 — `portfolio.py`'s
multi-instrument construction path produced `SimulatedTrade` records with `order_intent` and
`position_lifecycle` both legitimately `None` (it never supplied those keyword arguments to
`OpenPosition`). This checkpoint wires the SAME canonical `domain.order.contracts.OrderIntent` (via
the unmodified `order_intent_adapter.build_backtest_entry_order_intent()`) and the SAME canonical
`position_lifecycle.BacktestPosition`/`BacktestPositionLifecycleStatus` (via the unmodified
`open_backtest_position()`/`hold_backtest_position()`/`close_backtest_position()`) into
`run_portfolio_backtest()`, while explicitly preserving its multi-instrument semantics — multiple
concurrent positions, one `OrderIntent`/`BacktestPosition` pair per accepted entry per instrument,
never collapsed into the single-instrument model.

- **Portfolio baseline, established before any code was changed (by direct reading of
  `portfolio.py`):** `run_portfolio_backtest()` maintains `open_positions: dict[InstrumentId,
  OpenPosition]` — one slot per instrument, using the SAME `execution.OpenPosition` dataclass
  `engine.py` uses (never a portfolio-specific position type). A bar loop (`for i in range(n_bars)`)
  iterates every instrument assignment on every bar. Entry: `instrument_id not in open_positions`,
  a non-NEUTRAL signal, capital/`max_concurrent_positions` checks pass → `OpenPosition(...)` is
  constructed and inserted into the dict, `available_cash` reduced by notional. Exit: handled by a
  local `_close(...)` closure — signal reversal (`signal.direction != position.direction`) or
  end-of-data — which computes P&L/costs, appends a `SimulatedTrade`, records the
  `(entry_index, exit_index)` interval per instrument (used later for the portfolio mark-to-market
  curve), restores `available_cash`, and deletes the instrument's `open_positions` entry. Unlike
  `engine.py`'s single global `open_position`/`_close_trade()`, every operation here is keyed by
  `instrument_id`, and several instruments can be simultaneously open, closing, or re-entering on the
  very same bar index `i` — this is the material structural difference from `run_backtest()` that the
  64.33 directive itself called out, and it was preserved exactly.

- **OrderIntent integration:** at the same point `OpenPosition` is constructed for an accepted entry,
  `entry_order = build_backtest_entry_order_intent(strategy_id=assignment.strategy_id,
  instrument_id=instrument_id, direction=signal.direction, quantity=quantity,
  entry_timestamp=entry_bar.timestamp, entry_index=i + 1)` is called — the identical adapter function
  `engine.py` has used since 64.31, imported, never re-implemented. `OpenPosition(...,
  order_intent=entry_order, ...)` stores it; `_close(...)` carries `position.order_intent` verbatim
  onto the resulting `SimulatedTrade` — the exact same pattern as `engine.py`'s `_close_trade()`.

- **A genuine, objectively-proven defect was found and minimally fixed in
  `order_intent_adapter.build_backtest_entry_order_intent()`:** its `order_id` was constructed as
  `f"{strategy_id}-bt-entry-{entry_index}"` — qualified by `strategy_id` and `entry_index` only, NOT
  by `instrument_id`. `portfolio.py` explicitly supports "same strategy → multiple instruments"
  (its own header docstring, Part 9) with every instrument sharing the same bar-index namespace, so
  two different instruments assigned to the same strategy, both entering on the same relative bar,
  would previously have produced an IDENTICAL `order_id` for two genuinely different accepted orders
  — a direct violation of the deterministic per-instrument distinct-identity requirement this
  checkpoint exists to prove. `idempotency_key` already included `instrument_id`
  (`f"{strategy_id}:{instrument_id}:bt-entry:{entry_index}"}`); `order_id` did not. The fix widens
  `order_id` to `f"{strategy_id}-{instrument_id}-bt-entry-{entry_index}"` — additive to the format,
  not a semantic change for any existing single-instrument caller (still deterministic per entry,
  still unique within one run), and no existing test anywhere in the repository asserts an exact
  `order_id` string (confirmed by repo-wide search before making the change) — only type, inequality,
  and presence checks — so this widening breaks nothing pre-existing. This is the only change made to
  a file the checkpoint's own protected-files list names as "prefer untouched," made only because the
  multi-instrument case genuinely could not achieve the checkpoint's own required proof (test J/K)
  without it.

- **Position Lifecycle integration, per-instrument:** immediately before the entry/exit branch is
  evaluated for each instrument on each bar, a HELD guard mirrors `engine.py`'s 64.32 guard exactly,
  but scoped to that one instrument's own `open_positions[instrument_id]` entry: if a position is
  open for this instrument, its `position_lifecycle` is not `None`, the current bar index `i` is
  strictly past its own `entry_index`, and its status is still `OPEN`, it is advanced to `HELD` via
  `hold_backtest_position()`. This is O(1) per instrument per bar, evaluated independently for every
  instrument (never shared state across instruments), and makes no entry/exit decision of its own —
  the existing `should_exit`/`is_last_bar` logic remains entirely unchanged and solely authoritative.
  At entry, `OpenPosition(..., position_lifecycle=open_backtest_position(position_id=
  entry_order.order_id, direction=signal.direction, quantity=quantity, entry_price=filled_entry,
  entry_timestamp=entry_bar.timestamp))` — `position_id` reuses that SAME instrument's own
  `entry_order.order_id` (now instrument-qualified per the fix above), so every instrument's
  `BacktestPosition` carries a distinct `position_id`, never shared or collided across instruments.
  At close, `_close(...)` calls `close_backtest_position(position.position_lifecycle)` (same pattern
  as `engine.py`) and carries the terminal `CLOSED` snapshot onto the `SimulatedTrade`.

- **Multi-instrument semantics preserved, not collapsed:** each instrument's `OpenPosition` — and
  therefore its `order_intent` and `position_lifecycle` — is entirely independent of every other
  instrument's. No lifecycle object, `OrderIntent`, or `position_id` is ever shared across
  instruments; `open_positions` remains a `dict[InstrumentId, OpenPosition]` exactly as before, simply
  with each value now additionally carrying real canonical metadata. The portfolio's own
  `max_concurrent_positions` cap, per-instrument entry/exit independence, and capital-accounting
  invariants (Part 8, `available_cash` never negative, no double-position-per-instrument) are
  untouched — confirmed by the existing 8-test `test_portfolio_backtesting.py` suite passing
  unmodified.

- **`contracts.py`/`execution.py`/`position_lifecycle.py`/`order_intent_adapter.py`'s core builder
  logic/`mark_to_market.py`/`risk_gate_adapter.py`:** all confirmed untouched by this checkpoint
  except the one `order_id` line described above — no risk-gate wiring was added to `portfolio.py`
  (the portfolio configuration has no `risk_limits` field at all, confirmed by reading
  `PortfolioBacktestConfiguration`, so "existing risk/entry path where applicable" from the directive
  does not apply here — there is no existing portfolio risk gate to converge with).

- **Tests (20, `tests/unit/research/test_checkpoint_64_33_portfolio_convergence.py`), all passing:**
  A real canonical `OrderIntent` type at an accepted entry; B deterministic `order_id`/quantity/side
  across two identical re-runs; C every `OrderIntent` field honestly matches the trade's own recorded
  state; D the closed trade's `position_lifecycle` carries entry data consistent with an `OPEN` start
  (direct `OPEN`-state inspection is not exposed post-close, so this is proven via field continuity,
  matching 64.32's own honest framing); E at least one trade holds across ≥2 bars, proving the HELD
  guard's precondition is exercised; F every trade's terminal lifecycle status is `CLOSED`; G
  `position_lifecycle.position_id == order_intent.order_id` for every trade — the deterministic
  linkage the directive requires; H/I `order_intent`/`position_lifecycle` are retained on every
  `SimulatedTrade`; J every instrument's `OrderIntent.order_id` values are globally unique across the
  whole portfolio result; K every instrument's `position_lifecycle.position_id` values are likewise
  unique; L a source-text check proves `portfolio.py` defines no `BacktestPositionLifecycleStatus`,
  `BacktestPosition`, or `OrderIntent` class of its own — only imports the canonical ones; M
  `run_backtest()`'s own 64.31/64.32 behavior (real `OrderIntent`/`CLOSED` lifecycle on every trade)
  is independently re-exercised and still holds, proving this checkpoint did not regress the
  single-instrument path; N two portfolio re-runs produce byte-identical `entry_price`/`exit_price`/
  `quantity`/`gross_pnl`/`net_pnl`/`reason` for every trade; O `net_pnl == gross_pnl - costs` still
  holds; P exit reasons are still only `"signal_reversal"`/`"end_of_data"` — unchanged vocabulary; Q
  a deliberately tiny-capital configuration produces `rejected_entries > 0` and exactly zero trades —
  no OrderIntent/lifecycle/trade state is ever fabricated for a rejected entry; R a source-text check
  on `position_lifecycle.py` confirms its exactly-3-member `OPEN`/`HELD`/`CLOSED` vocabulary is
  unchanged. Two extra tests: an `is`-identity proof (via a monkeypatched spy on
  `build_backtest_entry_order_intent`) that the exact same `OrderIntent` object flows from
  construction through to the closed `SimulatedTrade`, never a copy; and an explicit statement,
  matching 64.32's own honest precedent, that whole-object `is` identity across OPEN→HELD→CLOSED is
  NOT claimed for the frozen `BacktestPosition` — only field continuity and `lifecycle_status`
  enum-singleton identity are.

- **Regression:** `tests/unit/research/` + `tests/unit/architecture/`: 226 (64.32 baseline,
  independently re-confirmed by re-running before making any change) + 20 (this checkpoint) = **246**,
  confirmed exactly. `tests/unit/research/test_portfolio_backtesting.py`'s pre-existing 8 tests
  (Part 7/8/9's own capital-accounting/max-concurrent/attribution suite) pass unmodified before and
  after. Full backend suite result reported in `taskReport.md` alongside the exact command output.

- **Performance:** a deterministic 20-instrument, 2,000-bar-per-instrument, ~6,150–6,200-trade
  workload (random-walk fixture, fixed seed per instrument), 3 runs each: pre-64.33 (using the
  unmodified `HEAD` copy of `portfolio.py`, restored via a plain file copy after benchmarking — never
  a git revert) averaged 0.665s; post-64.33 averaged 0.816s — a genuine, honestly-reported ~23%
  increase for this workload, NOT characterized as noise (unlike 64.32's single-instrument ~1%
  finding). The overhead is the real, expected cost of two additional dataclass constructions
  (`OrderIntent`, `BacktestPosition`) per accepted entry across many instruments/many bars — still
  O(1) per accepted position (not O(instruments × bars) beyond the portfolio's own existing
  per-bar-per-instrument iteration, which was already O(instruments × bars) before this checkpoint),
  but the per-bar HELD guard now also runs once per instrument per bar (previously zero per-bar
  lifecycle work existed in `portfolio.py` at all), which is the dominant new per-bar cost at this
  instrument count.

- **Protected files, explicitly confirmed status:** `domain/order/contracts.py`,
  `domain/risk/policy.py`, `domain/risk/contracts.py`, `risk_gate_adapter.py`,
  `position_lifecycle.py`, `mark_to_market.py`, `PaperBroker`, `TradePlan`, frontend, Dhan — all
  untouched. `order_intent_adapter.py` — modified, ONE line (`order_id` construction) plus its
  surrounding honesty-check comment, for the objectively-proven multi-instrument collision reason
  documented above; no other line changed, no field added/removed, no signature changed.

- **Not attempted, correctly, per this checkpoint's own scope:** Fill/ExecutionReport/BrokerOrder/
  PartialFill/SlippageModel (none introduced); partial exits/T1/T2/T3 (portfolio remains
  full-close-only, matching the single-instrument engine); exit-policy semantic changes (`should_exit`
  reversal/end-of-data logic byte-identical); P&L formula changes (`signed_gross_pnl`/cost-breakdown/
  `net_pnl` computation untouched); `mark_to_market.py`/`PaperBroker` changes; a portfolio-specific
  risk gate (none exists to converge with — `PortfolioBacktestConfiguration` has no `risk_limits`
  field); collapsing multi-instrument state into the single-instrument `run_backtest()` model (each
  instrument still gets its own independent `OpenPosition`/`OrderIntent`/`BacktestPosition`); live
  trading. All remain named, either correctly out of scope or a real future seam, not oversights.

## CHECKPOINT 64.34 IMPLEMENTATION NOTES

Closes the one remaining gap 64.33 explicitly named: `portfolio.py`'s multi-instrument entry
decision now consults the same canonical Risk Gate (`risk_gate_adapter.evaluate_backtest_entry_risk()`,
calling the real, unmodified `domain.risk.policy.evaluate_order_risk()`) that `run_backtest()` has
used since 64.30 — never a `PortfolioRiskGate`/`PortfolioRiskPolicy`/`PortfolioRiskDecision`/
`PortfolioRiskLimits` parallel vocabulary.

- **New OPT-IN field:** `PortfolioBacktestConfiguration.risk_limits: RiskLimits | None = None`,
  mirroring `BacktestConfiguration.risk_limits` exactly. `None` (the default, and every pre-64.34
  caller's configuration) skips the entire risk-gate block — numerically byte-identical to 64.33.

- **Ordering, deliberately preserved:** the risk gate is evaluated AFTER `portfolio.py`'s two
  pre-existing portfolio-level constraints (the `max_concurrent_positions` cap and the capital/
  notional check), which remain entirely unchanged in both logic and position in the control flow —
  these are portfolio execution constraints, not canonical risk-policy dimensions, and are never
  folded into the Risk Gate. The canonical `OrderIntent` is constructed once (as in 64.33), then fed
  to the risk gate; `available_cash` is deducted only AFTER the gate approves, so a risk rejection
  never needs to "undo" a capital commitment — the SAME `entry_order` object is both the risk-gate
  input and (on approval) the object retained on `OpenPosition`/`SimulatedTrade`, never a second
  construction.

- **Multi-instrument-honest risk inputs — the material design point:** unlike `engine.py`'s
  single-position engine (which could only ever hardcode `current_open_positions_count=0` and
  `current_total_exposure=Decimal("0")`, since its risk-gate branch runs only when no position is
  open at all), `portfolio.py` genuinely tracks multiple simultaneously open positions, so this
  checkpoint supplies REAL, honestly-computed values: `current_open_positions_count=len(open_positions)`
  (every OTHER currently-open instrument, since this instrument's own entry is not yet open) and
  `current_total_exposure=sum(p.entry_price * p.quantity for p in open_positions.values())` (the real
  notional of every other open position). `cumulative_closed_trade_net_pnl` is a new running
  `cumulative_realized_net_pnl` accumulator, updated in `_close()` alongside `available_cash` — the
  portfolio-level equivalent of `engine.py`'s `running_equity - initial_capital`. `max_total_exposure`
  uses the same honest `Decimal("Infinity")` "no configured cap" sentinel `engine.py` already uses
  (no portfolio-level total-exposure limit is tracked by either engine today).

- **`max_concurrent_positions` interaction, explicitly reasoned about:** the canonical risk policy
  (`evaluate_order_risk()`) ALSO has its own `MAX_CONCURRENT_POSITIONS_EXCEEDED` check
  (`current_open_positions_count >= max_concurrent_positions`). Because `portfolio.py`'s own
  pre-existing cap check runs FIRST and unconditionally rejects once `len(open_positions) >=
  config.max_concurrent_positions`, the risk gate's own equivalent check is structurally unreachable
  in this wiring — by the time the gate is consulted, `current_open_positions_count` is always
  strictly less than `max_concurrent_positions`. This is intentional, not an oversight: it means
  `max_concurrent_positions` behavior is provably unchanged from 64.33 (Test M), and the two
  "sources of max_concurrent_positions enforcement" agree with each other rather than conflict.

- **Rejection counting kept separate:** a NEW `PortfolioBacktestResult.risk_rejected_entries`/
  `risk_rejection_reason_breakdown` pair (mirroring `BacktestResult.risk_rejected_trades`/
  `risk_rejection_reason_breakdown` from 64.30) counts ONLY canonical-risk-gate rejections. The
  pre-existing `rejected_entries` counter (cap/capital causes) is completely unchanged in meaning and
  numeric value when `risk_limits=None`.

- **Rejection semantics:** a risk-rejected candidate produces no `OpenPosition`, no lifecycle OPEN
  state (`open_backtest_position()` is never called), no `SimulatedTrade`, and no capital deduction —
  proven by Tests E/F/G (`test_efg_risk_rejected_entry_produces_no_accepted_state`).

- **Multi-instrument independence:** each instrument's entry decision is a fully independent call to
  `evaluate_backtest_entry_risk()` with its own freshly-constructed `BacktestRiskGateInputs` — no
  mutable risk-decision object is shared across instruments. Proven by Tests I/J
  (`test_ij_rejection_of_one_instrument_does_not_corrupt_another`,
  `test_j_independent_instruments_can_have_different_outcomes`).

- **Files modified this checkpoint:** `src/intraday/research/backtesting/portfolio.py` (+138/-5,
  additive — no existing line's logic was changed, only new fields/blocks inserted; the
  `entry_order`/`OpenPosition` construction lines were reordered relative to the `available_cash -=
  notional` line so cash is committed only after risk approval, which is the one place existing code
  was reflowed rather than purely appended to).
  `tests/unit/research/test_checkpoint_64_34_portfolio_risk_gate.py` — new, 18 tests.
  `risk_gate_adapter.py`, `order_intent_adapter.py`, `position_lifecycle.py`,
  `domain/risk/contracts.py`, `domain/risk/policy.py`, `domain/order/contracts.py` — all confirmed
  UNMODIFIED (`git diff --stat` returns no output for every one of them).

- **Performance:** benchmarked on a 20-instrument, 2,000-bar-per-instrument workload (deterministic
  oscillating fixture, 7,980 trades). `risk_limits=None` (disabled path): ~0.81-0.83s — consistent
  with 64.33's own reported ~0.816s post-64.33 baseline, confirming no regression on the disabled
  path (the entire risk-gate block is skipped, as designed). `risk_limits=<permissive>` (gate
  genuinely evaluated for every accepted candidate): ~0.96s — an honest, disclosed additional ~18-19%
  over the already-64.33-elevated baseline, the real cost of one additional `RiskEvaluationContext`
  construction + `evaluate_order_risk()` call + a `sum()` over open positions per accepted-candidate
  evaluation, opt-in only.

- **Compatibility:** `risk_limits=None` remains the default and preserves 64.33's exact numerical
  behavior (Test N), proven both by the dedicated regression tests and by the unchanged
  `test_portfolio_backtesting.py`/`test_checkpoint_64_33_portfolio_convergence.py` suites (28/28,
  46/46 unaffected).

- **Not attempted, correctly, per this checkpoint's own scope:** Fill/ExecutionReport/BrokerOrder/
  PartialFill/SlippageModel; partial exits; exit-policy changes; P&L formula changes;
  `mark_to_market.py`/`PaperBroker` changes; a portfolio-specific risk vocabulary; live trading;
  reordering or reweighing the pre-existing portfolio-level constraints relative to each other.

## CHECKPOINT 64.35 IMPLEMENTATION NOTES

**Objective:** determine whether the canonical Risk Gate/RiskDecision/OrderIntent used by
Backtest (`engine.py`, `portfolio.py`, wired 64.30-64.34) can be safely converged with Paper
Trading (`PaperTradingService`, `PaperBroker`) — without touching Fill/Execution modeling,
without redesigning `PaperBroker`, without changing P&L formulas.

**Finding: convergence already existed, in full, before this checkpoint.** This was a
discovery-first checkpoint and the discovery is the deliverable — no source under `src/` was
modified. Prior checkpoints (34, 64.24, 64.29-64.34) had already produced exactly the
"Strategy Signal → Canonical OrderIntent → Canonical Risk Gate → RiskDecision → (Backtest /
Paper Trading)" shape the checkpoint brief described as desired, arrived at from two directions
independently converging on the same objects, not by this checkpoint forcing them together:

- **Paper Trading's risk architecture** (`src/intraday/application/services/paper_trading.py`,
  `PaperTradingService.submit_order()`, lines 86-157): builds a real
  `intraday.domain.risk.policy.RiskEvaluationContext` (imported directly, line 41-44) from live
  `PaperBroker` state (`get_positions()`/`get_orders()`), then calls the real, unmodified
  `evaluate_order_risk(order, context)` (line 151) — never a Paper-Trading-specific
  reimplementation. The order it evaluates is a real
  `intraday.domain.order.contracts.OrderIntent` (imported line 31), constructed by the caller
  (`application/services/paper_signal_execution.py`, `PaperSignalExecutionService.
  evaluate_and_submit()`, lines 346-357) directly from the canonical `OrderIntent` dataclass —
  no `PaperOrderIntent` type exists. The risk decision returned is a real
  `intraday.domain.risk.contracts.OrderRiskDecision` (imported via `domain.risk.contracts`,
  `risk_gate_adapter.py`/`policy.py` both import it under that exact name), carried unmodified
  in `PaperOrderSubmissionResult.risk_decision` (lines 50-61) all the way to the caller — never
  discarded, transformed, or recreated as a second type.
- **Backtest's risk architecture** (`src/intraday/research/backtesting/risk_gate_adapter.py`,
  wired into `engine.py` since 64.30 and `portfolio.py` since 64.34): `evaluate_backtest_entry_risk()`
  (lines 139-147) builds the SAME `RiskEvaluationContext` dataclass and calls the SAME
  `evaluate_order_risk()` function — confirmed by `risk_gate_adapter.py`'s own header docstring
  (line 96: "the exact same dataclass `PaperTradingService`'s own order-submission method
  builds"), a discipline this checkpoint mechanically verifies rather than merely trusts (see
  Tests A/B below). `order_intent_adapter.build_backtest_entry_order_intent()` constructs the
  SAME canonical `OrderIntent` type — no `BacktestOrderIntent` exists.
- **`trading_engine/risk_engine/evaluator.py` is a re-export shim, not a second implementation**
  (Checkpoint 64.24): it imports `RiskEvaluationContext`/`evaluate_order_risk` FROM
  `intraday.domain.risk.policy` and re-exports them under the same names, for backward
  compatibility only. There is exactly one function body for `evaluate_order_risk()` in the
  entire repository (`domain/risk/policy.py`, lines 121-279).

**Mechanical proof, not just narrative:** `tests/unit/research/test_checkpoint_64_35_risk_decision_convergence.py`
asserts `risk_gate_adapter.evaluate_order_risk is domain_risk_policy.evaluate_order_risk` and
`paper_trading_module.evaluate_order_risk is domain_risk_policy.evaluate_order_risk` (identical
function objects, `is`, not merely equal-behaving copies) and `type(backtest_decision) is
type(paper_result.risk_decision) is OrderRiskDecision`.

**Risk Gate ownership — Model B, confirmed, not chosen by preference:** Strategy → canonical
`OrderIntent` → canonical Risk Gate (`evaluate_order_risk`) → `PaperTradingService` →
`PaperBroker`. `PaperTradingService.submit_order()` is the ONE non-bypassable chokepoint
(mechanically proven since Checkpoint 34 Part 19,
`test_risk_evaluation_runs_before_broker_submission_in_service_source`); `PaperBroker` itself
never imports `domain.risk` at all (verified this checkpoint, `test_k_paper_broker_module_never_imports_the_risk_policy`)
and has no `RiskDecision`/`RiskLimits`/`evaluate_order_risk` symbol anywhere in its source
(`test_l_paper_broker_has_no_risk_decision_or_risk_limits_symbol`). For Backtest, ownership is
`engine.py`'s/`portfolio.py`'s own entry branch, calling the adapter — the same function, a
different but equally unambiguous single call site per engine.

**Duplicate risk evaluation: absent, confirmed by structural test, not merely by reading.**
`PaperTradingService.submit_order()` calls `evaluate_order_risk(` exactly once
(`test_k_paper_trading_service_calls_evaluate_order_risk_exactly_once`, counting `"= evaluate_order_risk("`
occurrences in the actual method source via `inspect.getsource`). `PaperBroker._attempt_fill()`'s
own balance-sufficiency check (`broker.py` lines 386-393, "if required > self._available_balance:
REJECTED") is a LEGITIMATE, DISTINCT broker/execution-safety concern (can this specific fill be
funded right now, given slippage/cost) — not a second risk-POLICY evaluation, has no `RiskLimits`
concept, and is structurally proven to never import or reference the risk-policy module at all.
This is the mandatory-stop condition #11 ("PaperBroker has legitimate broker/execution safety
checks that must remain independent of strategy risk policy") — confirmed present, correctly left
untouched, not a defect.

**OrderIntent convergence: already complete.** Both paths consume `domain.order.contracts.OrderIntent`
directly; no adapter is needed on the Paper Trading side because Paper Trading was built against
the canonical type from Checkpoint 34 onward — Backtest was the side that needed
`order_intent_adapter.py` (64.29) to converge TOWARD it, not vice versa.

**No duplicate risk/order vocabulary exists anywhere in the repository** — confirmed by a
repo-wide grep for `PaperOrderIntent`/`PaperRiskDecision`/`BacktestRiskDecision`/
`LiveRiskDecision`/`PortfolioRiskDecision` (zero matches,
`test_no_duplicate_risk_or_order_intent_vocabulary_exists_in_the_repository`).

**Convergence decision:** REUSE, not build. Per the checkpoint's own instruction ("If YES: reuse
it"), `domain.risk.contracts.OrderRiskDecision` and `domain.order.contracts.OrderIntent` are
already the correct canonical objects for both Backtest and Paper Trading; no `PaperRiskDecision`,
no adapter layer, no new abstraction was created. This is not a "nothing happened" checkpoint —
it is a checkpoint whose entire deliverable is the mechanical proof (17 new tests) that a
convergence risk earlier checkpoints could plausibly have left incomplete was, in fact, already
sound, closing the explicitly-named 64.34 gap ("Backtest and Paper Trading RiskDecision
convergence") by verification rather than by new code.

**Remaining execution boundary (explicitly out of scope, unchanged):** Backtest fills at
"next bar's open" inside `engine.py`'s own loop; `PaperBroker` fills via its own
MARKET/LIMIT/STOP simulation with configurable slippage/partial-fill/cost (`broker.py`'s own
documented execution model, lines 89-136). These remain two independently-modeled, disclosed,
UNRECONCILED execution engines — this checkpoint's own scope (Rule 17, "No Execution
Convergence") explicitly forbids touching this, and nothing here changes it. `SimulatedTrade.
net_pnl` (cost-inclusive) and `PaperBroker.Position.realized_pnl` (cost-exclusive) remain the
same disclosed, UNRESOLVED accounting-convention conflict `risk_gate_adapter.py`'s own header
docstring (lines 42-48) already named in 64.29 — P&L reconciliation is not, and was never
claimed to be, in this checkpoint's scope.

**Files modified by this checkpoint:** none under `src/`.
`tests/unit/research/test_checkpoint_64_35_risk_decision_convergence.py` (new, 17 tests, all
passing). This file (architecture doc, append only). `taskReport.md` (overwritten per mandatory
checkpoint structure).

**Protected files status:** `domain/risk/policy.py`, `domain/risk/contracts.py`,
`domain/order/contracts.py`, `risk_gate_adapter.py`, `position_lifecycle.py`,
`mark_to_market.py`, `PaperBroker` (`infrastructure/brokers/paper/broker.py`), Dhan integration,
frontend — all confirmed UNTOUCHED (`git diff --stat` shows no hunks for any of them from this
checkpoint's work; the only pre-existing uncommitted diffs, `portfolio.py` and this doc's prior
sections, are 64.34's own carried-forward, unmodified-by-64.35 changes).

---

## CHECKPOINT 64.36 ACCOUNTING CONVENTION NOTES

**Objective:** discovery-first reconciliation of P&L accounting convention between Backtest
(`research.backtesting`) and Paper Trading (`application.services.paper_trading` /
`infrastructure.brokers.paper.broker.PaperBroker`). Not an execution-convergence checkpoint -
Fill/ExecutionReport/BrokerOrder/PartialFill/SlippageModel unification remains explicitly
deferred, per this checkpoint's own Rule 9.

**Backtest accounting (source-verified, `engine.py::_close_trade`,
`contracts.py::SimulatedTrade`):**
- `gross_pnl = signed_gross_pnl(direction, entry_price, filled_exit_price, quantity)` -
  `(exit - entry) x quantity` for a long, sign-flipped for a short. `filled_exit_price` already
  includes slippage (`cost_model.py::slippage_adjusted_price`, applied to price BEFORE
  `gross_pnl` is computed) - slippage is a price-level effect, never a separate cost line item
  (`CostBreakdown.total`'s own docstring: "deliberately EXCLUDES slippage ... to avoid
  double-counting").
- `costs = cost_breakdown(entry_leg).combine(cost_breakdown(exit_leg)).total` - the REAL,
  itemized round-trip statutory/broker cost (brokerage, STT, exchange charges, SEBI charges,
  GST, stamp duty), computed via the injected `CostModel` (either the MODEL-ASSUMPTION
  `FlatPercentageCostModel` or the VERIFIED `IndianCashEquityIntradayCostModel`).
- `net_pnl = gross_pnl - costs` - COST-INCLUSIVE.
- `running_equity += trade.net_pnl` (per-trade, across the whole backtest) - the Backtest
  engine's own running-equity ledger is therefore also cost-inclusive.
- Risk-gate input: `BacktestRiskGateInputs.cumulative_closed_trade_net_pnl = running_equity -
  initial_capital` (`engine.py`, entry branch) - COST-INCLUSIVE, because it is built entirely
  from `net_pnl` values. `risk_gate_adapter.py`'s own header docstring (lines 30-48) already
  discloses this explicitly, since 64.29.
- Unrealized P&L (`mark_to_market.py`, untouched, unread by this checkpoint beyond its own
  docstring): mark-to-market values an open position at the bar's own close price, EXCLUDING
  exit costs (only realized on actual close) - a documented simplification.

**Paper Trading accounting (source-verified, `broker.py::_attempt_fill`/`_apply_to_position`,
`paper_trading.py::submit_order`):**
- `slipped_price = price x (1 +/- slippage_percent/100)` - same structural convention as
  Backtest: slippage is folded into the fill price BEFORE any P&L figure is computed. This one
  dimension is ALREADY convergent between the two engines (mechanically proven,
  `test_e`/`test_f`, Checkpoint 64.36 test module).
- `cost = compute_cost(is_buy, notional)` - the SAME real, verified
  `IndianCashEquityIntradayCostModel` is available to be injected
  (`paper_trading_runtime.py::_compute_cost` already does this for the production singleton
  broker) - but this cost is subtracted ONLY from `_available_balance`
  (`self._available_balance -= notional + cost` on a buy fill; `+= notional - cost` on a sell
  fill) inside `_attempt_fill`. It NEVER reaches `Position.realized_pnl`.
- `Position.realized_pnl` (`_apply_to_position`, opposite-side/closing fill):
  `realized = direction_sign x (fill_price - average_entry_price) x closing_quantity` -
  GROSS P&L on the slippage-adjusted fill price, COST-EXCLUSIVE. `new_realized =
  existing.realized_pnl + realized` - cumulative, still cost-exclusive at every step.
  `Trade.realized_pnl` (the per-round-trip record appended to `self._trades`) carries the exact
  same `realized` value - also cost-exclusive.
- Risk-gate input: `paper_trading.py::submit_order`, `daily_realized_pnl = sum(p.realized_pnl
  for p in positions)` - COST-EXCLUSIVE, because it sums a field that was never cost-adjusted.
- `Position`/`Trade` are the CANONICAL `domain.position.contracts.Position` /
  `domain.trade.contracts.Trade` types (imported directly by `broker.py`, not a
  `PaperPosition`/`PaperTrade` duplicate) - but those canonical contracts' own docstrings
  EXPLICITLY decline to define P&L semantics ("no P&L calculation is implemented here" -
  `domain/position/contracts.py` line 8; "no trade-calculation logic is implemented here" -
  `domain/trade/contracts.py` line 11). The cost-exclusive convention is PaperBroker's own
  populating choice, not something the canonical contract mandates or forbids.

**Exact accounting mismatch - worked numeric example (all figures computed by running the
REAL `cost_model.py`/`broker.py` code this checkpoint, not hand-estimated; see
`tests/unit/research/test_checkpoint_64_36_pnl_accounting_convergence.py`, `test_a` through
`test_j`):**

One long round trip, entry 1000, exit 990 (a loss), quantity 100 shares, zero slippage on
both engines (isolates the cost-treatment difference), the REAL verified NSE cash-equity
intraday cost schedule (`verified_nse_cash_equity_intraday_cost_model()`):

- Gross P&L (both engines compute the identical figure): `(990 - 1000) x 100 = -1000`.
- Real round-trip cost (`CostBreakdown.total`, actually computed): `82.39`
  (brokerage 40.00 + exchange charges 6.11 + SEBI charges 0.20 + GST 8.33 + STT 24.75 +
  stamp duty 3.00).
- **Backtest** `net_pnl = -1000 - 82.39 = -1082.39`. `cumulative_closed_trade_net_pnl` after
  this one trade: `-1082.39`.
- **Paper Trading** `Position.realized_pnl = -1000` exactly (the `82.39` cost WAS charged -
  proven by `_available_balance` dropping by `1000 + 82.39 = 1082.39` - but never subtracted
  from `realized_pnl`). `daily_realized_pnl` (sum over positions) after this one trade: `-1000`.
- **The mismatch is exactly the round-trip cost: `-1000 - (-1082.39) = 82.39`.** Not an
  estimate - the exact real-cost figure, every time, for any trade, because Paper Trading's
  `realized_pnl` is definitionally `gross_pnl` and Backtest's `net_pnl` is definitionally
  `gross_pnl - costs`.

**Risk Gate divergence - mechanically proven (`test_i`,
`test_i_identical_daily_loss_produces_divergent_risk_decisions`):** with
`RiskLimits.max_intraday_loss = 1050` (strictly between `1000` and `1082.39`), and the ONE
closed trade above already reflected in each engine's own accounting state, a subsequent,
otherwise-identical order is evaluated by the SAME function object,
`domain.risk.policy.evaluate_order_risk()`:
- Backtest side (`evaluate_backtest_entry_risk`, `cumulative_closed_trade_net_pnl = -1082.39`):
  `-1082.39 <= -1050` is `True` -> **REJECTED** (`MAX_DAILY_LOSS_EXCEEDED`).
- Paper Trading side (`PaperTradingService.submit_order`, real `PaperBroker` state,
  `daily_realized_pnl = -1000`): `-1000 <= -1050` is `False` -> **APPROVED**.

This is not a hypothetical: both branches run real production code end-to-end (a real
`PaperBroker` fills a real BUY then real SELL through `submit_order()`/`_attempt_fill()`/
`_apply_to_position()`; a real `evaluate_backtest_entry_risk()` call). The SAME economic
trade, the SAME `RiskLimits`, the SAME cost schedule - two different Risk Gate outcomes,
caused entirely by the accounting-convention mismatch, not by any legitimate difference in
risk policy or execution modeling.

**Canonical accounting decision:** NO pre-existing canonical accounting convention governs
cost-inclusion for `Position.realized_pnl`/`Trade.realized_pnl`. `domain.position.contracts`
and `domain.trade.contracts` supply the shared STRUCTURE (both engines already use, or could
use, the same `Position`/`Trade` shape for canonical objects) but explicitly do not define
P&L semantics - that was deliberately left to "a later checkpoint" by their own Checkpoint 5
docstrings, and no later checkpoint before this one made that decision either. Per this
checkpoint's own Rule 6/8/10 ("if no canonical convention exists: STOP BEFORE IMPLEMENTING";
"do NOT change formulas without proof the smallest safe implementation is objectively
proven"): **implementation is deferred, not performed.** Migrating `PaperBroker.
_apply_to_position()` to subtract cost from `realized_pnl` (the seemingly obvious fix) is a
real, non-trivial behavior change to a PROTECTED file (Rule 15) that would alter every
existing Paper Trading balance/P&L reading historically produced by this engine, and would
require deciding how partial exits, blended-price re-entries, and multi-leg positions should
each attribute cost - none of which this checkpoint's scope permits deciding unilaterally.
Migrating Backtest's `net_pnl` to become cost-exclusive would silently change every existing
backtest's historical P&L, forbidden by Rule 8 ("Backtest behavior can be preserved ... without
silently changing historical strategy results").

**Minimum domain-level contract a future checkpoint would need (documented, not built):** a
canonical, explicit accounting decision (not necessarily a new dataclass - could be a
documented convention on the existing `Trade`/`Position` contracts) stating unambiguously:
(1) `realized_pnl`/`net_pnl` semantics are cost-inclusive by convention across the WHOLE
platform; (2) a separate, always-available `gross_pnl` field/computation exists wherever a
cost-exclusive figure is also needed (e.g. execution-quality analysis); (3) `PaperBroker`
gains an explicit second field (or a computed property) so the migration is ADDITIVE, not a
silent redefinition of `realized_pnl`'s existing meaning - avoiding a breaking change to
every existing Paper Trading consumer of `Position.realized_pnl`. This checkpoint deliberately
does not build that field, in keeping with its own "STOP, document, do not force a migration"
directive.

**Risk Gate implications (documented, unresolved):** because
`RiskEvaluationContext.current_daily_realized_pnl` is fed a cost-inclusive figure from one
engine and a cost-exclusive figure from the other, `MAX_DAILY_LOSS_EXCEEDED` enforcement is
NOT numerically comparable across engines for the same underlying economics - proven above,
not merely asserted. This means a strategy validated in Backtest as "safely inside its daily
loss limit" could, on the same day's real economics, be evaluated as MORE room remaining in
Paper Trading (because Paper Trading's own daily figure understates the true cost-adjusted
loss) - a materially relevant gap for a future Live-Paper readiness review, though today
Paper Trading only ever sees its OWN accounting (this divergence matters when comparing
Backtest RESULTS against Paper Trading RESULTS for the same strategy, not within a single,
self-consistent live paper-trading session).

**Migration requirement if any:** none performed this checkpoint. A future checkpoint could
safely migrate ONLY if it (a) adds cost-inclusive net P&L as an ADDITIVE field to
`Position`/`Trade` (or a wrapping value object) rather than redefining `realized_pnl`'s
existing meaning, (b) updates `paper_trading.py::submit_order`'s
`current_daily_realized_pnl` to consume the new cost-inclusive field explicitly, with its own
dedicated test proving the Risk Gate now agrees with Backtest for the worked example above,
and (c) leaves `PaperBroker`'s existing `realized_pnl` numerically unchanged for any consumer
that already depends on the gross figure (e.g. UI P&L displays, if any exist) unless those are
also explicitly migrated in the same checkpoint.

**Remaining execution boundary:** unchanged from 64.35 - Backtest's "next bar open" fill model
and `PaperBroker`'s own slippage/partial-fill/cost fill model remain two independently-modeled,
UNRECONCILED execution engines. Not touched this checkpoint (Rule 9).

**Files modified by this checkpoint:** none under `src/`.
`tests/unit/research/test_checkpoint_64_36_pnl_accounting_convergence.py` (new, 14 tests, all
passing, all exercising real production code). This file (architecture doc, append only).
`taskReport.md` (overwritten per mandatory checkpoint structure).

**Protected files status:** `domain/risk/policy.py`, `domain/risk/contracts.py`,
`domain/order/contracts.py`, `risk_gate_adapter.py`, `position_lifecycle.py`,
`mark_to_market.py`, `PaperBroker` (`infrastructure/brokers/paper/broker.py`), Dhan
integration, frontend - all confirmed UNTOUCHED this checkpoint (`git diff --stat` shows no
hunks for any of them beyond the pre-existing, carried-forward `portfolio.py` diff, which is
64.34's own and remains byte-identical to its state at the start of this checkpoint).

## CHECKPOINT 64.37 — ADDITIVE NET P&L RISK CONTRACT

64.36 is accepted in full: it mechanically proved that Backtest's `SimulatedTrade.net_pnl`
(cost-inclusive) and Paper Trading's `Position.realized_pnl`/`Trade.realized_pnl`
(cost-exclusive) feed `RiskEvaluationContext.current_daily_realized_pnl` with two different
financial meanings, and that this could flip `evaluate_order_risk()`'s decision for
economically identical trades. This checkpoint implements the SMALLEST SAFE ADDITIVE fix.

### Old `realized_pnl` meaning (UNCHANGED)

`Position.realized_pnl` / `Trade.realized_pnl` remain exactly what they were: the GROSS,
cost-EXCLUSIVE price-movement P&L of a closed trade/round-trip
(`direction_sign * (fill_price - average_entry_price) * closing_quantity`,
`infrastructure/brokers/paper/broker.py::_apply_to_position`). `SimulatedTrade.net_pnl`
(`research/backtesting/contracts.py`/`engine.py`) remains exactly `gross_pnl - trade_costs`,
formula untouched. Neither field's formula, name, or existing callers changed.

### New `realized_net_pnl` contract

One new pure function: `domain/trade/net_pnl.py::compute_realized_net_pnl(gross_price_pnl,
transaction_cost) -> Decimal`, returning `gross_price_pnl - transaction_cost`. Deliberately a
single free function, not a class/service/engine — mirrors this project's existing small
domain-utility modules (`domain/order/idempotency.py`, `domain/order/state_machine.py`), per
the checkpoint directive's explicit instruction not to invent
AccountingEngine/AccountingLedger/NetPnlService/PnlManager vocabulary.

Two new, purely ADDITIVE dataclass fields, both `Decimal | None = None` (default `None` for
full backward compatibility — every pre-64.37 construction site is unaffected):
- `domain/position/contracts.py::Position.realized_net_pnl`
- `domain/trade/contracts.py::Trade.realized_net_pnl`

Chosen location: additive fields on the existing canonical `Position`/`Trade` contracts
(Rule 6's own suggested option), rather than a separate accounting projection/ledger type,
because both Backtest's `SimulatedTrade` and Paper's `Position`/`Trade` already carry P&L
fields at exactly this granularity — no new type, no new vocabulary, no new architecture layer
was needed; the smallest change that fits the existing shape.

### Backtest producer

No code changed in `engine.py`/`contracts.py`. `SimulatedTrade.net_pnl` is ALREADY, by
construction, equal to `compute_realized_net_pnl(gross_pnl, trade_costs)` — an equivalence,
not a new computation (`tests/unit/research/test_checkpoint_64_37_net_pnl_risk_contract.py::
test_b`). `research/backtesting/risk_gate_adapter.py` gained a documentation-only addendum
comment (no code line changed — verified: every added line in `git diff` is a `#` comment or
blank) explaining this equivalence; `evaluate_backtest_entry_risk`'s existing
`current_daily_realized_pnl=inputs.cumulative_closed_trade_net_pnl` mapping needed no change.

### Paper Trading producer

`infrastructure/brokers/paper/broker.py::PaperBroker` gained:
- A private `_position_entry_cost: dict[InstrumentId, Decimal]` bookkeeping dict (never exposed
  outside the class) that accumulates the entry-side transaction cost (the SAME `compute_cost`
  callable already charged, exactly once, to `_available_balance` in `_attempt_fill`) still
  attributable to a position's currently open quantity.
- `_attempt_fill` now passes its already-computed `cost` into `_apply_to_position` (no second
  cost computation — costs counted exactly once).
- On a closing fill, `_apply_to_position` computes `attributable_entry_cost` (the accumulated
  entry cost, prorated by `closing_quantity / existing.quantity`) and `attributable_exit_cost`
  (this fill's own cost, prorated by `closing_quantity / fill_quantity`), sums them into
  `trade_transaction_cost`, and calls `compute_realized_net_pnl(realized, trade_transaction_cost)`
  to populate the new `Trade.realized_net_pnl` and the new, cumulative
  `Position.realized_net_pnl`. `Position.realized_pnl`/`Trade.realized_pnl` formulas are
  completely untouched.

`application/services/paper_trading.py::PaperTradingService.submit_order` (the ONE behavior
change this checkpoint makes to a control-flow-bearing file) now sums
`p.realized_net_pnl or Decimal("0")` across positions instead of `p.realized_pnl`, to populate
`RiskEvaluationContext.current_daily_realized_pnl` — the same field, now fed the same semantic
quantity Backtest already provided.

### Risk Gate consumer

`domain/risk/policy.py::evaluate_order_risk()` — UNCHANGED. It consumes
`RiskEvaluationContext.current_daily_realized_pnl` exactly as before; only the VALUE fed into
that existing field by Paper Trading's producer changed, per Rule 7's explicit preference for
adapting producers over changing the consumed contract/type.

### Backward compatibility

`Position.realized_pnl`, `Trade.realized_pnl`, `SimulatedTrade.net_pnl` are all numerically
identical to pre-64.37 behavior — proven by
`test_checkpoint_64_37_net_pnl_risk_contract.py::test_d`/`test_d2`/`test_e`, and by the full
64.29-64.36 test-suite re-run (see `taskReport.md`, Regression Comparison). `Position`/`Trade`
gained one new field each, defaulted to `None`, so every existing construction site
(`historical_execution.py`, `paper_ledger_repository.py`, prior test fixtures) compiles and
behaves identically without modification.

### Central worked example (re-verified this checkpoint)

Entry 1000, exit 990, qty 100, zero slippage, real NSE cost model: gross P&L = -1000, real
round-trip cost = 82.39, `realized_net_pnl` = -1082.39 on BOTH engines
(`test_f_same_economic_trade_same_realized_net_pnl_both_engines`), while Paper
`Position.realized_pnl` remains exactly -1000 (`test_d`).

### Risk decision: before vs. after 64.37

Before (64.36's own proof, `max_intraday_loss=1050`): Backtest `evaluate_backtest_entry_risk`
→ REJECTED (`cumulative_closed_trade_net_pnl=-1082.39`); Paper
`PaperTradingService.submit_order` → APPROVED (`daily_realized_pnl=-1000`, cost-exclusive).
After 64.37 (re-run through the SAME real entry points): both REJECTED
(`test_checkpoint_64_37_net_pnl_risk_contract.py::test_g`), and the ORIGINAL 64.36
characterization test (`test_checkpoint_64_36_pnl_accounting_convergence.py::test_i`, updated
in place, not deleted, to assert the now-correct convergent outcome) confirms the same
convergence through its own independent fixture.

### Remaining accounting gaps (unchanged, explicitly out of scope this checkpoint)

`Position.unrealized_pnl` for Paper Trading remains `Decimal("0")` always (64.36's own noted
gap; `mark_to_market.py` untouched, per Rule 14). Fill/Execution model convergence remains
unreconciled (Rule 15/9). Partial exits remain deferred. Calendar-day scoping of
`current_daily_realized_pnl`/`realized_net_pnl` remains "since session/run start," not
midnight-scoped (Rule 13, unchanged from 64.36).

### Execution boundary

Unchanged from 64.35/64.36 — Backtest's "next bar open" fill model and `PaperBroker`'s own
slippage/partial-fill/cost fill model remain two independently-modeled, UNRECONCILED execution
engines. Not touched this checkpoint.

## CHECKPOINT 64.38 — PAPER MARK-TO-MARKET / UNREALIZED P&L

64.37 closed the REALIZED P&L divergence between Backtest and Paper. It explicitly left one
named gap untouched (previous section, "Remaining accounting gaps"): `Position.unrealized_pnl`
for Paper Trading was `Decimal("0")` at every construction/update site — an OPEN position's
financial state was never actually observable. This checkpoint closes that gap with a small,
additive, pure domain module plus its wiring into the existing Paper execution path.

### New module

`domain/position/mark_to_market.py` (pure, zero dependencies beyond
`domain/position/contracts.py` and `domain/shared_kernel/contracts.py`):
- `compute_unrealized_pnl(*, direction, average_entry_price, remaining_quantity, mark_price)` —
  `direction_sign * remaining_quantity * (mark_price - average_entry_price)`, `direction_sign`
  = +1 BUY / -1 SELL, identical to `research/backtesting/mark_to_market.py`'s own already-proven
  sign convention (reused, not reinvented). Raises `ValueError` on non-positive `mark_price` or
  negative `remaining_quantity`.
- `compute_market_value(*, direction, remaining_quantity, mark_price)` —
  `direction_sign * remaining_quantity * mark_price`. A short position's market value is carried
  NEGATIVE (a liability), matching the backtest module's convention.
- `mark_position(position, mark_price) -> Position` — returns a NEW `Position` (the contract is
  `frozen=True`) with `unrealized_pnl` recomputed. A CLOSED position is returned UNCHANGED
  (early return, no-op) — a closed position's remaining exposure is zero by construction.
- `position_market_value(position) -> Decimal` — derives market value from the position's own
  already-marked `unrealized_pnl`: `direction_sign * quantity * average_entry_price +
  unrealized_pnl`. For a never-marked position (`unrealized_pnl == 0`), this correctly reduces
  to book value, never a fabricated "no mark = zero value" answer.

`remaining_quantity` is always `Position.quantity`, which already means "current open quantity,
already reduced by any prior partial exit" in this codebase's existing convention
(`PaperBroker._apply_to_position`) — so a partially-closed position's unrealized P&L is
automatically correct with no separate "original quantity" bookkeeping.

### Mark price source (real, not invented)

The ONLY price source is `PaperBroker.record_price(instrument_id, price, timestamp)` — the
SAME existing "caller supplies observed price" entry point established in Checkpoint 34/35 and
already used to drive resting LIMIT/STOP fills. No new price feed, no polling, no Dhan import.
The caller (application/runtime layer — see `infrastructure/api/position_monitor_runtime.py`,
which already calls `record_price()` in the real Paper Trading runtime loop) is responsible for
feeding real observed market data in, exactly as before.

### Wiring (the one behavioral change)

`PaperBroker.record_price()` (`infrastructure/brokers/paper/broker.py`) now, AFTER driving any
resting-order fills for that instrument at that price (so a fill that just closed or resized the
position on this same price tick is marked using its post-fill state, not a stale pre-fill
snapshot): if an OPEN position exists for `instrument_id`, replaces it with
`mark_position(existing_position, price)`. `PaperBroker` deliberately does NOT poll market data
itself — it only reacts to a price the caller already pushed in, avoiding a
broker → market-data → broker circularity. Positions for OTHER instruments are untouched
(dict keyed by `InstrumentId`, isolation is structural, not merely tested).

### New account-level surface on `PaperBroker`

- `get_total_unrealized_pnl()` — sum of `unrealized_pnl` across OPEN positions.
- `get_open_positions_market_value()` — signed sum of `position_market_value()` across OPEN
  positions (a short position's contribution is negative, per the sign convention above).
- `get_equity()` — `available_cash (from get_funds()) + get_open_positions_market_value()`.
  Deliberately a thin derivation over the two already-authoritative sources
  (`get_funds()`, `get_positions()`), never a third, independently-tracked running total, so it
  cannot drift out of sync with either.

`total_pnl` (cumulative_realized_net_pnl + total_unrealized_pnl) is a CALLER-SIDE composition,
not a new field on any contract — this checkpoint does not add a `total_pnl` property anywhere,
deliberately, because the two addends use DIFFERENT cost conventions (see below) and summing
them silently, inside a single accessor, would hide that asymmetry from the caller.

### Missing/never-marked price handling

A position that has never been marked (no `record_price()` call yet for its instrument since it
was opened) carries `unrealized_pnl == Decimal("0")`. This is NOT redesigned by this checkpoint
— it is `PaperBroker._apply_to_position`'s existing pre-64.38 behavior at position-open time,
documented here precisely rather than replaced: `Decimal("0")` here means "honestly unmarked,"
not "no P&L." `position_market_value()` on such a position correctly reduces to book value
(`quantity * average_entry_price`, signed), never a fabricated zero valuation. There is no
separate "stale" concept distinct from "never marked" — `mark_position`/`record_price` carry no
freshness/timestamp parameter; the only two states are "never marked" and "marked against the
most recently observed price." A future checkpoint that needs true staleness detection
(e.g. "no price for N minutes during live hours") would need to add that as a new, explicit
capability — not something silently inferred from the current design.

### Cost treatment (cost-EXCLUSIVE, by design)

Neither `compute_unrealized_pnl` nor `compute_market_value` deducts any transaction cost.
`unrealized_pnl` is PURE PRICE P&L on the remaining open quantity — mirroring
`research/backtesting/mark_to_market.py`'s own already-documented "unrealized valuation excludes
exit costs" choice. This is DELIBERATE and asymmetric with `Position.realized_net_pnl` (64.37),
which IS cost-inclusive for CLOSED trades. The two are never summed by any function in this
checkpoint as if they used the same cost convention — a caller composing `total_pnl` must do so
knowingly, aware that the unrealized component omits the (not-yet-incurred) exit cost.

### Relationship to the Risk Gate — unaffected, verified

`RiskEvaluationContext.current_daily_realized_pnl` (consumed by
`domain/risk/policy.py::evaluate_order_risk()`, unchanged since 64.37) is fed by
`PaperTradingService.submit_order` summing `p.realized_net_pnl or Decimal("0")` across
positions — `realized_net_pnl` only. `mark_position`/`record_price`'s new marking behavior never
writes to `realized_pnl` or `realized_net_pnl` (it constructs a new `Position` via
`dataclasses.replace(position, unrealized_pnl=...)`, carrying every other field through
unchanged) and `PaperTradingService.submit_order`'s risk-context construction was NOT modified
by this checkpoint. `unrealized_pnl` therefore cannot reach the Risk Gate through any path this
checkpoint added. Verified directly: 64.37's Risk Gate contract test suite
(`test_checkpoint_64_37_net_pnl_risk_contract.py`) re-run fresh this checkpoint, 22/22 passing,
byte-identical assertions, no changes to that file.

### Backward compatibility

`Position.realized_pnl`/`Trade.realized_pnl`/`Position.realized_net_pnl`/
`Trade.realized_net_pnl` formulas are completely untouched — `mark_position` only ever touches
`unrealized_pnl`. `research/backtesting/engine.py`, `contracts.py`, and `portfolio.py` are not
edited by this checkpoint (verified via `git diff --stat` on `engine.py`/`contracts.py`
returning empty; `portfolio.py` carries a pre-existing UNCOMMITTED diff from an earlier
checkpoint (64.33) that predates this session and was not touched here).

### Remaining gaps (explicitly out of scope, unchanged from 64.37's own listing)

Fill/Execution model convergence between Backtest's "next bar open" model and `PaperBroker`'s
slippage/partial-fill/cost model remains unreconciled. Partial-exit EXECUTION (an engine that
actually issues partial-exit orders against a strategy's exit rules) remains deferred — this
checkpoint's `mark_position` correctly HANDLES an already-partially-reduced `Position.quantity`
if one exists, but does not create one. Calendar-day scoping of P&L figures remains
"since session/run start." `BacktestTrustLevel.POC` is unchanged by this checkpoint (not
touched, not re-evaluated) — Research Readiness is NOT upgraded by mark-to-market's existence.

---

## CHECKPOINT 64.39 — EXECUTION / FILL CONVERGENCE AUDIT

Audit-and-design-only, per its own directive: no production formula changed. All claims below
are cited to source line ranges read this checkpoint (`git status --short` at end of session
shows this doc, `taskReport.md`, and one new test file as the only 64.39 changes — every other
listed modification is carried forward, untouched, from 64.34-64.38).

### 1. Execution flow maps

**Backtest** (`research/backtesting/engine.py`, single-instrument path):

```
Strategy.evaluate() [execution.py:131, compute_signals()]
  -> StrategySignal (BULLISH/BEARISH/NEUTRAL)
  -> [if strategy has build_trade_plan] tradeplan_execution.compute_trade_plans() [tradeplan_execution.py:74]
  -> engine.py entry branch (i-th bar's signal read, entry ALWAYS deferred to i+1)
       entry_bar = bars[i+1]                                             engine.py:314
       filled_entry = costs.slippage_adjusted_price(..., entering=True)  engine.py:315-317
       quantity = quantity_for_config(...)                               engine.py:318
  -> [if backtest_config.risk_limits set] evaluate_backtest_entry_risk() engine.py:356-389
       REJECTED -> risk_rejected_trades += 1, no position opened
  -> [if quantity <= 0] rejected_trades += 1, no position opened          engine.py:436-437
  -> OpenPosition created (execution.py OpenPosition dataclass), position_lifecycle.open_backtest_position()
  -> [TradePlan strategies] tradeplan_execution.simulate_tradeplan_exit() precomputed at entry time
       engine.py:427-432, walked bar-by-bar; when loop reaches exit_index, _close_trade() called  engine.py:445-451
  -> [direction-flip strategies] reversal detected -> exit_bar = bars[i+1], _close_trade(i+1, exit_bar.open, "signal_reversal")  engine.py:474-476
  -> [EOD, either model] _close_trade(i, bars[i].timestamp, bars[i].close, EOD/"end_of_data")  engine.py:461,480
  -> _close_trade(): gross_pnl via signed_gross_pnl(), costs.cost_breakdown() combined entry+exit, net_pnl = gross_pnl - trade_costs  engine.py:214-228
  -> SimulatedTrade recorded directly (dataclass literal, no Fill/Order intermediate object)
  -> _build_mark_to_market_curve(): one point per bar, mark price = bar's own close, unrealized via signed_gross_pnl() for entry_index <= i < exit_index  engine.py:564-612
```

Producer/input/output/timing per stage: Strategy produces StrategySignal from Bar+FeatureValues
at bar i (timing: same bar as signal, but ACTED ON at bar i+1 — no state mutation at signal
time). Entry stage produces `OpenPosition` at bar i+1's open (state mutation: position map
gains an entry; quantity source `quantity_for_config`; cost source `costs.cost_breakdown`
combined at exit; slippage via `costs.slippage_adjusted_price`; no discrete "order state" object
exists — the transition from "signal" to "position" is a single synchronous function call with
no intermediate PENDING/ACKNOWLEDGED representation).

**Paper** (`infrastructure/brokers/paper/broker.py` + `application/services/paper_trading.py`):

```
Strategy (via live coordinator, outside this audit's file list this session)
  -> OrderIntent (domain/order/contracts.py, canonical, order_type/limit_price/trigger_price)
  -> [risk gate, application layer — not re-read this checkpoint, per 64.34/64.35 audits already on file]
  -> PaperTradingService (application/services/paper_trading.py) submits to PaperBroker
  -> PaperBroker.submit_order(): CREATED -> SUBMITTED -> TRANSIT -> ACKNOWLEDGED -> PENDING  broker.py:195-200
       [MARKET] price = self._latest_prices.get(instrument_id); None -> REJECTED (NoReferencePriceError semantics)  broker.py:202-210
       [MARKET, price found] _attempt_fill(record, price) synchronously                       broker.py:211
       [LIMIT/STOP] stays PENDING, no optimistic fill                                          broker.py:212-213
  -> record_price() [caller feeds observed market data, application layer responsibility]      broker.py:333-361
       drives _maybe_fill_resting_order() for every PENDING/PARTIALLY_FILLED order on that instrument  broker.py:345-350
       [LIMIT] crosses -> _attempt_fill(record, intent.limit_price)                            broker.py:407-411
       [STOP_LOSS_MARKET] triggered -> _attempt_fill(record, price)                            broker.py:419-420
       [STOP_LOSS] triggered AND crosses own limit -> _attempt_fill(record, intent.limit_price) broker.py:421-425
       NOTE: no branch exists for OrderType.MARKET in _maybe_fill_resting_order — see Finding F1 below
  -> _attempt_fill(): slippage applied to the `price` ARGUMENT (whatever stage passed in)       broker.py:428-435
       fill_quantity = round(remaining * partial_fill_ratio), clamped to remaining if <=0 or >remaining  broker.py:437-440
       cost = self._compute_cost(is_buy, notional) [injected closure]                           broker.py:443
       BUY: reject if required > available_balance; else charge balance                        broker.py:445-450
       record.filled_quantity += fill_quantity; average_fill_price = slipped_price              broker.py:454-455
       PARTIALLY_FILLED or FILLED transition                                                    broker.py:456-462
       _apply_to_position(): new/blend/close Position, realized_pnl, realized_net_pnl (64.37)    broker.py:464-598
  -> record_price() ALSO marks the resulting position via mark_position() (64.38), AFTER driving resting fills  broker.py:351-361
```

### 2. Backtest execution model semantics (cited)

- Entry: ALWAYS next bar's open, both models (`engine.py:314-317`).
- Exit (direction-flip strategies, e.g. `ema_crossover`, `sma_trend_filter` — no `build_trade_plan`
  hook): next bar's open on signal reversal (`engine.py:474-476`).
- Exit (TradePlan strategies, currently only `atr_volatility_breakout`): intrabar SL/T1/T2/T3/
  trailing simulated by `tradeplan_execution.simulate_tradeplan_exit()`, evaluated strictly AFTER
  the entry bar (`tradeplan_execution.py:145`, `entry_index + 1`), stop-loss-first-if-ambiguous,
  lowest-numbered-target-first-if-ambiguous (`tradeplan_execution.py:123-137` docstring, "v1"
  policy). Signal reversals are NOT used to exit TradePlan positions (confirmed: `engine.py`'s
  reversal branch at line ~474 is only reached in the direction-flip code path, not the
  TradePlan path per the engine's own branching — see `engine.py:427-451` vs `:474-480`).
- EOD force-close: both models, at the FINAL bar's own CLOSE (`engine.py:461` TradePlan path
  `ExitReason.EOD`; `engine.py:480` direction-flip path `"end_of_data"`).
- Slippage: `costs.slippage_adjusted_price()` (`cost_model.py:134-142`, `:163-168` flat-percentage
  impl, `:257-264` verified-schedule impl — SAME formula in both, only `slippage_percent` config
  differs) applied to both entry (`engine.py:315-317`) and exit (`engine.py:214-216`).
- Costs: `costs.cost_breakdown(is_buy=..., notional=...)` combined for entry+exit via
  `CostBreakdown.combine()` (`cost_model.py:88-103`), `net_pnl = gross_pnl - trade_costs`
  (`engine.py:228`).
- Quantity: `quantity_for_config()` (`execution.py:93-98`, delegating to `quantity_for()`
  `execution.py:75-90` — `FIXED_QUANTITY` mode truncates to integer; percentage-of-capital mode
  divides notional by entry price, truncates `ROUND_DOWN`). Zero quantity -> `rejected_trades +=
  1`, no trade (`engine.py:436-437`). No partial fills, no partial exits — all-or-nothing.
- Risk gate: opt-in via `backtest_config.risk_limits` (`engine.py:356-389`); REJECTED increments
  `risk_rejected_trades`, skips position open — no partial rejection/partial sizing.
- Order lifecycle: NO discrete Order/OrderIntent state machine is walked inside `engine.py`'s bar
  loop for the entry/exit decision itself — `OpenPosition.order_intent` (`execution.py:38-49`)
  stores the canonical `OrderIntent` built once at entry (via `order_intent_adapter`, referenced
  in `execution.py`'s own docstring) purely for RISK-GATE input, never advanced through
  `OrderStatus` transitions the way `PaperBroker` advances its own orders.
- Position lifecycle: `position_lifecycle.py`'s 3-state `BacktestPositionLifecycleStatus`
  (OPEN -> HELD -> CLOSED, `position_lifecycle.py:52-67`) — deliberately narrower than
  `domain.position_exit.contracts.PositionLifecycleStatus`'s 8-member vocabulary (module
  docstring, `position_lifecycle.py:10-32`), because the engine is full-close-only and has no
  PARTIAL_EXIT/TARGET_n/TRAILING/STOPPED intermediate states to represent honestly.
- `trust_level=BacktestTrustLevel.POC` hardcoded at `engine.py:527` — grepped fresh this
  checkpoint, confirmed still present, unchanged.
- No `Fill`/`Order`/partial-fill contract of any kind appears in `engine.py` — trades are
  recorded directly as `SimulatedTrade` dataclass entries.

### 3. Paper execution model semantics (cited)

- MARKET orders fill immediately against the latest `record_price()` value (`broker.py:202-211`);
  no recorded price -> `NoReferencePriceError` surfaces as REJECTED, never fabricated
  (`broker.py:203-210`).
- LIMIT orders stay PENDING until `record_price()` crosses the limit (BUY: price<=limit, SELL:
  price>=limit, `broker.py:407-411`); the price PASSED to `_attempt_fill` is `intent.limit_price`
  itself, not the observed crossing price.
- STOP_LOSS/STOP_LOSS_MARKET stay PENDING until triggered (`broker.py:414-426`): BUY triggers if
  price>=trigger, SELL if price<=trigger; STOP_LOSS_MARKET fills immediately at the OBSERVED
  crossing price (`broker.py:419-420`, confirmed by
  `TestPaperStopLossMarketTriggersAndFillsImmediatelyAtTriggerPrice` — SELL stop triggered at
  95.00 but the actual crossing tick was 93.00, and the order filled at 93.00, not 95.00); the
  limit-variant STOP_LOSS only fills if that same price also crosses its own `limit_price`, else
  stays PENDING, triggered (`broker.py:421-425`).
- Slippage: flat `slippage_percent`, applied inside `_attempt_fill` to whatever `price` argument
  it is given (`broker.py:428-435`) — for a MARKET order this is the latest observed price; for a
  crossed LIMIT order this is `intent.limit_price` (not the observed crossing price); for a
  triggered STOP_LOSS_MARKET this is the observed crossing price; for a triggered/crossed
  STOP_LOSS (limit variant) this is `intent.limit_price`.
- Quantity/fill quantity/partial fills: `partial_fill_ratio` (default `Decimal("1")`, always full,
  `broker.py:146`) — `fill_quantity = round(remaining * partial_fill_ratio)`, clamped to
  `remaining` if `<=0` or `>remaining` (`broker.py:437-440`).
- Order state transitions: via `domain/order/state_machine.py::validate_transition()`, called
  inside `_transition()` (`broker.py:380-401`) before every mutation — every transition this
  broker performs is checked against `ALLOWED_TRANSITIONS` (`state_machine.py:36-80`); an invalid
  transition raises `InvalidOrderTransitionError` rather than silently succeeding.
- Rejected order / insufficient funds: a BUY fill attempt whose `notional + cost` exceeds
  `_available_balance` transitions the order to REJECTED and performs NO balance mutation and NO
  position update (`broker.py:445-450`) — this is a REJECTION DISCOVERED MID-FILL-ATTEMPT, not a
  pre-submission balance check; a SELL fill is never rejected for insufficient funds (a closing/
  short-opening sale always credits the balance, `broker.py:451-452`).
- Position updates: `_apply_to_position()` (`broker.py:466-598`) — new position, same-direction
  blended-average-price add, or opposite-direction partial/full close with cost attribution
  proportional to `closing_quantity` (`broker.py:526-547`, 64.37's contribution, formula:
  `attributable_entry_cost = accumulated_entry_cost * closing_quantity / existing.quantity`,
  `attributable_exit_cost = fill_cost * closing_quantity / fill_quantity`).
- `record_price()` also marks the open position via `mark_position()` AFTER driving resting
  fills (`broker.py:351-361`, 64.38's contribution).
- End-of-data: `force_expire_end_of_session()` explicitly EXPIRES every still-PENDING/
  PARTIALLY_FILLED order (`broker.py:363-370`) — no forced position close analogous to Backtest's
  EOD close-at-final-bar's-close exists in `PaperBroker` itself (a forced flatten would be an
  application-layer/`position_monitor_runtime.py` concern, not audited in full this checkpoint).

### 4. FINDING F1 — MARKET orders have no resting-fill completion path for a partial remainder

`_maybe_fill_resting_order()` (`broker.py:403-426`) branches only on `OrderType.LIMIT` and
`OrderType.STOP_LOSS`/`STOP_LOSS_MARKET` — there is no `OrderType.MARKET` branch. A MARKET
order's only fill attempt happens synchronously inside `submit_order()` (`broker.py:211`). If
`partial_fill_ratio < 1` leaves a MARKET order PARTIALLY_FILLED, NO subsequent `record_price()`
call will ever drive a further fill attempt for it — the order remains PARTIALLY_FILLED
indefinitely unless some caller outside `PaperBroker` explicitly re-attempts it (no such call
site was found in `broker.py` itself). Locked down by
`TestPaperMarketOrderFillsAtLatestObservedPrice` and
`TestPaperPartialFillRatioProducesPartiallyFilledStateAndRemainingQuantity` in
`tests/unit/research/test_checkpoint_64_39_execution_fill_audit.py`. Not fixed this checkpoint
(audit-only) — flagged as a real behavioral gap, not a documentation nit, since a partial fill
via `partial_fill_ratio` is a genuine, reachable configuration.

### 5. FINDING F2 — LIMIT-order slippage is applied ON TOP of the stated limit price

The class docstring (`broker.py:101-103`) states a LIMIT fill "fill at the LIMIT price (never a
better price is fabricated, and never worse — matches standard limit-order semantics)." Reading
`_attempt_fill()` (`broker.py:428-435`) shows slippage is applied to WHATEVER `price` argument
the caller passes — and `_maybe_fill_resting_order()` passes `intent.limit_price` itself as that
argument for a crossed LIMIT order (`broker.py:411`). Consequently, with any nonzero
`slippage_percent` configured, a BUY LIMIT order's actual `average_fill_price` is
`limit_price * (1 + slippage%)` — WORSE than the stated limit, directly contradicting the
docstring's "never worse" claim. Mechanically proven by
`TestPaperLimitOrderSlippageAppliedOnTopOfLimitPrice::test_buy_limit_fill_price_exceeds_stated_limit_when_slippage_configured`
(limit 100.00, 1% slippage -> fills at 101.00). This is a genuine DOCSTRING/BEHAVIOR mismatch,
not merely a modeling choice — flagged, not fixed, this checkpoint. (Note: in production use with
`slippage_percent=Decimal("0")` — the class default — this mismatch is inert; it only manifests
when a caller configures nonzero paper-trading slippage.)

### 6. Price semantics table

| Event | Backtest price | Paper price | Same? | Why different | Unifiable? |
|---|---|---|---|---|---|
| Entry (market-style) | next bar's OPEN, slippage-adjusted (`engine.py:314-317`) | latest `record_price()` observation, slippage-adjusted (`broker.py:202-211`,`:428-435`) | No | Backtest has no "live tick" concept — only discrete bars; "next bar open" IS its analogue of "next observed price" | Only if Backtest fed sub-bar ticks (out of scope) |
| Stop-loss (TradePlan) | the trade plan's own `stop_loss` level (`tradeplan_execution.py:153-157`), never the triggering bar's actual low/high | the crossing OBSERVED price for STOP_LOSS_MARKET (`broker.py:419-420`), or the order's own `limit_price` for STOP_LOSS (`broker.py:421-425`) | No | Backtest assumes the exact stop level is achieved (conservative-but-optimistic on price, pessimistic on sequencing); Paper reflects whatever discrete price tick actually crossed | Not directly — different information availability (bar OHLC vs discrete ticks) |
| Target (TradePlan) | the trade plan's own target level (`tradeplan_execution.py:172-177`) | N/A (Paper has no TradePlan target-exit engine wired in `broker.py` itself) | N/A | TradePlan target-exit is a Backtest-only capability today (per this audit) | Deferred to a future TradePlan-in-Paper checkpoint |
| EOD | final bar's own CLOSE (`engine.py:461,480`) | no automatic EOD close inside `PaperBroker` (only pending-order expiry, `broker.py:363-370`) | No | Application/`position_monitor_runtime.py` layer concern for Paper, not audited to a line citation this checkpoint | Not evaluated this checkpoint |
| MARKET order | next bar OPEN (there is no separate "market order" concept — every Backtest entry/reversal IS a market-style fill) | latest observed price (`broker.py:202-211`) | Conceptually yes | Same "next available price, no look-ahead" principle, different granularity | Already conceptually unified; granularity differs by design |
| LIMIT order | not modeled at all in `engine.py` | `intent.limit_price` (`broker.py:411`) | N/A | Backtest has no LIMIT order type | N/A |
| STOP order | TradePlan SL/trailing (see above) | `trigger_price`-crossing logic (`broker.py:414-426`) | Partially | Different data granularity (bar-range touch vs tick-cross) | Not without unifying data granularity |
| Reversal exit | next bar OPEN (`engine.py:474-476`) | N/A — Paper has no "signal reversal" concept inside `broker.py` (that is a strategy/coordinator-layer decision, outside this file) | N/A | Different architectural layer owns the decision | N/A |
| Partial exit | Not supported (Backtest is full-close-only, `position_lifecycle.py` module docstring) | Structurally possible via a smaller-quantity opposite-side order into `_apply_to_position`'s partial-close branch (`broker.py:520-547`) but requires the STRATEGY/coordinator to issue such an order — `PaperBroker` itself does not decide to partially exit | No | Backtest structurally cannot; Paper CAN if the caller constructs the right order, but no such caller was found wired in this audit's file list | Prerequisite: Backtest engine would need a partial-exit-capable position model first |

### 7. Slippage comparison

Both engines use the IDENTICAL flat-percentage slippage FORMULA shape: `price * (1 ±
slippage_percent/100)`, worse-for-the-trader in both directions
(`cost_model.py:163-168`/`:257-264` for Backtest via `slippage_adjusted_price()`; `broker.py:428-
435` for Paper, inlined rather than delegated to `CostModel.slippage_adjusted_price()`). The
64.36-era claim that "slippage is folded into the fill price, never summed into cost" holds in
BOTH engines as re-verified this checkpoint: Backtest's `CostBreakdown.total` property explicitly
excludes slippage by its own docstring (`cost_model.py:74-77`); Paper's `_attempt_fill` computes
`slipped_price` BEFORE computing `notional`/`cost`, and `cost` (`self._compute_cost(...)`) is a
separate injected closure never touching slippage (`broker.py:428-443`). Difference: Paper's
slippage is INLINED (own multiplication, `broker.py:431-435`) rather than delegated to the SAME
`CostModel.slippage_adjusted_price()` Protocol method Backtest uses — two independent
implementations of the same formula shape, not one shared function call. This is a real (if
currently harmless, since the formulas are literally identical) duplication risk: a future change
to Backtest's slippage formula would NOT automatically propagate to Paper. Order-type dependence:
Backtest's slippage is direction-only (`entering: bool` flag, no order-type concept exists);
Paper's slippage is applied uniformly to whatever price argument `_attempt_fill` receives
regardless of order type — see Finding F2 for why this is NOT the same as "the stated limit
price" for LIMIT orders.

### 8. Transaction costs

Re-verified this checkpoint against current source: 64.37's `realized_net_pnl = gross - 
attributable costs` still holds exactly as implemented — Backtest: `engine.py:228`
`net_pnl = gross_pnl - trade_costs`; Paper: `broker.py:545`
`trade_realized_net_pnl = compute_realized_net_pnl(realized, trade_transaction_cost)` calling the
SAME `domain.trade.net_pnl.compute_realized_net_pnl()` function (`net_pnl.py:62-74`). 64.38's
claim that `unrealized_pnl` is cost-EXCLUSIVE also re-verified: `mark_to_market.py:73-93`
`compute_unrealized_pnl()` performs pure price arithmetic with no cost term, matching
`engine.py`'s `_build_mark_to_market_curve()` use of `signed_gross_pnl()` (`execution.py:67-72`,
also cost-exclusive). Cost flow (both engines): notional -> `CostModel.cost_breakdown(is_buy,
notional)` -> per-leg `CostBreakdown` -> combined (Backtest: `CostBreakdown.combine()` at
entry+exit; Paper: cost attributed proportionally across entry/exit legs in
`_apply_to_position()`) -> subtracted from gross price P&L via `compute_realized_net_pnl()`
(Paper, explicit) or inline subtraction (Backtest, `engine.py:228`, same formula, not yet routed
through the shared function — a MUST-SHARE candidate, see §13). No formula was changed.

### 9. Partial fills — explicit statement

**Paper supports fill_quantity < order_quantity** via `partial_fill_ratio` (`broker.py:146`,
`:437-462`), producing `OrderStatus.PARTIALLY_FILLED` and a resting order with nonzero remaining
quantity for LIMIT/STOP order types (subject to Finding F1's MARKET-order caveat).
**Backtest does NOT support partial fills at all** — `quantity_for_config()` computes one
quantity once at entry time (`engine.py:318`), and either that whole quantity fills or the trade
is rejected outright (`engine.py:436-437`) — there is no intermediate state.

### 10. Partial fills vs partial exits — conceptual distinction

- **Partial FILL**: an order for quantity 100 is only partially executed against available
  liquidity/configured ratio — e.g. `fill_quantity = 40` against `order.quantity = 100`, leaving
  `remaining_quantity = 60` still resting on the SAME order (Paper: `broker.py:437-462`).
- **Partial EXIT**: an already-fully-filled OPEN position of quantity 100 is reduced by an
  intentional, smaller, OPPOSITE-side order for quantity 40 (e.g. taking partial profit at
  Target 1) — a strategy/risk decision about how much of an existing position to close, not a
  liquidity/fill-ratio artifact. In `PaperBroker`, this is mechanically the SAME code path as any
  opposite-direction fill smaller than `existing.quantity` (`broker.py:520-547`,
  `closing_quantity = min(existing.quantity, fill_quantity)`), so a partial exit is representable
  TODAY in Paper's position model IF a caller issues the right order — but no strategy/coordinator
  call site issuing such a deliberate partial-exit order was found wired into `PaperBroker` in
  this audit's file list (this checkpoint did not re-read every trading_engine coordinator file,
  so absence-of-evidence here is not proof of absence — flagged as unverified rather than
  asserted false). Backtest has NEITHER capability — full-close-only by construction
  (`position_lifecycle.py` module docstring).

### 11. Order lifecycle comparison

| State/concept | Backtest | Paper | Canonical source |
|---|---|---|---|
| Discrete OrderStatus enum walked in engine loop | No — entry/exit are synchronous function calls, no state object advanced | Yes — every `_transition()` call validated against `state_machine.ALLOWED_TRANSITIONS` | `domain/order/contracts.py::OrderStatus`, `domain/order/state_machine.py` |
| CREATED/SUBMITTED/TRANSIT/ACKNOWLEDGED/PENDING | N/A | All four traversed synchronously on `submit_order()` (`broker.py:197-200`) | Paper only |
| PARTIALLY_FILLED | N/A (no partial-fill concept) | Real, reachable (`broker.py:456-462`) | Paper only |
| FILLED | Implicit — a `SimulatedTrade` simply exists; no explicit FILLED status object | Real (`broker.py:456-462`) | Paper canonical; Backtest has no equivalent object |
| REJECTED | `rejected_trades`/`risk_rejected_trades` COUNTERS incremented (`engine.py:381,437`), no per-trade OrderStatus object | Real, per-order (`broker.py:205-210`,`:448`) | Different representations — Backtest is aggregate-counter, Paper is per-order-object |
| CANCELLED/EXPIRED | N/A | Real (`broker.py:217-223`,`:363-370`) | Paper only |
| Canonical vs duplicated | Backtest never imports `domain.order.state_machine` for the entry/exit decision itself (only builds an `OrderIntent` value for risk-gate input, per `execution.py:38-49`'s docstring) | Uses the canonical domain state machine directly | No duplication of the STATE MACHINE itself — Backtest simply does not use one for this purpose. This is an ASYMMETRY, not a duplicated/competing implementation. |

### 12. Candidate Fill contract

No existing standalone domain `Fill` dataclass/contract was found (grepped repo-wide for
`class Fill`, `FillEvent`, `fill_price`, `filled_quantity`, `average_fill_price`,
`executed_quantity` this checkpoint — 18 files matched some term, none define a first-class
`Fill` domain object; `domain/order/events.py::OrderEvent` carries `filled_quantity`/
`remaining_quantity`/`price` as FIELDS OF AN ORDER EVENT, not as its own Fill entity, and
`domain/trade/contracts.py::Trade` represents a CLOSED round-trip, not a single fill). A future
minimal canonical `Fill` contract, if introduced, should carry (rationale in parens):

- `fill_id: str` — own identity, distinct from `order_id` (an order may have >1 fill).
- `order_id: OrderId` — traceable to its originating order (mirrors `Trade.order_ids`'s own
  linkage pattern, `domain/trade/contracts.py`).
- `instrument_id: InstrumentId` — required for any cross-instrument aggregation.
- `side: Side` — BUY/SELL, reused from `domain/shared_kernel/contracts.py` (never a new enum).
- `quantity: Decimal` — the fill's own quantity (NOT the order's total quantity — see §10's
  partial-fill/partial-exit distinction; this field answers "how much filled just now").
- `price: Decimal` — the ACTUAL price this fill executed at, post-slippage (both engines already
  compute this value today — Backtest's `filled_entry`/exit price, Paper's `slipped_price`).
- `timestamp: datetime` — when the fill occurred (UTC, per `ensure_utc()` convention already used
  throughout `domain/*/contracts.py`).
- `transaction_cost: Decimal` — the itemized-or-total cost attributable to THIS fill (both
  engines already compute a per-leg `CostBreakdown`/`fill_cost` today — reuse `CostBreakdown`
  itself rather than a scalar, to preserve `cost_model.py`'s existing itemization discipline).
- `slippage_applied: Decimal | None` — the price delta actually realized vs the pre-slippage
  reference price, kept SEPARATE from `transaction_cost` (mirrors `CostBreakdown.total`'s own
  explicit "excludes slippage" design, `cost_model.py:74-77` — never re-merge the two).
- `status_at_fill: OrderStatus` — FILLED or PARTIALLY_FILLED (the two states a fill can produce),
  so a consumer knows whether more fills may follow this order.
- `source: Literal["BACKTEST","PAPER","LIVE"]` (or similar) — explicit provenance metadata,
  never inferred from context, so a downstream accounting consumer can apply engine-specific
  caveats (e.g. Backtest fills never have genuine liquidity constraints) without guessing.

This is a DESIGN CANDIDATE ONLY — not implemented, not wired, no existing dataclass replaced.

### 13. Execution event ownership (current, per engine)

| Decision | Backtest owner | Paper owner |
|---|---|---|
| Can this order execute at all | `engine.py`'s own bar-loop branching + optional risk gate (`engine.py:356-389`) | `PaperBroker._transition`/`_attempt_fill` (balance check, `broker.py:445-450`) + risk gate (application layer, not re-read this checkpoint) |
| Fill price | `engine.py` (via `costs.slippage_adjusted_price()`) | `PaperBroker._attempt_fill` (own inlined slippage formula) |
| Fill quantity | `execution.py::quantity_for_config()` | `PaperBroker._attempt_fill` (`partial_fill_ratio` logic) |
| Position update | `engine.py`'s own `OpenPosition`/`_close_trade()` | `PaperBroker._apply_to_position()` |
| Transaction cost | `engine.py` calling injected `CostModel` | `PaperBroker` calling injected `compute_cost` closure |
| Realized/unrealized accounting | `engine.py`'s `SimulatedTrade`/`_build_mark_to_market_curve()` | `domain.trade.net_pnl`/`domain.position.mark_to_market` (shared pure functions, 64.37/64.38) |

Misalignment: Backtest's fill-price/quantity/cost decisions are all made INLINE inside `engine.py`
itself (no separate "broker" object); Paper's are made inside a dedicated `PaperBroker` object
that the application layer calls into. This is an architectural asymmetry (one engine IS its own
broker; the other HAS a broker), not merely a naming difference — any future convergence has to
either give Backtest a broker-shaped seam or accept the two will never share a single execution
object, only shared PURE FUNCTIONS (cost model, net_pnl, mark_to_market) called from each side.

### 14. MUST-SHARE table

| Concept | Backtest | Paper | Must share? | Why |
|---|---|---|---|---|
| OrderIntent | Built via `order_intent_adapter` for risk-gate input (`execution.py:38-49`) | Canonical, built by the application/coordinator layer | YES | Already the same `domain.order.contracts.OrderIntent` type on both sides — must stay one type. |
| RiskDecision | `evaluate_backtest_entry_risk()` (`engine.py:356-389`) | Application-layer risk gate (64.34/64.35 already established convergence) | YES (already converged per 64.34/64.35 — not re-verified line-by-line this checkpoint) | A risk-approved trade must mean the same thing in both engines. |
| OrderState | None (no discrete state object) | `domain.order.contracts.OrderStatus` + `state_machine.py` | Partially — the VOCABULARY should be shareable even if Backtest never walks the transitions; Backtest CAN keep no-op-ing through it conceptually | Prevents two competing status vocabularies from ever existing. |
| Fill | Neither has one (see §12) | Neither has one | YES if one is ever introduced | Exactly one canonical Fill shape prevents a future third "own way" model. |
| Fill price | `filled_entry`/exit price, slippage-adjusted | `slipped_price` | YES (semantically) | Both mean "price after slippage" — should be the SAME formula call, not two inlined ones (see §7). |
| Fill quantity | `quantity_for_config()` result, all-or-nothing | `fill_quantity`, possibly partial | Semantics MUST match where they overlap (full-fill case); partial-fill capability MAY differ (§9/§15 below) | |
| Slippage | `CostModel.slippage_adjusted_price()` | Inlined duplicate formula | YES — should call the SAME function, not two copies (Finding, §7) | Formula duplication risk. |
| Transaction cost | `CostModel.cost_breakdown()` | `compute_cost` injected closure (expected, per docstring, to wrap the same `CostModel`) | YES | Already intended to share the same verified schedule — injection point exists, verify call sites in a future checkpoint. |
| Position update | `OpenPosition`/`_close_trade()` | `_apply_to_position()` | Semantics MUST match (blended average price, proportional cost attribution) — ALREADY converged per 64.37/64.38 pure-function reuse (`net_pnl.py`, `mark_to_market.py`) | |
| Accounting event (realized_net_pnl/unrealized_pnl) | `SimulatedTrade.net_pnl`, `_build_mark_to_market_curve()` | `Position.realized_net_pnl`, `Position.unrealized_pnl` | YES — already share `compute_realized_net_pnl`/`compute_unrealized_pnl` pure functions | Converged 64.37/64.38; this checkpoint changes nothing here. |
| Position lifecycle | `BacktestPositionLifecycleStatus` (3-state) | `PositionStatus`/`PositionLifecycleStatus` (broader) | MAY legitimately differ — Backtest's 3-state vocabulary is an honest reflection of its full-close-only reality (§2's own citation), not an arbitrary alternate design | |
| Exit reason | `ExitReason` enum (`tradeplan_execution.py:78-88`) plus string literals `"signal_reversal"`/`"end_of_data"` (`engine.py:476,480`) | No equivalent enum found in `broker.py` (exit reason is implicit in which order type/side closed the position) | Should converge eventually — Backtest's typed `ExitReason` enum vs Paper's implicit/untyped reason is an inconsistency worth resolving in a future checkpoint, not this one | |

### 15. MAY-DIFFER list (explicit, measurable, documented)

- **Historical next-bar-open vs live observed-price execution**: Backtest deterministically knows
  the entire bar series in advance (constrained to never look ahead by construction, `engine.py`'s
  own next-bar discipline); Paper genuinely only knows prices as `record_price()` delivers them.
  Measurable: Backtest's fill price is always exactly `bars[i+1].open` (or a TradePlan level);
  Paper's is whatever the LAST recorded tick was. Documented here and in the entry/exit citations
  above.
- **Latency**: Paper's `_clock()` is injected and can model real elapsed time between submission
  and fill events (`broker.py`'s `OrderEvent.timestamp_utc`/`received_at_utc` split); Backtest has
  no concept of elapsed wall-clock time between signal and fill — only bar-index granularity.
- **Data availability**: Backtest requires the full bar series up front; Paper operates
  incrementally, tick-by-tick, and can legitimately have gaps (no `record_price()` call for a
  period) that Backtest cannot have (every bar in the series is, by construction, present).
- **Slippage realization**: both use the SAME flat-percentage MODEL ASSUMPTION formula (§7), but
  a future upgrade to a liquidity-based/order-book-based slippage model for Paper (reflecting
  actual observed spread) would legitimately differ from Backtest's necessarily-simplified
  bar-only assumption — acceptable ONLY if, as now, both sides' formulas are explicitly labeled
  MODEL ASSUMPTIONS (`cost_model.py:147-151`'s own docstring already does this).
- **Liquidity**: Backtest has no liquidity constraint at all (any computed quantity always fully
  fills or is rejected for being zero); Paper's `partial_fill_ratio` can model a liquidity
  constraint, however crude. Acceptable because it is an explicit, documented, off-by-default
  (`Decimal("1")`) configuration, not a silent behavioral drift.
- **Partial-fill probability**: Backtest never partially fills (§9); Paper can, via configuration.
  Acceptable ONLY because it is: (a) off by default, (b) explicitly documented in the class
  docstring, (c) mechanically tested (this checkpoint's new characterization tests).

Differences NOT on this list (i.e., NOT currently acceptable, flagged as findings instead):
Finding F1 (MARKET-order partial-fill stranding) and Finding F2 (LIMIT-order slippage exceeding
the stated limit) are NOT documented, explicit, intentional differences — they are undocumented
behavior/docstring mismatches, which is why they are recorded as Findings rather than as
MAY-DIFFER entries.

### 16. Parity test design (future, not implemented this checkpoint)

A future parity test would need to hold OrderIntent + RiskDecision + execution PARAMETERS
(quantity, direction, cost model, slippage percent) constant while allowing the PRICE SOURCE
MECHANICS to differ, then assert the resulting Fill's derived quantities agree wherever they
are supposed to:

1. Construct one canonical `OrderIntent` (same `quantity`, `side`, `order_type=MARKET`).
2. Feed Backtest a single-bar series whose `open == X` for the fill bar, and feed Paper a
   `record_price()` call with the SAME value `X` at fill time.
3. Configure BOTH engines with the IDENTICAL `slippage_percent` and the SAME
   `IndianCashEquityIntradayCostModel` instance (or equal-parameter instances).
4. Assert: `abs(backtest_filled_price - paper_average_fill_price) == 0` (both apply the identical
   slippage formula to the identical reference price — this WOULD catch Finding F2-style drift if
   ever a LIMIT-order case were included, since the reference price fed to slippage differs).
5. Assert: `backtest_trade_costs == paper_fill_cost` for equal notional and `is_buy` (both call
   into the same verified `CostModel`).
6. Assert: `backtest_quantity == paper_filled_quantity` ONLY for the full-fill case (never assert
   equality when `partial_fill_ratio < 1` is configured on the Paper side — that is a legitimate,
   documented MAY-DIFFER case per §15).
7. Explicitly do NOT assert equality of "which bar/tick supplied the price" — only the FINAL
   fill's derived price/cost/quantity, since price-source mechanics are allowed to differ (§15).

Acceptance criteria for such a test to be considered PASSING/MEANINGFUL: it must fail loudly if
Finding F1 or F2 is ever silently reintroduced after being fixed, and it must never assert
equality on Backtest's zero-partial-fill-capability vs Paper's partial-fill capability as if they
were bugs.

### 17. Execution/cost/P&L relationship trace

`OrderIntent` (risk-approved request) -> `Fill` (candidate future contract, §12; today: Backtest's
inline `filled_entry`/exit values, Paper's `slipped_price`/`fill_quantity`/`fill_cost`) ->
`Position` update (Backtest: `OpenPosition` mutation + `_close_trade()`; Paper:
`_apply_to_position()`) -> `realized_net_pnl` (via `domain.trade.net_pnl.compute_realized_net_pnl`,
shared, 64.37) + `unrealized_pnl` (via `domain.position.mark_to_market.compute_unrealized_pnl`,
shared, 64.38) -> equity (Backtest: `running_equity` threaded through the bar loop; Paper:
`PaperBroker.get_equity()` = `available_balance + get_open_positions_market_value()`,
`broker.py:316-323`). The eventual accounting event (a future formal "AccountingEvent" domain
object, if one is ever introduced) should be generated at the SAME point both engines already
compute `realized_net_pnl`/`unrealized_pnl` today — i.e. as a THIN WRAPPER over the existing 64.37/
64.38 pure functions, never a third, independently-computed figure. No accounting duplication
exists today to correct; this section is forward-looking design guidance only.

### 18. Performance observations (measured this checkpoint, not optimized)

`poetry run pytest -q` (full suite, 1801 tests after this checkpoint's 5 additions) completed in
**398.99s** measured test-runner time (`6m42.215s` wall via the `time` wrapper, most of the
difference being process startup/collection overhead measured by `time` but not by pytest's own
internal timer) on this machine, this session — comparable to 64.38's own ~413s baseline (no
regression, no improvement claimed; normal run-to-run variance). No per-bar/per-fill
microbenchmark was constructed this checkpoint (out of scope per the directive's "do NOT
optimize" instruction and "measure only if practical" — a dedicated benchmark harness was judged
not practical to build safely within an audit-only checkpoint without risking accidentally
becoming a mini-implementation effort). No Dhan/live network was touched, per the market-closed
constraint.

### 19. Future implementation sequence (design guidance only, NOT started)

1. Route Paper's inlined slippage formula (`broker.py:428-435`) through the SAME
   `CostModel.slippage_adjusted_price()` Protocol method Backtest already uses, eliminating the
   formula-duplication risk noted in §7 (fixes nothing behaviorally today since the formulas are
   identical, but removes the drift risk).
2. Fix Finding F2 (decide, explicitly, whether LIMIT-order slippage should apply on top of the
   limit price or not — currently undocumented-as-intended behavior) and Finding F1 (give MARKET
   orders a resting-fill completion path, or explicitly document that MARKET orders never
   partially-then-later-complete).
3. Introduce the candidate `Fill` contract (§12) as a genuinely new, additive domain object —
   populate it from BOTH engines' existing computations without changing either engine's existing
   fields.
4. Only once (1)-(3) are stable: consider whether Backtest's inline entry/exit logic could be
   refactored to consume the SAME `Fill`-producing seam Paper's `PaperBroker` already has, without
   changing any existing numerical backtest result (a pure architectural refactor, gated behind
   full regression parity).
5. Partial-exit EXECUTION (a strategy layer that actually ISSUES partial-exit orders) remains a
   separate, later concern from Fill/Execution convergence — do not conflate the two.

This checkpoint implements NONE of the above — it is guidance for a future checkpoint only.

## CHECKPOINT 64.40 — EXECUTION CORRECTNESS FIXES

64.39 audited-and-documented (but did not fix) two genuine execution defects and one duplication
risk. 64.40 fixes exactly those three items, additively, with full regression parity — no `Fill`
contract, no execution engine, no partial-exit engine.

### F1 — partial MARKET fill completion

**Root cause**: `PaperBroker._maybe_fill_resting_order()` (`broker.py`, pre-64.40) had branches
only for `OrderType.LIMIT` and `OrderType.STOP_LOSS`/`STOP_LOSS_MARKET`. A MARKET order left
`PARTIALLY_FILLED` by its one synchronous `_attempt_fill()` call inside `submit_order()` (when
`partial_fill_ratio < 1`) had NO branch driving any further fill attempt — `record_price()`'s
resting-order loop iterated it every tick but silently did nothing, forever.

**Intended semantics (decided this checkpoint)**: `partial_fill_ratio` models a ONE-TIME liquidity
constraint at initial submission, not a repeating one. The remaining quantity completes IN FULL on
the next valid `record_price()` observation — never re-applies the ratio to the shrinking
remainder (which would asymptotically approach, but never reach, zero — an infinite-fill risk
explicitly forbidden by the checkpoint directive). This matches the directive's own preferred flow
(remaining quantity -> next valid execution observation -> additional fill -> FILLED when
remaining = 0) and is the conservative, safety-first choice for a live-paper-intent broker: an
order that can never complete is a worse outcome than one that completes slightly later than a
strict ratio-repeated model might imply.

**Fix**: `_maybe_fill_resting_order()` gained an `OrderType.MARKET` branch: if `record.status is
OrderStatus.PARTIALLY_FILLED`, it calls `_attempt_fill(record, price, force_full_remaining=True)`.
`_attempt_fill()` gained a `force_full_remaining: bool = False` keyword parameter — when `True`,
`fill_quantity = remaining` (bypassing the `partial_fill_ratio` computation entirely, which was
already applied once at initial submission). No new `OrderStatus` value, no new order state, no
change to `OrderStatus` transitions beyond the already-legal `PARTIALLY_FILLED -> FILLED`
(`state_machine.py`'s existing `ALLOWED_TRANSITIONS` table, unchanged).

**Bounds proof (no infinite/zero/overfill loop)**: `force_full_remaining=True` sets
`fill_quantity = remaining` unconditionally — never zero (unless `remaining` is already zero, in
which case the order is already `FILLED` and the branch's own `record.status is PARTIALLY_FILLED`
guard prevents re-entry), never negative (Decimal arithmetic on a monotonically-decreasing
`filled_quantity <= intent.quantity` invariant preserved from the pre-existing formula), and never
more than one additional fill event completes it (the branch only fires while status is
`PARTIALLY_FILLED`; once `_attempt_fill` sets it to `FILLED`, the loop's own outer filter in
`record_price()` — `status not in (PENDING, PARTIALLY_FILLED)` — excludes it from all future
ticks).

**Tests**: `tests/unit/research/test_checkpoint_64_40_execution_correctness.py::TestF1PartialMarketFillCompletes`
(5 tests: multi-fill completes to exact quantity + FILLED; per-fill cost computed and summed
correctly; no duplicate fill on a repeated observation after completion; cannot exceed requested
quantity across an uneven ratio; `partial_fill_ratio = 1` remains ordinary full-fill behavior).
`test_checkpoint_64_39_execution_fill_audit.py`'s own MARKET-partial-fill test was updated in
place (it previously characterized the bug; it now characterizes the fix — see that file's
updated docstring).

### F2 — LIMIT order + slippage boundary

**Root cause**: `PaperBroker._attempt_fill()` (pre-64.40) computed `slipped_price` from whatever
`price` argument it was given, with no order-type awareness. `_maybe_fill_resting_order()` passed
`intent.limit_price` itself as that `price` for a crossed LIMIT order, so slippage was then applied
ON TOP of the stated limit price — a BUY LIMIT could fill WORSE than its own limit, contradicting
the class docstring's "never worse [than limit]" claim.

**Intended semantics (decided this checkpoint)**: the checkpoint directive's own recommended model
was verified against the existing docstring and adopted as-is (no contradicting project rule was
found): determine crossing against the raw observed price (unchanged), determine the execution
price, apply slippage, then ENFORCE the limit-price boundary by clamping — `min(slipped_price,
limit_price)` for BUY, `max(slipped_price, limit_price)` for SELL. This is the standard limit-order
guarantee ("never worse than your stated limit") applied consistently even under nonzero
`slippage_percent`.

**Scope decision**: the clamp is applied to BOTH plain `OrderType.LIMIT` (explicitly named by F2)
and the `OrderType.STOP_LOSS` limit leg (which also fills at `intent.limit_price` once triggered
and crossed — the identical defect, by the identical mechanism, in the same function). Applying the
fix there too is not scope creep; leaving it unfixed would have left a byte-identical bug
un-remediated in a sibling code path of the exact function this checkpoint modifies.
`STOP_LOSS_MARKET` is explicitly NOT clamped — it has no stated limit boundary (it is, by design, a
market order once triggered), so slippage applies unclamped there, matching its own already-audited
and unchanged behavior.

**Fix**: `_attempt_fill()` gained a `limit_boundary: Decimal | None = None` keyword parameter.
`_maybe_fill_resting_order()` passes `limit_boundary=intent.limit_price` for both the LIMIT branch
and the STOP_LOSS limit-leg branch. After computing and rounding `slipped_price`, `_attempt_fill()`
clamps it against `limit_boundary` when set, BEFORE computing `notional`/`cost` — so transaction
cost is always based on the ACTUAL (post-clamp) fill price, never the raw observed price, the
original limit price coincidentally, or the pre-clamp slipped price. Slippage remains an
execution-price adjustment, never folded into `CostBreakdown` as a cost line item (unchanged from
64.39's own finding).

**Tests**: `TestF2LimitOrderSlippageBoundary` (5 tests: BUY LIMIT clamped under adverse slippage;
SELL LIMIT clamped under adverse slippage; zero slippage unchanged; LIMIT not crossed does not
fill; STOP_LOSS's own limit leg also clamped). `test_checkpoint_64_39_execution_fill_audit.py`'s
own LIMIT-slippage test was updated in place (previously characterized the bug; now characterizes
the fix).

### Shared slippage function

**New module**: `src/intraday/domain/shared_kernel/slippage.py` —
`apply_flat_percentage_slippage(*, is_buy: bool, price: Decimal, slippage_percent: Decimal) ->
Decimal`. Pure function, no I/O, no rounding (rounding remains each caller's own responsibility —
Backtest's `CostModel.slippage_adjusted_price()` has always returned an unrounded Decimal; changing
that would have altered Backtest's numerical results, which the directive explicitly forbids).
Placed in `domain.shared_kernel` (not `research.backtesting`, not `infrastructure`) because
`.importlinter` contract 1/2 makes `domain` the one package both `research` and `infrastructure`
may depend on — the same placement pattern already used for `domain/trade/net_pnl.py` (64.37) and
`domain/position/mark_to_market.py` (64.38). Deliberately NOT a `SlippageEngine`/`SlippageManager`
class, per the directive's explicit instruction — exactly one function.

**Backtest caller**: `research/backtesting/cost_model.py`'s
`FlatPercentageCostModel.slippage_adjusted_price()` and
`IndianCashEquityIntradayCostModel.slippage_adjusted_price()` both now compute `is_buy = (direction
== StrategyDirection.BULLISH) == entering` (unchanged logic) and then call
`apply_flat_percentage_slippage(is_buy=is_buy, price=price, slippage_percent=self.slippage_percent)`
— the inline `factor = slippage_percent/100; return price*(1+/-factor)` body was deleted from both
methods.

**Paper caller**: `infrastructure/brokers/paper/broker.py::PaperBroker._attempt_fill()` now calls
`apply_flat_percentage_slippage(is_buy=is_buy, price=price, slippage_percent=self._slippage_percent)`
then applies its own pre-existing `_round()` (2dp, `ROUND_HALF_UP`) to the result — the inlined
`Decimal("1") +/- self._slippage_percent/Decimal("100")` expression was deleted.

**Proof both callers use the SAME function object (not structurally similar duplicate code)**:
`TestSharedSlippageFunction` in `test_checkpoint_64_40_execution_correctness.py` monkeypatches
`apply_flat_percentage_slippage` at each call site's own imported name
(`intraday.research.backtesting.cost_model.apply_flat_percentage_slippage` and
`intraday.infrastructure.brokers.paper.broker.apply_flat_percentage_slippage`) with a spy wrapper
and asserts the spy was actually invoked with the expected keyword arguments — a structural
duplicate could not pass this test, only a genuinely shared call site can.

**Numerical-parity proof**: `test_backtest_and_paper_produce_identical_numbers_for_same_inputs`
computes the same slippage-adjusted price via both `FlatPercentageCostModel.slippage_adjusted_price()`
and a live `PaperBroker` fill, and asserts Paper's (rounded) result equals Backtest's own result
quantized to 2dp.

### Accounting compatibility

`realized_net_pnl` (64.37's `compute_realized_net_pnl`) and `unrealized_pnl` (64.38's
`compute_unrealized_pnl`/`mark_position`) were not touched — `TestF1F2AccountingCompatibility`
proves both remain correct through an F1 multi-fill round trip and an F2 clamped-entry fill.
Transaction cost is proven to be based on the actual (post-clamp) fill price, never the raw or
pre-slippage price (`test_transaction_cost_based_on_final_clamped_fill_price_not_raw_price`). The
Risk Gate (`evaluate_order_risk()`/`RiskEvaluationContext`) was not modified.

### Fill contract / partial-exit status

Still NOT implemented, exactly as directed. No `Fill`/`FillEvent`/`ExecutionReport` class exists
anywhere in the codebase after this checkpoint (`TestNoNewAbstractionsIntroduced` mechanically
verifies this). No partial-exit engine/T1/T2/T3 executor was added.

## CHECKPOINT 64.41 — CANONICAL FILL CONTRACT

64.40 fixed F1, F2, and the slippage-formula duplication. 64.41 introduces the ONE canonical
`Fill` domain contract the 64.39 audit's §12 candidate design foreshadowed — re-evaluated fresh
against current source (not assumed final), and scoped to the contract ONLY: no unified execution
engine, no Backtest/PaperBroker producer wiring, no FillBook/FillManager/ExecutionLedger/
FillService. Files: `src/intraday/domain/execution/__init__.py` (NEW),
`src/intraday/domain/execution/contracts.py` (NEW — `Fill`, `FillSource`),
`tests/unit/research/test_checkpoint_64_41_fill_contract.py` (NEW — 49 tests).

### Fill purpose

`Fill` represents ONE actual execution/fill event — a historical fact, immutable once recorded.
It is the missing seam the 64.39 audit found absent: neither Backtest (`engine.py`'s inline
`filled_entry`/exit values) nor `PaperBroker` (`_attempt_fill`'s local `slipped_price`/
`fill_quantity`/`cost` variables) had ever had a first-class, shared shape for "what happened at
one execution."

### Fill vs order vs position vs trade

- `OrderIntent` (`domain/order/contracts.py`) = a risk-approved REQUEST, prior to and independent
  of execution. Unchanged by this checkpoint.
- `OrderStatus`/`OrderEvent` (`domain/order/contracts.py`, `domain/order/events.py`) = the
  order's LIFECYCLE vocabulary and per-transition event log. `Fill.status_at_fill` reuses
  `OrderStatus` directly (see below) rather than inventing a parallel vocabulary.
- `Fill` (this checkpoint) = ONE actual EXECUTION EVENT — how much filled, at what price, when,
  at what cost, with what slippage, resulting in what order state, from what environment.
- `Position` (`domain/position/contracts.py`) = current holdings, a snapshot Fills will
  (eventually, in a future checkpoint) feed into — never represented by `Fill` itself, and `Fill`
  does not reference `Position` at all.
- `Trade` (`domain/trade/contracts.py`) = a CLOSED round trip (entry + exit), an aggregate over
  potentially many Fills across potentially many orders (`Trade.order_ids` is already a tuple) —
  never a single execution event.
- Partial Exit = a strategy-level DECISION to reduce a Position (why an order was issued) — never
  represented by `Fill`, which only ever records that an execution happened.
- Partial Fill = an execution RESULT where `Fill.quantity < order.quantity` for that order overall
  — represented structurally by `Fill.quantity` plus `Fill.status_at_fill ==
  OrderStatus.PARTIALLY_FILLED`, and by the fact that one `order_id` can have more than one `Fill`.

These five concepts are kept structurally distinct in code — `Fill` has no field, method, or
import that reaches into `Position`, `Trade`, or any partial-exit/risk-decision type.

### Fill field decisions

| Field | Type | Required | Rationale |
|---|---|---|---|
| `fill_id` | `str` | Yes | Own identity, distinct from `order_id` (one order may have >1 fill). Producer supplies (deterministic for Backtest, uniquely generated for Paper/Live); contract validates non-empty only, mirroring `OrderIntent.idempotency_key`'s own pattern. |
| `order_id` | `OrderId` | Yes | Traces back to the originating `OrderIntent` (`Fill.order_id == OrderIntent.order_id`), mirrors `Trade.order_ids`'s linkage pattern. Never overloaded as the fill's own identity. |
| `instrument_id` | `InstrumentId` | Yes | Required for any cross-instrument aggregation; reused verbatim from `domain.shared_kernel.contracts`. |
| `side` | `Side` | Yes | BUY/SELL, reused from `domain.shared_kernel.contracts` — never a new enum. |
| `quantity` | `Decimal` | Yes, `> 0` | THIS fill's own quantity, never the order's total unless the whole order filled in one event (§2 semantics: qty-100 order filling 40-then-60 is two Fills, `quantity=40` and `quantity=60`). |
| `price` | `Decimal` | Yes, `> 0` | The ACTUAL execution price — AFTER slippage AND after any limit-boundary clamp (64.40 F2). Never the raw observed price, the stated limit price, or a pre-slippage value. |
| `timestamp` | `datetime` | Yes, UTC-aware | The execution timestamp (`ensure_utc()`, the same convention as every other domain contract) — historical simulated time for Backtest, real observed time for Paper. Never signal or order-creation time. |
| `transaction_cost` | `Decimal` | Yes, `>= 0` | See "Transaction cost representation" below — a scalar, not `CostBreakdown`. |
| `slippage_applied` | `Decimal` | Yes | See "Slippage representation" below — a signed price adjustment, kept structurally separate from `transaction_cost`. |
| `status_at_fill` | `OrderStatus` | Yes, restricted | `OrderStatus.FILLED` or `OrderStatus.PARTIALLY_FILLED` only — the two states a fill event can produce; validated in `__post_init__`, not left to caller discipline. |
| `source` | `FillSource` | Yes | See "Source/provenance" below — a new closed enum, not a bare string literal. |

No field was added "because it might be useful" — every field maps to one of the eight things the
directive required a Fill to represent (order/instrument/side/quantity/price/timestamp/
transaction-cost/slippage/resulting-status/origin).

### Identifier semantics

`fill_id` is the Fill's own identity; `order_id` is a reference to its originating order. The
relationship is `Fill.order_id == OrderIntent.order_id`, never the reverse and never conflated —
one `OrderIntent` may produce many `Fill`s, so `order_id` alone can never serve as a Fill's own
primary key. Enforcing "sum of a producer's Fills for one order stays within that order's
quantity" is explicitly the PRODUCER's responsibility (Backtest/PaperBroker/future Live), not
`Fill`'s own — `Fill` remains independently constructible as a valid event without depending on an
entire `OrderIntent` object (directive §19), since `OrderIntent` itself carries no mutable
`remaining_quantity` for `Fill` to check against.

### Quantity semantics

`Fill.quantity > 0` is enforced in `__post_init__`; `quantity <= order.remaining_quantity` is NOT
enforced by `Fill` itself (no Order-aggregate dependency exists), left to the producer, exactly as
the directive specifies. `TestSumOfFillQuantitiesInvariant` documents both sides of this boundary:
a well-behaved two-Fill sequence summing correctly, and an explicit test proving `Fill` does NOT
prevent a pathological producer from constructing an overfilling pair — a deliberate, documented
non-goal for this checkpoint, not an oversight.

### Actual-price semantics

`Fill.price` means the ACTUAL execution price — after slippage AND after any limit-boundary
clamp (64.40 F2's own enforcement: `min(slipped_price, limit_price)` for BUY,
`max(slipped_price, limit_price)` for SELL). Never the raw/reference/limit/pre-slippage price.
Documented at length in the dataclass docstring; `TestActualExecutionPriceSemantics` exercises the
LIMIT-clamped case explicitly (price=100.00 final, slippage_applied recorded separately) so the
distinction between "the price that happened" and "the adjustment that produced it" is testable,
not only documented prose.

### Timestamp semantics

`Fill.timestamp` uses the same `ensure_utc()` convention as every other domain timestamp in this
codebase (`OrderIntent.created_at`, `OrderEvent.timestamp_utc`, `Position.opened_at`, ...) — no
custom time type introduced. It means the execution timestamp specifically: for Backtest, the
historical simulated bar/tick time; for Paper, the real observed `record_price()`/`submit_order()`
time. Never signal time, never order-creation time — those already have their own fields elsewhere
(`OrderIntent.created_at`).

### Source/provenance

A new `FillSource` enum (`BACKTEST`/`PAPER`/`LIVE`) was introduced — a repo-wide grep this
checkpoint found NO existing canonical type for "which execution environment produced this event."
`domain.strategy.contracts.StrategyMaturityState.PAPER` was considered and rejected: it is a
strategy LIFECYCLE/promotion stage (IDEA → ... → PRODUCTION), an unrelated concept — a strategy
could be in maturity stage `PAPER` while its Fills (once a producer exists) are tagged `PAPER` for
a completely different reason (execution venue). Conflating the two would be a real modeling
error, not a convenience. A bare `Literal["BACKTEST","PAPER","LIVE"]` was also rejected in favor
of a proper enum, matching this project's own established convention (`OrderStatus`,
`PositionStatus`, `Side`, `TradingHaltStatus`, ... are all typed enums, never string literals).
`source` is never inferred from `order_id`/`fill_id`/context — it must always be supplied
explicitly by the (future) producer.

### Status semantics

`status_at_fill` reuses `domain.order.contracts.OrderStatus` directly — no new `FillStatus` enum
was created (`TestNoOrderStatusVocabularyDuplicated` mechanically confirms no such class exists).
Validated to be exactly `FILLED` or `PARTIALLY_FILLED` — the only two states a fill event can
produce; any other `OrderStatus` member is definitionally not a fill outcome (REJECTED/CANCELLED/
PENDING/etc. mean no execution happened at all in that event). A Fill event CAN and DOES coexist
with `PARTIALLY_FILLED` — that is precisely how a partial fill is represented.

### Transaction-cost representation

`Fill.transaction_cost: Decimal`, `>= 0` — deliberately a scalar, NOT `research.backtesting
.cost_model.CostBreakdown`. `CostBreakdown` lives in `intraday.research.backtesting`, and
`.importlinter` contract 1 forbids `intraday.domain` from importing anything under
`intraday.research` — reusing it here would either break that contract or require relocating
`CostBreakdown` into the domain layer, a much larger, unrelated architectural change explicitly
out of scope for a "canonical contract only" checkpoint. A scalar also matches what both current
producers already compute at their fill-price point: Backtest has a `CostBreakdown` and can
trivially pass `.total`; `PaperBroker._attempt_fill` already only ever has a scalar `cost` from its
injected `compute_cost` closure. No second, competing cost model was created — this field carries
a number an existing cost model produced.

### Slippage representation

`Fill.slippage_applied: Decimal` — a signed PRICE adjustment (not a percentage, not a cost-model
line item), kept structurally separate from `transaction_cost`, mirroring `CostBreakdown.total`'s
own explicit "excludes slippage" design (`cost_model.py` Part 8: slippage is priced into the fill
price, never summed into a cost total, to avoid double-counting it as both a price adjustment and
a cost line item). This checkpoint does not require a producer to populate it consistently (no
producer exists yet) — the contract only requires the field be present and of type `Decimal`; the
exact "reference price minus fill price" formula is left for the future producer checkpoint to
implement using the existing `apply_flat_percentage_slippage()` (64.40) as its source of truth.

### Immutability

`@dataclass(frozen=True, slots=True)`, the exact project-standard immutable-contract pattern used
by every other `domain/*/contracts.py` dataclass (`OrderIntent`, `OrderEvent`, `Trade`,
`Position`, `RiskDecision`, ...). `TestImmutability` proves both frozen-field-assignment rejection
and slots-based rejection of arbitrary new attributes.

### Domain dependencies

`src/intraday/domain/execution/contracts.py` imports only `enum`, `dataclasses`, `datetime`,
`decimal` (stdlib) and `intraday.domain.order.contracts.OrderStatus` +
`intraday.domain.shared_kernel.contracts` (domain-internal) — verified both by manual reading and
mechanically by `TestNoDjangoDhanApplicationResearchDependency`'s AST-based import walk, and by a
fresh `poetry run lint-imports` run (6 kept, 0 broken) after the new module was added.

### Producer integration status

NOT wired, exactly as directed. `PaperBroker` (`infrastructure/brokers/paper/broker.py`) and the
Backtest engine (`research/backtesting/engine.py`) were not modified — zero diff to either file
this checkpoint (confirmed via `git diff --stat -- <file>` isolation). No `Fill(...)` construction
call exists anywhere outside the new test file.

### Backtest/Paper parity implications

The contract is designed so BOTH a future Backtest-sourced Fill and a future Paper-sourced Fill
would use the identical schema (`TestBacktestPaperParityDesign` proves both `FillSource.BACKTEST`-
and `FillSource.PAPER`-tagged `Fill` instances share the exact same field set), differing only in
`source`/`timestamp`/`price` as the execution environment legitimately dictates (per §15's own
MAY-DIFFER list — historical vs live price-source mechanics, latency, liquidity). This checkpoint
does not itself increase Backtest/Paper execution convergence — no producer exists yet — it only
ensures that WHEN producers are built (a future checkpoint), they will populate one shared shape
rather than two independently-evolved ones.

## CHECKPOINT 64.42 — PAPERBROKER FILL PRODUCER

64.41 introduced the canonical `Fill`/`FillSource` contract, deliberately unwired. 64.42 is the
FIRST checkpoint permitted to make it real, and does so for exactly one producer: `PaperBroker`.
The `Fill` contract itself (`src/intraday/domain/execution/contracts.py`) was NOT modified this
checkpoint — no genuine integration defect was found in it.

### Every actual PaperBroker fill point (execution map)

All fills in `PaperBroker` — regardless of order type — pass through the ONE existing method
`_attempt_fill()` (`src/intraday/infrastructure/brokers/paper/broker.py`). Verified by re-reading
the file fresh this checkpoint (not assumed from 64.41's report), the callers of `_attempt_fill`
are:

1. `submit_order()` — MARKET order, immediate fill against the latest recorded price (full or
   `partial_fill_ratio`-limited).
2. `_maybe_fill_resting_order()`, LIMIT branch — fills at `intent.limit_price`,
   `limit_boundary=intent.limit_price` (64.40 F2 clamp).
3. `_maybe_fill_resting_order()`, STOP_LOSS_MARKET branch — fills at the triggering price, no
   boundary clamp (no stated limit leg for this order type).
4. `_maybe_fill_resting_order()`, STOP_LOSS branch — fills at `intent.limit_price` once triggered
   AND fillable, `limit_boundary=intent.limit_price` (same F2 reasoning as LIMIT).
5. `_maybe_fill_resting_order()`, MARKET branch (64.40 F1 completion) — a MARKET order left
   PARTIALLY_FILLED at initial submission completes its remainder in full on the next
   `record_price()` observation, via `_attempt_fill(..., force_full_remaining=True)`.

There is no sixth path — `_attempt_fill` is the single, exhaustive fill point for every order type
this broker supports, confirmed by grepping the file for every call site of `_attempt_fill` (5
call sites total, all enumerated above).

### Fill construction seam

Exactly one `Fill(...)` construction is added, inside `_attempt_fill()` itself, placed
IMMEDIATELY AFTER the existing `self._transition(...)` and `self._apply_to_position(...)` calls —
i.e. after all pre-existing order/position mutation has already happened, using the SAME local
variables that mutation already used (`fill_quantity`, `slipped_price`, `cost`, `target_state`),
never independently recomputed. If `_attempt_fill` returns early (insufficient funds -> REJECTED),
execution never reaches the `Fill` construction — no Fill is produced for a rejected order.

### Fill ID strategy

`fill_id=str(uuid.uuid4())` — a fresh UUID4 per actual execution event, generated via the
PaperBroker's existing `uuid` import (already used for `Position.position_id`, `Trade.trade_id`,
`OrderEvent.event_id` in this same file — no new ID mechanism introduced). Per the directive,
uniqueness matters more than reproducibility for Paper runtime; UUID4 gives that without inventing
a distributed-ID service. `order_id` is deliberately NEVER reused as `fill_id` — one `OrderIntent`
may produce multiple `Fill`s (F1 partial-then-complete), so they must have independent identities.

### Multi-fill behavior

Each call to `_attempt_fill` produces exactly one `Fill` for exactly the quantity that ACTUAL call
filled — never the order's total. A MARKET order with `partial_fill_ratio=0.5` submitted for
quantity 10 produces Fill #1 (`quantity=5`, `PARTIALLY_FILLED`) at `submit_order()` time, then Fill
#2 (`quantity=5`, `FILLED`) on the next `record_price()` call that completes it (F1's own
completion path) — both share `order_id`, both have distinct `fill_id`s, and
`fill_1.timestamp < fill_2.timestamp` in this exact order (never re-sorted).

### Actual price capture

`Fill.price = slipped_price` — the SAME post-slippage, post-F2-clamp `Decimal` already assigned to
`record.average_fill_price` and passed into `_apply_to_position()`. Never the raw observed price,
never the stated limit/trigger price pre-adjustment.

### Slippage capture

`Fill.slippage_applied = slipped_price - price`, where `price` is `_attempt_fill`'s own `price`
parameter — the reference price BEFORE slippage and BEFORE any F2 clamp (the market price for
MARKET/STOP_LOSS_MARKET, the stated `limit_price` for LIMIT/STOP_LOSS's limit leg). This is the
exact, already-available signed adjustment the execution path applied to arrive at the actual fill
price — not a second, independently-derived formula. Worked example matching the directive's own
(BUY, 1% slippage, raw=100): `slipped_price=101.00`, `slippage_applied=+1.00`; SELL case:
`slipped_price=99.00`, `slippage_applied=-1.00`. For a LIMIT fill clamped by F2, the clamp is
already baked into `slipped_price`, so `slippage_applied` correctly reflects the ACTUAL net
adjustment applied — verified by `TestLimitBoundaryReflectedInFill` in the new test file.

### Transaction cost capture

`Fill.transaction_cost = cost` — the exact `Decimal` `_attempt_fill` already computed via the
injected `compute_cost` closure and already charged to/credited from `_available_balance` for THIS
fill only. For a multi-fill order, each `Fill` carries its own separately-computed `cost` value
(proven by `test_multi_fill_order_attributes_cost_per_fill_not_per_order`, which injects a
stateful cost closure returning a different amount per call and asserts each `Fill.transaction_cost`
matches its own call's result, not the order-level total).

### Timestamp source

`Fill.timestamp` is a fresh call to `self._clock()` — the SAME clock function this class already
uses for `OrderEvent.timestamp_utc`, `Position.opened_at`, `Trade.closed_at`. Deliberately NOT
`intent.created_at` (order-creation time). This is one ADDITIONAL `self._clock()` call beyond what
`_attempt_fill` already made — purely additive, never replacing or reordering any existing
`self._clock()` call, so no existing timestamp value anywhere else in this class changes.

### status_at_fill

`Fill.status_at_fill = target_state` — the exact `OrderStatus.FILLED`/`OrderStatus.PARTIALLY_FILLED`
value `_attempt_fill` already computed and passed to `self._transition(...)` immediately above. No
new vocabulary, no possible drift between the order's own transitioned state and the Fill's
recorded state, because they are the same Python object reference.

### FillSource.PAPER

Every `Fill` constructed by `PaperBroker` is explicitly given `source=FillSource.PAPER` — never
inferred, matching the 64.41 contract's own explicit-supply requirement.

### Retention / observation mechanism

`PaperBroker.__init__` gains one new instance attribute, `self._fills: list[Fill] = []`, mirroring
the EXACT pre-existing pattern already used for `self._trades: list[Trade] = []` in this same
class. Each actual fill event appends one `Fill` to this list, in execution order, never re-sorted.
A new accessor, `get_fills() -> tuple[Fill, ...]`, exposes an immutable snapshot copy, mirroring
`get_trades()`'s own existing `tuple(self._trades)` pattern exactly. This was chosen over every
other option the directive listed (attaching to `_PaperOrder`, returning from `submit_order()`)
because: (1) it is the smallest change — one new list field plus one new accessor, no change to
any existing method signature or return type; (2) it naturally supports multiple fills per order
without needing a `list[Fill]` field added to `_PaperOrder` (which would touch that dataclass's
shape); (3) it is exactly the existing, already-reviewed pattern this class uses for `Trade`, so it
introduces no new architectural idiom for a future reader to learn. `get_fills()` is explicitly NOT
part of `BrokerGateway` (mirrors `get_order_events()`'s own "not part of BrokerGateway" note) — it
is Paper-specific observability, not a live-broker-portable Protocol method.

### Position compatibility

`Position` (`domain/position/contracts.py`) and `_apply_to_position()` were NOT modified. The
`Fill` construction happens strictly AFTER `_apply_to_position(intent, fill_quantity, slipped_price,
cost)` has already run, using the identical `fill_quantity`/`slipped_price` values —
`test_fill_quantity_and_price_equal_actual_position_update_values` proves `Fill.quantity ==
Position.quantity` and `Fill.price == Position.average_entry_price` for a position opened by
exactly one fill.

### Accounting compatibility

`realized_net_pnl` (64.37), `unrealized_pnl`/`market_value`/`equity` (64.38) formulas and call
sites (`compute_realized_net_pnl`, `mark_position`, `position_market_value`) were NOT touched.
`Fill` has no reference to, dependency on, or influence over any of them — it is constructed AFTER
they would already have been computed for this fill event, and none of those functions reads
`self._fills`. `test_realized_net_pnl_unrealized_pnl_equity_unaffected_by_fill_producer` proves a
full BUY-then-SELL round trip still produces `realized_pnl=100.00`, `realized_net_pnl=96.00`
(after two Decimal("2.00") attributed costs), `unrealized_pnl=0` (position closed), and
`equity=1000096.00` — identical to what those formulas would produce with no `Fill` producer at
all — while `get_fills()` independently reports 2 Fill events for the same scenario.

### Backtest deliberately untouched

`src/intraday/research/backtesting/engine.py`, `execution.py`, `portfolio.py`, `cost_model.py`,
`tradeplan_execution.py`, `position_lifecycle.py` were not read for modification and show zero new
diff this checkpoint (`git diff --stat -- src/intraday/research/backtesting/` isolates the SAME
3-file, 162-line diff already carried forward from before this checkpoint — `cost_model.py`,
`portfolio.py`, `risk_gate_adapter.py` — none of which changed size this session). No Backtest Fill
producer, no unified execution engine, no `ExecutionAdapter`/`FillBook`/`FillManager`/
`ExecutionLedger`/event store was created — mechanically confirmed by
`TestScopeDiscipline.test_no_fillbook_fillmanager_executionledger_introduced` in the new test file.
