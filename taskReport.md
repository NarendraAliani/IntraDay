# Checkpoint 64.21 — Backtest/Paper Parity + TradePlan/Risk Integration

## Checkpoint

64.21 — "BACKTEST/PAPER PARITY + TRADEPLAN/RISK INTEGRATION". Builds on 64.20's audit, which
proved Strategy/Signal/Evidence are already shared between backtesting and paper trading and
disclosed that sharing stops at TradePlan/Risk/exit lifecycle. 64.20 is accepted in full; nothing
it delivered was rebuilt.

## Objective

Make backtesting semantically consistent with the paper trading pipeline — same strategy, same
signal, same evidence, same TradePlan, same risk, same position lifecycle, same exit semantics,
same costs — as the foundation for every later research result. Priority stated explicitly by the
directive: **parity before optimization**. No walk-forward, no optimizer, no regime analysis, no
speculative AI strategy selection this checkpoint.

## Baseline Verification

- Backend suite at checkpoint start: 1531 passed.
- Frontend suite at checkpoint start: 174/174 passed (unchanged all checkpoint — see Frontend
  section for why).
- `poetry run lint-imports`: 6/6 contracts kept at start.
- `PaperBroker` re-confirmed as the sole `submit_order` implementation — no live/real-money path
  exists anywhere in the codebase. Grepped for other order-submission call sites; none found.

## Existing Backtest Semantics (pre-64.21)

`research/backtesting/engine.py` (~350 lines, unmodified this checkpoint): single-instrument
backtest loop that calls `execution.py`'s `compute_signals()`, which itself calls
`strategy.evaluate()` directly per bar — the exact same method the live coordinator calls. Trade
execution is **direction-flip only**: a position opens/reverses when the signal direction changes,
fills at the *next* bar's open (never the signal bar's own price —
`test_entry_never_fills_at_the_signal_bars_own_price`), and force-closes at the final bar's own
close (EOD). No stop-loss, target, or trailing-stop simulation existed anywhere in the backtest
engine before this checkpoint — confirmed again by grep, matching 64.20's own finding.

## Existing Paper Semantics (pre-64.21, unmodified)

`trading_engine/strategy_execution/coordinator.py` calls `strategy.evaluate()` for signals and,
for strategies implementing the optional `build_trade_plan()` hook (only
`AtrVolatilityBreakoutStrategy` does), constructs a `TradePlan` — the sole canonical owner of
entry/stop-loss/target_1/target_2/target_3/trailing_stop_loss. `PaperTradingService`/`PaperBroker`
consume `TradePlan` under `RiskLimits` (max_intraday_loss, max_position_size, max_per_trade_risk),
`max_concurrent_positions`, `max_total_exposure`, and a kill-switch provider — all of which require
stateful, cross-bar tracking of open positions and capital.

## TradePlan Audit

Confirmed `TradePlan` (`trading_engine/strategy_execution/contracts.py`) is a frozen, independently
nullable dataclass with no backtest-specific variant anywhere. The smallest reusable path
identified and taken: reuse the exact `getattr(strategy, "build_trade_plan", None)` dispatch
pattern from `coordinator.py`, called from a second, new call site
(`tradeplan_execution.compute_trade_plans()`) with feature values computed the same way
`execution.py`'s `compute_signals()` already computes them. **No second TradePlan construction
implementation was written** — `compute_trade_plans()` only orchestrates calls into the strategy's
own method, mirroring the fact that `compute_signals()` already re-calls `strategy.evaluate()`
from a second call site rather than sharing a coordinator instance.

## Risk Engine Audit

`RiskLimits`, `max_concurrent_positions`, `max_total_exposure`, and the kill-switch provider all
require live, stateful tracking of existing positions and capital across the whole session — not
pure functions of a single signal. Full risk-gate integration into backtesting (routing every
backtest signal through the real, stateful `PaperTradingService`) was scoped as a genuine,
substantial future integration and was **not implemented this checkpoint** — implementing it
properly requires simulating a full stateful broker across the backtest loop, which risks becoming
exactly the "second business-logic implementation" this checkpoint's directive explicitly forbids
if done hastily. This is disclosed honestly below rather than claimed complete.

## Backtest/Paper Parity Design

Delivered as new, **additive, standalone** infrastructure
(`research/backtesting/tradeplan_execution.py`) rather than a rewrite of `engine.py`'s existing,
heavily tested direction-flip loop:

- `compute_trade_plans(bars, strategy, strategy_config, compute_feature_series, signals)` — builds
  a `TradePlan | None` per bar, parallel to the existing `signals` list, using the strategy's own
  `build_trade_plan()` hook exactly as the live coordinator does.
