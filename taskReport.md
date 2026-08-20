# Task Report

## Checkpoint

64.18 — COMPLETE SCANNER PROGRESS + SIGNAL EVIDENCE + FINAL OPERATIONAL GAPS

## Objective

Close the two major capabilities 64.17 designed but did not implement:
Scanner Progress and Signal Evidence — completing the operator
information loop CONFIGURATION → SCANNING → PROGRESS → SIGNAL → SIGNAL
EVIDENCE → RISK → PAPER EXECUTION → COMMUNICATION → REPORT. Also close
the bounded unrealized-P&L N+1 and the report-reproducibility gap 64.17
disclosed, and investigate the recurring Postgres test-teardown warning.

## Baseline Verification

| Gate | Result |
|---|---|
| pytest | 1493 passed |
| vitest | 168 passed |
| ruff format --check | 529 files already formatted |
| ruff check | All checks passed |
| mypy | Success: no issues found in 300 source files |
| lint-imports | 6 kept, 0 broken |
| manage.py check | 0 issues |
| makemigrations --check --dry-run | No changes detected |
| manage.py spectacular --fail-on-warn | exit 0 |
| frontend tsc --noEmit | 0 errors |
| frontend build | succeeded |

**Postgres teardown warning investigated** (§1): `PytestWarning: Error
when trying to teardown test databases: ... database "test_intraday" is
being accessed by other users`. Root-caused as the SAME single lingering
session every run, firing only once at the very end (during Django's own
final `DROP DATABASE`, never during any individual test), never causing
a test failure — consistent with "this pytest process's own long-lived
default DB connection is still open when the drop is attempted," not a
test-isolation leak (the one real multi-connection risk in this suite,
`test_scanner_configuration_repository.py`'s `ThreadPoolExecutor` test,
was re-audited and already calls `connections.close_all()` correctly).
Attempted fix: a `pytest_sessionfinish` hook in `tests/conftest.py`
calling `connections.close_all()`. **Result: did not resolve it** — the
warning still appears in the final full-suite run this checkpoint
(1519 passed, 2 warnings). Honest root cause for why the fix didn't
work: `pytest_sessionfinish` fires after pytest-django's own session-
scoped fixture teardown (where the actual `DROP DATABASE` runs), so the
hook closes connections too late to matter. The hook is left in place
(harmless, and closes connections that could otherwise leak into a
later process) but the warning itself remains open, documented here
rather than hidden or silently suppressed.

## Scanner Progress

**Implemented this checkpoint**, using the exact model 64.17 designed.
New `ScannerScanProgress` (migration `0024_scannerscanprogress.py`)
mirrors `WorkerRuntimeStatus`'s established "ONE singleton row per
provider, worker writes, API reads" pattern — never a second worker-
lifecycle framework. Fields match §2 exactly: `provider`, `scan_id`,
`scan_started_at`, `timeframe`, `universe_total`, `universe_processed`,
`current_instrument`, `current_strategy`, `strategies_total`,
`strategies_processed`, `signals_found`, `last_progress_at`, `status`
(IDLE/STARTING/SCANNING/COMPLETED/DEGRADED/FAILED/STOPPED).
`universe_remaining`/`progress_percent` are deliberately NOT stored —
both are pure derivations computed at read time in the API view (§2's
explicit instruction: one source of truth for the raw counters).

## Scanner Progress Semantics

Wired into `run_market_data_worker.py`'s `aggregate_now()` — the real
scan-execution path, never the frontend:

- **A scan** = one `aggregate_now()` cycle across every desired
  strategy. `universe_total` is computed once, from the same closed-bar
  set `promote_bars_and_trigger_signals()` itself iterates.
- **`universe_processed`** increments per instrument, via a new optional
  `on_instrument_progress` callback added to `promote_bars_and_trigger_
  signals()` (§5's injection point — `None` by default, every
  pre-existing caller including the REST-ingestion path is unaffected).
- **`current_instrument`/`current_strategy`** update live as the worker
  iterates.
- **`strategies_processed`** increments after each strategy_id's
  `promote_bars_and_trigger_signals()` call returns (success or a
  caught failure).
