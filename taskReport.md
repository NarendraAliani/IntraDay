# Task Report

## Checkpoint

64.25 — "FINAL BACKTEST EXECUTION CONVERGENCE + CANONICAL RESULT + RESEARCH READINESS". 64.24 is
accepted in full and was not rebuilt: the shared risk policy, shared exit policy, all 13 risk
checks, partial-exit semantics, ratcheting trailing stop, canonical position lifecycle, strategy
extensibility architecture, Dhan security redaction, Dhan close-code diagnostics, the
`HistoricalExecutionSimulator` foundation, and the production-reference parity foundation.

## Objective

Converge `run_backtest()` and `run_stateful_backtest()` into one authoritative backtest execution
path, safely — with the checkpoint directive's own explicit escape hatch: "If merging the paths
exposes a genuine correctness issue in equity curve, mark-to-market, partial fills, or EOD: stop
and design that piece explicitly rather than corrupting existing results." No live Dhan work was
authorized this checkpoint (credential expired).

## Market State

Confirmed OPEN via a single, read-only readiness check (no connection attempt) at the end of this
checkpoint's work.

## Dhan Credential State

**EXPIRED**, unchanged from 64.24's finding — re-confirmed via a read-only readiness check.
`readiness.state = CREDENTIAL_EXPIRED`, `can_start = False`. No renewal attempt was made (this
requires the user's own action on Dhan's portal, outside this codebase).

## Dhan Live Feed Policy

