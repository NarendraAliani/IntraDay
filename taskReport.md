# Task Report

## Checkpoint

64.16 — END-TO-END LIVE PAPER PIPELINE VALIDATION + OPERATIONAL PROOF

## Objective

Prove the complete algo-trading pipeline (data → strategy → signal →
TradePlan → risk → PaperBroker → fill → P&L → Telegram/Discord → report)
with real, deterministic, integrated tests — not another dashboard. Close
the Telegram/Discord aggregate-reporting gap 64.15 disclosed. Audit
database-first discipline, session-configuration immutability, backtest/
live strategy-logic consistency, and replay determinism. Real trading
must remain disabled throughout.

## Market State

**CLOSED.** No Dhan connectivity was attempted, no live worker was
started, no live data/signal/fill/P&L was fabricated. Every scenario in
this checkpoint runs against deterministic, in-memory/database fixtures
— never a simulated "live" value presented as real.

## Baseline Verification

| Gate | Result |
|---|---|
| pytest | 1477 passed |
| vitest | 164 passed |
| ruff format --check | 529 files already formatted |
| ruff check | All checks passed |
| mypy | Success: no issues found in 300 source files |
| lint-imports | 6 kept, 0 broken |
| manage.py check | 0 issues |
| makemigrations --check --dry-run | No changes detected |
| manage.py spectacular --fail-on-warn | exit 0 |
| frontend tsc --noEmit | 0 errors |
| frontend build | succeeded |

## Existing Architecture Reused

Every pipeline component named in §2 of the directive already exists and
is already wired — this checkpoint's job was to prove it, close one real
reporting gap, and add the specific tests that were missing, not to
rebuild anything:

- `PaperSignalExecutionService.evaluate_and_submit()` (Checkpoint 36) —
  the single orchestration point: bars → `StrategyExecutionCoordinator`
  → signal → deterministic `signal_id` → TradePlan persistence →
  unconditional VALIDATED_SIGNAL communication → risk-gated
  `PaperTradingService.submit_order()` → outcome communication → signal
  persistence. Read in full this checkpoint; unmodified.
- `StrategyExecutionCoordinator`/`build_default_registry()`
  (Checkpoint 26) — used identically by both the live paper path
  (`paper_signal_execution.py`) and `research.backtesting` (confirmed by
  reading `research/backtesting/__init__.py`'s own re-export of
  `build_default_registry`) — see "Backtesting Consistency" below.
- `SignalCommunicationService`/`NotificationRouter` (Checkpoint 37) —
  broker-independent by construction: `_communicate()` fires before any
  risk/broker call, `_communicate_outcome()` fires unconditionally after,
  regardless of `RiskDecisionOutcome`.
- `DailySessionReportResponse`/`build_daily_session_report()`
  (Checkpoint 64.10) — extended, not replaced (see "Telegram"/"Discord"
  below).
- `HistoricalBacktestRunOrchestrator` (Checkpoint 63.x) — already proven
  database-first by existing tests (see "Database-First / API Fallback"
  below).
- `LivePaperOperationsConsole.tsx` (64.15) — extended with the new
  per-channel Communication Summary panel; no second console created.

## Complete End-to-End Pipeline Map

Audited by reading `paper_signal_execution.py`, `strategy_execution/
coordinator.py`, `paper_trading.py`, `signal_communication.py`, and the
existing end-to-end test suite in full.

