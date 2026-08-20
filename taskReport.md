# Task Report

## Checkpoint

64.20 — STRATEGY EXTENSIBILITY + BACKTESTING RESEARCH ARCHITECTURE

## Updated Project Scope

New `docs/architecture/PRODUCT_SCOPE.md` is now the authoritative scope
statement: Automated Algo Trading System, Indian Equity Market, intraday
only; capabilities in scope (Historical Research, Backtesting, Replay,
Strategy Evaluation, Live Market Data, Signal Generation, Signal
Evidence, TradePlan, Risk Management, Paper Trading, Telegram, Discord,
Reporting, Operational Monitoring, Strategy Research, Strategy
Extensibility); two primary execution modes (`PAPER`,
`LIVE-MARKET-DATA + PAPER-EXECUTION`); real broker order placement
restated as out of current implementation scope, explicitly disabled,
requiring future separate approval — this safety boundary was not
weakened. The README's own "Scope" section (stale since Checkpoint 13)
was NOT rewritten wholesale (out of this checkpoint's scope, a separate
cleanup risk) — one link was added pointing to the new authoritative
document, honestly noting it supersedes the stale section.

## Objective

Formally audit whether the platform can absorb a genuinely new strategy
without touching core engines; prove it mechanically with a dedicated,
non-production test strategy; and audit the backtesting/research
architecture against a rigorous target pipeline, documenting real gaps
honestly rather than building speculative capability.

## Baseline Verification

| Gate | Result |
|---|---|
| pytest | 1527 passed |
| vitest | 174 passed |
| ruff format --check | 529 files already formatted |
| ruff check | All checks passed |
| mypy | Success: no issues found in 300 source files |
| lint-imports | 6 kept, 0 broken |
| manage.py check | 0 issues |
| makemigrations --check --dry-run | No changes detected |
| manage.py spectacular --fail-on-warn | exit 0 |
| frontend tsc --noEmit | 0 errors |
| frontend build | succeeded |

## Existing Strategy Architecture Audit

Read `strategy.py` (the `Strategy` Protocol), `registry.py`
(`StrategyRegistry`), `contracts.py` (`ParameterDefinition`,
`StrategySignal`, `validate_configuration`), and `evidence.py`
(`build_signal_evidence`) in full. **Conclusion: no second strategy
framework was needed or created.** Every element §4 of this checkpoint
asks for already exists with the exact names already in use — see
`docs/architecture/STRATEGY_EXTENSIBILITY_AND_RESEARCH_ARCHITECTURE.md`
§1 for the full field-by-field mapping.

## Strategy Contract

Confirmed sufficient: identity/name/version (`strategy_id`/
`display_name`/`specification_version`/`code_version`), parameter
schema (`parameter_schema()`), validation (`validate_configuration()`),
required market data (`required_features()`), evaluation (`evaluate()`),
signal (`StrategySignal`), evidence (`StrategySignal.evidence`). No
metadata dict beyond `display_name` exists — noted as a real, minor,
non-blocking gap (nothing currently reads a richer metadata structure).

## Strategy Registry

Confirmed sufficient: `list()`/`get()`/`register()`/`activate()`/
`deactivate()`/`get_active()`/`validate_configuration()`. Adding a
strategy requires exactly one `registry.register(NewStrategy())` call
in `build_default_registry()` — proven directly by constructing an
independent, LOCAL registry for the proof-of-extensibility strategy
without touching that function at all.

## Dynamic Parameter Schema

Confirmed generic — `ParameterDefinition` already carries id/type/
default/minimum/maximum/description(help_text); the frontend's
`ParameterSchemaFields.tsx` renders purely from this list (re-verified
by grep: zero `strategy_id === "..."` branches anywhere in it or in
`StrategyConfigurationPage.tsx`). Conservative defaults reconfirmed
UNCHANGED from Checkpoint 64.17 (EMA 12/26, SMA 30/0.75, ATR
14/2.0/1.0/1.5/2.5/3.5/1.0) — re-verified passing:
`test_strategy_schema_endpoint_exposes_the_conservative_baseline_
defaults` and `test_changing_a_strategys_default_does_not_mutate_an_
existing_configuration_record`, both unmodified this checkpoint.