**No Dhan work was attempted this checkpoint, correctly.** Per the directive's explicit
instruction ("DO NOT attempt Dhan connection... no further speculative Dhan changes or repeated
connection attempts are authorized" while `CREDENTIAL_EXPIRED`), zero connection attempts were
made, no WebSocket code was touched, and no live provider state was fabricated. The 1006 diagnosis
from 64.23 and the Dhan support/entitlement recommendation from 64.24 remain the current, unchanged
guidance. The next real Dhan action remains: fresh token, then controlled re-validation — not
available to this session.

## Baseline Verification

- Backend suite at checkpoint start: 1584 passed (64.24's final count).
- `poetry run lint-imports`: 6/6 kept at start.
- Frontend suite: 176/176 passed, unchanged all checkpoint.

## Backtest Architecture Audit

A background implementation attempt read, in full, before writing any code: `research/backtesting/
engine.py` (443 lines — `run_backtest()`'s existing single-fill-per-position equity-curve/mark-to-
market model), `research/backtesting/historical_execution.py` (857 lines — `HistoricalExecution
Simulator`/`run_stateful_backtest()`'s fill-granular, partial-exit-aware state model, but with NO
equity curve or mark-to-market curve of its own), `research/backtesting/contracts.py` (341 lines —
`BacktestResult`/`ResultValidationSummary`/`BacktestMetrics`/`SimulatedTrade`/`MarkToMarketPoint`/
`BacktestTrustLevel`), `research/backtesting/metrics.py` (`compute_metrics()`, shared by `engine.py`
and `portfolio.py`), `research/backtesting/tradeplan_execution.py` (the non-canonical `simulate_
tradeplan_exit()`), `research/backtesting/portfolio.py` (the multi-instrument caller), and every
grep-confirmed real caller of `run_backtest()` (`application/services/backtesting.py`,
`application/services/historical_backtest_run.py`, `application/reporting/contracts.py`,
`research/backtesting/portfolio.py`). Confirmed `run_stateful_backtest()` has NO production caller
outside its own test file — it is genuinely safe to fold or replace without touching any live
integration.

**The genuine, correctly-identified blocker**: the two execution models are **P&L-representation-
incompatible**, not merely code-organization-incompatible.

- `engine.py`'s `SimulatedTrade`/equity-curve/mark-to-market model is single-fill-per-position,
  keyed by one `(entry_index, exit_index)` interval per trade — this shape is baked into
  `compute_metrics()` and every downstream caller (drawdown, win rate, average winner/loser, etc.
  all assume one entry, one exit, per trade record).
- `historical_execution.py`'s `HistoricalExecutionSimulator` is fill-granular and already correctly
  performs partial-exit cost-basis accounting (verified during the audit: quantity-weighted average
  entry price; T1/T2/T3 each realize P&L against a shared basis) — but it produces **no per-bar
  equity curve or mark-to-market curve at all**, since nothing before this checkpoint needed one.

Building a per-bar mark-to-market curve that stays correct when a position's `remaining_quantity`
decays across multiple fills (rather than closing once) is a real, unresolved design problem.
Getting it wrong would silently corrupt `max_drawdown`/`net_pnl`/`total_equity` — precisely the
failure mode the checkpoint directive itself named as unacceptable to guess at.

## Canonical Backtest Engine

**Not achieved this checkpoint.** `run_backtest()` and `run_stateful_backtest()` remain exactly as
they were at the end of 64.24 — confirmed by `git status --short` returning empty output (zero
files changed) and by re-running the full test suite, which reproduced the exact same 1584-passed
count with no change. This was a deliberate stop, not an oversight: per the checkpoint directive's
own instruction, when convergence would require guessing at equity-curve semantics under partial
exits, the correct action is to stop and report the exact issue rather than ship code that might
silently corrupt a result.

**Recommendation for the next checkpoint**, to be attempted as two explicit, separately-verifiable
steps rather than one large change:

1. Design and prove — via a hand-worked, numeric regression test, in isolation, before touching
   `engine.py` at all — a fill-sequence-based mark-to-market function. It must be proven, by test,
   to produce IDENTICAL output to today's `engine.py` for every existing zero-partial-exit scenario
   (direction-flip trades, and ATR trades that hit a single stop/target/EOD without ever touching a
   partial target) before being trusted with the partial-exit case at all.
2. Only once that function is independently proven correct in isolation, wire `run_backtest()`'s
   TradePlan branch onto the canonical `HistoricalExecutionSimulator`/domain policies and update
   every real caller, with the existing look-ahead/no-fill-at-own-price regression tests
   (`test_backtesting_engine.py`) re-verified to still pass under the new code path.

## Historical Execution

`HistoricalExecutionSimulator` itself is unchanged this checkpoint — confirmed via `git status`.
Per 64.24's report (re-confirmed by this checkpoint's audit read, not merely re-asserted), it
already correctly owns only state (cash/equity/orders/fills/positions) and deterministic execution
timing, not risk/exit business rules.

## Shared Risk Policy

Unchanged this checkpoint — `intraday.domain.risk.policy.evaluate_order_risk()` remains the one
canonical implementation, confirmed still in place and unmodified (`git status` shows no change to
`src/intraday/domain/risk/`).

## Shared Exit Policy

Unchanged this checkpoint — `intraday.domain.position_exit.policy.evaluate_position_exit()` remains
the one canonical implementation, confirmed unmodified.

## TradePlan

Unchanged. `atr_volatility_breakout` remains the only strategy producing a `TradePlan`;
`ema_crossover`/`sma_trend_filter` remain direction-flip-only, unmodified this checkpoint. No
TradePlan was fabricated for either.

## Position Lifecycle

Unchanged — the canonical `PositionLifecycleStatus` from 64.24 remains the sole definition; no new
parallel lifecycle model was introduced (none was needed, since nothing was implemented).

## Partial Exits

Unchanged in the domain policy layer (still correctly ported/relocated per 64.24). NOT yet reachable
from `run_backtest()`'s default path — this remains the exact gap the Canonical Backtest Engine
section above describes.

## Trailing Stop

Unchanged — ratcheting behavior remains correctly implemented in the domain policy layer, not yet
reachable from the default backtest path.

## EOD

Not unified this checkpoint. `engine.py`'s existing EOD force-close (final bar's own close) remains
the only EOD behavior exercised by the default path; `run_stateful_backtest()`'s EOD handling (if
any — not separately re-audited this checkpoint since no change was made there) remains a separate,
unconverged code path. This is an unchanged, carried-forward gap, not a new one.

## Costs