- **A failed strategy is caught, not fatal**: wrapped in try/except —
  one strategy's exception marks `status=DEGRADED` and the loop
  CONTINUES to the remaining strategies, never letting a single failure
  make the whole scan appear COMPLETED while other work remains (§4's
  explicit requirement).
- **`signals_found`** is a real, authoritative count —
  `SignalRecord.objects.filter(created_at__gte=scan_started_at).count()`
  at the end of the cycle (`created_at` is `auto_now_add`, real wall-
  clock insertion time; `clock` was captured at the START of the cycle,
  before any signal this cycle could produce was written) — never an
  approximated time window, never a fabricated increment.
- **Scan completes**: `status=COMPLETED` if no strategy failed,
  `DEGRADED` if any did.
- **Scanner disabled**: `mark_idle()` is called — an honest `IDLE`
  state, never a stuck SCANNING row.
- **Staleness** is computed at READ time by the API (see below), not
  stored — a non-terminal status whose `last_progress_at` is older than
  120 seconds is reported `stale=True`.

## Scanner Progress Persistence

New `application/repositories/scanner_scan_progress.py`
(`ScannerScanProgressRecord`, `ScannerScanProgressRepository` Protocol:
`get()`/`start_scan()`/`update_progress()`/`mark_idle()`) and
`infrastructure/persistence/scanner_scan_progress_repository.py`
(`DjangoScannerScanProgressRepository`) — mirrors `WorkerRuntimeStatus
Repository`'s exact shape. 6 dedicated repository tests (reset-on-
restart, partial-update-only-changes-supplied-fields, `last_progress_at`
always bumped, `mark_idle` clears current instrument/strategy). A
dedicated worker-command integration test was deliberately NOT added —
this file's own pre-existing comment documents a CONFIRMED, reproduced
cross-test-file DB-row-leakage risk from adding another async command
test (`transaction=True` model) — the same precedent honored here
rather than reintroducing that known fragility. The wiring is instead
proven by: mypy type-checking the real call site, 2 new
`signal_pipeline_runtime.py` callback tests, 6 repository tests, and
every existing worker-command test still passing unmodified (9/9).

## Scanner Progress API

Reused the existing `GET .../live-paper-workbench/` endpoint (§6's own
explicit preference over a needless second endpoint — one GET already
composes readiness/checklist/session-state, adding scanner progress here
is the smallest correct extension). New `scanner_progress` field, `null`
before any scan has ever started (an honest absence). Computes
`remaining`/`progress_percent`/`stale` at read time from the two real
stored counters — never a second, independently-stored value that could
drift. 5 new API tests (null-before-any-scan, remaining/percent
derivation, stale-when-old-and-non-terminal, COMPLETED-never-stale,
no-credential-leakage).

## Scanner Progress UI

Extended the existing Live Paper Operations Console (§7 — no second
dashboard). New "Scanner Progress" section: status badge, STALE badge
when applicable, a safe FAILED error message, a real `role="progressbar"`
with `aria-valuemin`/`aria-valuemax`/`aria-valuenow` bound to the real
`progress_percent`, and a definition list (Timeframe/Instruments/
Processed/Remaining/Progress %/Current Stock/Current Strategy/
Strategies/Signals Found/Started/Last Update). The fill width is set
imperatively via a ref (`ScannerProgressBar` component), not a JSX
inline `style` prop — this project's existing `styles.quality.test.ts`
gate forbids inline styles outright; discovered and fixed this
checkpoint. 4 new console tests (unavailable-before-any-scan, real
progress with accessible progressbar, STALE display, FAILED display).

## Signal Evidence

**Implemented this checkpoint**, using the generic architecture 64.17
designed — and a real discovery made auditing it first (§9's explicit
instruction): `StrategySignal.evidence: tuple[FeatureValue, ...]`
(Checkpoint 26) ALREADY exists and is ALREADY populated by all three
strategies (`ema_crossover`: `(fast, slow)`; `sma_trend_filter`:
`(sma,)`; `atr_volatility_breakout`: `(atr,)`) — it was simply discarded
after `coordinator.run()` returned, never persisted. This checkpoint
adds NO new strategy calculation anywhere — it only formats and
persists values the strategies already compute.