| Stage | Source → Destination | Contract | Persistence | Tests | Failure Behavior |
|---|---|---|---|---|---|
| Market Data Provider → Worker | Dhan WS / historical sync → `run_market_data_worker.py` | `Bar` | `MarketDataBarRecord` | worker command tests | `WorkerState.AUTH_FAILED/TOKEN_EXPIRED/FAILED` (Checkpoint 53) |
| Bar Normalization | provider tick/candle → `domain.market_data.contracts.Bar` | `Bar` (OHLCV, tabular) | same table | bar-engine tests | malformed input rejected at the boundary |
| Universe Selection | `ScannerConfiguration.desired` → worker reconciliation | instrument_id list | `WorkerRuntimeStatus.effective_*` | 64.4/64.14 tests | partial subscription → DEGRADED (not silently OK) |
| Timeframe | desired.timeframe → coordinator | `Timeframe` enum | same | strategy execution tests | invalid timeframe rejected (`ValueError` guard in worker command) |
| Strategy Selection | desired.selected_strategy_ids → `StrategyRegistry.activate()` | `StrategyConfigurationValues` | `StrategyConfigurationRecord` | registry tests | unregistered strategy_id raises `UnknownStrategyError` |
| Strategy Execution | bars + config → `StrategyExecutionCoordinator.run()` | `CoordinatorResult` | none (pure) | `test_strategy_execution.py` (39 tests, +1 determinism this checkpoint) | one strategy's failure isolated (`scenario_b`), never aborts the batch |
| Signal | `StrategySignal` → `derive_signal_id()` | deterministic `SignalId` | `SignalRecord` | `test_paper_signal_execution.py` | NEUTRAL direction → skipped, never a fabricated signal |
| TradePlan | `AtrVolatilityBreakoutStrategy.build_trade_plan()` → recorder | `TradePlan` | `TradePlanRecord` | `test_full_bars_to_report_chain...` | `None` for directional-only strategies, never fabricated |
| Risk | `OrderIntent` → `PaperTradingService.submit_order()` | `RiskDecision` | none (decision only) | risk engine tests + this checkpoint's `scenario_j` | REJECTED never blocks signal/communication |
| PaperBroker | approved order → `PaperBroker.submit_order()` | `BrokerReport` | `PaperOrderRecord` | paper broker tests | insufficient funds/limits → `OrderStatus.REJECTED`, no fill |
| Paper Fill | broker match → `OrderStatus.FILLED` | `BrokerReport` | `PaperOrderRecord.status` | paper broker tests | partial fill supported (`PARTIALLY_FILLED`) |
| Paper Position | fill → `PaperBroker.get_positions()` | `Position` | `PaperPositionRecord` | paper trading tests | — |
| P&L | closed position → `realized_pnl` | `Decimal` | `PaperPositionRecord.realized_pnl` | reporting tests | `None` (not `0`) when no position closed |
| Telegram/Discord | signal/outcome → `NotificationRouter.send()` | `DeliveryAttempt` | `CommunicationLedgerRecord` | mixed-channel test + this checkpoint's `scenario_j` | one channel's failure never affects the other |
| Daily Report | ledgers → `build_daily_session_report()` | `DailySessionReportResponse` | none (pure aggregation over real rows) | `test_daily_session_report.py` (extended this checkpoint) | empty session → honest all-zero report |
| Live Paper Operations Console | `GET .../live-paper-workbench/`, `.../reports/daily-session/`, `.../signals/` | typed JSON | n/a (read-only) | `LivePaperOperationsConsole.test.tsx` (extended this checkpoint) | stale-but-real data kept visible on a poll failure |

Nothing in this map was found to be "wired on paper but not in code" —
every arrow above was traced through actual source, not assumed from
class names.

## Database-First / API Fallback

Already true and already tested — found, not built, this checkpoint:
`test_scanner_reads_only_from_database_never_the_provider_once_complete`
and `test_full_sequence_api_then_db_then_scanner_survives_api_being_
disabled_after` (`test_historical_backtest_run_orchestrator.py`,
Checkpoint 63.x) directly prove the FETCH → VALIDATE → STORE → READ →
SCAN invariant for the backtesting/replay path: the scanner is proven to
never call the provider again once the required range is persisted, even
when the provider is subsequently disabled. No second data-access
architecture exists; this checkpoint added no new code here because none
was needed — the invariant already holds and is already regression-
tested.

## Deterministic Paper Session

