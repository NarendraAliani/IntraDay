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
    around.
  - **CHECKPOINT-GAINZ-C** (extends B1 IN PLACE again, `code_version`
    `"v2"` -> `"v3"`, same `strategy_id`/`specification_version`,
    `registry.py`/`market_regime` still untouched): added a NEW gate,
    `minimum_setup_quality_score` (DECIMAL, default `Decimal("0")`, a
    deliberate NO-OP default), authorized directly by the operator
    after a genuine gap was found while building this checkpoint's own
    3 config presets — `setup_quality_score` was pure evidence, never
    a gate, so no preset could be proven to change a signal's actual
    `direction`, only its attached evidence number. When a genuine
    bull/bear winner exists (never for a tie -
    `REJECTION_REASON_TIE` still takes precedence) but
    `setup_quality_score` falls below the configured threshold,
    `direction` is downgraded to NEUTRAL with a new
    `REJECTION_REASON_BELOW_QUALITY_THRESHOLD` (`Decimal(2)`) - the
    score itself always stays in `evidence` unchanged. Created and
    verified (direct DB read) 3 real, persisted
    `StrategyConfigurationRecord` presets in the dev database via the
    real `StrategyConfigurationService.save_configuration()` path:
    `gainz_conservative` (`minimum_setup_quality_score=70`),
    `gainz_balanced` (`=55`), `gainz_aggressive` (`=40`) - each also
    varies `adx_minimum`/`relative_volume_minimum`/
    `candle_body_ratio_minimum`/`rsi_alpha_threshold` by strictness
    tier; every indicator-lookback-window parameter is deliberately
    identical across all 3 (feature parameters, not risk parameters).
    Proved per-preset gating behaviorally (`test_checkpoint_gainz_c_
    presets.py`, 5 tests, all passing): the SAME hand-computed
    `evaluate()` feature set produces 3 DIFFERENT outcomes depending
    only on which preset's config is passed in (score=68 -> BULLISH
    under aggressive/balanced, NEUTRAL under conservative; score=52 ->
    BULLISH only under aggressive; score≈25.33 -> NEUTRAL under all 3,
    with a control case confirming the NO-OP default would have let
    that same weak signal through un-gated). Full before/after test
    suite comparison (both runs synchronous, foreground, `--reuse-db`,
    ~10-11 min each): BEFORE (clean `763c19e` tree) 5 failed/1
    error/3277 passed; AFTER (full GAINZ-C diff) 7 failed/3281 passed
    - exact-name comparison found **zero genuine regressions**: 5
    failures identical in both runs (pre-existing, files this
    checkpoint never touches), 1 flaky/order-dependent test
    (`test_notification_channel_registry_lists_telegram_and_discord`)
    present only in BEFORE and confirmed passing in isolation, and 2
    failures present only in AFTER
    (`test_canary_backup_restores_with_exact_field_preservation_in_
    disposable_db`, `test_h_live_backup_restored_three_way_equality`)
    confirmed via `--create-db` to be stale-disposable-table
    contamination left by an earlier, unrelated interrupted
    `manage.py shell` process THIS SAME SESSION, not caused by any
    code this checkpoint changed (neither migration test file, nor
    anything they import, appears in the diff). See
    `CHECKPOINT_GAINZ-C_SUMMARY.md` for the full exact-name failure
    tables and reasoning. Still **pending** after GAINZ-C too:
    registration in `registry.py` (deliberately out of scope every
    Gainz checkpoint so far) and any walk-forward proof for this
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
- **UPDATE (`CHECKPOINT_69`/`CHECKPOINT_70`): the `LIVE-2` Stream 2
  coverage-gap finding above is RESOLVED**, and its "pending" status
  and the "no genuinely research-eligible walk-forward result exists
  yet" bullet above are both now stale. Root cause (found by
  `CHECKPOINT_69`, confirmed via a controlled, zero-persistence
  diagnostic in `LIVE-4` beforehand): `_provider_request_envelope()`'s
  `from_time` widening was one bar-duration too narrow — Dhan's
  `fromDate` comparison is EXCLUSIVE, so a single bar of widening
  still landed on the immediately-preceding candle's own timestamp,
  which Dhan then also excludes for the same reason. Fix: widen by
  TWO bar-durations instead of one (`historical_provider.py:301-323`,
  regression-tested through the real, unbypassed
  `HistoricalDataPreparationService` path). `CHECKPOINT_69` then
  recovered the day-start bar for all 13 already-known-gapped
  CANONICALIZED days (RELIANCE/TCS/HDFCBANK/INFY, 52 rows, 1/day, zero
  duplicates/alterations) and proved the real `ResearchDataGateService`
  now ACCEPTS a genuine multi-day CANONICALIZED request end-to-end for
  the first time this session (720/720 bars, RELIANCE
  2026-08-03..08-14). `CHECKPOINT_70` then widened the backfill
  forward to the most recent closed trading day (+3 new days,
  2026-09-03/09-04/09-07, 216 rows/symbol, every new day landing as a
  complete, genuinely fresh 72-bar day — proving the fix holds on data
  it never diagnosed against, not just the originally-fixed range) and
  ran the first proper gate-verified walk-forward comparison across
  ALL 4 strategies (`ema_crossover`, `sma_trend_filter`,
  `atr_volatility_breakout`, and all 3 `gainz_compatible_research`
  presets) against 1,152 bars / 16 real, gate-verified trading days
  (two separately gate-accepted CANONICALIZED blocks concatenated
  around the still-untouched, still-`UNCANONICALIZED`
  `2026-08-17`..`2026-08-28` interior gap - that specific gap remains
  a SEPARATE, unresolved issue, not addressed by this fix). Honest
  finding: the legacy 3 strategies' qualitative comparative picture
  from `68.4`'s mixed/bypassed dataset does NOT hold up unchanged
  under the real gate-verified subset (e.g. `ema_crossover` was
  consistently profitable in-sample in `68.4`, consistently
  unprofitable in-sample in both `69` and `70`) - still not enough
  data for real confidence in any of the 3. The Gainz presets' pattern
  (conservative: zero signals under this real data's actual score
  distribution; balanced/aggressive: consistently unprofitable,
  in-sample and out-of-sample, no sign flips) DID reproduce
  identically across two independent real datasets
  (`CHECKPOINT-GAINZ-D`'s mixed 25-day set and `CHECKPOINT_70`'s
  gate-verified 16-day set) - modestly stronger evidence for that
  specific claim, still far short of validation. No
  `RESEARCH_ACTIVE`/status change made for any strategy at either
  checkpoint, per the roadmap's own manual-gate finding.