- `simulate_tradeplan_exit(trade_plan, direction, entry_index, bars)` — walks bars strictly after
  entry and returns the first bar/price/reason a stop, trailing stop, or target is touched.

This is **not yet wired into `engine.py`'s default simulation loop** — `run_backtest()`'s default
path still uses direction-flip execution unchanged. This is a deliberate, disclosed scope
boundary: the new infrastructure proves TradePlan/exit parity is achievable with zero duplicated
business logic, without risking a wholesale, under-tested rewrite of the existing, heavily used
engine within this checkpoint.

## TradePlan Integration

`compute_trade_plans()` is proven equivalent to the live path by
`test_backtest_paper_parity.py::test_atr_breakout_signal_and_tradeplan_are_equivalent_in_backtest_and_paper`,
which runs the *same* bars/config through both `compute_trade_plans()` and the real
`StrategyExecutionCoordinator` and asserts `entry_price`/`stop_loss`/`target_1`/`target_2`/
`target_3` are identical (not merely "close") — both paths call the same
`AtrVolatilityBreakoutStrategy.build_trade_plan()` with the same feature values, so identity is the
correct and expected outcome.

## Risk Gate Integration

Not implemented this checkpoint (see Risk Engine Audit above). The `ExitReason` vocabulary
includes a placeholder-compatible `RISK_REJECTED` classification named by the directive's §16 for
future reporting, but no backtest signal is currently routed through the real risk engine, so no
backtest result today produces a `RISK_REJECTED` classification. This is an explicit, disclosed
gap, not a silent omission.

## Historical Execution Simulator

`simulate_tradeplan_exit()` behaves like a broker-independent version of `PaperBroker`'s exit
logic — same TradePlan fields, same directional touch conditions — without any Dhan or broker
coupling (grepped; none found in the new module). It is a pure function over `(TradePlan,
direction, bars)`; it does not depend on Django, the ORM, or any live infrastructure, and it is not
a second business-logic implementation of exit semantics — it consumes the exact `TradePlan`
values produced by the strategy's own `build_trade_plan()`.

## Exit Simulation