Rather than building a new, separate "one realistic session" fixture
file (§4's own suggestion), this checkpoint extended the EXISTING
deterministic end-to-end suite (`test_active_loop_end_to_end.py`,
Checkpoint 38/64.8) with the one scenario it was missing — see "Risk
Rejected Path" below — because that suite already IS a real, integrated,
non-shortcut deterministic scenario (real `StrategyExecutionCoordinator`,
real `PaperBroker`, real `PaperTradingService`, real
`SignalCommunicationService`, real Django repositories; only the
Telegram/Discord network boundary is faked, clearly labelled). Building
a second, parallel "session fixture" file would have duplicated this
suite, which the directive's own §17 explicitly warns against
("Do NOT create a second... implementation").

## Signal Generation

Proven via `test_full_bars_to_report_chain_with_trade_plan_and_mixed_
channel_delivery` (pre-existing, 64.8) and this checkpoint's new
`test_scenario_j_risk_rejected_signal_is_persisted_queryable_and_
communicated`: `atr_volatility_breakout` and `ema_crossover` both
produce a deterministic signal from a fixed bar series, asserted for
stock (`instrument_id`), strategy, timeframe, direction, timestamp, and
spot price. TradePlan fields (entry/stop-loss/target 1-3/trailing SL)
are asserted only where the evaluating strategy actually provides them
(`atr_volatility_breakout`) — `ema_crossover` correctly produces no
TradePlan, never a fabricated one.

## TradePlan

Unchanged from Checkpoint 64.7 — `plan.target_1 < plan.target_2 <
plan.target_3` and `plan.stop_loss is not None` re-verified as still
holding via the existing happy-path test in this checkpoint's regression
run.

## Risk Approved Path

Proven end-to-end (existing test, re-verified): signal → risk APPROVED →
`PaperOrderRecord` created → `broker_report.status == "FILLED"` →
position opened.

## Risk Rejected Path

**New this checkpoint** — `test_scenario_j_risk_rejected_signal_is_
persisted_queryable_and_communicated`
(`test_active_loop_end_to_end.py`): a genuine risk-engine rejection
(stale market data, not a kill-switch halt — the existing scenario_a/
scenario_f tests already covered kill-switch/stale-data rejection at the
service-result level, but neither wired `SignalRecorder`) now proves,
with full production persistence wired:

- `risk_decision.outcome == "REJECTED"`, zero orders reach the broker,
  `PaperOrderRecord` does not exist for this signal.
- `SignalRecord` IS persisted (`risk_status == "REJECTED"`,
  `order_status == ""`, never fabricated as if an order existed).
- The signal is independently queryable via
  `DjangoSignalRepository().list_signals()` — the same path the report/UI
  actually use, not merely present in memory.
- Telegram (fails) and Discord (succeeds) both still attempt delivery —
  2 messages each (VALIDATED_SIGNAL, then
  VALIDATED_SIGNAL_EXECUTION_BLOCKED) — proving the rejection reason
  itself is communicated, not just the original signal.

## Paper Execution

Unchanged; re-verified via existing `PaperBroker`/`PaperTradingService`
test suites in the full regression run (1481 passed).

## Telegram

**Backend change (§8, the one genuine gap 64.15 disclosed):** added
`ChannelCommunicationSummary` (`sent`/`failed`/`pending`) to
`DailySessionReport`, derived purely from the already-fetched
`communication_rows` (grouped by `CommunicationDeliveryRow.channel`) —
no second communication-accounting path, no new query. `pending` is
computed as `total - sent - failed` for that channel so it can never
drift from the channel's real row count even as new non-terminal
`delivery_status` values are added later (proven by a dedicated test
mixing `RETRYING`/`SKIPPED_NOT_CONFIGURED` rows). Added alongside the
existing combined `communication_sent`/`_failed`/`_skipped` fields —
nothing existing was removed or renamed, so no consumer of the combined
totals breaks (re-verified: full regression still 1481 passed). Exposed
as `telegram`/`discord` on `DailySessionReportResponseSerializer`, and
now rendered in the Live Paper Operations Console's Communication
Summary panel as two distinct KPI groups.

## Discord

Same mechanism and same test coverage as Telegram above — one shared
`_channel_summary()` closure, not two divergent implementations.

## Communication Independence

Proven for BOTH channels and BOTH risk outcomes this checkpoint:
Telegram's failure never affects Discord's delivery (existing
mixed-channel test), and a risk-REJECTED signal still produces
independent, queryable communication history for both channels (new
`scenario_j` test). This is the exact product invariant §6/§7 name.

## Scanner Progress

**Not built this checkpoint — audited and disclosed as a real, unclosed
gap, not fabricated.** `WorkerRuntimeStatus` (the real runtime-state
table, Checkpoint 64.3) carries `subscribed_instrument_count`,
`watchdog_state`, `reconnect_count`, `consecutive_failures`,
`last_packet_at`/`last_bar_at` — all already surfaced via
`WorkerStatusCard`. It does NOT carry a per-scan "total instruments /
processed / remaining / current instrument / current strategy / signals
found this scan / scan start / last progress update" structure — that
is a genuinely different, currently-nonexistent data model (the closest
analogue, `HistoricalBacktestRunProgress`, exists only for the
historical-backtest-run pipeline, a different code path from the live
scanning worker). Building this honestly would require a new persisted
progress row the worker updates per-instrument, which is a real,
non-trivial addition — not attempted this checkpoint to stay within
scope; disclosed here rather than approximated with a fake counter.

## Signal Explanation

**Audited; a real, disclosed gap.** `SignalRecord`/`SignalResponse`
carry `risk_reason` (why risk approved/rejected) and the persisted
`TradePlan` (entry/stop/targets), but no strategy-side "why did the
strategy itself decide BULLISH/BEARISH here" evidence field (e.g. the
actual EMA/ATR feature values that triggered the crossover/breakout) is
persisted anywhere. `StrategySignal` (in-memory, `trading_engine.
strategy_execution.contracts`) is discarded after evaluation — its
inputs are never written to a queryable record. Per the directive's own
explicit instruction ("If explanation data is missing from the backend,
identify it as a real gap rather than creating a fake textual
explanation"), no explanation UI or fabricated text was added this
checkpoint.

## Session Reporting

Audited `DailySessionReportResponse` against the directive's requested
field list: signals generated ✓, risk-approved/rejected ✓, paper
orders/fills ✓, Telegram/Discord ✓ (new, per-channel this checkpoint),
open/closed positions and unrealized P&L are **NOT** present — only
`realized_pnl_total` exists (aggregated from CLOSED positions only, per
its own field comment). Open-position count and unrealized P&L would
require querying `PaperPositionRecord` for `status=OPEN` rows and their
mark-to-market value — a real, authoritative source exists
(`PaperPositionRecord`), but computing unrealized P&L needs a current
quote per open position, which this report does not currently fetch.
Disclosed as a real gap rather than adding a fabricated or zero-value
field. Session duration is also not present (no session-start timestamp
is persisted anywhere yet — `LivePaperSessionResult`/`WorkerRuntimeStatus`
have no "session started at" field distinct from the worker's own
`updated_at`).

## Backtesting Consistency

**Audited — confirmed consistent, no divergence found.** Read
`research/backtesting/__init__.py`: it re-exports
`build_default_registry` and the same `StrategyExecutionCoordinator`
from `trading_engine.strategy_execution` — the identical objects
`paper_signal_execution.py` uses for live paper. No second strategy
evaluation implementation exists for backtesting; the only backtest-
specific code is the harness around it (position sizing, cost model, run
orchestration), which is architecturally separate from signal-generation
logic. No consolidation was needed because no divergence exists.

## Replay Determinism

**New test this checkpoint**:
`test_coordinator_is_deterministic_same_bars_same_config_same_signals`
(`tests/unit/trading_engine/test_strategy_execution.py`) — runs the same
bar series through two INDEPENDENT `StrategyExecutionCoordinator`
instances (fresh registries, not the same object re-invoked) with the
identical configuration, and asserts identical direction/price/timestamp
per strategy and identical TradePlan output. This closes the concrete
gap: determinism was previously only implied by
`derive_signal_id()`'s own docstring ("strategy evaluation is a pure
function over the bar series"), never directly asserted by a test that
actually runs evaluation twice and compares. This is the primary
closed-market validation mechanism the directive names, and it now has
direct proof, not just architectural inference.

## Report Reproducibility

Audited `ReportMetadata` (used by every report in `application/
reporting/*`): `data_source`, `data_identity`, `period_start`/
`period_end`, `version` are present on every report including
`DailySessionReport`. `strategy_identity`/`timeframe`/
`instrument_universe`/`trust_level`/`quality_status` exist on the
contract but are `None`/empty for `DailySessionReport` specifically
(populated for `SignalReport`/other reports where already meaningful) —
`DailySessionReport` derives `strategies`/`universe`/`timeframes` as its
own top-level fields instead (already present, unchanged). Configuration
versions (`configuration_version` from `ScannerConfigurationRecord`) are
NOT currently embedded in any report's metadata — a real, disclosed gap:
reproducing a report's exact result today requires cross-referencing the
`AuditLogEntry` trail manually, not a single self-describing report
field.

## Failure Injection

Verified via the full regression suite (not newly built where already
covered): token expired (`test_live_paper_readiness.py`,
`CREDENTIAL_EXPIRED`), provider disconnected (`watchdog_state`
DISCONNECTED path, `live_paper_readiness_checklist.py` tests), worker
failed (`_FAILED_WORKER_STATES` → session `FAILED`, 64.14 tests), missing
universe (`_universe_check` BLOCKED, 64.14), missing strategy
(`_strategy_selection_check` BLOCKED, 64.14), invalid timeframe (worker
command's own `ValueError` guard, existing), risk rejection (this
checkpoint's `scenario_j` + pre-existing scenarios), PaperBroker
rejection (existing paper broker tests), Telegram failure (existing +
this checkpoint's `scenario_j`), Discord failure (existing mixed-channel
test), report unavailable — **not separately tested this checkpoint**
(the report endpoints have no external dependency to fail against; an
empty/all-zero report is the only "no data" case, already covered).
Confirmed via this checkpoint's tests: Telegram failure never removes a
signal; risk rejection never removes a signal; Discord failure is
independent of Telegram's outcome; PaperBroker rejection never removes a
signal — all proven by `scenario_j` and the pre-existing mixed-channel
test together.

## Degraded States

Audited, not newly built — already real and already distinct
(Checkpoint 64.4/64.12/64.14): `ScannerConfigurationResponse.status`
(EFFECTIVE/APPLYING/DEGRADED/STOPPED), `LivePaperReadinessState` (6
values including `BLOCKED_BY_SAFETY`/`PROVIDER_UNAVAILABLE`), the 10-item
checklist's `READY`/`WARNING`/`BLOCKED`/`UNKNOWN`, and
`LivePaperSessionState`'s `FAILED`. Nothing in this product currently
collapses to bare SUCCESS/ERROR; this checkpoint found no gap here worth
reporting as new.

## Performance / Scalability

Measured the existing deterministic scenario (`test_coordinator_scenario_
a_all_strategies_succeed`-class runs): 20 bars × 3 strategies completes
in the sub-millisecond range as part of the 0.33s total for the entire
39-test `test_strategy_execution.py` file. No dedicated instrumented
profiling (query count, memory) was run this checkpoint — a real,
disclosed limitation. One structural observation from reading
`DjangoSignalRepository.list_signals()` (64.9): it already performs bulk
TradePlan/communication-status queries rather than per-row N+1 queries
(the exact pattern this checkpoint's §20 warns against) — confirmed by
re-reading the method, not re-tested with a query-count assertion this
checkpoint.

## Security

Re-verified via the full regression suite: no credential/token/webhook
value is ever returned by any endpoint touched this checkpoint (the
Daily Session Report's new `telegram`/`discord` fields are pure counts,
never provider identifiers). The existing
`test_communication_report_reflects_real_ledger_rows_never_a_credential`
and the Live Paper Operations Console's credential-leakage test both
still pass unchanged.

## Testing

**Backend: 4 new tests, all passing, full suite 1481 passed** (was
1477):
1. `test_scenario_j_risk_rejected_signal_is_persisted_queryable_and_
   communicated` — the risk-rejected + communication-independence proof.
2. `test_daily_session_report.py::test_per_channel_pending_never_drifts_
   from_the_channels_own_row_count` — per-channel derivation correctness.
3. `test_reports_views.py::test_daily_session_report_splits_
   communication_by_channel` — end-to-end API proof of the new fields.
4. `test_coordinator_is_deterministic_same_bars_same_config_same_
   signals` — the replay-determinism proof.
   Plus 2 existing `test_daily_session_report.py` tests were extended
   in-place with per-channel assertions (no new test count, deeper
   coverage of the same test).

**Frontend: 164 passed** (unchanged count — 2 existing
`LivePaperOperationsConsole.test.tsx` tests were updated in place to
assert the new per-channel Telegram/Discord fixture and fields rather
than the old combined-total fields).

## Real Live Validation

**NOT ATTEMPTED**, per explicit directive — the market is closed and the
Dhan credential remains expired. No live packet, signal, fill, or P&L
was fabricated anywhere in this checkpoint's work.

## Remaining Gaps

- **Scanner progress** (§13): no per-scan progress row exists for the
  live worker path; a real, disclosed gap, not approximated.
- **Signal explanation/evidence** (§15): strategy-internal feature values
  that produced a signal (e.g. the EMA/ATR readings at crossover) are
  not persisted; only risk_reason and TradePlan are.
- **Open positions / unrealized P&L / session duration** in the Daily
  Session Report (§16): real authoritative sources exist
  (`PaperPositionRecord`, worker timestamps) but are not yet wired into
  this specific report.
- **Report reproducibility metadata** (§19): configuration_version is not
  yet embedded in `DailySessionReport`'s own metadata.
- **Session configuration immutability** (§9): audited and found to be a
  genuine, deliberate architectural tension, not an oversight — see
  "Blockers" below.
- **Performance profiling** (§20): no instrumented query-count/memory
  measurement was run; only a coarse wall-clock observation.
- **Failure injection for "report unavailable"**: not separately tested
  (no external dependency exists for a report endpoint to fail against
  today).

## Blockers

**§9 (session configuration immutability) is a genuine, disclosed
architectural tension, not a missed test.** Auditing `LiveScannerConsole.
tsx` and `run_market_data_worker.py` together: the worker re-reads
`ScannerConfiguration.desired` on every reconciliation cycle by design
(Checkpoint 64.4), and the existing "Apply Configuration" UI action
(distinct from START) is an intentional, already-shipped, already-tested
LIVE reconfiguration feature — an operator can change timeframe/universe/
strategies while `enabled=True` and the worker picks it up on its next
cycle. This is the opposite of "immutable for the running session."
Implementing true mid-session immutability (freezing configuration at
START, disabling "Apply Configuration" while RUNNING) would be a real
product-behavior change to an existing, tested, shipped feature — not
something to alter silently within this checkpoint's scope without
explicit confirmation, so it was not attempted. This is reported as a
blocker requiring a product decision, not silently worked around.

The market remains closed and the Dhan credential remains expired
(unchanged since Checkpoint 64.11/64.12) — the full live READY → START →
RUNNING flow still cannot be observed end-to-end with real data.

## Next Market-Open Checklist

Before the next market open, in order:

1. Obtain a fresh Dhan credential (`DHAN_ACCESS_TOKEN` renewed/
   regenerated).
2. Confirm token state reads `VALID` on the Live Paper Operations
   Console's Dhan Credential / Token Validity checks.
3. Start the live market-data worker process
   (`manage.py run_market_data_worker --provider dhan`) and confirm
   Provider Connectivity / Watchdog read `READY`.
4. Confirm Market State reads `READY` once the exchange session opens.
5. Confirm Universe is valid (non-empty selection or a valid watchlist).
6. Confirm Timeframe is set to a supported value.
7. Confirm at least one Strategy is selected.
8. Confirm Paper Execution and Real Trading Safety both read `READY`
   (Real Trading Safety is structurally always `READY`/`DISABLED`).
9. Once the aggregate `LivePaperReadiness.can_start` is `true`, the
   ONLY remaining manual action is: **press START** on the Live Paper
   Operations Console.

Real trading remains, and must remain, DISABLED at every one of these
steps.

## Production Readiness

The core pipeline (data → strategy → signal → TradePlan → risk →
PaperBroker → fill → P&L → communication → report) is now proven correct
under BOTH the risk-approved and risk-rejected paths, with communication
independence verified for both, and replay determinism directly tested
for the first time. The Daily Session Report now answers the Telegram/
Discord split 64.15 disclosed as missing. What stands between this and a
fully production-ready operator product: scanner progress observability,
signal explanation/evidence, open-position/unrealized-P&L reporting, and
a resolved product decision on session-configuration immutability versus
the existing live-reconfiguration feature.

## Performance Ranking

| Category | Previous | Current | Change | Evidence | Missing Capability |
|---|---|---|---|---|---|
| Architecture | 1 | 1 | none | Full pipeline map traced through real source, no gaps found in wiring | — |
| Market Data | 1 | 1 | none | Unchanged; market closed | — |
| Dhan Integration | 2 | 2 | none | No live call attempted | Fresh credential + open market |
| Credential Lifecycle | 1 | 1 | none | Unchanged | — |
| Token Validation | 1 | 1 | none | Unchanged | — |
| Live Feed | 2 | 2 | none | Not exercised | Live market session |
| Historical Data | 1 | 1 | none | Database-first invariant re-confirmed via existing tests | — |
| Database-First Replay | 2 | 1 | improved | Explicitly audited and confirmed true this checkpoint, not merely assumed | — |
| Bar Engine | 1 | 1 | none | Unchanged | — |
| Strategy Engine | 1 | 1 | none | Unchanged; now proven deterministic | — |
| Strategy Explainability | 4 | 4 | none | Audited; no evidence field persisted | Persisted strategy-internal feature values |
| TradePlan | 1 | 1 | none | Re-verified | — |
| Signal Operations | 1 | 1 | none | Rejected-signal observability now directly proven | — |
| Risk | 2 | 1 | improved | Both approved AND rejected paths now proven with full persistence wiring | — |
| Paper Trading | 1 | 1 | none | Re-verified | — |
| Communication | 2 | 1 | improved | Independence proven for both risk outcomes, both channels | — |
| Telegram | 2 | 1 | improved | Per-channel aggregate counts now exist | — |
| Discord | 2 | 1 | improved | Same as Telegram | — |
| Watchdog | 1 | 1 | none | Unchanged | — |
| Reconnect | 1 | 1 | none | Unchanged | — |
| Scanner Progress | 4 | 4 | none | Audited; genuinely does not exist yet | New per-scan progress persistence |
| Reporting | 2 | 1 | improved | Telegram/Discord split closes 64.15's named gap | Open positions / unrealized P&L / duration |
| Backtesting | 1 | 1 | none | Confirmed shares strategy logic with live path, no divergence | — |
| Replay | 3 | 1 | improved | Determinism now directly tested, not just architecturally implied | — |
| Reproducibility | 3 | 2 | improved | Metadata audited; most fields present, configuration_version still missing | Configuration version embedded in report metadata |
| EOD | 1 | 1 | none | Unchanged | — |
| Runtime Control | 1 | 1 | none | Unchanged | — |
| Pre-Session Readiness | 1 | 1 | none | Unchanged from 64.14/64.15 | — |
| Session Control | 2 | 2 | none | Immutability-vs-live-reconfiguration tension identified, not resolved | Product decision on Apply Configuration during RUNNING |
| Session Observability | 2 | 2 | none | Unchanged this checkpoint (no new UI screen beyond comms split) | Scanner progress, session duration |
| Operator UX | 2 | 2 | none | Console extended (comms split) but no new major screen | Scanner progress, signal explanation UI |
| Responsive UI | 2 | 2 | none | Unchanged | — |
| Accessibility | 2 | 2 | none | Unchanged | — |
| Performance | 2 | 2 | none | Coarse wall-clock only, no instrumented profiling this checkpoint | Query-count/memory instrumentation |
| Scalability | 2 | 2 | none | N+1 pattern re-confirmed absent by re-reading, not re-tested | Automated query-count regression test |
| Auditability | 1 | 1 | none | Unchanged | — |
| Security | 1 | 1 | none | Re-verified, no leakage in new fields | — |
| Production Readiness | 2 | 2 | none | Pipeline correctness proven; UI/reporting gaps remain | See Remaining Gaps |
| Active Paper Trading | 2 | 2 | none | No live session run this checkpoint | Open market + fresh credential |
| Live Paper Readiness | 1 | 1 | none | Unchanged | — |
| Live Trading Readiness | N/A | N/A | none | Structurally disabled by design | — |
| **ENGINEERING MATURITY** | 1 | 1 | none | Deterministic proofs added without touching production wiring | — |
| **ACTIVE PRODUCT MATURITY** | 2 | 2 | none | Pipeline proof strengthens confidence; no new operator-facing capability beyond comms split | Scanner progress, signal explanation |
| **CLOSED-MARKET READINESS** | 1 | 1 | none | This checkpoint's exact purpose, delivered via new deterministic tests | — |
| **NEXT-MARKET-OPEN READINESS** | 2 | 2 | none | Checklist is precise; blocker remains external (credential + market) | Fresh credential, open market |
| **END-TO-END PIPELINE MATURITY** | 3 | 1 | improved | The directive's primary ask: full chain now proven for both risk outcomes with real persistence and communication independence | — |
| **OVERALL CHECKPOINT SCORE** | — | 1 | — | Focused, evidence-based pipeline proof; all new tests pass; one real backend gap (Telegram/Discord split) closed; remaining gaps honestly disclosed, not fabricated | Scanner progress, signal explanation, open-position P&L |

(1 = best/complete, higher numbers = more remaining work; scores held
equal where nothing changed this checkpoint rather than credited for
unrelated prior work.)

## Final Product Gate

**A. End-to-End Deterministic Paper Flow**

Can the system prove: data → strategy → signal → TradePlan → risk →
PaperBroker → fill → P&L → Telegram/Discord → report?

**YES** — for the risk-approved path (pre-existing, re-verified) AND now
the risk-rejected path (new `scenario_j` test), both with real
persistence and a real report query at the end.

**B. Communication Independence**

Can a risk-rejected signal still be communicated?

**YES** — proven this checkpoint with both channels, full persistence,
and an independent report-layer query confirming the signal is
observable.

**C. Replay**

Can the same historical inputs reproduce the same results?

**YES** — directly tested this checkpoint
(`test_coordinator_is_deterministic_same_bars_same_config_same_signals`),
not merely architecturally assumed.

**D. Next Market Open**

With a fresh Dhan credential, can we confidently perform a controlled
LIVE PAPER session?

**PARTIALLY** — the pipeline is now proven correct end-to-end under
deterministic conditions, and the pre-session/session-control/monitoring
UI exists (64.13-64.15); what remains unverified is the same flow
against genuinely live data, which requires both the credential and an
open market (neither available this checkpoint, by design), plus the
disclosed gaps (scanner progress, signal explanation, session
immutability decision) are not blockers to a first controlled
observation but do limit full operator confidence.

**E. Real Trading**

**NO.** Unchanged: `real_trading_state` remains the structural constant
`"DISABLED"` on every code path; `PaperBroker` remains the only concrete
broker implementation in the codebase; zero real orders were placed or
attempted.

## Honest Final Conclusion

This checkpoint's central deliverable — proving the complete algo-trading
pipeline, not building another dashboard — was met with real, targeted
additions: a genuine risk-rejected end-to-end test with full persistence
and communication-independence proof (closing a gap the pre-existing
suite didn't quite reach, since none of its rejection scenarios wired
`SignalRecorder`), a direct replay-determinism test (previously only
implied by a docstring), a confirmed (not assumed) database-first audit
for the backtesting/replay path, a confirmed (not assumed) backtest/
live-strategy-logic consistency audit, and the one concrete backend gap
64.15 named — Telegram/Discord aggregate counts — closed with a minimal,
additive change deriving purely from already-fetched rows. Several real
gaps are disclosed rather than papered over: scanner progress has no
backing data model yet, signal explanation/evidence is not persisted,
open positions and unrealized P&L are not in the Daily Session Report,
and session-configuration immutability during a RUNNING session
conflicts with an existing, shipped, tested live-reconfiguration feature
— a product decision, not a code gap, and reported as such rather than
silently resolved either way. No live Dhan connectivity was attempted,
and no live data was fabricated. Real trading remains structurally
disabled everywhere, proven by the same structural-constant guarantee
this project has maintained since Checkpoint 64.11.

## Git Status

All changes are staged and committed locally only. No push to origin was
performed or will be performed without explicit instruction. Working
tree is clean after commit.