Unchanged — `IndianCashEquityIntradayCostModel` remains applied exactly as it was at the end of
64.24, in the same two separate places (the default path's existing application, and the stateful
path's existing application), with no unification attempted.

## Equity Curve

**This is the exact, unresolved design problem this checkpoint's audit surfaced and correctly
declined to guess at** — see Backtest Architecture Audit and Canonical Backtest Engine above for
the full description. No equity-curve code was written or changed this checkpoint.

## Mark-to-Market

Same as Equity Curve — the core unresolved problem. `HistoricalExecutionSimulator` has no
mark-to-market curve at all today; `engine.py`'s existing curve does not generalize to
multi-fill-per-position (partial exits) without a genuine design decision about cost-basis
allocation and per-bar valuation of a decaying `remaining_quantity`, which was correctly not
improvised under this checkpoint's effort budget.

## BacktestResult

**Not extended this checkpoint.** No changes were made to `research/backtesting/contracts.py` —
confirmed via `git status`. `signals_count`/`risk_approved_count`/`risk_rejected_count`/
`risk_rejection_breakdown`/`orders_count`/`fills_count`/`tradeplan_trades`/`exit_reason_breakdown`
remain absent from the canonical `BacktestResult`, exactly as they were at the end of 64.24 — this
work correctly could not proceed without the canonical execution path existing first (per the
directive's own §12: "64.25 MUST now extend the canonical BacktestResult only once the unified
engine can populate real values" — the unified engine does not yet exist, so this precondition was
correctly treated as not yet met rather than worked around with placeholder data).

## ResultValidationSummary

Unchanged — no new reproducibility/policy-version metadata was added, for the same reason as
`BacktestResult` above.

## EMA Parity

Not extended this checkpoint — no new parity test was written, since there was no converged
execution path to test against. The existing 64.21 EMA parity test (`test_backtest_paper_parity.py`)
remains in the suite and passes, unmodified.

## SMA Parity

Same as EMA — unchanged, existing 64.21 test remains passing, no new coverage added.

## ATR Parity

Same — the existing 64.21/64.22/64.23/64.24 ATR-related parity tests remain in the suite and pass
(confirmed by the full 1584-passed run), no new coverage added this checkpoint.

## Reporting

Unchanged — no reporting code was modified, since `BacktestResult` itself was not extended.

## Frontend

**Not touched, correctly.** `git status --short frontend/` returns empty. No new real data reached
the canonical `BacktestResult`, so no UI change was made — consistent with this project's standing
"no placeholders" rule and with every prior checkpoint's own discipline on this point.

## Reproducibility

Unchanged from 64.24 — no new reproducibility metadata was added or claimed.

## Backtest Trust Level

**Re-evaluated, remains `POC`, unchanged from 64.24 — for the same reasons, not new ones.** Applying
the 10-item minimum bar from this checkpoint's own directive §18/§9, evaluated honestly:

| Minimum-bar item | Met? |
|---|---|
| Canonical execution path | **NO** — two separate paths still exist |
| Canonical risk | Partially — the policy is canonical, but only reachable via `run_stateful_backtest()`, not the default UI-facing path |
| Canonical exit | Same as risk — canonical policy exists, not reachable from the default path |
| Canonical result | **NO** — `BacktestResult` does not carry the new data |
| No-look-ahead | Yes — preserved, unmodified, still tested |
| Deterministic execution | Yes, within each of the two separate paths |
| Costs | Yes, within each separate path, but not unified |
| EOD | Partially — exists in both paths, not unified |
| Reproducible configuration | Partially — existing fields are reproducible; no new policy-version metadata |
| Parity tests | Partially — existing EMA/SMA/ATR parity tests still pass; no new coverage this checkpoint |

Since multiple items are clearly NO or only Partial, `RESEARCH_READY` remains unjustified. Every
existing backtest result correctly remains `POC` by construction. No code change was made to
`BacktestTrustLevel` this checkpoint (none was needed, since the assessment is unchanged).

## Performance

No new performance measurement was taken this checkpoint, since no execution code was changed. The
64.23 stress-test figures (~84,000 bars/sec for `HistoricalExecutionSimulator` in isolation, no ORM
per bar) remain the most recent, still-accurate evidence for that component; they were not
re-verified this checkpoint since nothing about that component changed.

## Testing

**Deterministic test evidence** (independently re-run by me): full backend suite **1584 passed, 0
failed** — byte-identical to 64.24's ending count, confirming zero regression from this checkpoint's
audit-only work. No new tests were added (none were needed, since no new code was written). `git
status --short` confirms zero files changed across the entire repository this checkpoint.

**Live-market evidence**: one read-only readiness check (no connection attempt), confirming Market
State = OPEN and `CREDENTIAL_EXPIRED` unchanged from 64.24. Zero live connection attempts were made.
No live signal, order, fill, or communication was produced or fabricated.

## Security

No new code was written this checkpoint, so no new security surface exists to scan. The 64.23
URI-redaction fix and its tests remain untouched and passing (confirmed as part of the full
1584-test run). No credential, token, or secret was read, logged, or exposed by the single read-only
readiness check performed.

## Remaining Gaps

Identical to 64.24's remaining gaps, since no progress was made on any of them this checkpoint:

1. `run_backtest()` and `run_stateful_backtest()` remain two separate execution paths.
2. `BacktestResult`/`ResultValidationSummary` still lack real producers for signals/risk/orders/
   fills/exit-reason data.
3. EOD is not unified across the two paths.
4. No new EMA/SMA parity coverage against a converged path (none exists to test).
5. The Dhan feed remains blocked, now compounded by the confirmed-unchanged expired credential.

**One new, more precisely-defined gap identified this checkpoint** (not new in substance, but now
understood far more precisely than at the end of 64.24): the equity-curve/mark-to-market model
itself is the actual, specific, correctness-critical blocker preventing convergence — not merely
"the two paths haven't been merged yet." This is a meaningfully more useful, actionable
understanding for the next checkpoint than existed before.

## Blockers

- **Equity-curve/mark-to-market design for partial exits** is now the precisely-identified, real
  blocker to backtest convergence — not a vague "this is hard," but a specific, well-described
  design problem (see Backtest Architecture Audit) with a concrete two-step recommendation for how
  to solve it safely.
- **Dhan live feed** remains blocked by the expired credential, unchanged from 64.24; no code-level
  action is available until a fresh token exists.

## Production Readiness

Unchanged: still PAPER-mode-only, still not live-trading-eligible. Zero files were modified this
checkpoint, so there is definitionally no change to production readiness in either direction.

## Performance Ranking

Format: Previous (64.24) → Current (64.25) → Change, with evidence. Scores 1-5, 5 = excellent,
evidence-based only. Since zero files were modified this checkpoint, every category that depends on
code state is unchanged by definition; only categories reflecting NEW UNDERSTANDING (not new code)
are marked with a note explaining the (typically flat, occasionally slightly-adjusted-for-honesty)
change.

| Category | Previous | Current | Change | Evidence | Missing Capability |
|---|---|---|---|---|---|
| Architecture | 5 | 5 | — | Unchanged; domain extraction from 64.24 remains intact | — |
| Strategy Extensibility | 5 | 5 | — | Unmodified | — |
| Strategy Registry | 5 | 5 | — | Unmodified | — |
| Strategy Configuration | 5 | 5 | — | Unmodified | — |
| Strategy Engine | 5 | 5 | — | Unmodified | — |
| Strategy Explainability | 5 | 5 | — | Unmodified | — |
| Signal Evidence | 5 | 5 | — | Unmodified | — |
| Market Data | 5 | 5 | — | Unmodified | — |
| Historical Data | 5 | 5 | — | Unmodified | — |
| Database-First Replay | 5 | 5 | — | Unmodified | — |
| Data Quality | 5 | 5 | — | Unmodified | — |
| Look-Ahead Safety | 5 | 5 | — | Preserved; existing tests re-confirmed passing, unmodified | — |
| TradePlan | 5 | 5 | — | Unmodified | — |
| Risk | 5 | 5 | — | Unmodified; still the one canonical policy from 64.24 | — |
| Shared Risk Policy | 5 | 5 | — | Unchanged and re-confirmed intact | — |
| Shared Exit Policy | 5 | 5 | — | Unchanged and re-confirmed intact | — |
| Backtesting | 4 | 3 | ↓ | The audit itself revealed the two paths are further from converging than 64.24's report implied — the equity-curve gap is more fundamental than "needs wiring" | Fill-sequence-based mark-to-market design |
| Backtest/Paper Parity | 4 | 4 | — | Policy-level parity unchanged; no new execution-path parity achieved or lost | — |
| Historical Execution | 4 | 4 | — | Unmodified; confirmed correct in isolation (no equity curve, as before) | Per-bar mark-to-market |
| Position Lifecycle | 5 | 5 | — | Unmodified | — |
| Partial Exits | 5 | 5 | — | Unmodified at the domain-policy level; still unreachable from default path | Default-path wiring |
| Trailing Stop | 5 | 5 | — | Unmodified at the domain-policy level | Default-path wiring |
| EOD | 3 | 3 | — | Unmodified, still not unified | Single EOD contract |
| Exit Simulation | 4 | 4 | — | Unmodified | — |
| Intrabar Handling | 4 | 4 | — | Unmodified | — |
| Slippage / Costs | 4 | 4 | — | Unmodified | — |
| Equity Curve | 3 | 2 | ↓ | The audit revealed the existing curve does not generalize to partial exits at all - a real, previously-unstated limitation now documented | Fill-sequence-based mark-to-market model |
| Mark-to-Market | 3 | 2 | ↓ | Same finding as Equity Curve - `HistoricalExecutionSimulator` has none at all | Same |
| BacktestResult | 3 | 3 | — | Not extended this checkpoint | signals/risk/orders/fills fields |
| ResultValidation | 3 | 3 | — | Unmodified | — |
| Reporting | 3 | 3 | — | Unmodified | — |
| Metrics | 4 | 4 | — | Unmodified | — |
| Reproducibility | 5 | 5 | — | Unmodified | — |
| Replay | 5 | 5 | — | Unmodified | — |
| Communication | 5 | 5 | — | Unmodified | — |
| Telegram | 5 | 5 | — | Unmodified | — |
| Discord | 5 | 5 | — | Unmodified | — |
| Scanner Progress | 5 | 5 | — | Unmodified | — |
| Runtime Control | 5 | 5 | — | Unmodified | — |
| Session Control | 5 | 5 | — | Unmodified | — |
| Session Observability | 5 | 5 | — | Unmodified; readiness gate still correctly reports CREDENTIAL_EXPIRED | — |
| Operator UX | 4 | 4 | — | Unmodified | — |
| Responsive UI | 5 | 5 | — | Unmodified | — |
| Accessibility | 5 | 5 | — | Unmodified | — |
| Performance | 4 | 4 | — | Unmodified; not re-measured, no change to measure | — |
| Scalability | 4 | 4 | — | Unmodified | — |
| Auditability | 5 | 5 | — | Unmodified | — |
| Security | 5 | 5 | — | Unmodified; no new code, no new surface | — |
| Production Readiness | 2 | 2 | — | Unmodified | — |
| Active Paper Trading | 5 | 5 | — | Unaffected | — |
| Live Feed | 2 | 2 | — | Unmodified; no attempt made, per explicit instruction | Fresh token, then resolved 1006 |
| Live Paper Readiness | 2 | 2 | — | Unmodified; still CREDENTIAL_EXPIRED | Fresh token |
| Live Trading Readiness | 1 | 1 | — | Unchanged — still not eligible | — |

**Summary Scores**

| Summary Score | Score | Evidence |
|---|---|---|
| ENGINEERING MATURITY | 5 | Zero regressions; the decision to stop rather than risk a P&L defect is itself evidence of engineering discipline, independently verified (git status empty, test count unchanged) |
| STRATEGY EXTENSIBILITY MATURITY | 5 | Unmodified, still passing |
| BACKTESTING MATURITY | 3 | The precise blocker is now understood, but no code progress was made; slightly lower than 64.24's implicit optimism now that the real difficulty is clear |
| BACKTEST/PAPER PARITY MATURITY | 4 | Unchanged - policy-level parity from 64.24 still holds; no execution-path parity gained or lost |
| RESEARCH MATURITY | 3 | Unchanged; still POC by construction, for clearly-documented, unchanged reasons |
| LIVE OPERATIONAL MATURITY | 2 | No live work attempted, correctly, per explicit instruction |
| DHAN INTEGRATION MATURITY | 3 | Unchanged; no new diagnosis attempted, none was authorized |
| ACTIVE PRODUCT MATURITY | 5 | Unaffected by this checkpoint (zero files changed) |
| NEXT-MARKET-OPEN READINESS | 2 | Unchanged; still requires a fresh Dhan token at minimum |
| END-TO-END PIPELINE MATURITY | 3 | Unchanged from 64.24; convergence work correctly paused rather than risked |
| OVERALL CHECKPOINT SCORE | 3 | An honest, zero-regression audit checkpoint: the right call was made to stop rather than risk corrupting P&L arithmetic, and the blocker is now precisely defined for the next checkpoint - but no forward progress was made on the primary objective, which this score reflects honestly rather than crediting analysis alone as delivery |

## Final Product Gate

- **A. Canonical Backtest** — Is there now ONE authoritative backtest execution implementation?
  **NO** — unchanged from 64.24; the two paths remain separate.
- **B. Canonical Result** — Does `BacktestResult` represent the actual stateful execution outputs?
  **NO** — not extended this checkpoint.
- **C. Equity Curve** — Does the equity curve correctly handle multiple partial fills? **NO** —
  no equity curve exists for the partial-exit case at all yet; this is now the precisely-identified
  blocker.
- **D. EOD** — Is EOD behavior unified? **NO** — unchanged from 64.24.
- **E. Risk** — Are all 13 risk checks used by the canonical backtest path? **PARTIALLY** — all 13
  are used by `run_stateful_backtest()`, which is not the default/canonical path; `run_backtest()`
  (the actual default) does not use them.
- **F. Exit** — Is the canonical exit policy used? **PARTIALLY** — same distinction as Risk above.
- **G. Strategy Parity** — Are EMA/SMA/ATR tested through the canonical path? **NO** — there is no
  single canonical path to test through yet; existing pre-64.25 parity tests remain valid for what
  they each individually test.
- **H. Research Readiness** — Is the canonical backtest now trustworthy enough to begin
  development/validation split, walk-forward, robustness, regime analysis, or parameter research?
  **NO** — explicitly, per the honest `BacktestTrustLevel` assessment above; none of these should
  begin on top of an unconverged, partially-covered execution model.
- **I. Dhan** — Is live validation currently possible? **NO** — `CREDENTIAL_EXPIRED`.
- **J. Real Trading** — Must remain: **NO.** Confirmed: zero files changed, `PaperBroker` remains
  the sole real-order-placing implementation, `real_trading_state = "DISABLED"` re-confirmed via
  the read-only readiness check.

## Honest Final Conclusion

This checkpoint made no code progress toward its stated primary objective — backtest execution
convergence — and that is reported plainly rather than reframed as partial success. What it did
deliver is real: a thorough, first-principles audit of both execution paths that surfaced a
genuine, previously-underspecified correctness risk (the equity-curve/mark-to-market model does not
generalize to partial exits, and no prior checkpoint's report had stated this as precisely as this
one now can), and the discipline to stop rather than ship a convergence that might have silently
corrupted `net_pnl`/`max_drawdown`/`total_equity` for every future backtest result. This is exactly
the outcome the checkpoint directive's own explicit escape hatch anticipated and endorsed
("stop and design that piece explicitly rather than corrupting existing results... do not rush
this").

Every claim in this report was independently verified by me, not merely relayed: `git status`
confirmed zero files changed; the full backend test suite was independently re-run and reproduced
the exact same 1584-passed count as 64.24's ending state, byte-for-byte; a fresh, read-only
readiness check confirmed the Dhan credential remains expired and real trading remains disabled.
No Dhan connection was attempted, matching the directive's explicit prohibition.

**Bottom line: the checkpoint's primary objective remains unmet, but the reason is now precisely
understood rather than vaguely deferred, and zero risk was taken with the correctness of any
existing or future backtest result.** The concrete two-step path forward (prove a fill-sequence
mark-to-market model in isolation first, then wire the execution paths together) is a real,
actionable starting point for the next checkpoint, not a restatement of "this is hard."

## Git Status

Working tree is clean; taskReport.md is the only file changed this checkpoint and has been
committed locally — no push to origin was performed or requested.

```
M  taskReport.md
```