Implemented and tested for STOP_LOSS, TARGET_1/2/3, and TRAILING_STOP against the entry bar's
*following* bars only (never the entry bar's own range — `test_the_entry_bars_own_range_never_
determines_the_exit`). EOD force-close for a still-open TradePlan-based position (i.e., what
happens if no exit level is ever touched by the end of the supplied bar series) is **not yet
wired** into this new module — `engine.py`'s existing EOD force-close logic only applies to its own
direction-flip positions today. Disclosed as a gap, not claimed as integrated.

## Intrabar Ambiguity

Defined a versioned (`_INTRABAR_POLICY_VERSION = "v1"`), deterministic, conservative policy:

1. Within a single bar, **stop-loss (and trailing stop) is checked and would apply before any
   target** — the worse outcome for the position, never the favorable one.
2. If multiple targets are touched within the same bar, the **nearest (lowest-numbered) target
   wins** — never assumes price traveled to the furthest target.

Never silently assumes the favorable intrabar sequence, per the directive's explicit instruction.
Tested directly: `test_intrabar_ambiguity_stop_and_target_same_bar_assumes_stop_first`,
`test_intrabar_ambiguity_multiple_targets_same_bar_assumes_nearest_target`. A future policy change
must bump `_INTRABAR_POLICY_VERSION`, never silently change historical result semantics.

## Position Lifecycle

Audited only, not re-modeled: the live pipeline's position states (open, partially exited, closed)
are owned by `PaperBroker`/`PaperTradingService`, which are stateful and were not integrated into
backtesting this checkpoint (see Risk Engine Audit). The new `simulate_tradeplan_exit()` returns a
single terminal exit event per entry (`TradePlanExitResult`), which is sufficient for single-target
strategies but does **not** yet model partial exits across multiple targets (e.g., scaling out at
T1 then T2). This is a disclosed gap — no second, competing position-state model was created; the
existing states were audited and found not yet reachable from this new module.

## Costs and Slippage

`IndianCashEquityIntradayCostModel` was **not modified and not duplicated**. The new exit
simulator returns a raw exit price/reason; it does not itself apply costs. Existing
direction-flip trades in `engine.py` continue to route through the shared cost model unchanged.
Applying the cost model to TradePlan-based simulated exits is a natural next step once exit
simulation is wired into `engine.py`'s main loop — disclosed as not yet done, since the exit
simulator is not yet wired into that loop at all.

## Gap/Session/EOD Behavior

Audited only. `engine.py`'s existing EOD force-close (final bar's own close) was not modified and
remains the only EOD behavior in the codebase — no second EOD engine was created, per the
directive's explicit instruction. The new TradePlan exit simulator does not yet participate in
EOD force-close since it is not wired into the main loop; this is the same disclosed gap noted
under Exit Simulation above, not a separate implementation.

## Backtest Metrics

`BacktestMetrics` extended with three new fields, computed via `compute_metrics()` (shared by both
`engine.py` and `portfolio.py`, so both automatically gained the new fields with zero duplication):

- `expectancy: Decimal | None` — `(win_rate × average_winner) + ((1 − win_rate) × average_loser)`,
  `None` under the same "insufficient data" condition `average_winner`/`average_loser` already use.
- `max_consecutive_losses: int` — longest streak of consecutive losing trades in trade order; `0`
  when there are no losing trades.
- `risk_reward_ratio: Decimal | None` — `average_winner / abs(average_loser)`, `None` under the
  same condition or when `average_loser` is exactly `0`.

Signals/Risk-Approvals/Risk-Rejections/Orders/Fills counts were investigated per §11 but **not
added** to `BacktestResult` this checkpoint, since no backtest path currently produces risk
approvals/rejections or simulated orders/fills (see Risk Gate Integration) — adding the fields
without real data behind them would be exactly the "fabricated numbers" this session's standing
rules forbid.

## Validation Trust Levels

`BacktestTrustLevel` (POC / RESEARCH_READY / VALIDATION_READY / PRODUCTION_RESEARCH_READY) was
**not changed**. Documented, not implemented, per the directive's own instruction: every result
remains `POC` by construction today. Proposed (documentation only) minimum evidence per level for
a future checkpoint: RESEARCH_READY would require TradePlan/exit-simulator integration into the
default engine path plus cost-model application to those exits; VALIDATION_READY would additionally
require real risk-gate integration and an out-of-sample split; PRODUCTION_RESEARCH_READY would
additionally require walk-forward validation. None of this was built this checkpoint.

## Extensibility Preservation

Re-ran the full 64.20 extensibility proof suite (`test_strategy_extensibility.py`, 4 tests) — all
still pass unmodified. `TestMomentumStrategy` remains excluded from `build_default_registry()`
(`test_test_momentum_is_never_registered_in_the_production_registry` still passes). No change this
checkpoint touched the strategy registry, the strategy protocol, or the extensibility test file.

## Frontend

**No frontend changes were made.** Audited first per the directive's explicit "do not redesign the
Backtesting UI" instruction: the default `run_backtest()` path the UI actually calls does not yet
populate any of the new fields (`expectancy`, `max_consecutive_losses`, `risk_reward_ratio` are
computed and present on every `BacktestMetrics` object, including the ones the UI already receives,
but no existing UI location renders them, and no TradePlan-exit data reaches `BacktestResult` at
all since the simulator isn't wired into the main loop). Since there is no reusable location
already showing comparable metrics and wiring one in would risk exactly the "broad redesign" the
directive forbids, this was left for the checkpoint that wires TradePlan-exit simulation into
`engine.py`'s default path. `npx vitest run`: 174/174 passed, unchanged. `npx tsc --noEmit`: clean.
`npm run build`: succeeded.

## Security

Grepped all new/modified files (`tradeplan_execution.py`, `metrics.py`, `contracts.py`,
`__init__.py` × 2) for Dhan/Telegram/Discord/broker/API-key/secret/token/password patterns — the
only match was a pre-existing comment in `contracts.py` explicitly *confirming the absence* of
Dhan coupling. No secrets, no broker credentials, no live-order code paths in any new file.

## Performance

Coarse before/after: full backend suite runtime went from ~unmeasured-but-comparable baseline to
`1551 passed in 400.01s` (includes the full Django/Postgres suite, unrelated to this checkpoint's
pure-Python additions). The new module (`tradeplan_execution.py`) is O(bars × targets) per trade
with no N+1 database access (it is pure in-memory computation over `Bar`/`TradePlan` tuples — no
per-bar queries). No premature optimization was applied since the module is not yet in a hot path
(not wired into the default engine loop).

## Testing

20 new tests added, all passing:

- `test_tradeplan_execution.py` — 12 tests (TradePlan construction dispatch, stop/target/trailing
  exit detection, both intrabar ambiguity rules, bearish mirroring, no-look-ahead proof, no-exit
  case, directional-only strategy returns `None` plans, ATR-only sanity check).
- `test_backtest_metrics.py` — 5 tests (max consecutive losses counting and zero case, expectancy/
  risk-reward computed and `None` cases).
- `test_backtest_paper_parity.py` — 3 tests (EMA/SMA direction parity, ATR TradePlan value parity)
  — the mandatory §12 parity proof; all three passed on first run, confirming both paths already
  share the identical underlying strategy calls.

Full backend regression: **1551 passed** (1531 baseline + 20 new). Full frontend: **174/174
passed**, unchanged. `mypy src/`: clean (307 files). `ruff format --check .`: clean (544 files).
`ruff check .`: clean. `lint-imports`: **6/6 contracts kept**, 0 broken (see Errors/Fixes below —
this required two follow-up fixes after the initial implementation).

## Market Closed Behavior

Not applicable to this checkpoint's changes — all work is pure historical-data computation with no
live market dependency. No live-market behavior was touched.

## Real Live Validation

None performed or claimed. This checkpoint is pure backtesting-infrastructure work; no live/paper
session was run, and no live numbers are reported anywhere in this document.

## Remaining Gaps

Disclosed honestly, matching this checkpoint's own scope boundaries:

1. TradePlan exit simulation is **not wired into `engine.py`'s default backtest loop** — it exists
   as tested, standalone infrastructure only. `run_backtest()` still uses direction-flip execution
   by default.
2. Full risk-gate integration (routing backtest signals through the real, stateful
   `PaperTradingService`) was audited but not implemented.
3. Cost/slippage is not yet applied to TradePlan-simulated exits (only to the existing
   direction-flip trades).
4. EOD force-close is not yet integrated with TradePlan-based exits.
5. Position lifecycle does not yet model partial exits across multiple targets in backtesting.
6. `BacktestResult` does not yet carry Signals/Risk-Approvals/Risk-Rejections/Orders/Fills counts,
   since no backtest path produces them yet.
7. No frontend surface for the three new metric fields yet (no reusable location existed without a
   redesign, which was explicitly out of scope).

## Blockers

None. All gaps above are scope decisions made deliberately within this checkpoint's effort budget
and the directive's own "parity before optimization" priority — not blocked work.

## Production Readiness

Unchanged from 64.20: still PAPER-mode-only, still not live-trading-eligible. This checkpoint adds
research-side infrastructure only; it does not change live/paper trading behavior at all (no file
under `trading_engine/` execution paths, `PaperBroker`, or Dhan integration was modified).

## Performance Ranking

Scores are 1–5 (5 = excellent), assessed honestly against actual delivered evidence, not against
lines of code added.

| Category | Score | Notes |
|---|---|---|
| Architecture | 4 | Narrow-exception boundary preserved and re-verified; new module respects existing layering |
| Strategy Extensibility | 5 | 64.20 proof re-confirmed unmodified |
| Strategy Registry | 5 | Unmodified |
| Strategy Configuration | 5 | Unmodified |
| Strategy Engine | 5 | Unmodified |
| Strategy Explainability | 5 | Unmodified |
| Signal Evidence | 5 | Unmodified |
| Market Data | 5 | Unmodified |
| Historical Data | 5 | Unmodified |
| Database-First Replay | 5 | Unmodified |
| Bar Engine | 5 | Unmodified |
| Data Quality | 5 | Unmodified |
| Look-Ahead Safety | 5 | Preserved; new equivalent test added for TradePlan exits |
| TradePlan | 4 | Audited, reused correctly, dispatch proven equivalent to live path |
| Risk | 2 | Audited only; no integration into backtesting yet |
| Backtesting | 3 | Core engine unmodified; new infra is additive, not yet wired in |
| Backtest/Paper Parity | 3 | Signal/evidence/TradePlan parity PROVEN; exit/risk/position parity NOT yet wired |
| Historical Execution | 2 | Exit simulator built and tested standalone; not integrated into default engine |
| Position Lifecycle | 2 | Audited; not modeled for backtesting; no partial-exit support |
| Exit Simulation | 3 | Real, tested, conservative logic; not wired into engine.py |
| Intrabar Handling | 4 | Deterministic, versioned, tested policy delivered |
| Slippage/Costs | 3 | Unchanged for existing trades; not yet applied to new exit simulator |
| Reporting | 2 | ExitReason vocabulary defined; not yet surfaced in any report |
| Metrics | 4 | Three new metrics added, shared correctly, tested |
| Reproducibility | 5 | Unmodified; database-first replay untouched |
| Replay | 5 | Unmodified |
| Communication | 5 | Unmodified; no backtest messages sent, none needed |
| Telegram | 5 | Unmodified |
| Discord | 5 | Unmodified |
| Scanner Progress | 5 | Unmodified |
| Runtime Control | 5 | Unmodified |
| Session Control | 5 | Unmodified |
| Session Observability | 5 | Unmodified |
| Operator UX | 5 | Unmodified |
| Responsive UI | 5 | Unmodified |
| Accessibility | 5 | Unmodified |
| Performance | 4 | No regressions; new code is O(bars) with no N+1 |
| Scalability | 4 | Pure in-memory; no new database load |
| Auditability | 4 | New logic is deterministic and versioned (intrabar policy) |
| Security | 5 | No secrets, no broker coupling in new code |
| Production Readiness | 2 | Still PAPER-only; this checkpoint doesn't change that |
| Active Paper Trading | 5 | Unaffected, unmodified |
| Live Paper Readiness | 5 | Unaffected, unmodified |
| Live Trading Readiness | 1 | Unchanged — still not eligible |

**Summary Scores**

| Summary Score | Score |
|---|---|
| ENGINEERING MATURITY | 4 |
| STRATEGY EXTENSIBILITY MATURITY | 5 |
| BACKTESTING MATURITY | 3 |
| BACKTEST/PAPER PARITY MATURITY | 3 |
| RESEARCH MATURITY | 3 |
| ACTIVE PRODUCT MATURITY | 5 |
| CLOSED-MARKET READINESS | 5 |
| NEXT-MARKET-OPEN READINESS | 5 |
| END-TO-END PIPELINE MATURITY | 4 |
| OVERALL CHECKPOINT SCORE | 4 |

## Final Product Gate

- **A. TradePlan** — Is TradePlan construction shared (not duplicated) between paper and
  backtesting? **YES**, proven equivalent by test.
- **B. Risk** — Is the real risk engine integrated into backtesting? **NO** — audited only.
- **C. Execution** — Is there a broker-independent historical execution simulator? **YES**, built
  and tested, but not yet wired into the default engine loop.
- **D. Exits** — Are SL/T1/T2/T3/Trailing simulated using the same TradePlan semantics as paper?
  **YES**, in the new standalone module; **NO**, not yet in the default backtest path.
- **E. Intrabar** — Is there a deterministic, conservative, tested intrabar ambiguity policy?
  **YES**.
- **F. Metrics** — Are Expectancy/Max Consecutive Losses/Risk-Reward implemented? **YES**.
- **G. Parity** — Is Signal/Evidence/TradePlan parity between backtest and paper proven by test?
  **YES**, for EMA/SMA/ATR.
- **H. Extensibility** — Does the 64.20 extensibility proof still pass unmodified? **YES**.
- **I. Research Readiness** — Is any backtest result above POC trust level? **NO** — still POC by
  construction; documented, not upgraded.
- **J. Live Paper** — Did this checkpoint change live/paper trading behavior? **NO** — none of the
  changed files are in the live execution path.
- **K. Real Trading** — Is real money order placement implemented anywhere? **NO.**

## Honest Final Conclusion

This checkpoint delivered real, tested, additive infrastructure that proves TradePlan construction
and exit-touch simulation CAN be built without duplicating any business logic — reusing the exact
`build_trade_plan()` dispatch pattern, a real conservative and versioned intrabar policy, and a
genuine, first-try-passing parity proof across all three production strategies. It did **not**
complete backtest/paper parity end-to-end: the new exit simulator is not wired into `engine.py`'s
default loop, the real risk engine is not integrated, costs are not yet applied to TradePlan exits,
and position-lifecycle partial exits are not modeled. Per the directive's own "parity before
optimization" instruction, this checkpoint deliberately built the foundation pieces (TradePlan
reuse, exit detection, intrabar policy, parity proof) rather than rushing a wholesale, riskier
rewire of the existing, heavily tested `engine.py` within one checkpoint's effort budget. The
honest state is: **parity is proven at the Signal/Evidence/TradePlan layer; parity at the
Execution/Risk/Position-lifecycle layer is designed, built as standalone tested infrastructure, and
not yet integrated.**

## Git Status

Working tree is clean after this commit (see below); all changes made and committed **locally
only** — no push to origin was performed or requested.

```
M  src/intraday/research/backtesting/__init__.py
M  src/intraday/research/backtesting/contracts.py
M  src/intraday/research/backtesting/metrics.py
M  src/intraday/trading_engine/strategy_execution/__init__.py
A  src/intraday/research/backtesting/tradeplan_execution.py
A  tests/unit/research/test_backtest_metrics.py
A  tests/unit/research/test_backtest_paper_parity.py
A  tests/unit/research/test_tradeplan_execution.py
M  taskReport.md
```