- **`CHECKPOINT_71`: cross-symbol walk-forward (TCS/HDFCBANK/INFY,
  reusing `CHECKPOINT_70`'s already-backfilled/gate-verified data, no
  new fetch) + interior-gap recon.** Which of `CHECKPOINT_70`'s
  RELIANCE-only findings generalize: `ema_crossover`'s in-sample
  unprofitability now holds on ALL 4 symbols (12/12 fold/symbol
  in-sample returns negative) - genuinely cross-symbol-confirmed, not
  a RELIANCE artifact. `gainz_aggressive` is now the single most
  consistent result of this whole session: zero sign flips on every
  fold, all 4 symbols (12/12 same-signed, always negative);
  `gainz_balanced` nearly as consistent (1 small flip, HDFCBANK only).
  **`gainz_conservative`'s "zero signal" finding did NOT generalize** -
  RELIANCE/HDFCBANK/INFY all stayed silent (HDFCBANK's one IS-only
  trade never repeats in any OOS window, still functionally silent),
  but **TCS produced genuine non-zero IS and OOS trades** under the
  identical `minimum_setup_quality_score=70` threshold - the earlier
  "too strict to ever fire" characterization was RELIANCE-specific
  (and coincidentally also true for 2 other symbols), not universal;
  do not repeat it as a general property of the preset going forward.
  `atr_volatility_breakout` and `sma_trend_filter` both remain
  symbol-dependent and unstable (different flip fold/direction on
  every symbol, `atr`'s `mean_degradation_ratio` even changes SIGN
  between symbols) - reinforces the existing "not meaningful at this
  fold count" caveat rather than adding confidence either way. Still
  not enough for any `RESEARCH_ACTIVE`/trading decision - more
  instrument coverage, not more history, on the same 16-day real
  window. **Interior-gap recon**: `2026-08-17`-`08-28`'s
  `UNCANONICALIZED` state is CONFIRMED to be the already-known,
  already-documented migration gap (`67.7`-`67.13-C`), not a new or
  different issue - verified directly by calling
  `DhanHistoricalBarProvider.canonicalization_state_for()` for this
  exact range against TODAY's code, which returns `CANONICALIZED`
  (this range is comfortably inside the proven `(NSE_EQ, FIVE_MINUTE,
  CAS_ERA)` scope, `CAS_EFFECTIVE_DATE=2026-08-03`) - meaning these
  rows were written under an earlier processing state and are exactly
  the class of row the still-unexecuted migration exists to
  retroactively reclassify. No fix attempted (read-only recon, per
  the checkpoint's own rule); migration-execution remains the
  operator's own deferred decision, not re-litigated.
- **`CHECKPOINT_72`: lightweight recurring daily backfill routine
  built.** New Django management command `backfill_daily_coverage`
  (`src/intraday/infrastructure/persistence/management/commands/
  backfill_daily_coverage.py`, thin wrapper) + application service
  `daily_coverage_backfill.py` (`run_daily_backfill()`,
  `most_recent_closed_trading_day()`) — keeps RELIANCE/TCS/HDFCBANK/
  INFY's 5m coverage current by calling
  `HistoricalDataPreparationService.prepare()` (completely unmodified,
  no new fetch mechanism) for a `[most_recent_closed_trading_day -
  7 days, most_recent_closed_trading_day]` rolling window each run.
  **Operator-triggered only** — `.venv\Scripts\python.exe manage.py
  backfill_daily_coverage` (add `--dry-run` to preview, `--lookback-days
  N` for a one-off override). Deliberately NOT wired to the existing
  Celery Beat schedule (`src/intraday/celery.py` already runs 3 other
  tasks automatically) because that would make a REAL, unconditional
  Dhan network call every day with no per-run operator action — P6 and
  this checkpoint's own "no surprise automation" rule both forbid that;
  every real Dhan call this session has been explicitly triggered, and
  this preserves that. Automating it via Windows Task Scheduler is
  documented (not performed) in `CHECKPOINT_72_SUMMARY.md` §5 for the
  operator to opt into themselves. Idempotency and P4 (upsert-only,
  never mutates an existing row) both proven directly via dedicated
  unit tests, plus one real, explicitly-reported test against
  production data today confirming a genuine `api_requests=0`
  zero-network no-op. **Incidental finding while choosing the lookback
  value** (refines, does not contradict, `CHECKPOINT_71`'s interior-gap
  recon): the `2026-08-17`–`2026-08-28` gap is missing BOTH its
  day-start AND day-end bar every single day (70/72 bars, uniformly),
  not just the day-start bar — `DEFAULT_LOOKBACK_DAYS` was set to `7`
  (not the originally-tried `10`) specifically so this routine's window
  can never reach back far enough to touch that block. Not
  investigated further or fixed, per the checkpoint's own rule —
  remains the operator's same deferred migration decision.
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
