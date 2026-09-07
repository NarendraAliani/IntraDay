# MEMORY.md — Standing Context Bootstrap

Written because `C:\Users\Admin\.claude\projects\d--IntraDay\memory\`
was found empty — this file captures only what is actually evident
from this conversation's history, so a future session with no
persisted memory can pick up standing conventions without
re-deriving them. Not a full transcript; no invented detail.

## 1. Standing operating rules

- **One `.md` summary per checkpoint, committed, before the next
  prompt is issued.** Every checkpoint in this conversation
  (`67.12.2-D` through `LIVE-2`) produced a
  `CHECKPOINT_<NAME>_SUMMARY.md` at repo root, and it was committed
  to `active-development` as part of that same checkpoint's work —
  this was stated explicitly as a standing instruction mid-session
  ("Write an `.md` summary file for this checkpoint — this is now a
  standing instruction for every future checkpoint, not just this
  one").
- **Work happens only on `active-development`.** Never `main`. This
  matches `CLAUDE.md`'s own P16 ("One persistent working branch...
  `main` is not committed to by any checkpoint") and P11 (commit only
  when explicitly authorized for that checkpoint, never push without
  separate explicit authorization).
- **Independent verification discipline.** Every claim reported to
  the operator as confirmed was independently re-checked in this
  conversation — re-running a claimed test, re-reading an actual
  `git diff`, re-running a DB query directly — rather than trusting a
  delegated agent's or an earlier document's assertion. This caught
  real errors more than once (see §3 and the checkpoint summaries
  themselves for specifics) and matches `CLAUDE.md`'s own `[F]`/`[D]`/
  `[I]` evidence-tagging convention.
- **No DB writes / no persistence unless explicitly authorized for
  that specific task.** Walk-forward smoke tests (`68.3`, `68.4`,
  `LIVE-2` Stream 2) were run via `run_walk_forward_backtest()`
  directly and never via `BacktestingService.run()` (the only path
  that persists a `BacktestResultRecord`) specifically so nothing
  would be written — and `BacktestResultRecord.objects.count()` was
  checked before and after each such run to prove it.
- **No migration execution, no production-identity work, without an
  explicit operator decision.** The canonicalization migration control
  plane (`migration_67_10`, `migration_production_execute`, and the
  supporting gate modules) has been built and tested against the
  disposable test database only. Running it against real production
  data is explicitly left as a future, separate, operator-initiated
  decision — not a blocker, a deliberate deferral.
- **Sensitive/hard-to-reverse live-system actions go through
  `AskUserQuestion` first.** Writing a live `ScannerConfiguration` row
  and launching a real Dhan-connected supervisor process in `LIVE-2`
  were both preceded by an explicit `AskUserQuestion` approval before
  any tool call acted on them.
- **A real Dhan network call is handled directly, not delegated to a
  subagent.** Read-only queries and real-service-path computation
  (no live connection) have been delegated to background agents in
  this conversation, but every step that opens an actual Dhan
  WebSocket/API connection has been done directly.

## 2. Architecture facts learned during this conversation

- **`CLAUDE.md`'s P1-P16 govern this repo** (paper-trading-only, no
  live orders, no Dhan order calls, no unauthorized DB writes, no
  `HistoricalBar` mutation, no weakening of an existing safety guard,
  no fingerprint/checksum semantics change without authorization, the
  `active-development`-only branch rule, etc.) — referenced
  throughout this conversation as the effective ruleset; see the file
  itself for the exact current wording rather than this summary.
- **Two-dimensional provenance/canonicalization model on
  `HistoricalBar`**: `canonicalization_state`
  (UNCANONICALIZED/CANONICALIZED/NOT_APPLICABLE/UNKNOWN — a pure
  processing-state fact) is kept strictly separate from
  `source_timestamp_semantics` (OPEN/CLOSE/UNKNOWN/NOT_APPLICABLE — a
  pure semantics fact). Both must hold specific values for a row to
  be research-eligible via `ResearchDataGateService
  .get_research_eligible_bars()`.
- **`ResearchDataGateService.get_research_eligible_bars()`** applies,
  in order: a completeness gate
  (`HistoricalDataCoverageService.get_coverage(...).is_complete`), a
  provenance gate (`REAL_DHAN` only), a canonicalization gate
  (`canonicalization_state` AND `source_timestamp_semantics` both
  proven), and a migration-status fail-closed gate — raising
  `ResearchDataRejectedError` (never silently downgrading) on any
  failure. Confirmed in `LIVE-2` Stream 2 that this gate currently
  rejects every multi-day request against the CANONICALIZED subset of
  real data, due to a uniform 1-bar/day coverage gap (missing the
  `03:50 UTC` bar every day, all 4 symbols checked) — this is a newly
  surfaced finding, not previously documented.
- **`DhanHistoricalBarProvider.canonicalization_state_for()`**
  correctly stamps `CANONICALIZED` at write time for genuine new
  fetches into the one proven scope
  (`("NSE_EQ", Timeframe.FIVE_MINUTE, "CAS_ERA")`, the sole member of
  `_PROVEN_INTRADAY_SCOPES`). The separate, never-yet-executed
  migration control plane exists to retroactively upgrade
  pre-existing rows, not to gate new fetches — this distinction was a
  major discovery in checkpoint `68.4`.
- **Walk-forward tool**: `src/intraday/research/backtesting
  /walk_forward.py` — `compute_walk_forward_folds()`,
  `run_walk_forward_backtest()`. It wraps the existing, unmodified
  `engine.py::run_backtest()` (called twice per fold: in-sample,
  out-of-sample) without modifying it — confirmed via `git diff`
  against `engine.py` being empty when this module was built.
- **`run_walk_forward_backtest()` vs. `BacktestingService.run()`**:
  the former takes bars directly and never persists anything; the
  latter is the only method in the codebase that calls
  `self.repository.save(...)` on a `BacktestResultRecord`. Every
  real-data walk-forward run in this conversation
  (`68.3`/`68.4`/`LIVE-2` Stream 2) used the former exclusively, and
  checked the `BacktestResultRecord` count before/after to prove
  zero-persistence.
- **Three registered strategies** seen in use throughout this
  conversation, each with a saved configuration used repeatedly for
  walk-forward smoke tests: `ema_crossover` (config version
  `ema_conservative`: fast=12, slow=26), `sma_trend_filter` (config
  version `sma_conservative`: lookback=30, band=0.75%),
  `atr_volatility_breakout` (config version `atr_aggresive`:
  lookback=10, atr_multiplier=1.2). No confirmed detail from this
  conversation about a per-strategy "research status" field beyond
  this — not included here to avoid guessing.
- **The canonicalization migration's status**: built and tested
  (`67.7`-`67.13-C`) against the disposable test database only, never
  executed against real production data at any point in this
  conversation. `67.13-C` built a new, symmetric, three-gate
  production entry point (`migration_production_execute`,
  composing `verify_environment_identity()`, a dedicated
  test-database refusal, and `authorize_one_unit_execution()`) —
  built and proven-to-refuse, but never invoked with real arguments.
  This is a deliberate deferral pending the operator's own separate
  decision, not a blocker.
- **Live-capture supervisor crash-handling history and its two
  fixes** (checkpoint `LIVE-1-INSTRUMENT`):
  - *Per-attempt WebSocket close-code logging* — added because
    `LIVE-1-POSTMORTEM` found only an aggregate crash summary
    existed, not a per-attempt close code, making the original
    5-crashes-in-40-minutes cause impossible to diagnose. Verified
    working for real in `LIVE-2`: all 40 reconnect attempts (8
    crash cycles × 5 attempts each) logged a real close code
    (`close_code=1006`) individually.
  - *`sleep(poll_interval_seconds)` race fix in
    `market_data_worker_supervisor.py`* — fixes a "phantom restart"
    race where the supervisor could re-poll a stale `FAILED` status
    row immediately after restarting, before the new worker process
    had time to overwrite it. Verified working for real in `LIVE-2`:
    every one of the 8 crash-to-restart gaps measured exactly the
    full 15.0s cooldown, with no near-zero-elapsed restart recurring
    even once.
  - In `LIVE-2`'s actual run (2026-09-04), the supervisor still
    exhausted all 8 configured restarts and stopped itself
    permanently — every attempt failed identically with
    `close_code=1006` and zero quotes ever received. This was
    diagnosed as a real external connectivity problem separate from
    either fix (both fixes were confirmed working correctly on top
    of that failure), root cause undetermined as of that checkpoint.

## 3. Open/pending threads as of today

- **Gainz integration** — UPDATED, no longer "untouched": a
  `GAINZ_ROADMAP.md` recon (untracked, per its own checkpoint's rule)
  found a working `GainzCompatibleResearchStrategy`
  (`gainz_compatible_research.py`, Checkpoint 64.99,
  `strategy_id="gainz_compatible_research"`, deliberately NOT
  registered in `registry.py`) already existed, with 3 documented
  blockers (A: 20-bar breakout feature missing; B: no previous-bar
  feature-value channel; C: `regime` labeling — later found stale,
  `market_regime` was built one checkpoint later at 65.08). The
  roadmap re-scoped Phase B as "close 64.99's gaps incrementally,"
  not "build Gainz from scratch":
  - **BLOCKER A closed** at `CHECKPOINT-GAINZ-A` (`1af77bb`): a new
    canonical `rolling_breakout` feature
    (`signal_intelligence/feature_engine/rolling_breakout.py`,
    field_id `rolling_breakout`, default lookback 20, signed
    `1`/`-1`/`0` — breakout/breakdown/in-range), pure feature-engine
    addition, no strategy/registry change.
  - **Supersede-in-place decision** (made at `CHECKPOINT-GAINZ-B1`,
    not re-derived here — see that checkpoint's own directive): future
    Gainz strategy-logic changes extend `GainzCompatibleResearchStrategy`
    IN PLACE (same `strategy_id`/`specification_version`, bump
    `code_version`) rather than forking a second, parallel strategy
    identity. `CHECKPOINT-GAINZ-B1` bumped `code_version` `"v1"` →
    `"v2"` — the FIRST time any strategy in this codebase has ever
    bumped its own `code_version` (checked via `git log -p` on all 3
    registered strategies: none had ever bumped it before) — and, in
    the same checkpoint: replaced the equal-weight (1/8, now
    conceptually 1/9) scoring scheme with a
    `0.72*dominant_score + 0.28*separation` formula (`bull_score`/
    `bear_score` defined as the 0–100 proportion of 9 directional
    conditions satisfied per side), wired `rolling_breakout` in as a
    real 9th bull/bear condition (BLOCKER A closed FOR REAL, not just
    feature-availability), and added a `gainz_alpha_rejection_reason_code`
    evidence entry alongside the existing `setup_quality_score` one —
    all via `StrategySignal.evidence`, the existing extension point,
    with the frozen `StrategySignal` schema itself untouched.
    `market_regime` deliberately NOT wired in (a separate, explicitly
    deferred decision). `registry.py` NOT touched — the strategy
    remains unregistered/unreachable from the live scanner and
    backtest API after both Gainz checkpoints.
  - **Current Gainz roadmap phase status**: Phase A (feature layer)
    complete for `rolling_breakout`; Phase B in progress, first
    sub-step (`B1`, scoring formula + breakout wiring) done; BLOCKER B
    (previous-bar feature-value channel, an architecture gap) and
    BLOCKER C-successor (whether/how to wire `market_regime` in) both
    remain open, undecided, explicitly deferred — not silently routed
    around. Still **pending**: registration in `registry.py` (so the
    strategy becomes reachable from the live scanner/backtest API),
    any config-preset work, and any walk-forward proof for this
    strategy specifically.
- **`LIVE-2` live-capture connectivity failure**: Stream 1's
  `close_code=1006` / zero-quotes failure across all 8 restart
  attempts on 2026-09-04, root cause undetermined at checkpoint close.
  The operator chose to investigate this directly rather than have a
  further automatic relaunch attempted. `ScannerConfiguration(dhan)`
  was deliberately left at the non-default `SELECTED`/`5m`/15-symbol
  state (not reverted to its original `ALL_CONFIGURED`/`3m`) so a
  relaunch is ready once diagnosed. Status: **pending**, operator's
  own investigation, not yet resumed as of this file's writing.
- **`LIVE-2` Stream 2 coverage-gap finding**: `ResearchDataGateService`
  currently rejects every multi-day request against the CANONICALIZED
  real-data subset, due to a uniform 1-bar/day gap (missing `03:50
  UTC`/09:20 IST bar every day, all 4 symbols: RELIANCE, TCS,
  HDFCBANK, INFY). Root cause (a `DhanHistoricalBarProvider`
  fetch-boundary issue vs. a `HistoricalDataCoverageService`
  expected-bar-count miscalibration vs. something else) not yet
  investigated. Status: **pending**.
- **No genuinely research-eligible walk-forward result exists yet**
  this session/conversation — every real-data walk-forward run so far
  (`68.3`, `68.4`) either bypassed `ResearchDataGateService` directly
  or (in `LIVE-2` Stream 2, the one attempt that went through the
  real gate) was rejected outright by it. Status: **pending**, blocked
  on the coverage-gap finding above.
- **`LIVE-2-FINALIZE`**: an end-of-day close-out checkpoint for
  `LIVE-2` was requested with the premise that market had just closed
  on the same day as the `LIVE-2` run — but this conversation's
  current date is three days after `LIVE-2`'s actual run
  (2026-09-04), and market was confirmed open, not closed, at the
  time the finalize checkpoint was issued. Status: **pending** /
  being reconciled honestly against the stale premise, in parallel
  with this file.
- **Frontend/nav work**: earlier checkpoints in this conversation
  (`FRONTEND-1` through `FRONTEND-6`) covered icon/glyph audits,
  accessibility disclosure widgets, and a durable enforcement test —
  no further frontend work was open or requested as of the last
  frontend checkpoint seen in this conversation. Not marked pending
  here since no open frontend item was stated; noted only for
  completeness.