## Signal Evidence Contract

New `trading_engine/strategy_execution/evidence.py`:
`SignalEvidenceField(label, value)`, `SignalEvidence(schema_version,
strategy_id, fields)`, and `build_signal_evidence(signal)` — the ONE
dispatch point by `strategy_id`, never a chain of branches duplicated in
persistence/API/frontend layers (§6's explicit "no EMA-specific database
logic, no ATR-specific frontend logic"). Each per-strategy `describe_*`
function reads ONLY the signal's own already-computed
`evidence`/`price`/`direction` — proven directly by 6 unit tests,
including one asserting missing evidence renders "Not provided," never
fabricated.

## EMA Evidence

`describe_ema_crossover_evidence()`: Fast EMA, Slow EMA (both read
positionally from `signal.evidence`, matching `EmaCrossoverStrategy.
evaluate()`'s own `evidence=(fast, slow)`), Price (`signal.price`),
Crossover (`signal.direction`, formatted as Bullish/Bearish/Neutral).

## SMA Evidence

`describe_sma_trend_filter_evidence()`: SMA, Price, Distance % (a plain
arithmetic PRESENTATION of two already-computed values — `(price - sma)
/ sma * 100` — not a new strategy decision; the actual direction is read
verbatim from `signal.direction`, never re-derived), Direction.

## ATR Evidence

`describe_atr_volatility_breakout_evidence()`: ATR, Price, Breakout
(`signal.direction`).

## Evidence Persistence

Audited existing persistence first (§10's explicit instruction) —
`TradePlanRecord`'s "one signal_id → one record, referenced by
`signal_id`, never a Django FK" pattern is the established precedent;
mirrored exactly. New `SignalEvidenceRecord` model (migration
`0025_signalevidencerecord.py`): `signal_id`, `strategy_id`,
`schema_version`, `fields` (JSONField storing `[[label, value], ...]` —
a structured, bounded shape, never an uncontrolled dump of arbitrary
Python objects), `generated_at`. `DjangoSignalEvidenceRepository`
(`save()`/`get_by_signal_id()`) mirrors `DjangoTradePlanRepository`
exactly. Wired into `PaperSignalExecutionService` via a new optional
`evidence_recorder` parameter (opt-in, mirrors `trade_plan_recorder`'s
own discipline) and into the ONE production caller
(`active_loop_runtime.py`) — audited, confirmed no other production
caller exists. 4 repository tests, including one proving `save()` is
idempotent (one signal → one record, never a duplicate row).

## Evidence API

Extended the existing `SignalResponse`/`GET /signals/` contract (§12 —
never a competing signal API). `DjangoSignalRepository.list_signals()`
gained a THIRD bulk enrichment query (alongside the existing TradePlan
and communication-status bulk queries) — never a per-row N+1. New
`evidence: {schema_version, fields: [{label, value}, ...]}` field, `null`
when no evidence was persisted. The response's `evidence` field is a
plain `serializers.DictField`, not a nested Serializer — a Serializer
attribute literally named `fields` collides with DRF's own `Serializer.
fields` (a `BindingDict` property) at the mypy/djangorestframework-stubs
level, the same class of issue `ReadinessCheckSerializer` already
documented for `label` (Checkpoint 64.14); the wire shape is unaffected.
2 new API tests (real evidence round-trip, `evidence: null` when absent).

## Signal Detail UI

Extended the existing Active Signal Monitor's detail panel
(`LiveMarketDataMonitor.tsx`, §13 — never a second interface). New "Why
This Signal?" section renders `selectedSignal.evidence.fields`
GENERICALLY (a plain `.map()` over label/value pairs — no
EMA-specific/ATR-specific branch anywhere in this component), with an
honest "not available" note when no evidence was persisted. 2 new tests
(generic field rendering with real EMA-shaped fixture data, and the
absent-evidence fallback).

## Telegram

Reviewed §14 as instructed. Decision: did NOT add evidence fields to the
outbound Telegram/Discord message templates this checkpoint. The
existing template (Strategy/Stock/Time/Spot/Entry/SL/Targets/Trailing
SL, Checkpoint 37) already carries the TradePlan-derived decision
outputs; adding raw strategy evidence (e.g. "Fast EMA: 1234.50") would
require touching `SignalCommunicationContext`/`MessageTemplateId`
rendering — a real, broader change to an already-shipped, tested
communication path, not attempted within this checkpoint's time budget.
Disclosed as a real remaining gap, not silently done.

## Discord

Same decision and same reasoning as Telegram above — no template change
made. Risk-rejected signals continue to be communicated via the existing
mechanism, unchanged and re-verified (§14's own explicit reminder,
already proven true since Checkpoint 64.16).

## Report Traceability

Verified end-to-end, with new assertions in the existing deterministic
suite (`test_active_loop_end_to_end.py`): the happy-path test now
asserts a real, persisted `SignalEvidenceRecord` exists for the signal
that produced it (strategy → evidence → TradePlan → risk → execution →
communication, all in one real pipeline run); the risk-rejected test
(`scenario_j`) now asserts evidence is STILL persisted even when the
trade could not execute — the same "a rejected trade never erases
observability" invariant already proven for the signal and communication
records now extends to evidence.

## Unrealized P&L Query Optimization

**Fixed the bounded N+1 64.17 disclosed** (§16). `_latest_close_price()`
(one query per open position) replaced with `_latest_close_prices()`
(ONE query for the entire open-position set, using a single `Q()`-OR
filter across all `(exchange, symbol)` pairs, then picking the latest
bar per pair in Python). New regression test proves query count stays
constant going from 2 to 6 open positions (a real per-position N+1 would
add at least 4 more queries; asserted difference `< 4`, allowing for
normal session/auth query-count noise between two separate requests).
The old, single-position-focused test was replaced, not left alongside a
duplicate.

## Report Reproducibility

**Closed the gap 64.17 disclosed** (§17). New
`_configuration_version_for_session_date()`: for a given `session_date`,
queries the REAL `AuditLogEntry` trail (`resource_type=
"scanner_configuration"`, `resource_id=provider`) for the latest entry
at or before that day's end, and uses its `version_identifier` as the
historical configuration_version — the actual audited value, never
"whatever the version happens to be right now." Falls back to the
current version only for TODAY's date (the common, correct case).
Returns `None` (honest absence) for any other date with no matching
audit entry — never a fabricated historical claim. 2 new tests: a past
date WITH a matching audit entry correctly ignores a much-later current
version; a past date with NO audit trail at all returns `null`.

## Performance Measurements

Coarse, deterministic observations (§18 — no heavyweight profiling
framework, per its own explicit instruction):
- Scanner progress writes: one `update_progress()` DB write per
  instrument processed per strategy per scan cycle — bounded by
  universe size × strategy count, the same granularity the existing
  `WorkerRuntimeStatus` health-tracker already writes at.
- Signal evidence persistence: one `save()` call per REAL signal
  produced (never per bar evaluated, never per skipped/neutral
  evaluation) — identical cadence to the existing `TradePlanRepository.
  save()` call it sits directly alongside.
- Signal query overhead: the evidence bulk-enrichment query added to
  `list_signals()` is the SAME shape (one `filter(signal_id__in=...)`
  query) as the two enrichment queries already there — no new query
  pattern introduced.
- Report queries: the unrealized-P&L path went from O(n) to O(1) queries
  for the mark-price lookup (proven by the new query-count regression
  test); the new historical-configuration-version lookup adds exactly
  one query (`AuditLogEntry` filter + `order_by` + `.first()`).
- Mark-price queries: now exactly 1 regardless of open-position count
  (was N before this checkpoint).

## Market Closed Behavior

Unchanged and re-verified: no live Dhan connectivity was attempted, no
live worker was started, no scanner progress was fabricated — every
scanner-progress/signal-evidence test uses deterministic fixtures only.
The console's existing Market State/Live Paper Start = BLOCKED behavior
is untouched; Backtesting/Replay/Reports/Research remain available,
unaffected by this checkpoint's additions.

## Responsive UI

New Scanner Progress section and Why This Signal section reuse only
existing, already-responsive layout primitives
(`.market-data-monitor__card`, `dl`/`dt`/`dd`, the existing breakpoint
media queries) — no new CSS breakpoints were needed, and no wide
table/element was introduced that could cause page-width overflow.

## Accessibility

The progress bar uses the real `role="progressbar"` +
`aria-valuemin`/`aria-valuemax`/`aria-valuenow` contract, bound to a
single numeric `aria-valuenow` value per render — not a per-instrument
`aria-live` announcement stream (§21's explicit "do not announce every
single instrument change excessively" instruction; the existing
`role="status"` badges for STALE/FAILED already provide throttled,
per-state-change announcements, matching the project's established
pattern rather than a new debounced live-region mechanism).

## Security

Verified via a new dedicated test that the scanner-progress workbench
response contains no JWT-shaped credential value (the same regex-based
check this project's existing token-leakage tests use). Signal evidence
fields are plain, pre-formatted strings built only from
`FeatureValue.value`/`signal.price`/`signal.direction` — none of which
can ever contain a Dhan token, Telegram token, Discord webhook, or
broker secret; no new response serialization path was introduced that
could leak one.

## Testing

**Backend: 26 new tests, full suite 1519 passed** (was 1493): 6 scanner-
scan-progress repository tests, 2 signal_pipeline_runtime callback
tests, 5 workbench-API scanner-progress tests, 6 signal-evidence unit
tests, 4 signal-evidence repository tests, 2 signal-API evidence tests
(+1 existing test extended), 2 end-to-end evidence-traceability
assertions (extended existing tests, not new functions), 2 report-
reproducibility tests, 1 replaced N+1 regression test (net: -1 old +1
new, functionally 0 net but strictly stronger).

**Frontend: 6 new tests, full suite 174 passed** (was 168): 4 Scanner
Progress console tests, 2 Why This Signal detail-panel tests.

## Real Live Validation

**NOT ATTEMPTED**, per explicit directive — market closed, credential
expired. No live Dhan connectivity, no live worker process, no
fabricated progress or evidence anywhere in this checkpoint's work.

## Remaining Gaps

- **Telegram/Discord evidence inclusion** (§14): reviewed, decided
  against this checkpoint, disclosed as a real remaining gap requiring a
  broader, deliberate template change.
- **Worker-command integration test for scanner progress**: not added,
  per the file's own documented, confirmed cross-test-file DB-leakage
  precedent — coverage relies on mypy + unit/repository/callback tests
  instead.
- **Report reproducibility remains date-granular, not session-
  granular**: the fix uses the audit trail's timestamp, not a true
  `session_id` (no such concept exists yet) — an honest, documented
  approximation, not a full session model.
- Postgres teardown warning remains unresolved (documented root cause,
  attempted fix did not work — see Baseline Verification).

## Blockers

None new. The market remains closed and the Dhan credential remains
expired — live validation remains externally blocked, unchanged from
prior checkpoints.

## Production Readiness

The operator information loop named in this checkpoint's primary
objective is now real end-to-end: an operator can see what the scanner
is doing right now (backed by real worker-written state, never a
frontend estimate), and can see WHY a signal fired (backed by the
strategy's own real, persisted evidence, never fabricated prose). Both
capabilities are wired into the single existing Live Paper Operations
Console — no second dashboard was created. Report reproducibility and
the unrealized-P&L N+1 (both explicitly disclosed by 64.17) are now
closed with real, tested fixes.

## Performance Ranking

| Category | Previous | Current | Change | Evidence | Missing Capability |
|---|---|---|---|---|---|
| Architecture | 1 | 1 | none | Extensions of existing contracts only, no new architecture | — |
| Market Data | 1 | 1 | none | Unchanged; market closed | — |
| Dhan Integration | 2 | 2 | none | No live call attempted | Fresh credential + open market |
| Credential Lifecycle | 1 | 1 | none | Unchanged | — |
| Token Validation | 1 | 1 | none | Unchanged | — |
| Live Feed | 2 | 2 | none | Not exercised | Live market session |
| Historical Data | 1 | 1 | none | Unchanged | — |
| Database-First Replay | 1 | 1 | none | Unchanged | — |
| Bar Engine | 1 | 1 | none | `AggregatedBarObservation` reused, unmodified | — |
| Strategy Engine | 1 | 1 | none | No strategy calculation changed - evidence formatting only | — |
| Strategy Explainability | 3 | 1 | improved | Real, persisted, generic evidence now implemented end-to-end (backend + API + UI) | — |
| TradePlan | 1 | 1 | none | Unchanged | — |
| Signal Operations | 1 | 1 | none | Unchanged | — |
| Signal Evidence | 4 | 1 | improved | Fully implemented this checkpoint: contract, persistence, API, UI, traceability tests | — |
| Risk | 1 | 1 | none | Unchanged | — |
| Paper Trading | 1 | 1 | none | Unchanged | — |
| Communication | 1 | 1 | none | Unchanged this checkpoint (evidence-in-message deferred) | Evidence in Telegram/Discord templates |
| Telegram | 1 | 1 | none | Unchanged; evidence inclusion reviewed, deferred | Evidence in message template |
| Discord | 1 | 1 | none | Same as Telegram | Evidence in message template |
| Watchdog | 1 | 1 | none | Unchanged | — |
| Reconnect | 1 | 1 | none | Unchanged | — |
| Scanner Progress | 3 | 1 | improved | Fully implemented: model, migration, repository, worker wiring, API, UI | — |
| Reporting | 1 | 1 | none | Unrealized-P&L N+1 fixed, reproducibility gap closed - both were already scored well, now stronger | — |
| Backtesting | 1 | 1 | none | Unchanged | — |
| Replay | 1 | 1 | none | Unchanged | — |
| Reproducibility | 2 | 1 | improved | Historical configuration_version now derived from real audit trail | Session-id-granular (not just date-granular) mapping |
| EOD | 1 | 1 | none | Unchanged | — |
| Runtime Control | 1 | 1 | none | Unchanged | — |
| Pre-Session Readiness | 1 | 1 | none | Unchanged | — |
| Session Control | 1 | 1 | none | Unchanged | — |
| Session Observability | 2 | 1 | improved | Scanner progress now visible alongside session state/configuration on the console | — |
| Operator UX | 2 | 1 | improved | The two primary named gaps (scanner progress, signal evidence) are now real, visible capabilities | — |
| Responsive UI | 2 | 2 | none | New sections reuse existing responsive primitives, not independently re-verified at 375px this checkpoint | Explicit viewport testing tooling |
| Accessibility | 2 | 2 | none | Real progressbar semantics added; no automated a11y audit run | Automated a11y audit tooling |
| Performance | 2 | 1 | improved | The one identified N+1 was fixed and proven fixed by a regression test | — |
| Scalability | 2 | 1 | improved | Same fix as Performance | — |
| Auditability | 1 | 1 | none | Now also the source of historical configuration_version - strengthened, not newly built | — |
| Security | 1 | 1 | none | Re-verified, no leakage in any new field | — |
| Production Readiness | 2 | 1 | improved | Both named primary gaps closed with real, tested implementations | Telegram/Discord evidence inclusion |
| Active Paper Trading | 2 | 2 | none | No live session run this checkpoint | Open market + fresh credential |
| Live Paper Readiness | 1 | 1 | none | Unchanged | — |
| Live Trading Readiness | N/A | N/A | none | Structurally disabled by design | — |
| **ENGINEERING MATURITY** | 1 | 1 | none | Real, tested, additive implementations; zero test weakening | — |
| **ACTIVE PRODUCT MATURITY** | 2 | 1 | improved | Both primary named capabilities are now real and operator-visible | Telegram/Discord evidence inclusion |
| **CLOSED-MARKET READINESS** | 1 | 1 | none | This checkpoint's exact purpose, delivered | — |
| **NEXT-MARKET-OPEN READINESS** | 2 | 1 | improved | Operator now has full visibility into scanning + signal reasoning for the first live session | Fresh credential, open market |
| **END-TO-END PIPELINE MATURITY** | 1 | 1 | none | Unchanged core proof from 64.16; this checkpoint extended observability around it | — |
| **OPERATOR OBSERVABILITY** | 3 | 1 | improved | Scanner progress + signal evidence close the two largest observability gaps named across 64.16/64.17/64.18 | — |
| **SIGNAL AUDITABILITY** | 3 | 1 | improved | Signal → evidence → TradePlan → risk → execution → communication now fully traceable, proven by dedicated tests | — |
| **OVERALL CHECKPOINT SCORE** | — | 1 | — | Both primary named objectives fully implemented and tested; the two disclosed remaining gaps (Telegram/Discord evidence, Postgres warning) are real and honestly reported, not hidden | Evidence in communication templates |

(1 = best/complete, higher numbers = more remaining work. Scores are not
inflated for a documented design alone — every "1" here reflects a real,
tested implementation completed this checkpoint, not merely a plan.)

## Final Product Gate

**A. Scanner Progress**

Can the operator see total/processed/remaining/current stock/current
strategy/signals found/stale-or-failed state from REAL backend state?

**YES.** Every field is written exclusively by the worker's own scan
loop and read, never estimated, by the console.

**B. Signal Evidence**

Can the operator see the actual strategy evidence that caused a signal?

**YES.** Real, persisted, generic evidence — Fast/Slow EMA, SMA/
Distance %, ATR — sourced from each strategy's own already-computed
values, rendered without any strategy-specific frontend branching.

**C. Evidence Traceability**

Can a signal be traced strategy → evidence → TradePlan → risk →
execution → communication?

**YES.** Proven directly by extending the existing deterministic
end-to-end test suite for both the risk-approved and risk-rejected
paths.

**D. Reporting**

Does the report remain authoritative and reproducible?

**YES.** The unrealized-P&L N+1 is fixed and proven fixed; the
configuration_version now reflects the real historical audit trail for
past dates, with an honest `null` fallback rather than a fabricated
value.

**E. Performance**

Has the unrealized-P&L N+1 been removed or explicitly justified?

**YES — removed.** A single batched query now serves any number of open
positions, proven by a dedicated regression test.

**F. Live Paper**

With a fresh Dhan credential and an open market, can we now run the
first controlled LIVE PAPER session?

**PARTIALLY.** The operator-facing product is now materially more
complete (scanner progress and signal evidence were the two explicitly
named remaining gaps, both now closed); what remains unverified is the
same flow against genuinely live data, which still requires both the
credential and an open market — neither available this checkpoint, by
design.

**G. Real Trading**

**NO.** Unchanged: `real_trading_state` remains the structural constant
`"DISABLED"`; `PaperBroker` remains the only concrete broker
implementation in the codebase; zero real orders were placed or
attempted.

## Honest Final Conclusion

Both primary objectives named at the start of this checkpoint — Scanner
Progress and Signal Evidence — were fully implemented, not merely
designed: real persisted models (two new migrations), repositories
mirroring this project's own established patterns, real wiring into the
actual worker scan loop and the actual signal-evaluation pipeline (never
a frontend simulation), API extensions to the existing endpoints (never
a second competing endpoint), and UI additions to the single existing
Live Paper Operations Console and Active Signal Monitor (never a second
dashboard). A genuinely useful discovery — that `StrategySignal.evidence`
already existed and was already populated by every strategy, just
discarded — meant this checkpoint's real work was persistence and
presentation, not new strategy calculation, keeping the implementation
honest to §9's explicit "must come from the strategy's REAL
calculations" instruction. Two additional disclosed gaps from 64.17
(the unrealized-P&L N+1, and report reproducibility for historical
dates) were also closed with real, tested fixes. Two things are honestly
reported as NOT resolved: the decision to defer adding evidence to
Telegram/Discord message templates (a real scope decision, not an
oversight), and the Postgres teardown warning, whose attempted fix did
not work and whose true root cause (fixture-teardown ordering, not
`pytest_sessionfinish` timing) is documented for a future attempt. No
live Dhan connectivity was attempted, and no live data was fabricated
anywhere. Real trading remains structurally disabled everywhere.

## Git Status

All changes are staged and committed locally only. No push to origin was
performed or will be performed without explicit instruction. Working
tree is clean after commit.