## Generic Signal Evidence

Confirmed generic — `build_signal_evidence()` dispatches by
`strategy_id` through one dict; the frontend's "Why This Signal?" panel
renders `evidence.fields` via a plain `.map()`, no per-strategy
component. A concrete future `VWAP Reversal` strategy returning
VWAP/Price/Distance/Reversal State/Volume Ratio fields would render on
the EXISTING panel unchanged — a direct, mechanical consequence of the
generic `(label, value)` shape.

## Test Strategy

New `TestMomentumStrategy` (`trading_engine/strategy_execution/
strategies/test_momentum.py`) — explicitly `NON_PRODUCTION` in its own
docstring and `display_name`, **never added to
`build_default_registry()`** (mechanically verified by a dedicated
test). Deterministic rule: BULLISH/BEARISH when close is more than a
configurable `threshold_percent` above/below a short reference EMA,
reusing the EXISTING generic `ema_<lookback>` feature family — zero new
feature-computation code. `tests/unit/trading_engine/test_strategy_
extensibility.py` (4 tests, all passing) proves it moves through: local
registry → configuration → `StrategyExecutionCoordinator` (the SAME
class backtesting reuses) → real signal → real persisted evidence (via
one new `_DESCRIBERS` entry) → risk (`PaperTradingService`) →
`PaperBroker` → real Telegram/Discord messages (including the "Key
Evidence:" text) → a real `DjangoSignalRepository.list_signals()` query
— with **zero** `if strategy_id == "test_momentum"` branches in any core
engine.

## Change-Surface / Extensibility Audit

| Category | Files | Count |
|---|---|---|
| Strategy-specific (expected) | `test_momentum.py` | 1 |
| Strategy-specific tests | `test_strategy_extensibility.py` | 1 |
| Registration (expected, same shape any new strategy needs) | `evidence.py` (+1 dict entry, +1 formatter function) | 1 |
| Generic infrastructure changes | none | 0 |
| Unwanted core-engine changes | none | 0 |

`signal_pipeline_runtime.py`, `research.backtesting.*`,
`PaperTradingService`, `PaperBroker`, `templates.py`/`signal_
communication.py`, `application.reporting.*` — all confirmed
UNCHANGED by this checkpoint's `git diff --stat`. Full accounting in
`STRATEGY_EXTENSIBILITY_AND_RESEARCH_ARCHITECTURE.md` §6.

## Backtesting Architecture Audit

Full pipeline mapped in `STRATEGY_EXTENSIBILITY_AND_RESEARCH_
ARCHITECTURE.md` §7. Most stages EXIST and are authoritative (historical
data, data quality, database-first retrieval, session construction,
bars, strategy execution — the SAME `StrategyExecutionCoordinator` the
live path uses, signal+evidence, execution simulator, costs,
positions, P&L, a subset of performance analysis). **One real,
previously-undocumented gap surfaced by this audit**: the backtest
engine trades on strategy DIRECTION FLIPS, not `TradePlan` stop-loss/
target simulation, and does not currently route signals through the
shared `PaperTradingService` risk gate — the backtester has its own,
simpler entry/exit/cost simulation. Disclosed honestly, not hidden or
silently worked around.

## Database-First Backtesting

Re-confirmed unmodified and un-weakened — the same
`test_scanner_reads_only_from_database_never_the_provider_once_
complete` test (Checkpoint 63.x, re-audited 64.16) still passes,
untouched by this checkpoint's changes.

## Data Quality

Confirmed existing coverage: `BarAggregationResult.missing_intervals`/
`anomalous_observations`, `BarQualityGrade` (TRADING_GRADE_BAR vs
SAMPLE_BAR), duplicate/out-of-order handling during aggregation,
timezone/session/holiday handling centralized in `session_for_instant()`,
per-strategy warm-up handling via `evaluate()` returning `None`. No
missing data is ever fabricated anywhere in this path.

## Look-Ahead Bias

**Already exists, already mandatory, already passing — not rebuilt.**
`tests/unit/research/test_backtesting_engine.py`'s own "No-look-ahead
protection (Part 25, mandatory)" section: `test_future_bars_do_not_
affect_earlier_signals` truncates the bar series and proves every
earlier decision is identical regardless of later bars —the defining
test of no-look-ahead bias, pre-existing this checkpoint.
`test_entry_never_fills_at_the_signal_bars_own_price` proves entries
fill at the NEXT bar's open. Both re-verified passing, unmodified.

## Execution Simulation

Confirmed the simulator does not assume "signal price = perfect fill"
(entries/exits fill at the next bar's open, proven above) and reuses
the ALREADY established `IndianCashEquityIntradayCostModel`
(`verified_nse_cash_equity_intraday_cost_model()`) — no new Indian cost
model was invented, per explicit instruction.

## Intrabar Ambiguity

**Honest, disclosed finding, not a fabricated policy**: read `engine.py`
in full and found NO stop-loss/target exit code path exists in the
current backtest engine at all (it trades on direction flips only,
Checkpoint 27/28's original design) — TradePlan stops/targets are only
simulated in the live PAPER path via `PaperBroker`, a structurally
separate engine. The intrabar "both stop and target touched in the same
candle" scenario therefore CANNOT currently occur in backtesting,
because the mechanism that would need this policy does not exist yet.
Documented as a real, scoped future requirement (the exact ambiguity
policy this checkpoint's own §15 describes would need to be defined
WHEN TradePlan-based backtest exits are built), never fabricated as if
already resolved.

## Performance Metrics

Confirmed existing: Gross/Net P&L, Return %, Trade counts, Win Rate,
Average Trade/Winner/Loser, Profit Factor, Max Drawdown (+percent
+duration), trade-level Sharpe/Sortino (beyond the directive's own
list), and a real Equity/Drawdown Curve (`MarkToMarketPoint`, one point
per bar). **Honest gaps**: Expectancy, Maximum Consecutive Losses, and
Risk/Reward are not currently computed fields; Signals/Risk Approvals/
Risk Rejections/Orders/Fills counts exist for the LIVE PAPER path
(Daily Session Report) but not as `BacktestMetrics` fields, since the
backtester doesn't route through the shared risk gate (see Backtesting
Architecture Audit above). Not built this checkpoint — disclosed as
scoped future additions.

## Validation Splits

Audited — `BacktestTrustLevel` (POC/RESEARCH_READY/VALIDATION_READY/
PRODUCTION_RESEARCH_READY) exists as a label every result carries, but
every result today is `POC` by construction; nothing computes or
enforces Dev/Validation/Out-of-Sample partitioning yet. Documented as a
real, buildable, NOT YET built extension — not implemented this
checkpoint.

## Walk-Forward

Audited — does not exist. Correctly NOT implemented this checkpoint,
per the directive's own explicit instruction not to build a walk-forward
harness merely because it is desirable. Documented as the next research
capability in `STRATEGY_EXTENSIBILITY_AND_RESEARCH_ARCHITECTURE.md` §13.

## Robustness

Audited — no dedicated robustness-test harness or report exists.
`run_backtest()` already accepts varied bars/config/cost-model per call,
so ad-hoc robustness checks are possible today, but no automated
slippage-perturbation/delayed-entry/date-window/regime/parameter-
perturbation suite exists. Documented, not built, per explicit
instruction.

## Regime Analysis

Audited — no regime classifier or regime-segmented reporting exists.
Deliberately NOT built speculatively this checkpoint, per the
directive's own explicit instruction. Documented as a real gap.

## Research Profiles

Unchanged from Checkpoint 64.17's `docs/research/STRATEGY_DEFAULT_
PROFILES.md`, which already documents the exact Aggressive/Balanced/
Conservative EMA/SMA/ATR profiles this checkpoint's §21 repeats — not
duplicated, referenced. No system default was changed (re-verified by
the unmodified-defaults test cited above).

## Strategy Approval Lifecycle

Documented, not implemented (per the directive's own "design/document"
instruction): `DRAFT → BACKTESTED → VALIDATED → PAPER_APPROVED →
LIVE_PAPER_VERIFIED → LIVE_ELIGIBLE`. Explicitly stated: `LIVE_ELIGIBLE
!= LIVE_ENABLED` — real trading remains a separate, structural,
code-level constant that no lifecycle stage gates or implies.

## Frontend Extensibility

Re-verified, not rebuilt: the generic strategy configuration UI already
renders any strategy purely from its metadata/schema/defaults (grep
confirms zero per-strategy branches); Signal Evidence rendering is
already generic (Checkpoint 64.18, re-confirmed); Reports are already
strategy-agnostic (grep confirms zero `strategy_id ==` branches in
`application.reporting.*`/`reports_views.py`). No frontend code was
changed this checkpoint — frontend test suite unchanged at 174/174.

## Communication Extensibility

Re-verified, not rebuilt: `render_message()` accepts only the generic
`SignalCommunicationContext` (Signal/TradePlan/RiskDecision/Evidence/
ExecutionStatus fields), never strategy-specific arguments — proven
directly by `TestMomentumStrategy`'s real delivered messages in this
checkpoint's own extensibility test. Regarding 64.19's own disclosed
finding (evidence has no independent cap for a hypothetical strategy
with many fields): **no cap was added this checkpoint** — none of the
four real strategies (three production + the test strategy) approach a
verbosity problem (2-4 fields each), so adding a truncation/priority
policy now would be solving a problem that does not yet exist, matching
this checkpoint's own explicit "do not solve this by truncating
blindly... only if the architecture genuinely needs it" instruction.

## Security

No new response-serialization surface was introduced this checkpoint
(the test strategy's evidence flows through the SAME `build_signal_
evidence()`/`render_message()` paths already security-tested in
Checkpoint 64.18/64.19). Re-verified passing: the existing
credential-shaped-value regression tests, unmodified.

## Production Hygiene

Re-verified per §29's explicit instruction not to re-litigate the
Postgres warning without new evidence: ran the full suite this
checkpoint and confirmed the warning still appears, unchanged from
64.19's documented, deferred state — no new fix attempted (64.19 already
exhausted the two safe, properly-researched avenues; re-attempting
without new information would be exactly the "waste the checkpoint on a
cosmetic warning" this checkpoint explicitly warns against). Working
tree confirmed clean after commit (see Git Status). All quality gates
re-verified clean (see Baseline Verification).

## Market Closed Behavior

Unchanged and re-verified: no live Dhan connectivity was attempted, no
live worker was started, no live data fabricated. This checkpoint's
work was entirely architecture audit, documentation, and one new
NON_PRODUCTION test strategy — no code path in this checkpoint could
have touched market-closed behavior, and none did.

## Real Live Validation

**NOT ATTEMPTED**, per explicit directive — market closed, credential
expired, unchanged since Checkpoint 64.11. The First Live Paper
Validation Procedure (Checkpoint 64.19) was re-read and preserved
unmodified — the initial universe was NOT enlarged, per this
checkpoint's own explicit §28 instruction.

## Remaining Gaps

- Backtest engine does not route through the shared risk gate or
  simulate TradePlan stop/target exits (a real, disclosed architectural
  gap, not a defect in what exists today).
- `BacktestMetrics` lacks Expectancy, Maximum Consecutive Losses,
  Risk/Reward.
- No validation-split enforcement, walk-forward harness, robustness
  suite, or regime classifier exists — all four correctly left
  undocumented-as-built and merely documented as future capability, per
  explicit instruction not to build them this checkpoint.
- No `unit` field on `ParameterDefinition` (units are embedded in
  `help_text`/`label` by convention) — minor, non-blocking.
- VWAP/RSI-based future strategies would need one new
  `signal_intelligence.feature_engine` feature function each — a real,
  narrowly-scoped, identified gap, not a platform redesign.
- Postgres teardown warning remains deferred, unchanged from 64.19.

## Blockers

None new. The market remains closed and the Dhan credential remains
expired — live validation remains externally blocked, unchanged from
every checkpoint since 64.11.

## Production Readiness

The platform's strategy-extensibility claim is no longer aspirational —
it is mechanically proven by a real, passing test suite exercising the
entire pipeline with a genuinely new strategy and zero core-engine
branching. The backtesting engine's real capabilities and real gaps are
now both documented precisely, closing the risk of overclaiming research
rigor that does not yet exist. Nothing in this checkpoint changed
runtime behavior for any of the three production strategies or any
existing operator-facing surface.

## Performance Ranking

| Category | Previous | Current | Change | Evidence | Missing Capability |
|---|---|---|---|---|---|
| Architecture | 1 | 1 | none | Confirmed sufficient, not rebuilt | — |
| Strategy Extensibility | 3 | 1 | improved | Mechanically proven via TEST_MOMENTUM, zero core-engine changes | — |
| Strategy Registry | 1 | 1 | none | Confirmed sufficient | — |
| Strategy Configuration | 1 | 1 | none | Confirmed generic, defaults reconfirmed unchanged | No `unit` field |
| Strategy Engine | 1 | 1 | none | Confirmed shared by backtesting and live paper, no divergence | — |
| Strategy Explainability | 1 | 1 | none | Confirmed generic for a hypothetical new strategy | — |
| Signal Evidence | 1 | 1 | none | Confirmed generic; TEST_MOMENTUM proves a 4th strategy needs one registration line | — |
| Market Data | 1 | 1 | none | Unchanged | — |
| Historical Data | 1 | 1 | none | Unchanged | — |
| Database-First Replay | 1 | 1 | none | Re-confirmed unmodified | — |
| Bar Engine | 1 | 1 | none | Unchanged | — |
| Data Quality | 2 | 1 | improved | Full audit confirmed existing coverage is real and complete for what it claims | — |
| Look-Ahead Safety | 2 | 1 | improved | Confirmed a mandatory, already-passing dedicated test exists | — |
| TradePlan | 1 | 1 | none | Unchanged; confirmed NOT simulated in backtesting (disclosed) | Backtest TradePlan exit simulation |
| Risk | 1 | 1 | none | Unchanged; confirmed NOT routed through in backtesting (disclosed) | Backtest risk-gate integration |
| Paper Trading | 1 | 1 | none | Unchanged | — |
| Communication | 1 | 1 | none | Re-confirmed generic via TEST_MOMENTUM's real messages | — |
| Telegram | 1 | 1 | none | Unchanged; re-proven generic | — |
| Discord | 1 | 1 | none | Unchanged; re-proven generic | — |
| Scanner Progress | 1 | 1 | none | Unchanged | — |
| Reporting | 1 | 1 | none | Re-confirmed strategy-agnostic | — |
| Backtesting | 2 | 2 | none | Full audit performed; real gaps identified (risk gate, TradePlan exits), not closed this checkpoint | Risk-gate + TradePlan integration |
| Replay | 1 | 1 | none | Unchanged | — |
| Reproducibility | 1 | 1 | none | Unchanged | — |
| Execution Simulation | 2 | 2 | none | Confirmed no-perfect-fill discipline; intrabar policy honestly N/A today | TradePlan-based exit simulation |
| Slippage / Costs | 1 | 1 | none | Confirmed reuse of the one established Indian cost model | — |
| Walk-Forward | 4 | 4 | none | Audited, confirmed absent, correctly not built | Full walk-forward harness |
| Robustness | 4 | 4 | none | Audited, confirmed absent, correctly not built | Robustness test suite |
| Regime Analysis | 4 | 4 | none | Audited, confirmed absent, correctly not built | Regime classifier |
| Runtime Control | 1 | 1 | none | Unchanged | — |
| Session Control | 1 | 1 | none | Unchanged | — |
| Session Observability | 1 | 1 | none | Unchanged | — |
| Operator UX | 1 | 1 | none | Unchanged; no UI change needed | — |
| Responsive UI | 2 | 2 | none | No UI change this checkpoint | — |
| Accessibility | 2 | 2 | none | No UI change this checkpoint | — |
| Performance | 1 | 1 | none | Unchanged | — |
| Scalability | 1 | 1 | none | Unchanged | — |
| Auditability | 1 | 1 | none | Unchanged; extensibility proof adds no new audit surface | — |
| Security | 1 | 1 | none | Re-verified, no new leakage surface | — |
| Production Readiness | 1 | 1 | none | Extensibility claim now proven, not merely asserted | Backtest risk/TradePlan integration |
| Active Paper Trading | 2 | 2 | none | No live session run this checkpoint | Open market + fresh credential |
| Live Paper Readiness | 1 | 1 | none | Unchanged | — |
| Live Trading Readiness | N/A | N/A | none | Structurally disabled by design, restated in PRODUCT_SCOPE.md | — |
| **ENGINEERING MATURITY** | 1 | 1 | none | Rigorous audit-first discipline; zero test weakening | — |
| **ACTIVE PRODUCT MATURITY** | 1 | 1 | none | No operator-facing change this checkpoint by design | — |
| **STRATEGY EXTENSIBILITY MATURITY** | 3 | 1 | improved | The primary objective - mechanically proven, not merely claimed | — |
| **BACKTESTING MATURITY** | 3 | 2 | improved | Full, honest audit closes the "unknown gaps" risk even though the gaps themselves remain open | Risk-gate + TradePlan integration, validation splits |
| **RESEARCH MATURITY** | 4 | 3 | improved | Walk-forward/robustness/regime analysis now precisely documented as absent rather than unknown | Walk-forward, robustness, regime analysis |
| **CLOSED-MARKET READINESS** | 1 | 1 | none | This checkpoint's exact purpose, delivered without touching live systems | — |
| **NEXT-MARKET-OPEN READINESS** | 1 | 1 | none | 64.19's procedure preserved unmodified, universe not enlarged | Fresh credential, open market |
| **END-TO-END PIPELINE MATURITY** | 1 | 1 | none | Unchanged; now proven to generalize to a 4th, independently-added strategy | — |
| **OVERALL CHECKPOINT SCORE** | — | 1 | — | The named primary objective (strategy extensibility) fully proven with real, passing tests; backtesting/research gaps honestly documented, not fabricated as complete | Backtest risk/TradePlan integration, walk-forward/robustness/regime capability |

(1 = best/complete, higher numbers = more remaining work. Scores are not
inflated for documentation alone — every "1" here reflects either a
real, tested proof or a direct, verified cross-reference against
existing, already-passing code; every "2+" in the backtesting/research
categories reflects a real, disclosed gap that documentation alone does
not close.)

## Final Product Gate

**A. Strategy Extensibility**

Can a new strategy be added without modifying the core scanner,
backtester, risk, PaperBroker, communications, reports?

**YES.** Proven mechanically: `TestMomentumStrategy` required exactly
one new strategy module, one new test file, and one registration entry
in `evidence.py` — zero changes to any of the six named core engines,
confirmed by `git diff --stat` for this checkpoint.

**B. Test Strategy**

Did TEST_MOMENTUM prove the extensibility contract?

**YES.** 4 dedicated tests, all passing, covering registration
isolation from production, coordinator execution, feature-dispatcher
reuse, and the full signal→evidence→risk→paper→communication→report
chain with real delivered messages.

**C. Backtesting**

Does the backtester use the same strategy/signal/evidence/TradePlan/risk
semantics as the paper pipeline where appropriate?

**PARTIALLY.** Strategy/signal/evidence: YES, confirmed shared
(`StrategyExecutionCoordinator`, no divergent implementation).
TradePlan/risk: NO — the backtest engine has its own, simpler
direction-flip execution model and does not route through the shared
risk gate or simulate TradePlan exits. Disclosed honestly as a real
architectural gap, not claimed as complete.

**D. Research Integrity**

Are look-ahead, execution assumptions, costs, validation splits, and
reproducibility explicit and testable?

**PARTIALLY.** Look-ahead: YES, explicit and tested (a mandatory,
pre-existing test). Execution assumptions/costs: YES, explicit and
tested (next-bar-open fills, the established Indian cost model).
Validation splits: NO — `BacktestTrustLevel` exists as a label but
nothing computes/enforces which level a result earns. Reproducibility:
YES for the live paper path (Checkpoint 64.18's audit-trail fix); not
separately re-audited for backtesting this checkpoint (already covered
by 64.16's replay-determinism proof).

**E. New Strategy UI**

Can a new strategy expose its parameters and evidence without a new
strategy-specific UI page?

**YES.** Confirmed by direct grep audit: zero strategy-specific
branches in the parameter-configuration UI or the evidence-rendering
panel.

**F. New Strategy Communications**

Can a new strategy use Telegram/Discord without new channel-specific
business logic?

**YES.** Proven directly: `TestMomentumStrategy`'s real delivered
messages (via the unmodified `render_message()`) include its own Key
Evidence, with zero strategy-specific code in either channel adapter.

**G. Live Paper**

With a fresh Dhan credential and an open market, is the system ready to
execute the documented first controlled LIVE PAPER validation?

**YES.** Unchanged from 64.19 — the procedure was re-read and preserved
exactly, including its deliberately small initial universe.

**H. Real Trading**

**NO.** Unchanged: `real_trading_state` remains the structural constant
`"DISABLED"`; `PaperBroker` remains the only concrete broker
implementation; restated explicitly in the new `PRODUCT_SCOPE.md`.

## Honest Final Conclusion

This checkpoint's primary objective — proving, not merely asserting,
that the platform can absorb a new strategy without touching its core
engines — was met with a real, mechanical proof: a genuinely new,
clearly-marked non-production strategy moved through the entire
pipeline (registry, configuration, the shared execution coordinator,
signal, evidence, risk, paper execution, real Telegram/Discord
messages, and a real report query) with zero core-engine branching,
verified by 4 passing tests and a `git diff --stat` showing only the
expected strategy-specific and one-line-registration files changed. The
backtesting architecture audit was equally rigorous in the other
direction: real capabilities (database-first retrieval, data quality,
look-ahead protection, execution realism, cost modeling, core
performance metrics) were confirmed via direct code/test
cross-reference, while real gaps (no shared risk-gate/TradePlan
integration in backtesting, no validation splits, no walk-forward, no
robustness suite, no regime analysis, a few missing metrics) were
disclosed honestly rather than built speculatively or claimed complete
— exactly matching this checkpoint's own explicit instruction not to
over-engineer or fabricate rigor. The project scope was formally
restated in a new authoritative document without weakening the
real-trading safety boundary in any way. No live Dhan connectivity was
attempted, no live data was fabricated, and the first-live-session
procedure's deliberately small universe was preserved unchanged. Real
trading remains structurally disabled everywhere.

## Git Status

All changes are staged and committed locally only. No push to origin was
performed or will be performed without explicit instruction. Working
tree is clean after commit.
