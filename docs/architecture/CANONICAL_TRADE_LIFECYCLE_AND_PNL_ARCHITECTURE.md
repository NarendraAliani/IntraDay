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
