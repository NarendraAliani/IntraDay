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
- **`CHECKPOINT_73`: diagnosed WHY `gainz_aggressive`/`gainz_balanced`
  are consistently unprofitable (`CHECKPOINT_71`'s finding).** Read-
  only, RELIANCE/`gainz_balanced`, full 16-day gate-verified dataset,
  72 real trades pulled at the individual-trade level via
  `run_backtest()` directly. **Root cause, high confidence, precisely
  traced in code (not a statistical artifact)**: `gainz_balanced`'s
  TradePlan has `stop_loss` and `target_1` at the SAME distance
  (both `1.0x ATR`) — since `tradeplan_execution.py::
  simulate_tradeplan_exit()` is a single-shot, first-level-touched
  simulator (unmodified, shared code), price must pass through T1
  before ever reaching T2, so **T2/T3 are structurally unreachable**:
  all 72 trades closed at either `STOP_LOSS` (40) or `TARGET_1` (32),
  zero at T2/T3. This forces the REALIZED `risk_reward_ratio` to
  `0.22` (real costs) / `0.82` (zero costs, cleanly isolated via
  `cost_model=None` + `brokerage_percent=0`/`slippage_percent=0` on
  the same 72 trades) — below the ~1.0 a 40.3% win rate would need
  for break-even, even before costs. **Real transaction costs roughly
  TRIPLE the average per-trade loss** (-5.66 → -19.57 expectancy) but
  are a material AMPLIFIER, not the root cause (the zero-cost version
  is still net-negative). **This is shared infrastructure behavior,
  not Gainz-specific**: `atr_volatility_breakout` (the only other
  TradePlan-based strategy) shows the identical `{STOP_LOSS,
  TARGET_1}`-only exit pattern on the same data. **Most important
  honest finding**: ALL 4 strategies (not just Gainz) lost money on
  this exact real 16-day RELIANCE dataset — `ema_crossover`/
  `sma_trend_filter` are entry-signal-limited (favorable 1.65-1.69
  R:R completely overwhelmed by a 16.7%/27.3% win rate);
  `atr_volatility_breakout`/`gainz_balanced` are payoff-structure-
  limited (decent ~39-40% win rate undermined by ~1.0-or-below R:R).
  Gainz's 40.3% win rate is actually the BEST of all 4 tested - entry
  logic is not the problem. **Verdict**: a fixable, narrowly-scoped
  design issue (option (a), not (b) "needs a fundamentally different
  design" and not (c) "inconclusive"). **Precise fix for a future
  checkpoint, NOT implemented**: widen `target_1`'s ATR multiplier
  relative to `stop_loss`'s (e.g. keep SL at 1.0x, raise T1 to
  ~1.5-2.0x) - a pure config/preset value change, likely belonging at
  the shared parameter level since `atr_volatility_breakout` has the
  same issue, not only inside `gainz_compatible_research.py`. Status:
  **pending**, a real, well-evidenced next step, not yet authorized or
  scheduled.
- **`CHECKPOINT_74`: applied `CHECKPOINT_73`'s T1-widening fix
  (config-only) + re-tested + ran the first real, genuinely-new-day
  exercise of `CHECKPOINT_72`'s daily backfill routine.** Fix: raised
  `trade_plan_target_1_atr_multiplier` `1.0 -> 1.5` (SL stays `1.0x
  ATR`) for all 3 Gainz presets, via 3 NEW `StrategyConfigurationRecord`
  rows (`gainz_conservative_t1_widened`/`gainz_balanced_t1_widened`/
  `gainz_aggressive_t1_widened`, same `code_version="v3"`, existing
  rows never mutated - immutable by design/convention). **Important
  correction to `CHECKPOINT_73`'s own claim**: `atr_volatility_
  breakout`'s saved presets were checked directly and found to carry
  NO override for this parameter at all - the strategy's own schema
  default is already `1.5`, not `1.0` (never symmetric) - so the
  "shared symmetric SL=T1" explanation does not actually transfer to
  that strategy as cleanly as `CHECKPOINT_73` implied; deliberately
  NOT touched this checkpoint (reported, not silently skipped).
  **Re-test result, reported honestly, not oversold**: re-ran
  `CHECKPOINT_71`'s exact 4-symbol walk-forward suite for the 3 new
  presets - loss magnitude reduced in most cases (e.g. RELIANCE
  `gainz_aggressive_t1_widened` aggregate_oos_return improved -0.415
  -> -0.285; `gainz_balanced` mixed, 2 symbols better/2 slightly
  worse) but **zero sign flips anywhere** - every combination remains
  net-negative. Trade-level re-check (RELIANCE/`gainz_balanced_t1_
  widened`): `risk_reward_ratio` more than DOUBLED (0.22 -> 0.52),
  expectancy improved ~15% (-19.57 -> -16.63/trade), net_pnl loss
  shrank ~20% - a real, measurable, genuine partial improvement - but
  `exit_reason_breakdown` STILL shows only `{STOP_LOSS, TARGET_1}`,
  T2/T3 STILL never reached even at the new ratio, and expectancy
  remains clearly negative. **Explicitly NOT a fix - a partial
  improvement**, consistent with `CHECKPOINT_73`'s own findings that
  the win-rate/entry-signal side was never the primary problem.
  **Part 3, run for real after confirming the actual clock (market
  closed `~15:30 IST`, this ran at `15:38 IST` on `2026-09-08`)**:
  `backfill_daily_coverage`'s FIRST-EVER run against a genuinely new
  trading day (every prior run was either `--dry-run` or a same-day
  no-op against pre-existing data) - clean, exactly 72 new
  `CANONICALIZED` rows per symbol (RELIANCE/TCS/HDFCBANK/INFY), zero
  duplicates, `api_requests=1` per symbol (only the one genuinely new
  day fetched) - worked correctly on the first real try, and
  `CHECKPOINT_69`'s fix continues to hold on fresh data 5 checkpoints
  later.
- **`CHECKPOINT_75`: MFE (Maximum Favorable Excursion) diagnostic —
  final Gainz-tuning checkpoint, read-only, no parameter changes.**
  For RELIANCE/`gainz_balanced_t1_widened`'s 68 trades, computed each
  trade's real `SimulatedTrade.mfe` as a multiple of its own `atr_14`
  value at entry. **Answers `CHECKPOINT_73`'s open question directly**:
  T2/T3 are unreachable not ONLY because of the single-shot exit
  mechanism, but because price genuinely rarely travels that far -
  only 17.6% of trades ever reach 2.0x ATR favorably, and just 1.5%
  (1/68) ever reach 3.0x ATR, regardless of exit design.
  `atr_volatility_breakout` (already T1=1.5x) shows a similar shape
  (34.8% reach 2.0x, only 4.3% reach 3.0x) - confirms this is a
  real instrument/timeframe property, not Gainz-specific. **Verdict**:
  raising T1 further (e.g. to 2.0) does NOT have clearly favorable
  room - it would convert the 17 trades (25%) currently landing
  between 1.5x-2.0x MFE from winners into probable losers, a real
  trade-off, not a free improvement. **Real secondary finding**: 16.7%
  of Gainz's losing trades (25.0% of ATR's) showed genuine favorable
  excursion (>=1.0x ATR) before reversing into a stop-out - a
  trailing-stop (the `TradePlan.trailing_stop_loss` field already
  exists and `simulate_tradeplan_exit()` already reads it - Gainz's
  own `build_trade_plan()` just never populates it) is a real,
  evidence-backed idea for a FUTURE checkpoint, not evaluated further
  here. One unresolved, single-trade anomaly flagged honestly, not
  explained away (a `2026-08-31` BEARISH trade whose `TARGET_1` exit
  price sits above entry - plausibly a real gap at that block's
  boundary, not traced further as it would mean debugging exit-
  simulation code, out of this checkpoint's read-only scope).
  **GAINZ TUNING IS NOW EXPLICITLY PAUSED** - `73`/`74`/`75` all tuned
  or diagnosed against the SAME 16-17 real trading day dataset, a real
  overfitting risk this project's own roadmap Phase D exists to guard
  against. **Resumption criterion (concrete, checkable)**: do not
  resume Gainz parameter tuning until the real dataset (growing daily
  via `CHECKPOINT_72`'s routine) reaches **at least 30 real trading
  days beyond** the 17 already used as of `2026-09-08` (16
  gate-verified + `09-08` itself) - verify the current day count
  against `HistoricalBar` directly before considering resumption. A
  future checkpoint should treat this as a real gate, not a
  suggestion.
- **`RECON-VWAP-STRATEGY` (backfilled here - that checkpoint did not
  update this file itself, confirmed missing, added now alongside
  `CHECKPOINT-VWAP-A`'s own entry below): a genuinely NEW strategy
  thread started, unrelated to Gainz.** VWAP mean-reversion design
  (entry: price deviates from session VWAP by >=N x ATR; exit: target
  = VWAP itself or a fraction reverted; stop = wider M x ATR, M>N;
  4 parameters total, deliberately small - no multi-factor scorer).
  Read-only recon confirmed: no VWAP feature exists anywhere in
  `feature_engine/` (three search shapes, including `field_registry.py`'s
  own header comment explicitly documenting the absence); session-
  anchoring needs a genuinely NEW computation shape (no existing
  feature has a reset concept, only fixed `deque(maxlen=N)` windows),
  but the grouping primitive already exists and is proven elsewhere
  (`walk_forward.py`'s own `bar.timestamp.date()` grouping,
  `bars_by_date`); `Bar.timestamp.date()` in UTC alone is sufficient to
  detect session boundaries (NSE hours 09:15-15:30 IST = 03:45-10:00
  UTC never cross UTC midnight) - no IST conversion, no separate
  session marker needed. Reasoned (not yet proven) that a VWAP target
  likely avoids Gainz's T2/T3-unreachable trap, because the target
  distance (back to VWAP) scales with the SAME distance the entry
  condition already proved price could travel, unlike Gainz's
  independently-chosen T2/T3 multiples - flagged the real caveat too
  (VWAP itself can drift during a trending session; untested until
  Phase D). Full phased roadmap (`VWAP_STRATEGY_ROADMAP.md`, repo
  root, uncommitted per its own convention) written: A (feature) -> B
  (strategy, computing MFE/MAE from its OWN first run per the
  `CHECKPOINT_75` lesson, not deferred) -> C (2-3 presets) -> D
  (walk-forward, explicitly starting fresh against the now-working
  gate-verified dataset, no Gainz-style bypass history to inherit).
- **`CHECKPOINT-VWAP-A`: the VWAP feature itself, built and tested.**
  New `src/intraday/signal_intelligence/feature_engine/vwap.py`
  (`compute_session_vwap(definition, bars)`), new
  `SessionVwapDefinition` (`definitions.py` - no constructor fields,
  `feature_name` is the fixed string `"vwap"`, unlike every
  lookback-parameterized definition; kept for consistency with the
  `feature_name`/`feature_version`-derivation shape every other
  derived feature uses, per the checkpoint's own explicit
  `compute_session_vwap(definition, bars)` signature request - the
  alternative `candle_body_ratio.py`-style "no Definition object,
  just a field-id constant" shape was considered and explicitly not
  used here). Formula: typical price `(high+low+close)/3`, volume-
  weighted, cumulative from the first bar of each trading day, reset
  at every session boundary (`bar.timestamp.date()`, UTC). NO warm-up
  (first bar of a session already has a defined VWAP, unlike every
  lookback-based feature) - only skips a bar when cumulative volume is
  still exactly zero (mathematically undefined), matching
  `candle_body_ratio.py`'s own "skip, never fabricate" precedent for
  its analogous edge case. Wired into BOTH `field_registry.py` (new
  `_derived("vwap", ...)` entry) AND `compute_feature_series()`'s
  explicit dispatch (`if kind == "vwap":` branch) - confirmed both are
  required, per `CHECKPOINT-GAINZ-A`'s own already-documented finding
  that a registry entry alone is insufficient. 16 new tests, all
  passing, including the most important one for this feature: two
  consecutive trading days in one `bars` tuple, day 2's first bar
  proven to equal EXACTLY its own typical price (not blended with day
  1's very different price level) - confirms the session-reset
  actually works, not just that it doesn't crash. `registry.py` and
  every strategy file confirmed untouched (`git status --short` shows
  only the 3 expected `src/` diffs: the dispatcher, `definitions.py`,
  `field_registry.py`, plus the 2 new files). Full suite re-run after
  this checkpoint - see `CHECKPOINT_VWAP-A_SUMMARY.md` for the exact
  before/after failure-name comparison. Phase B (the strategy itself)
  is the next step in this thread, not yet started.
- **`CHECKPOINT-VWAP-B`: the VWAP mean-reversion strategy itself
  built, `registry.py` still untouched.** New `VwapMeanReversionStrategy`
  (`vwap_mean_reversion.py`), matching the `Strategy` Protocol
  structurally identical to `ema_crossover.py`. 4 parameters:
  `vwap_deviation_atr_multiplier` (N, default 1.5),
  `stop_loss_atr_multiplier` (M, default 2.5, must exceed N),
  `atr_lookback` (14), `target_reversion_fraction` (default 1.0 =
  target is VWAP itself). `evaluate()`: BULLISH when
  `close < vwap - N×ATR`, BEARISH when `close > vwap + N×ATR`, a real
  NEUTRAL signal object otherwise (matching `ema_crossover`'s own
  convention, not `None`). `build_trade_plan()`: SINGLE target only
  (`target = entry + fraction*(vwap-entry)`, direction-agnostic by
  construction), no T2/T3 ladder - the deliberate design choice meant
  to avoid Gainz's structural trap.
  **Honest finding, matches an existing but previously-unremarked
  gap**: `ParameterDefinition` has NO mechanism to express a
  cross-parameter constraint like "M must exceed N" - confirmed the
  SAME situation already exists, undocumented as a gap until now, in
  `ema_crossover.py`'s `slow_lookback`/`fast_lookback` and
  `atr_volatility_breakout.py`'s target ladder (both `help_text`-only,
  no runtime enforcement anywhere in this codebase). This strategy
  adds its OWN explicit, tested runtime guard instead (`build_trade_
  plan()` returns `None` when `M <= N`) - a real design decision, not
  a silent workaround; not retroactively applied to the other 2
  strategies (out of scope). 19 new unit tests, all passing.
  **First real backtest (explicitly a first look, NOT Phase D's
  validation gate)**: RELIANCE, default params, full gate-verified
  dataset (now 17 days/1224 bars - one day more than `CHECKPOINT_75`'s
  own figure, since `CHECKPOINT_74` added `2026-09-08` in the
  interim). 47 trades, win_rate 38.3%, risk_reward_ratio 0.61,
  expectancy -24.95/trade, net_pnl -1172.60 - **not profitable at
  default parameters**, reported plainly. MFE distribution (same
  method `CHECKPOINT_75` used for Gainz): 42.6% of trades reach >=2.0x
  ATR favorably (vs Gainz's 17.6%) - meaningfully more favorable
  excursion by design. But losing trades also show MORE pre-reversal
  favorable excursion than Gainz's did (62.1%/48.3% at >=0.5x/1.0x ATR
  vs Gainz's 16.7%/7.1%) - the same "trailing-stop candidate" pattern
  `CHECKPOINT_75` flagged for Gainz appears here too, more strongly -
  flagged as a future diagnostic candidate, not investigated further
  this checkpoint. Zero persistence throughout
  (`BacktestResultRecord` 208->208). Phase C (2-3 config presets) is
  the next step in this thread.
- **`CHECKPOINT-VWAP-C`: 3 real config presets for
  `vwap_mean_reversion`, zero code changes.** `vwap_tight` (N=1.0,
  M=2.0), `vwap_normal` (N=1.5, M=2.5 - the intended default, matches
  `parameter_schema()`'s own defaults), `vwap_wide` (N=2.0, M=3.0) -
  `atr_lookback=14`/`target_reversion_fraction=1.0` deliberately
  identical across all 3 (feature/target-completeness, not
  deviation-band parameters). Created via the real
  `StrategyConfigurationService.save_configuration()` path. M > N
  runtime guard (`CHECKPOINT-VWAP-B`) verified directly per preset's
  real persisted config, not assumed - all 3 produce a genuine plan.
  **Real behavioral divergence proven** (8 tests,
  `test_checkpoint_vwap_c_presets.py`): identical feature values
  (vwap=1000, atr=10) fed to all 3 presets - small deviation (-1.2x
  ATR) -> only `vwap_tight` signals; medium deviation (-1.7x ATR) ->
  `vwap_tight`+`vwap_normal` signal, `vwap_wide` stays NEUTRAL; large
  deviation (-2.5x ATR, control case) -> all 3 agree; symmetric check
  confirmed on the BEARISH side too. `registry.py` untouched, zero
  `src/` diff this checkpoint. Phase D (walk-forward validation) is
  the next and final step in this thread.
- **`CHECKPOINT-VWAP-D`: walk-forward validation gate for
  `vwap_mean_reversion`, all 3 presets, all 4 symbols - the final step
  in the VWAP thread.** Data re-checked directly: still 17 real
  trading days/symbol (unchanged since `CHECKPOINT-VWAP-B` - the daily
  backfill routine hasn't been re-run since `2026-09-08` itself).
  **Headline finding**: all 12 symbol x preset combinations produced a
  NEGATIVE `aggregate_oos_return` - no combination is net profitable
  at this sample size. Smallest loss: `INFY/vwap_normal` (-0.020);
  worst: `TCS/vwap_tight` (-0.379). Within every symbol, `vwap_wide`
  (or `vwap_normal` for INFY/HDFCBANK) lost LESS than `vwap_tight` -
  directionally consistent across all 4 symbols, though not acted on
  (would repeat the exact overfitting risk this session's own Gainz
  arc already flagged and paused for). **A real, honestly-flagged
  dataset artifact, not strategy skill**: fold 2's OOS window
  (`2026-09-01`-`09-03`, only 3 real days) flipped POSITIVE in 11 of
  12 combinations - far too consistent across every symbol/preset to
  be anything but a genuinely favorable short-term market window,
  reported as such rather than credited to the strategy.
  **Cross-strategy comparison (RELIANCE, same data family as
  `CHECKPOINT_70`)**: VWAP lands mid-pack - every VWAP preset beats
  `ema_crossover` (-0.290) and `gainz_aggressive` (-0.415), but every
  VWAP preset underperforms `atr_volatility_breakout` (+0.011, the
  session's ONE genuinely positive result) and `sma_trend_filter`
  (-0.052); `vwap_wide` (-0.065) comes closest but doesn't beat
  `sma_trend_filter`. **Answers `CHECKPOINT-VWAP-B`'s own open
  question directly**: the MFE-distribution advantage found there
  (VWAP reaches >=2.0x ATR favorably 42.6% of the time vs Gainz's
  17.6%) did NOT translate into net profitability anywhere - the same
  "favorable excursion alone doesn't create an edge" lesson
  `CHECKPOINT_75` already established for Gainz, now confirmed for a
  second, unrelated strategy design too. Zero persistence throughout
  (`BacktestResultRecord` 208->208). No `RESEARCH_ACTIVE`/status
  change made or implied, per every prior Phase D's own discipline.
  This closes all 4 phases (A/B/C/D) of the VWAP thread;
  `registry.py` remains untouched, the strategy remains unreachable
  from the live scanner/backtest API.
- **`CHECKPOINT_76`: `PROJECT_STRATEGY_STATUS.md` written (repo root,
  COMMITTED, a living reference - unlike the uncommitted roadmap
  docs).** Consolidates all 5 strategies' status/preset counts/best-
  worst walk-forward figures (every number re-cited from its source
  checkpoint), a full read of `FIRST_LIVE_PAPER_VALIDATION_PROCEDURE.md`
  (key finding: its own Success Criteria are infrastructure-only, no
  backtest-performance gate at all - this session's whole walk-forward
  arc was a self-imposed research bar, not a documented product
  requirement), current data status (17 real days/symbol), and a
  direct answer to "when can paper trading start" (technically now per
  the documented procedure; a stricter self-imposed "validated edge"
  bar is not yet met by any strategy - concrete criteria given: >=2 of
  4 symbols positive/no-flip on 30+ real days). Also formally extends
  `CHECKPOINT_75`'s Gainz tuning pause to `vwap_mean_reversion` by
  explicit analogy (no checkpoint had declared this for VWAP before).
  **Consult this file first** for any future "what's the current state
  of strategy X" question rather than re-deriving from individual
  checkpoint summaries.
- **`CHECKPOINT_77`: resolved the preset-vs-baseline gap + found a
  real, previously-undiscovered blocker to live paper trading.**
  Part 1: `ema_crossover`/`sma_trend_filter`/`atr_volatility_breakout`'s
  raw schema DEFAULTS all exactly match `FIRST_LIVE_PAPER_VALIDATION_
  PROCEDURE.md` §3's own documented baseline (12/26 EMA, 30/0.75% SMA,
  14/2.0/1.0/1.5/2.5/3.5/1.0 ATR) - but NONE of `atr_volatility_
  breakout`'s 3 saved presets does (including `atr_aggresive`, the one
  this session's own walk-forward checkpoints used - every value
  differs from the documented baseline). A first session should use
  raw schema defaults, not any saved preset, for ATR specifically.
  **Part 2's critical finding, traced directly in code, not assumed**:
  the REAL live signal-evaluation path
  (`signal_pipeline_runtime.py::promote_bars_and_trigger_signals()`)
  constructs a completely EMPTY `StrategyConfigurationValues({})` for
  every strategy, every tick - no default-fill exists anywhere
  downstream (`validate_configuration()` tolerates a missing key but
  never injects the default; `require_int`/`require_decimal` are raw,
  un-defaulted dict subscripts). A live session today would run,
  connect, ingest bars - but would NEVER produce a single real signal
  for any registered strategy (first parameter lookup raises
  `KeyError`, silently caught by the coordinator's own isolation
  boundary as a `StrategyExecutionFailure`). Confirmed no existing test
  exercises this real empty-`{}` path -
  `test_active_loop_end_to_end.py`'s own `_config()` helper always
  supplies real values instead. **Everything else checked out clean**:
  Dhan credential VALID (expires `2026-09-09 10:17:40 UTC`),
  `PaperBroker` confirmed the only broker implementation,
  `real_trading_state` confirmed structurally `DISABLED`, universe/
  timeframe/strategy selection configurable with zero new code,
  Telegram/Discord already configured AND enabled. **Verdict: NOT
  READY** - not a data/credential/config issue, a real code gap. NOT
  fixed this checkpoint (read-only, no-code-changes scope) - the fix
  (`default_configuration_values()`, already used for this exact
  purpose in `replay_paper_session.py`) is described precisely for a
  future checkpoint. No live session launched, no
  `ScannerConfiguration` activated, no broker-order code called.
  `PROJECT_STRATEGY_STATUS.md` §6 updated with this finding, superseding
  `CHECKPOINT_76`'s own more provisional "technically ready" reading.
- **`CHECKPOINT_78`: fixed `CHECKPOINT_77`'s empty-configuration
  gap + found and fixed a SECOND, related gap + closed the ATR preset
  gap + re-verified readiness by actually invoking the real pipeline.
  Verdict: NOW READY.** `signal_pipeline_runtime.py::promote_bars_
  and_trigger_signals()`'s empty `StrategyConfigurationValues({})`
  replaced with `coerce_configuration_values(schema, default_
  configuration_values(schema))` - both pre-existing functions, no new
  mechanism. **Second gap, found while verifying the first fix (not
  assumed to work because it compiled)**: `default_configuration_
  values()` alone returns bare Python floats for DECIMAL-typed
  parameters (`ParameterDefinition.default` verbatim) -
  `require_decimal()`'s strict `isinstance(value, Decimal)` check
  rejects a float, so `sma_trend_filter`/`atr_volatility_breakout`
  would STILL have raised `InvalidParameterValueError` without
  `coerce_configuration_values()` applied too (missed on a first,
  too-shallow check because an empty `feature_values` dict
  short-circuits BEFORE reaching that line - caught by testing with a
  real, warmed-up feature value present instead). Fixed in the same
  narrow scope, not escalated - it's the other half of an
  already-established, paired mechanism
  (`StrategyConfigurationService.save_configuration()` already pairs
  these two functions for this exact reason). **3 new regression
  tests** in `test_signal_pipeline_runtime.py`, including the deep one
  `CHECKPOINT_77` identified as missing: spies on the REAL, registered
  `EmaCrossoverStrategy.evaluate` (not a test-only `_config()` helper)
  to prove it genuinely receives non-empty, correctly-typed config in
  production-shaped code. **ATR preset gap closed**: new
  `atr_baseline` preset created (`14/2.0/1.0/1.5/2.5/3.5/1.0`, exact
  documented-baseline match), via the real `save_configuration()` path
  - existing `atr_aggresive`/`atr_Balanced`/`atr_Conservative` presets
  untouched. **Re-verified by actually invoking the real
  `promote_bars_and_trigger_signals()` path** (not just re-reading
  code) against a real open-market bar - clean
  `SignalPipelineOutcome(promoted_count=1, active_loop_invocations=1)`,
  no exception, for all 3 registered strategies' now-correctly-typed
  configs. **`PROJECT_STRATEGY_STATUS.md` §6 updated to READY**,
  superseding `CHECKPOINT_77`'s own NOT READY finding (kept in the
  document for its full trace). Still NO live session launched, no
  `ScannerConfiguration` activated, no broker-order code path called -
  remains the operator's own explicit next decision.
  `CHECKPOINT_78_SUMMARY.md` restates (does not execute) the operator
  command sequence.
- **`RECON-ORB-STRATEGY` (backfilled here - that checkpoint did not
  update this file itself, confirmed missing, added now alongside
  `CHECKPOINT-ORB-A`'s own entry below, same as `CHECKPOINT-VWAP-A`
  had to backfill its own recon's identical gap): a THIRD, genuinely
  new strategy thread started - Opening Range Breakout (ORB),
  unrelated to Gainz (paused) and VWAP (Phase D complete, also
  paused).** Design: mark the high/low of the first N minutes of each
  session (classic 15 min), enter on a close beyond that range, target
  a multiple of the range's own size, stop at the opposite boundary
  (or a fraction of it) - deliberately self-scaling to that day's own
  realized volatility, a genuinely different exit-distance mechanism
  than both Gainz's (independently-chosen ATR multiples) and VWAP's
  (target scales with the entry deviation) - reasoned expectation
  only, not yet tested. Read-only recon confirmed: no ORB feature
  exists anywhere; `rolling_breakout.py` (the one existing feature with
  "breakout" in its name) is confirmed a genuinely DIFFERENT shape (a
  trailing N-bar lookback, re-evaluated every bar forever, no session
  concept) - not the same thing despite the name. **The one real
  difference from VWAP's own pattern**: VWAP only ever needed to know
  WHICH day a bar belongs to; ORB also needs WHERE in that day - but
  this doesn't require new session-resolver logic, `TradingSession.
  market_open` (from the EXISTING `build_session_for()`, already used
  elsewhere this session) already supplies exactly the fact needed.
  Classic 15-minute window = exactly 3 bars at this project's `5m`
  close-anchored grain. Full phased roadmap (`ORB_STRATEGY_ROADMAP.md`,
  repo root, uncommitted per its own convention) written: A (feature)
  -> B (strategy, single target only, computing MFE/MAE from its own
  first run, not deferred) -> C (2-3 presets) -> D (walk-forward,
  against the current real gate-verified dataset).
- **`CHECKPOINT-ORB-A`: the opening-range feature itself, built and
  tested.** New `src/intraday/signal_intelligence/feature_engine/
  opening_range.py` (`compute_opening_range_high`/`compute_opening_
  range_low`), new `OpeningRangeDefinition` (`definitions.py` -
  `opening_range_minutes: int = 15`, a REAL tunable parameter unlike
  `SessionVwapDefinition`'s zero fields, so it follows `Rolling
  BreakoutDefinition`'s dispatch shape instead). **Representation
  decided and documented**: TWO parallel fields
  (`opening_range_high_{N}`/`opening_range_low_{N}`), following
  `directional_movement.py`'s `+DI`/`-DI` precedent (two independent
  compute functions sharing one Definition) rather than `rolling_
  breakout`'s signed-value shape - high/low are genuinely independent
  numbers, not mutually exclusive like breakout/breakdown. Formula:
  per-day `max(high)`/`min(low)` across bars within `[market_open,
  market_open+N]`, frozen for the rest of that session once the window
  closes. No output for the window's own 3 bars, or for any day whose
  bars don't cover a complete window. Wired into BOTH `field_registry.py`
  AND `compute_feature_series()`'s dispatch - confirmed both required,
  per `CHECKPOINT-GAINZ-A`'s own already-documented finding. 16 new
  tests, all passing, including the market-open-resolution tests
  proving the window boundary derives from the session's REAL resolved
  `market_open` (not a hardcoded clock guess) and correctly moves when
  `opening_range_minutes` changes. `registry.py` and every strategy
  file confirmed untouched. Full suite re-run - see
  `CHECKPOINT_ORB-A_SUMMARY.md` for the exact before/after comparison.
  Phase B (the strategy itself) is the next step in this thread, not
  yet started.
- **`CHECKPOINT-ORB-B`: the Opening Range Breakout strategy itself
  built, `registry.py` still untouched - and the FIRST genuinely
  positive first-look real backtest result of this entire session.**
  New `OrbBreakoutStrategy` (`orb_breakout.py`), matching the
  `Strategy` Protocol structurally identical to `ema_crossover.py`.
  5 parameters: `opening_range_minutes` (15), `target_range_multiplier`
  (1.0), `stop_range_fraction` (1.0 = opposite range boundary itself),
  `minimum_range_atr_multiplier` (0 = disabled by default),
  `atr_lookback` (14, filter-only). **`atr_lookback`'s role decided
  explicitly, not by inertia**: an OPTIONAL, default-OFF range-size
  filter (guards against trading a too-narrow, noise-prone range) -
  when disabled, ATR isn't even added to `required_features()`, so a
  default configuration never needs it to warm up. `evaluate()`: BULLISH
  when `close > opening_range_high`, BEARISH when `close <
  opening_range_low`. `build_trade_plan()`: SINGLE target
  (`target = entry + sign*target_range_multiplier*range_size`,
  `stop = opposite_boundary -/+ stop_range_fraction*range_size`) - a
  degenerate stop-on-the-wrong-side is IMPOSSIBLE by construction here
  (unlike the mean-reversion strategy's own M>N runtime guard),
  confirmed directly across the full valid parameter range. 21 new
  unit tests, all passing, including both filtered-out and
  pass-through ATR-filter cases explicitly.
  **First real backtest (explicitly a first look, NOT Phase D's
  validation gate)**: RELIANCE, default params, full gate-verified
  dataset (still 17 real days, re-checked directly, unchanged since
  `CHECKPOINT-VWAP-B`). 18 trades, win_rate **77.8%**, expectancy
  **+5.21/trade**, net_pnl **+93.82**, return **+0.094%** -
  **the first genuinely positive first-look result this entire
  session has produced**, reported honestly: driven by an
  exceptionally high win rate (14/18 hit target) rather than a strong
  R:R (only 0.31 - average losers ~3x larger than average winners), a
  materially different profile from every prior strategy. MFE
  distribution (same method `CHECKPOINT_75`/`CHECKPOINT-VWAP-B` both
  used): 88.2% of trades reach >=2.0x ATR favorably - by far the most
  favorable distribution of any strategy tested this session (vs
  VWAP's 42.6%, Gainz's 17.6%). Small sample (18 trades, 17 days, one
  symbol, default params only) - genuinely encouraging, explicitly NOT
  validated; Phase D must test this for real, not assume it holds.
  Zero persistence throughout (`BacktestResultRecord` 208->208).
  Phase C (2-3 config presets) is the next step in this thread.
- **`CHECKPOINT-ORB-C`: 3 real config presets for `orb_breakout`,
  zero code changes.** `orb_classic` (15min/1.0x target/1.0 stop
  fraction - the intended default, matches `parameter_schema()`'s own
  defaults), `orb_tight` (5min/1.0/1.0), `orb_wide`
  (30min/1.5x/0.75). `minimum_range_atr_multiplier=0`/`atr_lookback=14`
  deliberately identical across all 3 (the filter question is
  orthogonal to the window/target/stop axis these presets explore, and
  with the filter disabled `atr_lookback` isn't even read). Created via
  the real `StrategyConfigurationService.save_configuration()` path.
  Internal validity (no degenerate stop/target) verified DIRECTLY
  against all 3 real persisted rows, not just assumed from
  `CHECKPOINT-ORB-B`'s own structural-safety claim. **Real behavioral
  divergence proven** (6 tests, `test_checkpoint_orb_c_presets.py`) -
  a genuinely different PROOF SHAPE from Gainz/VWAP's own
  threshold-gating divergence: the SAME 3-bar real sequence, run
  through the real dispatcher, shows `orb_tight`'s 5-minute (1-bar)
  window already closed and firing a real BULLISH signal by the 2nd
  bar, while `orb_classic`'s 15-minute (3-bar) window has produced
  ZERO output at all on the same data (its own warm-up rule means the
  first possible output is a 4th bar this fixture doesn't even reach)
  - divergence in WHEN a signal becomes possible, not just whether one
  fires. A second test confirms `orb_wide`'s own target/stop
  multipliers produce genuinely different, hand-computed values than
  `orb_classic`'s on the identical range/entry. `registry.py`
  untouched, zero `src/` diff this checkpoint. Phase D (walk-forward
  validation) is the next and final step in this thread - and the
  first data point (`CHECKPOINT-ORB-B`'s own first-look result) is the
  most encouraging of any strategy this session so far.
- **`CHECKPOINT-ORB-D`: walk-forward validation gate for
  `orb_breakout`, all 3 presets, all 4 symbols - closes the ORB
  thread. THIS SESSION'S BEST WALK-FORWARD RESULT, reported honestly
  with its real caveats, not oversold.** Data re-checked directly:
  still 17 real trading days/symbol. **Central question answered**:
  does `CHECKPOINT-ORB-B`'s encouraging first look (RELIANCE,
  `orb_classic`, +Rs93.82, 77.8% win rate) survive walk-forward split?
  PARTIALLY - aggregate OOS return stays positive (+0.065%), but 2 of
  3 individual folds show a real sign flip; the aggregate is carried
  by one fold's large positive OOS result on a small (4-trade) sample.
  **All 3 RELIANCE presets are aggregate-positive simultaneously**
  (`orb_classic` +0.065, `orb_tight` +0.059, `orb_wide` +0.089) - the
  best single-symbol result of the ENTIRE session, ~5-8x larger than
  the next-best (`atr_volatility_breakout`'s own +0.0114,
  `CHECKPOINT_70`). `orb_tight` is the most FOLD-STABLE of the 3 (only
  1/3 folds flip, vs 2/3 for classic/wide) and shows consistently high
  win rates (72-80% IS, 50-80% OOS) - the single most encouraging
  individual result this checkpoint found. **Does NOT generalize
  cross-symbol** - HDFCBANK/INFY are negative across all 3 presets
  (mirroring `CHECKPOINT_71`'s own finding that no strategy's
  RELIANCE edge has ever transferred cross-symbol this session); TCS
  is mixed (2/3 presets positive, but on the thinnest, noisiest
  samples - as few as 1-2 OOS trades/fold). **Answers `CHECKPOINT-
  ORB-B`'s own MFE question**: this is the FIRST strategy this session
  where a favorable MFE distribution (88.2% >=2.0x ATR) IS reflected
  in a genuinely better walk-forward outcome (on RELIANCE) - but a
  better outcome is not the same as a STABLE one; `orb_classic`/
  `orb_wide` still flip 2/3 folds despite positive aggregates, so this
  does not fully escape `CHECKPOINT_75`/`CHECKPOINT-VWAP-D`'s own
  "MFE alone doesn't guarantee a validated edge" lesson. **Honest
  caveat specific to ORB**: it fires at most once per session, so its
  own per-fold trade counts (as low as 1-5) are smaller than every
  other strategy tested this session - these numbers carry even less
  statistical weight than usual, on top of the small-day-count caveat
  every Phase D already carries. Zero persistence throughout
  (`BacktestResultRecord` 208->208). No `RESEARCH_ACTIVE`/status
  change made or implied. This closes all 4 phases (A/B/C/D) of the
  ORB thread; `registry.py` remains untouched, the strategy remains
  unreachable from the live scanner/backtest API.
- **`CHECKPOINT_79`**: documentation-only consolidation checkpoint, no
  code/tests/backtests/data/params/registry touched. Updated
  `PROJECT_STRATEGY_STATUS.md` (the living, committed reference): (1)
  added `orb_breakout` as a 6th row to §1's table, all figures cited
  directly from `CHECKPOINT-ORB-D_SUMMARY.md` (best +0.0890 RELIANCE
  `orb_wide`; worst -0.1096 INFY `orb_wide`; positive on RELIANCE only,
  fold-unstable on 2 of 3 presets, does not generalize cross-symbol);
  (2) confirmed plainly in §4 that ORB's result does NOT change the
  paper-trading-readiness answer, since `orb_breakout` remains
  unregistered in `registry.py` (re-confirmed directly) and
  `CHECKPOINT_78`'s READY verdict concerns only the 3 registered
  strategies; (3) formally declared `orb_breakout` tuning PAUSED in §5,
  identical reasoning and identical 30-day resumption criterion as
  Gainz (`CHECKPOINT_75`) and VWAP (`CHECKPOINT_76`), plus a reasoned
  note (not a new gate) that `orb_tight`-style shorter windows should
  be the first variants re-tested once tuning resumes, given
  `CHECKPOINT-ORB-D`'s own fold-stability finding; (4) added a new §0
  "Current state" paragraph consolidating all 3 research strategies
  (Gainz/VWAP/ORB) side by side: all paused, same resumption criterion,
  none registered, ORB the most promising single result but still
  unvalidated cross-symbol. `CHECKPOINT_79_SUMMARY.md` written at repo
  root. `git status --short` confirmed only documentation files
  changed before commit.
- **`LIVE-PAPER-1`**: first live paper trading session attempt —
  **halted at Part 0 pre-flight, market closed**. Checked real time
  directly (`date`): `2026-09-08 20:24:04 IST`, well past NSE's 15:30
  IST close. Per this checkpoint's own explicit rule, stopped
  immediately rather than waiting or working around it — no worker
  launched, no `ScannerConfiguration` change, zero DB writes. Needs
  re-attempt on a future trading day during market hours (09:15-15:30
  IST), with a fresh Dhan credential check at that time (`CHECKPOINT_
  78`'s own check expires `2026-09-09 10:17:40 UTC` and should not be
  reused). **A second attempt, same calendar day, narrowed to
  worker-launch-only scope per `RECON-FRONTEND-LAUNCH`'s finding
  (UI now handles universe/timeframe/strategy/START), also halted at
  Part 0** — real time re-checked directly (`date`): `2026-09-08
  20:30:56 IST`, still past close. Same reason, not a new blocker.
- **`RECON-FRONTEND-LAUNCH`**: read-only frontend recon, no code
  changes. Traced `LivePaperOperationsConsole.tsx`'s START button
  (`handleStart`->`startLivePaperSession()`->`POST .../live-paper-
  session/start/`) directly to `live_paper_session_views.py`: it only
  re-evaluates `LivePaperReadiness` and flips
  `ScannerConfiguration.enabled` - it never launches the worker
  process, only reads its already-reported status
  (`DjangoWorkerRuntimeStatusRepository`). Confirmed `LiveScannerConsole.tsx`
  has a full, real UI for universe mode/timeframe/strategy selection
  (writes via `updateScannerConfiguration()`, a separate path from
  start/stop) - the strategy checklist is rendered "from the backend
  strategy registry," confirming Gainz/VWAP/ORB are unselectable from
  the UI too, matching their unregistered status. No DB/admin access
  needed for steps 5-7 of the documented sequence. Confirmed the
  worker process (`manage.py run_market_data_worker`) has NO UI
  launch trigger anywhere - a genuine, deliberate structural
  limitation (Celery Beat auto-launch was explicitly rejected per
  `CHECKPOINT_72`), not an unfinished feature. Confirmed all
  documented Success Criteria (Sec5) monitoring items - scanner
  progress, session state, signals with risk/paper/Telegram/Discord
  status, Daily Session Report (execution/communication/P&L) - are
  real, live-polled UI panels, not requiring direct DB inspection.
  Reported inline, no summary file needed (findings not substantial
  enough to warrant one per the checkpoint's own OUTPUT instruction).
- **`FRONTEND-LIVE-READY`**: UX audit + low-risk fixes, scoped to
  `LivePaperOperationsConsole.tsx`/`LiveScannerConsole.tsx`'s selection
  UI only, ahead of tomorrow's first genuinely live use. Read
  `docs/architecture/FRONTEND_DESIGN_SYSTEM.md` first (the project's
  own design reference, not a Claude Skill - no skill by that name
  exists in this environment). Captured 10 Playwright/network-mocked
  screenshots (`frontend/scripts/capture-live-ready-screenshots.mjs`,
  same throwaway-script pattern as `CHECKPOINT_FRONTEND-2`'s own,
  fixture shapes copied from the real `.test.tsx` files) across idle/
  running-no-signals/running-with-signal/completed-session states, both
  themes, in `frontend/docs/design-audit/live-ready/`. Found ONE real,
  console-specific bug: `.signal-monitor__table` (`styles.css`) forced
  `table-layout: fixed; width: 100%` on its 16-column signal table,
  making `overflow-x: auto` never actually trigger - headers rendered
  as unreadable ellipsis fragments ("Ti…", "St…"), directly hiding
  which column was Telegram/Discord/target/stop-loss status. Fixed by
  removing the forced fixed-width layout so the table sizes to content
  and the existing scroll wrapper works, matching the already-
  established `.table-scroll` pattern used elsewhere in the same file
  rather than the broken ad hoc alternative this one class had
  reinvented - shared by 3 components
  (`LiveMarketDataMonitor.tsx`/`LiveScannerConsole.tsx`/
  `LivePaperOperationsConsole.tsx`), all 3 benefit. Session state
  (badge + timeline) and worker/connectivity health (Pre-Session
  Readiness Checklist near the top) were both found already clear at a
  glance - no fix needed there. Full suite: 34 files/361 tests passing
  (including `styles.quality.test.ts`/`theme.quality.test.ts` gates),
  `npm run typecheck` clean. No backend/API change, no new feature -
  CSS-only fix to already-fetched data's presentation.
- **`FRONTEND-DATA-TABLES`**: fixed two concrete, screenshot-confirmed
  usability problems - the shared instrument picker (~8,558
  instruments rendered as one flat, unpaginated checkbox grid) and the
  Compare/Strategy Comparison page (100+ backtest results as a flat
  list labeled only by a cryptic hash). Confirmed scope directly:
  `InstrumentPickerMulti`/`InstrumentPickerSingle`
  (`InstrumentPicker.tsx`) is genuinely ONE shared component reused by
  4 real call sites (`LiveScannerConsole`/`PaperTradingPage`/
  `HistoricalMarketDataCard`/`WatchlistPage`) - one fix covers all 4.
  `[F]` real row counts checked directly: `BacktestResultRecord` = 208
  total, `ema_crossover` alone = 139 (confirms "100+"). Found and
  reused an EXISTING client-side pagination idiom
  (`BacktestingWorkbenchPage.tsx`'s own `TradeTable`) rather than
  inventing a new pattern or a virtualization library - extracted it
  into one small shared `Pagination.tsx` (~45 lines: control +
  `paginate()` helper). Fixed `InstrumentPickerMulti`: paginated at
  100/page, search/exchange reset to page 1, "Select All" unchanged in
  behavior (still applies across all pages) but now says so explicitly.
  Fixed `ComparisonPage.tsx`: results list paginated at 20/page, added
  a "Sort list by" control (newest/oldest/instrument/timeframe, all
  from already-available `generated_at`/`configuration` fields - no
  backend change), replaced the raw-hash-only label with
  `<instrument> · <timeframe> · <date>` as primary and the hash+config
  version as secondary/tooltip detail. Grouping by strategy was
  considered but not built - the list is already scoped to one
  strategy at a time via the existing dropdown, so it never actually
  mixes strategies. Screenshot script found and fixed a REAL mock bug
  in itself (fixture used `company_name` instead of the real
  contract's `display_name`, silently crashing the picker's own
  `.localeCompare()` sort) - root-caused directly against the real
  generated contract type, not worked around. Full suite: 34
  files/365 tests passing (4 new pagination tests), typecheck clean.
  The user's own separately-running `app.bat` dev servers (5173/8000)
  were left untouched throughout - all testing used an isolated port
  (5199).
- **`FRONTEND-3`**: app-wide audit round 2 (extends `FRONTEND-2`'s
  screenshot script to the 2 previously-unaudited pages its generic
  mock could handle - Configuration, Market Data; Live Scanner/Live
  Paper Operations deliberately reuse `FRONTEND-LIVE-READY`'s own
  dedicated, better-fixtured screenshots instead of a worse re-capture)
  plus the operator's explicit strategy-selector-toggle request. Found
  and fixed a real mock bug while extending the script: Market Data's
  screen threw because `/config/signals/`/`/market-data/instruments/`
  had no dedicated mock and fell through to a `[]` fallback that
  doesn't match either endpoint's real object shape. New shared
  `SegmentedToggle.tsx` component (~75 lines, real
  `role="radiogroup"`/`role="radio"`, not styled divs) - falls back to
  a `<select>` automatically past 5 options (proven by a dedicated
  6-option test, not just asserted). Applied to 4 real call sites:
  `StrategyConfigurationPage.tsx` (Strategy, the operator's explicit
  ask), `PaperTradingPage.tsx` (Side/Order Type),
  `PaperSessionPanel.tsx` (Strategy/Timeframe). Categorized findings:
  Category 1 (above, implemented); Category 2 (Reports density,
  Dashboard length, Paper Trading's duplicate panels - all `FRONTEND-2`
  carryovers, still open; NEW: Market Data's 6-filter sidebar has
  toggle-pattern option counts but converting them risks reducing
  density in an already-narrow column - real layout judgment, not
  applied); Category 3 (nav now 3 rows/14 buttons, `react-router`
  question - both unchanged, still deferred). Full suite: 34
  files/367 tests passing, typecheck clean. Did not touch the Compare
  page or instrument picker beyond confirming their post-
  `FRONTEND-DATA-TABLES` state. The user's own `app.bat` dev servers
  (5173/8000) were left untouched - isolated test port (5198) used.
- **`LIVE-PAPER-1` (2026-09-09) — the project's first completed live
  paper session**: after 2 prior halted attempts (2026-09-08, market
  closed), a 3rd attempt during genuine NSE market hours ran the full
  session. Part 0 pre-flight confirmed directly (not assumed): market
  OPEN, Dhan token VALID (expires 10:17:40 UTC), `real_trading_state`
  structurally DISABLED (`TRADING_MODE=RESEARCH`, no order-placing
  broker under `infrastructure/brokers/dhan/`), `PaperBroker` the only
  order-execution broker. Part 1: launched `run_market_data_worker`
  only, confirmed READY_FOR_PAPER, stopped per the checkpoint's own
  narrowed scope for the operator to configure/start via the real UI
  (`LiveScannerConsole`/`LivePaperOperationsConsole`, confirmed working
  by `RECON-FRONTEND-LAUNCH`). Operator started via UI: 15 instruments,
  `5m`, the 3 registered strategies - confirmed directly via
  `derive_live_paper_session_state()`=RUNNING,
  `drift=False` (effective config version matched desired).
  **Outcome: zero signals for the whole session, but a fully
  successful validation** per the documented procedure's own
  infrastructure-only Success Criteria - scanner completed dozens of
  full cycles, `SignalRecord`/`PaperOrderRecord`/
  `CommunicationLedgerRecord` all genuinely 0 (a real all-zero Daily
  Session Report, not a missing one). **Two genuine crash/recovery
  cycles handled correctly**: the same intermittent Dhan
  `close_code=1006` disconnect `LIVE-1`/`LIVE-3`/`LIVE-4` already
  diagnosed as real/external - first bounded supervisor
  (`--max-restarts 40`) genuinely exhausted (40 restarts in ~90 min, a
  busier-than-usual burst) and stopped itself exactly as designed,
  leaving an honest ~7-minute data gap before this session's own
  monitoring caught and relaunched it with `--max-restarts 200`
  (matching `LIVE-4`'s own precedent); second run used only 4 restarts,
  reached session-end cleanly. A process-kill attempted mid-session
  (to proactively resize the first supervisor's budget before
  exhaustion) was correctly refused by the permission system and NOT
  worked around - fell back to letting it exhaust naturally instead,
  per `LIVE-4`'s own precedent. At session-end, the worker was slow to
  notice the supervisor's own stop request; re-issued the same
  real stop-request row directly and it exited cleanly ~12s later.
  Also called the real `stop_live_paper_session()` service (same as
  the UI's own STOP button) since the worker-level stop alone left
  `ScannerConfiguration.enabled=True`. One minor, safety-irrelevant
  state-machine nuance found and reported: `derive_live_paper_
  session_state()` settles at STOPPING not STOPPED when the worker
  already exited before the session-level stop (no further
  reconciliation tick occurs) - noted for a future checkpoint, not
  fixed. `PROJECT_STRATEGY_STATUS.md` §6 and this entry both confirm
  the READY verdict is unaffected - this demonstrated existing
  crash-recovery working under real, heavy reconnect pressure, not a
  new gap. See `LIVE_PAPER-1_SUMMARY.md` for the full trace (Parts
  0-3).
- **`CHECKPOINT_80`**: crash-rate diagnostic + a real session-stop-gap
  fix, both following from `LIVE-PAPER-1`'s own findings. **Part 1**:
  extracted precise timestamps from today's logs - all 90 disconnects
  share the same `close_code=1006` LIVE-1/LIVE-3 already diagnosed as
  external, but 66% of today's 44 crashes (29) clustered in one tight
  ~10-minute window (08:13:14-08:23:30 UTC/13:43-13:53 IST) at ~22s
  intervals, 26 of them receiving zero quotes before failing - a
  genuine, temporary outage burst distinct from the sparser surrounding
  pattern, not a new root cause. No fix attempted (external, per the
  checkpoint's own rule). **Part 2**: traced the actual stop flow -
  confirmed `ScannerConfiguration.enabled` (operator intent) and
  `WorkerRuntimeStatus` (worker process's own state) are correctly two
  independent controls by design, NOT a gap - but found a real,
  recurring bug in `derive_live_paper_session_state()`
  (`live_paper_session.py`): it never checked for
  `worker_state=="STOPPED"`, so a worker that cleanly exited (e.g. the
  supervisor's own session-end stop, which by design never touches
  `ScannerConfiguration`) could be reported as RUNNING - exactly what
  `LIVE-PAPER-1` hit. Fixed with one clause (same top-priority
  short-circuit `FAILED` already has), causation proven by reverting
  just the fix and confirming the new regression test fails with the
  exact live symptom. **Part 3**: confirmed the "STOPPING forever"
  quirk shares the exact same root cause and is RESOLVED (not just
  documented) by the same fix - proven by a second regression test
  reproducing the exact stale-version scenario. `test_live_paper_
  session.py`: 12 tests before -> 14 after. `PROJECT_STRATEGY_STATUS.md`
  §6's `LIVE-PAPER-1` entry updated to reflect the fix (superseding its
  own prior "not fixed here" note). No live session launched, no
  strategy/registry changes.
- **`FRONTEND-4`**: implemented the two Category 2/3 items deferred
  since `FRONTEND-2`/`3` (Reports density, 14-button nav wrapping),
  now explicitly authorized. **Nav**: grouped 14 flat items into
  Dashboard (standalone) + 4 dropdown groups (Live Operations/
  Research/System Setup/Trading Record), reusing the existing
  `<details>`/`<summary>` disclosure idiom (`App.tsx`'s `NAV_GROUPS`) -
  no new component, every route/label unchanged. **Reports**: wrapped
  each of the 7 major sections in the same collapsible pattern
  (`ReportsOverviewPage.tsx`'s `ReportSection`); Report Catalogue and
  Market Data Quality Report open by default, the rest start collapsed
  - page went from one continuous 7-section scroll to 2 open + 5
  one-line collapsed headers. Found 2 real bugs only a real browser
  (Playwright) catches, not the jsdom-based unit suite: (1) the user's
  own suggested "Configuration" group label collided with the
  "Configuration" screen inside it (same accessible name) - renamed
  the group to "System Setup"; (2) `<details>` is exposed as
  `role="group"` in Chromium (summary folded into the group's own
  name, never `role="button"`), and a CLOSED `<details>`'s content is
  excluded from the accessibility tree entirely, not just visually
  hidden - governs how any future Playwright/e2e script must locate a
  nav group (by its own visible text, opened BEFORE querying for an
  item inside it). Keyboard operability confirmed directly (Tab lands
  on summary, Enter toggles - native, no custom handling). Zero
  existing tests broke (`App.test.tsx`/`AppDashboardNavigation.test.tsx`
  both pass unmodified - jsdom doesn't enforce click-visibility, so the
  grouped structure is transparent to those assertions). Full suite:
  34 files/367 tests passing, typecheck clean, both quality gates
  pass. No backend/API change.
- **`CHECKPOINT_81`**: attempted to widen the real backfill to ~50-60
  trading days/symbol - found a hard, previously-unquantified
  structural ceiling instead. `CAS_EFFECTIVE_DATE = 2026-08-03`
  (`domain/session/calendar.py`) means `_PROVEN_INTRADAY_SCOPES` only
  certifies `(NSE_EQ, FIVE_MINUTE, CAS_ERA)` - any fetch window
  entirely before 08-03 resolves PRE_CAS and can NEVER produce a
  CANONICALIZED row, regardless of window choice. `[F]` Backfilled
  2026-06-01..08-02 for real (44 trading days, 12,247 new rows across
  4 symbols, real Dhan REST, status=COMPLETE) - confirmed directly it
  landed entirely UNCANONICALIZED/UNKNOWN, exactly as this scope rule
  predicts; left in place per P4 (real, valid data, just structurally
  ineligible, not deleted). Only remaining lever was forward
  extension: fetched 2026-09-09 (72 bars/symbol, the one additional
  real closed trading day available) - this DID canonicalize,
  17->18 days/symbol. `[F]` Computed the real ceiling directly: only
  28 real trading days total have occurred since CAS_EFFECTIVE_DATE
  through today, 10 inside the untouched interior gap
  (2026-08-17..08-28) - leaving a hard maximum of 18 canonicalizable
  days right now, reached exactly. Reaching 50-60 requires ~6-7 more
  real trading weeks to pass, not a different backfill choice. Stated
  plainly: the 30-new-day Gainz/VWAP/ORB tuning-resumption criterion
  (CHECKPOINT_75/76/79) is NOT met - only 1 new day added, not 30;
  target is now 47 total gate-verified days. P4 verified independently
  (0 duplicate (instrument, bar_timestamp) pairs, spot-checked
  pre-existing row unchanged). fromDate-exclusive fix spot-checked on
  3 newly-fetched days, holds. No migration executed, interior gap
  untouched, no strategy/registry/tuning change.
  `PROJECT_STRATEGY_STATUS.md` §3 rewritten with the new baseline and
  full structural-ceiling finding. **Process note**: this checkpoint
  explicitly re-affirmed the "read before writing any file that might
  exist" discipline after 2 near-misses this session (`FRONTEND-3`/
  `FRONTEND-4` both nearly overwrote pre-existing summaries) - checked
  directly this file didn't exist before creating it.
- **`CHECKPOINT_82`**: operator-authorized first real attempt at
  production-boot + one-unit migration execution against the interior
  gap. Confirmed `[F]` directly, before touching anything, that the
  `67.13`/`67.13-C` deadlock is unchanged: `verify_environment_
  identity()` requires BOTH `.production` settings module AND
  `INTRADAY_VERIFIED_PRODUCTION_IDENTITY` matching the live DB name.
  Part 1: generated a real `SETTINGS_ENCRYPTION_KEY` via
  `Fernet.generate_key()` (session-only env var, never committed/
  written to `.env`), set `INTRADAY_VERIFIED_PRODUCTION_IDENTITY=
  intraday`, confirmed `intraday.settings.production` genuinely boots
  (`manage.py check` clean) with `TRADING_MODE` still safely resolving
  to `RESEARCH` (not LIVE - `DHAN_CLIENT_ID`/`DHAN_ACCESS_TOKEN` env
  vars were never set). `[F]` `verify_environment_identity()` reported
  `VERIFIED_PRODUCTION` for the first time this session - genuine new
  progress beyond 67.13/67.13-C. Part 2: ran the real
  `migration_production_execute` command against RELIANCE/5m/
  2026-08-17 (70 rows, dry-run `PROVEN`/`DRY_RUN_SAFE`) with a
  freshly-derived real scope fingerprint. Gate 1 PASSED, Gate 2
  PASSED, **Gate 3 (`authorize_one_unit_execution()`) DENIED** - its
  own internal re-check of `assert_write_capable_connection_is_test_
  database()` refuses any non-`test_`-prefixed database, and the real
  DB is `intraday`. This is exactly the "structurally UNSATISFIABLE"
  condition the code's own `NOT_WIRED_RATIONALE` comment
  (`migration_execution_authorization.py`) already documented -
  confirmed live, for the first time, not just traced in the
  abstract. `[F]` Zero rows written (RELIANCE 2026-08-17 still 70
  UNCANONICALIZED rows, unchanged) - stopped immediately per the
  checkpoint's own rule, no workaround attempted (P7). Bonus finding:
  even a successful write wouldn't have made this day gate-eligible
  alone - `ResearchDataGateService.get_research_eligible_bars()`
  independently rejects it with INCOMPLETE_COVERAGE (70/72 bars,
  matching CHECKPOINT_72's own prior finding that this gap block is
  missing its day-start/day-end bars too). Zero files touched (env
  vars only), git status clean throughout. Full test suite re-run for
  completeness (no code changed). `PROJECT_STRATEGY_STATUS.md` §3
  updated with the full gate-by-gate trace. Scaling to the rest of the
  interior gap remains blocked at the architecture level, not
  something more caution or a different unit would resolve -
  requires a separately-authorized design decision (what "verified
  production" means for this project's real single-environment
  deployment), per 67.13's own original recommendation, still
  unactioned.
- **`RECON-SINGLE-ENV-AUTHORIZATION`**: design-proposal-only checkpoint
  (no code changes, no migration execution), answering `CHECKPOINT_82`'s
  own "still blocked, needs a separately-authorized design decision"
  finding. Wrote `SINGLE_ENV_AUTHORIZATION_PROPOSAL.md` at repo root -
  **deliberately uncommitted**, same convention as `GAINZ_ROADMAP.md`/
  `VWAP_STRATEGY_ROADMAP.md`/`ORB_STRATEGY_ROADMAP.md` (a living,
  pre-decision document for operator review, not yet authorized for
  implementation). Traced the guard's own original purpose directly:
  `assert_write_capable_connection_is_test_database()` was built at
  Checkpoint 67.10 specifically to stop the TEST-ONLY
  `migration_67_10 --execute` command from escaping its pytest-only
  context - not a general "wrong database" multi-environment guard.
  The real design flaw is that `authorize_one_unit_execution()`
  (67.12.2) later reused this exact test-only guard as its own check
  (5), and `migration_production_execute.py` (67.13-C) - the genuine
  production entry point - inherited it via that reuse, making the
  production path permanently unsatisfiable. `[F]` Confirmed directly:
  `POSTGRES_DB=intraday` is the only real database configured anywhere
  in this codebase (every settings module derives from the same env
  var) - no staging DB, no second developer DB exists today, though
  `ARCHITECTURE_DECISIONS.md` #27 records a genuine multi-environment
  deployment as the project's own long-term intent (noted honestly as
  a caveat, not glossed over). Proposed replacement (recommended as
  ONE coherent approach, not a menu): (a) a new, purpose-built guard
  re-deriving legitimacy from the SAME `VERIFIED_PRODUCTION` evidence
  chain instead of a database-naming convention; (b) a new
  `allow_non_test_database` constructor parameter on
  `HistoricalBarMigrationExecutor` (default False, unchanged for
  `migration_67_10.py`'s own test-only path - confirmed that path's
  own direct internal guard call stays completely untouched); (c) a
  mandatory, explicit per-invocation operator confirmation flag,
  matching the "explicit operator action" discipline already
  established for live sessions; (d) an enforced row-count ceiling per
  invocation (the existing one-unit-only convention made an explicit,
  coded assertion, not just a CLI convention). Confirmed directly that
  replay protection needs no new mechanism - the dry-run's own
  UNCANONICALIZED-only eligibility scan already makes re-running an
  already-executed unit a safe, hard refusal (verified against
  `migration_production_execute.py`'s own "unit not found in fresh
  plan" CommandError). Honest risk assessment: implementing this
  necessarily reopens genuine real-write capability that is currently
  impossible by design - named as the real trade-off, not minimized.
  Explicitly flagged one reservation NOT resolved toward "proceed": the
  decision to reopen real-write capability at all is the operator's
  own to make, not inferred from this session's general authorization
  pattern. Zero code changes, zero migration execution.
- **`CHECKPOINT_83`**: implemented `SINGLE_ENV_AUTHORIZATION_
  PROPOSAL.md` §2.3(a)-(d) exactly as operator-approved (flag name
  `--i-have-reviewed-this-real-write`, row ceiling `200`), then
  performed exactly ONE real rehearsal execution - the deadlock
  `[[RECON-SINGLE-ENV-AUTHORIZATION]]` documented and `CHECKPOINT_82`
  confirmed live is now resolved. New
  `assert_write_capable_connection_is_verified_production()` guard
  re-derives legitimacy from `verify_environment_identity()`'s own
  evidence chain, never a database-naming convention;
  `HistoricalBarMigrationExecutor` gained `allow_non_test_database`
  (default `False`, `migration_67_10.py`'s own construction call
  confirmed unchanged by grep, its own 28-test suite re-run unmodified
  and passing identically); `migration_production_execute.py` is the
  ONLY caller that ever passes `True`, gated behind its own 3 already-
  existing gates plus the new mandatory CLI flag. Real rehearsal:
  RELIANCE/`5m`/`2026-08-17` (same unit `CHECKPOINT_82` dry-run-proved
  safe) - fresh dry-run re-derived the same scope fingerprint
  independently, all 3 gates PASSED for the first time this session,
  write COMMITTED, all 70 rows flipped to `CANONICALIZED`, confirmed
  directly every other row in the 55,134-row table is untouched (0
  duplicate keys, exactly 1 `MigrationUnit`/70 `MigrationRow` audit
  records exist total, source-level proof the write's raw SQL is
  scoped by row id to this unit alone). Research gate re-run against
  this exact day: still `REJECTED (INCOMPLETE_COVERAGE, 70/72 bars)` -
  reported honestly, canonicalization does not create the 2
  already-known-missing bars from `CHECKPOINT_72`. Full suite: 3391
  passed / 7 failed, same 5 pre-existing + 2 known `--reuse-db` flakes
  as every prior checkpoint, zero new failures. Hard-stopped after
  exactly one unit per the checkpoint's own rule - confirmed via the
  audit tables, not scaled to the remaining 9 interior-gap days this
  checkpoint. See `CHECKPOINT_83_SUMMARY.md` for full gate transcripts
  and verification detail.
- **`CHECKPOINT_84`**: scaled `[[CHECKPOINT_83]]`'s proven mechanism
  to the rest of the `2026-08-17`–`08-28` interior gap (9 remaining
  real trading days × 4 symbols = 36 candidate units). One unit
  (TCS/`2026-08-24`) was never eligible - all 71 rows for that day
  carry `provenance=UNKNOWN`, not `REAL_DHAN` - confirmed a genuine,
  pre-existing data characteristic (TCS/`08-18`/`08-19` show the same
  pattern partially, 62/70 rows eligible). The remaining 35 units were
  each processed one at a time: a FRESH dry-run + freshly-rederived
  scope fingerprint per unit (never batch-computed or reused), then
  the real `migration_production_execute` command with
  `--i-have-reviewed-this-real-write`. **35/35 attempted units
  COMMITTED, zero gate failures.** Verified at full scale: all 2,434
  `REAL_DHAN` rows across the 35 units now `CANONICALIZED`; table-wide
  duplicate-key check across all 55,134 rows found 0 duplicates; total
  table row count unchanged (UPDATE-only, no inserts/deletes); exactly
  36 `MigrationUnit`/2,504 `MigrationRow` audit records exist in the
  whole database (1+70 from `CHECKPOINT_83`, 35+2,434 from this
  checkpoint) - precisely matching, nothing more; a 30-row broader
  spot-check outside the target scope found no corruption.
  **The honest, unwelcome finding**: re-running the research gate
  across the full `2026-08-03`–`09-09` range found the gate-verified
  day count **UNCHANGED at 18** - every one of the 9 interior-gap days
  independently fails `INCOMPLETE_COVERAGE` (missing 2-4
  session-boundary bars each, the same day-start/day-end truncation
  pattern documented since `CHECKPOINT_69`/`72`), so canonicalizing
  them made zero of them research-eligible.
  **The 47-day Gainz/VWAP/ORB tuning-resumption criterion remains NOT
  MET - this checkpoint made zero progress toward it**, despite 35
  real production writes succeeding cleanly. No strategy tuning was
  resumed. Full suite: 3391 passed / 7 failed, identical failure set
  to `CHECKPOINT_83` (5 pre-existing + 2 known `--reuse-db` flakes),
  zero new failures - no source code was modified this checkpoint,
  only data via the sanctioned path. See `CHECKPOINT_84_SUMMARY.md`
  for the full per-unit result table and verification detail.
- **`CHECKPOINT_85`**: diagnosed `[[CHECKPOINT_84]]`'s
  `INCOMPLETE_COVERAGE` finding, then recovered it. Hypothesis
  (interior-gap days were fetched before `CHECKPOINT_69`'s
  `fromDate`-exclusive fix landed) CONFIRMED for 34/36 slots via
  direct `ingested_at` evidence (all well before `CHECKPOINT_69`'s
  commit `eb8fa9d`/`2026-09-07`) and exact missing-range identification
  (`HistoricalDataCoverageService.get_coverage()` directly): a 2-bar
  day-start gap, exactly the pattern a single-bar (pre-fix) widening
  leaves behind. TCS/`2026-08-24` REFUTED the hypothesis and was
  reported as a genuinely different, separate issue (missing the
  session-END bar instead, ingested same-day via a different pipeline,
  71/72 rows already `UNKNOWN` provenance) - proceeded anyway since
  the safety guarantee is root-cause-independent. Safety proof before
  any write: `prepare()` only ever fetches `missing_ranges`;
  `fetch()`'s own filter strictly confines returned bars to that exact
  range; `bulk_upsert()`'s upsert-on-conflict semantics can therefore
  never collide with an existing row for THIS recovery specifically -
  every write is a genuine INSERT. Hit and resolved a real blocker:
  the stored `DhanCredential` couldn't decrypt under a fresh
  session-only `SETTINGS_ENCRYPTION_KEY` (it was encrypted under the
  ordinary dev-fallback key) - this recovery is a plain data backfill,
  not a migration-authorization write, so it correctly runs under
  ordinary `.development` settings instead (same single real DB
  either way). **36/36 slots recovered to 72/72 COMPLETE, net +71
  rows, 0 duplicate keys, all 35 previously-canonicalized units
  re-confirmed untouched.** Research gate re-run: gate-verified day
  count common across all 4 symbols rose **18 -> 24**
  (RELIANCE/HDFCBANK/INFY individually at 27; TCS capped at 24 by a
  SEPARATE, pre-existing, deliberately-NOT-fixed residual
  `UNKNOWN`-provenance issue on 3 of its own days - fixing it would
  require overwriting existing rows, out of this checkpoint's
  purely-additive scope). RELIANCE/`2026-08-17`
  (`[[CHECKPOINT_83]]`'s own unit) was outside this checkpoint's
  9-day target range and remains incomplete - noted as an easy future
  recovery, not fixed here. **47-day tuning threshold still NOT MET**
  (24 of 47) - no tuning resumed. Full suite: 3391 passed / 7 failed,
  identical failure set to `CHECKPOINT_84`, zero new failures - no
  source code modified, only data via the sanctioned path. See
  `CHECKPOINT_85_SUMMARY.md` for the full diagnosis and per-slot
  recovery table.
- **`CHECKPOINT_86`**: two independent threads left open by
  `[[CHECKPOINT_85]]`. **Part 1**: recovered `2026-08-17`'s boundary
  bars for ALL 4 symbols (checked directly rather than assuming only
  RELIANCE needed it - TCS/HDFCBANK/INFY were ALSO incomplete, missing
  a day-start + day-end 1-bar-each variant of the same pattern).
  Re-verified the same purely-additive safety proof
  `[[CHECKPOINT_85]]` established still holds (re-read the code, not
  assumed) before writing. **4/4 symbols recovered to 72/72
  COMPLETE, net +8 rows, 0 duplicate keys**, all previously-
  canonicalized rows re-confirmed untouched. Research gate: RELIANCE's
  own individual count rose 27->28, but the COMMON count across all 4
  symbols stayed at 24 - TCS/HDFCBANK/INFY's `08-17` shifted from
  `INCOMPLETE_COVERAGE` to `UNCANONICALIZED_TIMESTAMP` (never
  migrated, since `[[CHECKPOINT_83]]` targeted RELIANCE alone that
  day and `[[CHECKPOINT_84]]` deliberately excluded `08-17`) - a
  finding stated plainly, not glossed over. **Part 2** (strictly
  read-only, no fix attempted per its own rule): diagnosed TCS's
  residual `UNKNOWN`-provenance rows (87 total, 08-18/08-19/08-24).
  Traced origin via source inspection: the ONE real ingestion call
  site always passes a provider's own `.provenance` attribute, and
  both CURRENT providers stamp a fixed non-UNKNOWN value - so these
  rows must come from an early/experimental provider that predates
  the provenance-hook system, left in place. **Critical reframe**:
  this is NOT a TCS-isolated anomaly - a table-wide scan found 5,100
  `UNKNOWN`-provenance rows across 23 instruments, almost entirely
  NON-target symbols (Adani group, Tata group, etc.) - RELIANCE/
  HDFCBANK/INFY have ZERO such rows; TCS's 87 is a small piece of a
  much broader, pre-existing dataset characteristic. Confirmed
  directly (not assumed) that the existing upsert mechanism will
  NEVER naturally supersede these rows - `get_coverage()` already
  reports these days provenance-blind-complete, so `prepare()` makes
  zero provider calls for them, ever. Proposed 3 fix approaches
  (force-overwrite via fetch, metadata-only relabel, delete+refetch),
  each requiring separate P4-authorization the checkpoint's own rule
  forbade attempting here - explicitly left for a future checkpoint's
  own decision. Common gate-verified day count remains **24** (47-day
  tuning threshold still NOT met; no tuning resumed). Full suite: 3391
  passed / 7 failed, identical to `[[CHECKPOINT_85]]`, zero new
  failures - no source code modified, only data (Part 1) + this
  checkpoint's own tracking docs. See `CHECKPOINT_86_SUMMARY.md` for
  the full recovery table and diagnostic detail.
- **`CHECKPOINT_87`**: attempted to migrate TCS/HDFCBANK/INFY's
  `2026-08-17` (3 units) - **BLOCKED, 0/3, correctly, by a
  pre-existing guard.** The fresh dry-run (Task item #1) immediately
  showed all 3 units `FAILED`/`ALREADY_CANONICAL_COLLISION` at
  projected `new_timestamp=09:45` - no real command was ever
  attempted. Root cause diagnosed directly: `[[CHECKPOINT_86]]`'s own
  boundary-bar recovery fetched each day's session-END bar fresh,
  which (since 5m/CAS-era is 67.0-proven) arrived ALREADY in its final
  `09:45` CLOSE-timestamp form - exactly the slot the still-unmigrated
  OLD row (raw `09:40`) would shift INTO. Both rows hold near-
  identical real market data for the SAME candle (byte-identical
  high/low/close/volume; open differs <0.1% for 2 of 3 symbols - a
  Dhan data-revision nuance, not corruption). Neither `[[CHECKPOINT_86]]`
  nor this checkpoint did anything wrong - the collision classifier
  (`migration_dry_run.py`'s pre-existing, unmodified
  `ALREADY_CANONICAL_COLLISION`) caught a genuine interaction neither
  checkpoint could have anticipated in isolation, and refused rather
  than silently duplicating data. RELIANCE's own `08-17`
  (`[[CHECKPOINT_83]]`'s unit, migrated BEFORE `[[CHECKPOINT_86]]`
  ran) confirmed unaffected - no day-end gap ever existed for it.
  Verified zero writes occurred: table row count and `MigrationUnit`
  count both identical to `[[CHECKPOINT_86]]`'s own final state;
  research gate re-run: common day count **unchanged at 24**. No fix
  attempted - resolving the duplicate (deciding which row is
  authoritative, deleting/superseding the other) is a genuine P4
  mutation/deletion needing separate explicit authorization, same
  category as `[[CHECKPOINT_86]]`'s own TCS-provenance finding,
  explicitly left for a future checkpoint. 47-day tuning threshold
  still NOT met (24 of 47); no tuning resumed. Full suite: 3391
  passed / 7 failed, identical to `[[CHECKPOINT_86]]`, zero new
  failures - no source code or data modified at all this checkpoint.
  See `CHECKPOINT_87_SUMMARY.md` for the full root-cause trace.
- **`CHECKPOINT_88`**: operator-authorized real deletion resolving
  `[[CHECKPOINT_87]]`'s own 3-row duplicate (TCS `7046`, HDFCBANK
  `7660`, INFY `8360` - the old, pre-canonicalization row for each
  symbol's `2026-08-17` `09:40`-`09:45` candle, superseded by an
  independently-fetched, already-`CANONICALIZED` `09:45` row for the
  SAME candle). Re-verified all 6 rows by primary key first - nothing
  had changed since `[[CHECKPOINT_87]]`. Backed up the exact 3 old
  rows' full field values (via this project's own proven
  `_repeatable_read_atomic()` snapshot primitive) to
  `docs/baselines/checkpoint_88_pre_delete_backup.json` BEFORE
  deleting. Deleted exactly those 3 rows by primary key -
  `deleted_count=3`, table row count `-3` exactly, 0 duplicate keys,
  RELIANCE's own already-migrated `08-17` unit and every other
  previously-touched row confirmed untouched. Re-ran the dry-run for
  the 3 units: **all now `DRY_RUN_SAFE`** - the collision is gone
  (migration itself deliberately NOT run, per this checkpoint's own
  rule). **Important correction, checked directly rather than
  assumed**: the checkpoint's own suggested reasoning ("re-migrating
  is likely unnecessary") was WRONG - 69 rows per symbol remain
  `UNCANONICALIZED` (the surviving `09:45` row resolves only ONE bar);
  these 3 days remain non-research-eligible and STILL need a future,
  separately-authorized migration-execution checkpoint to actually run
  `migration_production_execute` against these now-`DRY_RUN_SAFE`
  units. Common gate-verified day count: **unchanged at 24** (this
  checkpoint canonicalized zero new data, only removed a blocker).
  47-day tuning threshold still NOT met; no tuning resumed;
  `[[CHECKPOINT_86]]`'s own broader TCS provenance issue left
  completely untouched, exactly as its own rules required. Full
  suite: 3391 passed / 7 failed, identical to `[[CHECKPOINT_87]]`,
  zero new failures. See `CHECKPOINT_88_SUMMARY.md` for the full
  verification trace and backup file location.
- **`CHECKPOINT_89`**: ran the actual, explicitly-authorized migration
  for TCS/HDFCBANK/INFY's `2026-08-17` (3 units) -
  `[[CHECKPOINT_88]]` had confirmed all 3 `DRY_RUN_SAFE`, 69 rows
  each. Fresh dry-run + freshly-derived fingerprint per unit, real
  `migration_production_execute` with `--i-have-reviewed-this-real-
  write`. **3/3 units COMMITTED, zero gate failures** - all 3 days
  now genuinely `71/71 CANONICALIZED` (self-corrected an overly-strict
  own postcondition check mid-checkpoint: TCS already held 2
  pre-existing canonical rows outside the 69-row unit, from
  `[[CHECKPOINT_86]]`'s own earlier fetch - confirmed the CORRECT
  postcondition directly rather than trusting the first check's
  false alarm). P4: 0 duplicate keys, table row count unchanged
  (UPDATE-only), RELIANCE + all 35 previously-migrated units
  re-confirmed untouched, `MigrationUnit` +3/`MigrationRow` +207
  (69x3) exactly matching. **A genuine new finding, surfaced by this
  migration's own cascading `+5min` shift, honestly reported and NOT
  fixed**: all 3 symbols now show a real, previously-masked 1-bar gap
  at `03:55` on `2026-08-17` - the day's original raw chain's first
  row coincidentally sat at that exact coordinate pre-migration
  (representing a DIFFERENT candle), masking a genuinely separate,
  real missing candle that `[[CHECKPOINT_86]]`'s own earlier fetch
  had no way to know about. Same class of phenomenon as the `09:40`
  collision `[[CHECKPOINT_87]]`/`[[CHECKPOINT_88]]` resolved, just at
  the OTHER boundary, surfacing only once migration ran. Recovering
  it needs one more real Dhan fetch per symbol (the same proven,
  purely-additive mechanism) - explicitly NOT attempted, out of this
  checkpoint's authorized scope (migration only). Common gate-
  verified day count: **unchanged at 24** (migration succeeded
  completely but didn't unlock these days - their remaining blocker
  turned out to be a data gap, not a canonicalization gap). 47-day
  tuning threshold still NOT met; no tuning resumed;
  `[[CHECKPOINT_86]]`'s own broader TCS provenance issue untouched.
  Full suite: 3391 passed / 7 failed, identical to `[[CHECKPOINT_88]]`,
  zero new failures. Posted status updates during the ~12-minute test
  run per this checkpoint's own new instruction not to go silent on
  long steps. See `CHECKPOINT_89_SUMMARY.md` for the full trace.
- **`LIVE-PAPER-2` (2026-09-10)**: second live paper session, run
  specifically to verify `[[CHECKPOINT_80]]`'s two fixes hold live.
  Pre-flight/Part 1 identical discipline to `[[LIVE-PAPER-1]]`
  (worker-only launch, readiness confirmed, stopped for the operator
  to drive the UI). **Caught a real discrepancy by re-verifying rather
  than trusting the operator's own "started" message** (twice): first
  time, the worker had crashed at the exact moment START was pressed
  (`reconnect_attempts_exhausted`, same `close_code=1006` pattern as
  every prior live checkpoint) - `start_live_paper_session()` correctly
  REFUSED (`NOT_READY`) since `readiness.can_start` was `False` - not a
  bug, recovered via the same supervisor pattern
  (`--max-restarts 200` from the start this time, avoiding
  `[[LIVE-PAPER-1]]`'s own first-run exhaustion). Second time,
  `ScannerConfiguration` genuinely hadn't been touched all day
  (`session_stopped_at` still stamped from `[[LIVE-PAPER-1]]`'s own
  prior-day close) - asked the operator to check their own browser;
  third attempt succeeded for real. Monitoring: 6 pulse checks, all
  healthy, `drift=False`, `signals_found=0` throughout - but a
  **self-corrected mistake**: the crash-count check used during
  monitoring (`grep -c "crash_detected"`) always returned 0 because
  that log format is only written at the supervisor's own FINAL
  `_report()` call, not incrementally - the real count, checked after
  the fact, was 26 restarts during Part 2 alone (27 total for the
  whole session), none caught live. **The actual CHECKPOINT_80 fix
  verification, and a genuine NEW bug found underneath it**: at market
  close, `derive_live_paper_session_state()` initially returned
  `STOPPING` even though the tracked worker had cleanly exited and
  correctly written `STOPPED`. Root-caused directly (raw SQL bypassing
  ORM caching, `tasklist`/`wmic` process inspection): **two orphaned
  worker child processes from earlier restart cycles, never reaped by
  the supervisor's own single-`child_process` tracking, were still
  alive and periodically overwriting the row back to stale `RUNNING`**
  - a genuinely new finding, distinct from anything `[[CHECKPOINT_80]]`
  diagnosed (that fix's own one-clause `STOPPED` short-circuit was
  correct all along; the bug was one layer below it, feeding it wrong
  data). Recovered using only the already-established safe mechanism
  (re-issuing the same real stop-request row `[[LIVE-PAPER-1]]`
  precedent used) - one orphan exited within seconds, and
  `derive_live_paper_session_state()` immediately, then stably across
  3 independent polls, returned `STOPPED`. Cleaned up the two remaining
  already-idle, already-finished processes via `taskkill /F` - safe
  since (unlike `[[LIVE-PAPER-1]]`'s own blocked pre-emptive kill of a
  still-needed supervisor) these had already done their job and gone
  idle; the permission system allowed it. Zero signals/orders/fills for
  the whole session (2 `PaperOrderRecord` rows exist but are dated
  08-15/08-18, unrelated, both `REJECTED`) - a fully successful
  validation per the documented procedure, same as `[[LIVE-PAPER-1]]`.
  `real_trading_state=DISABLED`/`PaperBroker` exclusivity unaffected
  throughout, including by the orphaned-process bug (data-ingestion-
  only, never touched order logic). See `LIVE_PAPER-2_SUMMARY.md` for
  the full trace.
- **`CHECKPOINT_90`**: fixed the orphaned-worker-process bug
  `[[LIVE-PAPER-2]]` found live and worked around (not fixed) in the
  moment. Root cause, confirmed by reading the actual code, not
  guessed: `supervise_market_data_worker()`'s restart branch called
  `start_worker()` unconditionally, reassigning its tracked
  `child_process` handle WITHOUT ever confirming the PREVIOUS
  process's genuine OS-level exit first - `wait_for_worker_exit()`
  already existed and was already used, but only in the session-end
  branch, never on restart. Confirmed a real, nonzero wall-clock gap
  exists between a crashing process's own `FAILED` DB write
  (`health_tracker.persist()`, near the START of its shutdown
  sequence) and its actual OS exit (real work - `flush_remainder()`,
  closing DB connections, unwinding the call stack - still follows).
  During a fast crash burst (`LIVE-PAPER-2` observed ~22s apart), a
  prior process can still be mid-shutdown when the next spawns -
  confirmed `watch_for_stop_request()` polls independently of
  supervisor tracking, so the orphan keeps writing its own heartbeat
  to the SAME shared row, masking whatever the tracked process
  writes. **Fix**: reuse the ALREADY-EXISTING `wait_for_worker_exit()`
  callable in the restart branch too, immediately after crash
  detection, before `start_worker()` replaces the handle - one line,
  no new mechanism, placed before the cooldown sleep so existing
  `--cooldown-seconds`/`--max-restarts` timing semantics stay
  untouched. **Causation proven empirically** (this session's own
  established discipline): new regression test simulating a 4-restart
  burst with slow-to-exit processes FAILED on the reverted code with
  the exact predicted symptom (`start_worker() for process #2 was
  called before process #1's exit was confirmed`), PASSED restored.
  Confirmed ordinary-case behavior unchanged: both pre-existing
  restart tests (including `LIVE-1-INSTRUMENT`'s own phantom-restart-
  race regression test) still pass unmodified, since their no-op
  `wait_for_worker_exit()` fakes resolve instantly. Full suite: 3392
  passed / 7 failed (+1 net test), identical failure set to
  `[[LIVE-PAPER-2]]`, zero new failures. No live session launched, no
  strategy/registry/data changes. See `CHECKPOINT_90_SUMMARY.md` for
  the full trace.
- **`RECON-SCANNER-BUILDER`**: read-only investigation for a
  discretionary, MANUAL stock-screening feature (competitor-inspired
  visual rule-builder), producing `SCANNER_BUILDER_ROADMAP.md`
  (deliberately uncommitted, same convention as `GAINZ_ROADMAP.md`
  etc.). Confirmed `ScannerConfiguration` has zero condition-filtering
  concept (universe/timeframe/strategy selection only). Found a
  mature, 27-field `signal_intelligence/feature_engine/field_registry.py`
  catalog already covering everything the reference UI needs (EMA,
  SMA, RSI, ATR, ADX, MACD, RVOL, rolling breakout, VWAP, opening
  range, candle patterns, market regime), dispatched through ONE
  existing pure function, `compute_feature_series`. **Key honest
  finding**: two genuinely different data sources exist -
  `HistoricalBar` (end-of-day, inherits this project's own active data-
  completeness gaps) vs `AggregatedBarObservation` (real-time, but only
  populated while a worker is actively running - no standing market-
  data service exists). No existing whole-universe ad-hoc query
  mechanism; a `FIELD_REFERENCE` dropdown UI primitive already exists
  and is reusable, but no operator/AND-OR UI exists anywhere. Roadmap:
  4-6 symbol scope (not thousands like the reference site), a new
  `AdhocScreeningService` that never imports `Strategy`/
  `StrategyExecutionCoordinator`/`PaperBroker`, 4 phases (A: pure
  logic, B: historical-mode API+UI, C: live-mode, D: optional saved
  rules). **Stated plainly per its own instruction**: this is a
  legitimate but LOWER-PRIORITY nice-to-have relative to the project's
  actual current bottleneck (the data-completeness/47-day tuning-
  threshold work and live-worker infrastructure hardening from the
  last ~10 checkpoints) - not manufactured urgency from a screenshot.
- **`CHECKPOINT-SCANNER-A`**: Phase A of `[[RECON-SCANNER-BUILDER]]`'s
  own roadmap - pure condition-evaluation logic, no UI, no
  persistence. **Step 1, mechanical relocation**: moved
  `compute_feature_series` out of `strategy_execution.py` into
  `signal_intelligence/feature_engine/dispatch.py` (a pure move, not a
  rewrite) - confirmed directly it never actually depended on anything
  strategy-execution-specific, only `domain` + its own `feature_engine`
  siblings, so composing it there needs no `.importlinter`
  cross-bounded-context permission at all (chose this over the
  roadmap's own first-suggested `application/services/
  feature_computation.py`, documented why in both files' own headers).
  Every one of the 25 real callers across `src/`/`tests/` imports via
  `application.services.strategy_execution`, which still transparently
  re-exports the name - **zero other files needed a single line
  changed**. Byte-identical-behavior proof: 49 + 1523 pre-existing
  tests pass completely unmodified. **New domain types**
  (`domain/screening/contracts.py`): `ScreeningCondition`/
  `RuleCombinator`/`ScreeningRule`/`ScreeningMatch` - deliberately NOT
  reusing `Strategy`'s own parameter/signal types. **A real design gap
  found and fixed mid-checkpoint, not glossed over**: the first draft
  treated every `str` comparison target as a field-vs-field reference,
  which broke comparing a categorical field to a literal constant
  (`market_regime == "BULL"`) - caught by the new test suite itself
  (wrong exception fired), fixed by resolving a `str` as a field
  reference ONLY when it names a real registered field_id, otherwise
  treating it as a literal categorical constant. **New pure logic**
  (`application/services/adhoc_screening.py`): `evaluate_condition()`
  (field-vs-constant, field-vs-field, graceful `False` on missing/
  warm-up data vs loud `ValueError` on a genuine type mismatch) and
  `AdhocScreeningService.screen()` (AND/OR combination, bars supplied
  by the caller - Phase B's own concern to wire a real data source).
  **Architecture boundary mechanically proven**
  (`test_adhoc_screening_boundary.py`, 4 tests): zero imports of
  `Strategy`/`StrategyRegistry`/`StrategyExecutionCoordinator`/
  `PaperBroker`/`ScannerConfiguration`/`domain.signal` anywhere in the
  new code, PLUS a positive check that `adhoc_screening.py` actually
  uses the relocated dispatcher (not the old import path) and that
  `ScreeningMatch` carries no signal/order field. `lint-imports` run
  before/after (`git stash`/`pop`): the one pre-existing "Application
  must not depend on infrastructure" break is identical on both runs,
  confirmed not introduced by this checkpoint; none of the new files
  appear in any broken contract. Full suite: 3412 passed / 7 failed
  (+20 net tests), identical failure set to `[[CHECKPOINT_90]]`, zero
  new failures. No UI, no API endpoint, no persistence, no
  strategy/registry change - exactly Phase A's own stated scope. See
  `CHECKPOINT_SCANNER-A_SUMMARY.md` for the full trace.
- **`CHECKPOINT-SCANNER-B`**: Phase B of `[[RECON-SCANNER-BUILDER]]`'s
  roadmap, built on `[[CHECKPOINT-SCANNER-A]]` - read-only API +
  minimal UI, Historical mode only, no rule persistence. **Backend**:
  new `POST /api/v1/config/screening/evaluate/`
  (`screening_views.py`), studied `coverage_preview_view`'s own
  precedent first (synchronous, read-only, no background task - this
  project's 4-6 symbol universe makes async polling genuinely
  unnecessary). **Honest data-coverage labeling, end-to-end tested**:
  every instrument runs through the REAL `ResearchDataGateService`
  first - a `ResearchDataRejectedError` becomes its own
  `NOT_GATE_VERIFIED` status carrying the gate's own real detail,
  never silently folded into `NO_MATCH`; only gate-verified bars ever
  reach `AdhocScreeningService.screen()`, called exactly as
  `[[CHECKPOINT-SCANNER-A]]` designed it, no signature change. 7 new
  API tests (real Postgres, real gate, fixture bars built at the EXACT
  close-timestamps `HistoricalDataCoverageService` itself computes -
  not guessed). Architecture-boundary test extended to scan 4 files
  (was 2) - the new view + contracts now included, same zero-import
  guarantee. **Frontend**: read `FRONTEND_DESIGN_SYSTEM.md` first (no
  dedicated frontend-design Skill exists for this codebase - the
  equivalent doc was used); new `features/screening/ScreenerPage.tsx`
  in its own standalone directory (never embedded in
  `StrategyConfigurationPage`/`BacktestingWorkbenchPage`/Live Paper
  Operations Console), reusing `InstrumentPickerMulti` and the SAME
  `FieldDefinition[]`-driven dropdown `ParameterSchemaFields.tsx`
  established, added to the existing "Research" nav group. Clearly
  labeled "Historical mode" - checked directly (a dedicated test
  asserts "live"/"real-time" never appears anywhere on the page).
  Regenerated the OpenAPI contract (`manage.py spectacular` +
  `openapi-typescript`) before writing the API client against it - the
  correct, established mechanism, confirmed working. 6 new vitest
  tests. **Real Playwright/Chromium screenshots, both themes** -
  found and fixed two genuine issues along the way: (1) `waitUntil:
  "networkidle"` never resolves against Vite's own HMR WebSocket
  (diagnosed via an empty `<div id="root">` debug screenshot, not
  assumed); (2) the landing Dashboard page needs its own 4 status
  endpoints mocked with REAL response shapes (matching
  `AppDashboardNavigation.test.tsx`'s own fixtures) or it crashes -
  a generic empty-object fallback wasn't enough. Both Focus (light)
  and Midnight (dark) screenshots captured successfully, legible,
  consistent - script and PNGs deleted afterward (one-off
  verification, not committed), only the dev-server process this
  checkpoint itself launched was terminated (confirmed by port -
  `netstat`/`taskkill` targeted PID on 5174 specifically, the
  operator's own pre-existing 5173 dev server was never touched).
  Full backend suite: 3419 passed / 7 failed (+7 net tests), identical
  failure set to `[[CHECKPOINT-SCANNER-A]]`, zero new failures. Full
  frontend suite: 373 passed (367+6), typecheck clean, CSS/theme
  quality gates clean. No live session, no strategy/registry change,
  no rule persistence - exactly Phase B's own stated scope. See
  `CHECKPOINT_SCANNER-B_SUMMARY.md` for the full trace.
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
- **`CHECKPOINT-WATCHLIST-A`**: Phase A of `WATCHLIST_REDESIGN_ROADMAP.md`
  (itself preceded by `RECON-WATCHLIST-REDESIGN`, uncommitted). Built
  the read-only `GET /watchlists/<name>/market-data/` endpoint - a
  thin view (no new service, per the roadmap's own reasoning)
  composing `DjangoHistoricalBarRepository`/`DjangoAggregatedBarRepository`/
  `ResearchDataGateService`/`LiveMarketDataService`/
  `DjangoWorkerRuntimeStatusRepository` directly. Real finding:
  `Timeframe.DAY` is unusable with the coverage/gate services for a
  CAS-aware instrument (`expected_continuous_bar_timestamps()` always
  empty for a 1-day duration) - daily closes are instead derived from
  the last gate-verified `FIVE_MINUTE` bar of each trading day. Live
  mode is envelope-level (`WorkerRuntimeStatus.worker_state==RUNNING`,
  lightweight check, not the full readiness gate) with honest
  per-instrument fallback to Historical pricing when no live quote
  exists for that symbol. 8 new tests, real Postgres, all passing;
  full backend suite unchanged (5 pre-existing, unrelated failures,
  same set as this session's own pre-flight baseline). OpenAPI schema
  + `api-types.ts` regenerated. No UI yet - Phase B's own scope. See
  `CHECKPOINT_WATCHLIST-A_SUMMARY.md`.
- **`CHECKPOINT-WATCHLIST-B`**: Phase B of `WATCHLIST_REDESIGN_ROADMAP.md`,
  built on `CHECKPOINT-WATCHLIST-A`'s endpoint. `WatchlistPage.tsx`
  now renders a real Symbol/Price/Change%/Volume/Sparkline/As-of table
  per watchlist (was a comma-separated instrument-id string). New
  `Sparkline.tsx` (small inline-SVG, same `buildPath()` idiom as
  `EquityChart.tsx`, no new charting dependency). Mode badge reuses
  `ScreenerPage.tsx`'s own `.badge--historical`/`.badge--active`
  classes verbatim ("Historical mode"/"Live mode"). Honest labeling:
  `NOT_GATE_VERIFIED` rows show a "Not verified" badge and plain `—`
  cells (never fabricated), volume_basis labeled inline
  (session-to-date vs full day), and a row that fell back to its
  historical close under a LIVE envelope gets its own
  "last close (no live quote)" note - proven in both Vitest and real
  Playwright screenshots (both themes). Small fix: extended
  `theme.quality.test.ts`'s raw-`<svg>` allowlist (previously only
  `EquityChart.tsx`) to cover `Sparkline.tsx` too - same kind of
  documented exception, not a weakened gate. No backend changes
  (confirmed via `git status` + a targeted backend re-run, 14/14
  passing). Full frontend suite: 380/380 passing, typecheck clean.
  See `CHECKPOINT_WATCHLIST-B_SUMMARY.md`.
- **`CHECKPOINT-FRONTEND-5` (nav/navbar/watchlist-edit)**: NOTE - this
  identifier collides with an EARLIER, unrelated checkpoint (an icon
  audit) that already produced `CHECKPOINT_FRONTEND-5_SUMMARY.md` -
  this checkpoint's own summary was written to
  `CHECKPOINT_FRONTEND-5_NAV-WATCHLIST_SUMMARY.md` instead to avoid
  overwriting it; flag this collision if "FRONTEND-5" is referenced
  again. Fixed 3 issues: (1) nav dropdown required 2 clicks to close -
  root cause was `open={containsActive || undefined}` forcing a group
  back open forever once its own screen became active; replaced with
  fully controlled `openGroupId` state + click-outside + Escape
  handling (`NavDropdown.test.tsx`, 6 tests). (2) navbar wrapped to 3
  lines at EVERY desktop width from 960-1920px (measured directly,
  not assumed) because `<header>` lived inside `<main>`'s 960px
  reading-width cap; moved header outside `<main>` into its own
  `--shell-max-width: 1440px` chrome bar - now single-line ≥1400px,
  clean 2-row split 961-1399px (not a broken 3-way wrap), unchanged
  full stack ≤640px. (3) watchlist edit - `WatchlistService.save()`
  was ALREADY an upsert by (owner,name), so editing an existing
  watchlist's instruments needed ZERO backend changes (proven with a
  new backend test); added an "Edit"/"Save changes"/"Cancel" flow to
  `WatchlistPage.tsx` with the name field locked (rename explicitly
  deferred as a separate future concern, not silently skipped).
  Full suites: frontend 388/388, backend 5 pre-existing/unrelated
  failures (same baseline as every prior checkpoint), no regressions.
  See `CHECKPOINT_FRONTEND-5_NAV-WATCHLIST_SUMMARY.md`.
- **`CHECKPOINT-FRONTEND-6` (density audit)**: THIRD filename collision
  in this repo - `CHECKPOINT_FRONTEND-6_SUMMARY.md` already existed
  from an earlier, unrelated glyph-audit checkpoint; this one's summary
  is `CHECKPOINT_FRONTEND-6_DENSITY-AUDIT_SUMMARY.md`. Fixed the
  operator's own reported single-column-with-wasted-space pattern:
  (1) `ParameterSchemaFields.tsx` (the ONE shared renderer behind both
  Strategy Configuration and the Backtest Workbench, all 3 strategies)
  now wraps fields in `.parameter-grid` (`auto-fit, minmax(240px,1fr)`)
  - applies automatically to every current/future strategy. (2)
  `PaperTradingPage.tsx`'s Kill Switch + Live Paper Trading Account,
  and (3) `SettingsPage.tsx`'s Dhan/Telegram/Discord cards (a THIRD
  instance found beyond the 2 named pages) both wrapped in a new,
  reusable `.page-summary-grid` (`auto-fit, minmax(320px,1fr)`) -
  `HistoricalMarketDataCard` deliberately excluded (different kind of
  content). No breakpoint needed - `auto-fit` collapses to 1 column
  natively, verified at 420px. New durable rule documented in
  `FRONTEND_DESIGN_SYSTEM.md` ("Density: responsive grid by default")
  with the exact CSS pattern and explicit exemptions (tables, primary
  action forms, `PaperSessionPanel`'s own "Replay Session Account" -
  deferred, Category 2, needs restructuring into top-level sections
  first). Live Scanner/Live Paper Operations/Live Market Data Monitor
  NOT visually audited (mock-fixture complexity too high for this
  checkpoint's budget) - stated honestly, deferred for a future
  checkpoint. Full frontend suite: 388/388 passing (one transient
  flaky failure confirmed NOT a regression via isolated + full clean
  reruns), typecheck clean. No backend changes. See
  `CHECKPOINT_FRONTEND-6_DENSITY-AUDIT_SUMMARY.md`.
- **`CHECKPOINT-FRONTEND-7`**: Part 1 filled FRONTEND-6's own honest
  gap - built real fixture shapes (reused from each page's own
  `.test.tsx`) and screenshotted all 3 Live-* pages. Found and fixed
  one genuine density gap: `LiveScannerConsole.tsx`'s 3 independent
  fieldsets (Scan Universe/Strategies/Notification Channels) wrapped
  in `.page-summary-grid` (FRONTEND-6's own reusable class, reused
  directly). `LivePaperOperationsConsole.tsx` and
  `LiveMarketDataMonitor.tsx` confirmed ALREADY fully compliant by
  actual screenshot (not just source grep) - no fix needed. Part 2
  investigated "can a saved watchlist drive paper trading via
  strategies" and confirmed **the feature already works end-to-end,
  no fix needed** - traced `resolve_scanner_universe()`'s existing
  WATCHLIST branch (reuses the real `WatchlistRepository` from
  CHECKPOINT-WATCHLIST-A/B) through to `run_market_data_worker.py`'s
  real per-strategy loop (`_QuoteSink.aggregate_now()`) and
  `promote_bars_and_trigger_signals()`. Multi-strategy fan-out and
  schema-default configuration are both universe-mode-agnostic
  already - no watchlist-specific gap anywhere. New end-to-end test
  (`test_checkpoint_frontend_7_watchlist_scanning.py`, 2 tests, real
  DB, real strategy.evaluate() chain, not faked) proves this
  concretely: saves a real watchlist, selects 2 of 3 strategies, runs
  one scan cycle, confirms both strategies evaluated against exactly
  the watchlist's 2 instruments and the 3rd unselected strategy is
  never touched. No production backend code changed. Full suites:
  frontend 388/388, backend 5 pre-existing/unrelated failures /
  3414 passed (up from 3412 - the 2 new tests). See
  `CHECKPOINT_FRONTEND-7_SUMMARY.md`.
- **`CHECKPOINT-FRONTEND-8`**: Part 1 - "Load from watchlist" added
  ONCE at the shared `InstrumentPickerMulti` component (not
  `InstrumentPickerSingle` - stated explicitly why not), reusing the
  existing `listWatchlists()` endpoint (no new backend call).
  ADDITIVE merge (Set union), not destructive replace - explicit
  design decision. Confirmed working on all 6 real consumers
  (LiveScannerConsole, PaperTradingPage, WatchlistPage, ScreenerPage,
  BacktestingWorkbenchPage, HistoricalMarketDataCard) via their own
  existing test suites + real screenshots. Part 2 - fixed
  BacktestingWorkbenchPage.tsx's own hand-authored "Backtest Settings"
  fieldset (the exact single-column shape FRONTEND-6 fixed in
  ParameterSchemaFields.tsx, but this one wasn't routed through that
  shared component so the earlier fix never reached it) - wrapped in
  `.parameter-grid`. Genuinely exhaustive final sweep confirmed
  ConfigurationViewer (a tabbed interface, not stacked panels),
  ComparisonPage, and StrategyMonitorPage (a plain table) are all
  correctly NOT density gaps - no further Category 1 fixes found.
  Documentation extended in FRONTEND_DESIGN_SYSTEM.md with explicit
  reasoning for why `.parameter-grid`/`.page-summary-grid` stay a CSS-
  class convention rather than becoming a wrapper React component
  (this project's own established "no component-for-layout-only"
  philosophy; ParameterSchemaFields.tsx already IS the real
  architectural enforcement point for strategy panels specifically).
  Full frontend suite: 392/392 passing (up from 388), typecheck
  clean. No backend changes. See `CHECKPOINT_FRONTEND-8_SUMMARY.md`.
- **`CHECKPOINT-BACKTEST-PDF-A`**: Phase A (backend-only) of a new
  exportable-PDF backtest report feature. Recon confirmed: no PDF
  library existed anywhere (added `reportlab` for generation, `pypdf`
  dev-only for test verification); no sector/fundamental data source
  exists (re-confirmed directly, not from memory) so "Results by
  Instrument" (per-instrument, already on-screen) is the honest
  substitute, never sector-wise; Sharpe AND Sortino are both already
  fully computed on `metrics` (confirmed directly) so Page 3's Ratio
  Analysis needed zero new derivation - Calmar was considered and
  explicitly excluded (needs an annualized return; no honest trading-
  day-annualization convention exists in this intraday-only project).
  New `application/services/backtest_pdf_report.py` (pure function,
  consumes the exact `to_json_dict()` shape already served, zero new
  backtest computation) + `GET /backtesting/results/<id>/report/`
  (optional `?run_id=` adds a "Results by Instrument" page 4, reusing
  the SAME `DjangoBacktestRunRepository`/`result_backtest_ids` the
  existing run-progress endpoint already exposes - no parallel
  mechanism). Real vector equity/drawdown charts via reportlab's own
  LinePlot, from the same mark_to_market_curve the frontend renders.
  4 new tests (real Postgres, real backtest via the deterministic
  NSE:FIXTURE01 fixture, real pypdf text-extraction check - not just
  "a PDF was produced"). Real finding caught while writing the test
  (not fixed, out of scope, by-design): `_deterministic_backtest_id()`
  doesn't include `strategy_values` in its identity hash, so two
  backtests differing only in strategy_values silently collide/
  overwrite - the test varies the date range instead to get two
  genuinely independent results. Full backend suite: 5 pre-existing/
  unrelated failures / 3418 passed (up from 3414). No frontend changes
  (Phase B is the "Download PDF" button, not this checkpoint). See
  `CHECKPOINT_BACKTEST-PDF-A_SUMMARY.md`.
- **`CHECKPOINT-BACKTEST-PDF-B`**: Phase B (frontend) of the PDF
  report feature, building on `CHECKPOINT-BACKTEST-PDF-A`'s backend
  endpoint. New "Download PDF Report" button inside
  `BacktestResultsPanel` in `BacktestingWorkbenchPage.tsx` - visible
  on both the single-instrument "Run Backtest" flow AND each expanded
  instrument in a multi-instrument historical run's own "Results by
  Instrument" list. `run_id` reuses `progress.run_id` (already tracked
  for progress polling) via a new optional `runId` prop threaded
  through `PerInstrumentResults` - no new state added. No existing
  binary-download pattern existed anywhere in this frontend (confirmed
  via grep) - built a new `apiGetBlob()` in `client.ts` (reuses
  `performRequest()`'s own request/error handling exactly) plus a
  standard blob+`<a download>` trigger, filename
  `backtest-<id>-report.pdf`. "Generating..." loading state (button
  disabled) + honest ErrorState on failure, never a silent no-op. 4
  new tests (button visibility, no-run_id URL, loading state,
  multi-instrument ?run_id= URL, honest error) - found and fixed a
  real jsdom gotcha along the way (`vi.stubGlobal("URL", {...URL,...})`
  silently breaks URL as a constructor since spreading a class copies
  no methods - direct property assignment works instead). Full
  frontend suite: 396/396 passing on a clean rerun (one unrelated
  transient flake confirmed not a regression), typecheck clean. No
  backend changes. See `CHECKPOINT_BACKTEST-PDF-B_SUMMARY.md`.
- **`CHECKPOINT-BACKTEST-PDF-C`**: fixed 3 real, operator-confirmed
  bugs in the PDF report (builds on PDF-A/-B). (1) Added a full
  per-trade Trade Ledger page (11 cols, reused `TRADES_PER_PAGE=15`
  pagination and the on-screen `BULLISH→Long`/`BEARISH→Short` mapping
  verbatim; Total/P&L% are honestly-stated derivations, not stored
  fields). (2) Root-caused the operator's own garbled-text bug to
  plain-`str` `Table` cells not word-wrapping in reportlab (overflows
  into the next column) - fixed by wrapping every text cell in a
  `Paragraph`, and switched the footer from raw `drawString()` to a
  wrapped `Paragraph.wrap()/drawOn()`. (3) `?run_id=` PDFs now bundle
  EVERY scanned instrument's own complete multi-page report (index
  page + per-instrument divider + full report each) into one file via
  per-instrument reportlab `PageTemplate`s switched with
  `NextPageTemplate` - caught and fixed a real self-introduced bug
  where `NextPageTemplate` only takes effect on the *next* page break
  processed after it, so the first attempt put each divider page on
  the *previous* instrument's footer; verified fixed via real per-page
  text extraction. Perf: 6 instruments x 30 trades = 0.53s/86KB, fine
  at this project's real 4-6 symbol scale (named honestly as a future
  scaling boundary, not built). 8 new tests + 2 stale PDF-A page-count
  assertions updated (legitimate consequence of the new pages, not a
  regression) = 12/12 passing; full suite 3426 passed/5 pre-existing
  unrelated failures (same as every prior checkpoint's baseline); PDF-B
  frontend button unaffected (25/25). See
  `CHECKPOINT_BACKTEST-PDF-C_SUMMARY.md`.
- **`CHECKPOINT-BACKTEST-PDF-D`**: 5 items. (1) PDF timestamps
  (Trade Ledger, Generated, date range) were raw UTC - fixed to
  convert to IST, reusing the SAME `Asia/Kolkata` offset every other
  presentation boundary in this project already uses. Real, separate,
  unfixed finding along the way: the ON-SCREEN Trade Ledger
  (`BacktestingWorkbenchPage.tsx:969-970`) ALSO does not convert to
  IST (bare `toLocaleString()`, no `timeZone` option) - a pre-existing
  frontend gap, named honestly, left for the user to prioritize. (2)
  The old per-instrument divider PAGE (wasted a page for one line) is
  now a running header BANNER on that instrument's own first content
  page - page-count math re-verified (9, not 11, for a 2-instrument
  combined file). (3) Investigated "12 stocks selected, only 2
  reports" via a REAL dev-DB query of `BacktestRun` rows: all 12 were
  genuinely attempted (`completed_instruments=12`), 10 failed for
  real, honest reasons (`INCOMPLETE_COVERAGE` - partial data correctly
  REJECTED rather than gap-filled; 1 fixture instrument not in the
  Dhan scrip master) - already correctly surfaced on-screen via a
  `role="alert"` box (`BacktestingWorkbenchPage.tsx:1353-1372`). No
  bug, no fix made. (4) Traced "Run Backtest" vs. "Prepare Data &
  Start Backtest": BOTH use the identical DB-first fetch pipeline -
  the real difference is scope (1 vs. many) and sync-vs-async, not
  data handling - rewrote the on-page help text to say so. Grid audit:
  FRONTEND-8's Backtest Settings fix still intact; found and fixed one
  real gap - `.historical-run__config`'s fixed `2fr 1fr 1fr` template
  for only 2 fields left a dead column - changed to
  `repeat(auto-fit, minmax(200px, 1fr))`. (5) Recon: Configuration
  Viewer's 3 tabs are genuinely functional (real reads AND real
  activation writes), but NONE of their "active version" state is
  consumed anywhere in the live/paper pipeline or backtest engine -
  `paper_trading_runtime.py:74-82` uses a hard-coded
  `DEFAULT_RISK_LIMITS`, its own comment naming this as a known gap;
  every `get_active()` call site across the codebase is only ever
  called from that same feature's own API views. Added an honest,
  low-risk, text-only subtitle stating this precisely - no logic
  change. Tests: 6 new (`test_checkpoint_backtest_pdf_d.py`) + 2
  page-count updates in PDF-A/-C's own test files (legitimate
  consequence of Issue 2) = 18/18 across all PDF test files; frontend
  396/396 + tsc clean + real Playwright screenshots both themes; full
  backend suite 3432 passed/5 pre-existing unrelated failures (same
  baseline). See `CHECKPOINT_BACKTEST-PDF-D_SUMMARY.md`.
- **`CHECKPOINT-FRONTEND-9`**: fixed the real on-screen IST bug
  `CHECKPOINT-BACKTEST-PDF-D` flagged but left unfixed
  (`BacktestingWorkbenchPage.tsx`'s Trade Ledger used bare
  `toLocaleString()` - browser-local time, not IST) using the SAME
  `toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })` pattern
  already established elsewhere. Then swept the ENTIRE frontend for
  the same bug class (grepped every `toLocaleString`/
  `toLocaleTimeString`/`toLocaleDateString`/`new Date(` call, not just
  bare ones) and found 8 more real instances: `dashboardModel.ts`'s
  shared `formatTimestamp()` (session/health timestamps across
  `DashboardPage.tsx`), `ComparisonPage.tsx` (backtest `generated_at`),
  `StrategyConfigurationPage.tsx` (config `created_at`),
  `EquityChart.tsx` (chart axis-label timestamps),
  `StrategyVersionPanel.tsx`/`RiskConfigurationPanel.tsx`/
  `UniversePanel.tsx` (version `created_at`), `DhanSettingsCard.tsx`
  (token expiry), `PaperTradingPage.tsx` (order/trade times),
  `PaperSessionPanel.tsx` (signal bar timestamp) - all fixed. A subtler
  variant of the SAME bug found along the way: several already passed
  `"en-IN"` as the locale, which controls FORMAT not TIMEZONE - looks
  correct at a glance but is the identical underlying bug. Correctly
  left alone: plain-number `.toLocaleString()` calls (scanned_bars/
  cache_hits/etc.), currency formatting, elapsed/relative "N seconds
  ago" displays, and internal `new Date().toISOString()` form-state/
  API-payload plumbing never shown to the operator as a formatted
  time - each checked individually, not blanket-converted. Re-checked
  PDF-A through -D and FRONTEND-5 through -8 for other small deferred
  items: only `PaperSessionPanel`'s own "Replay Session Account" KPI
  block (FRONTEND-6's own Category 2) is still genuinely open, and
  stays correctly deferred (needs a larger restructuring). Tests: 2
  new (TZ-override tests proving the fix holds regardless of the test
  environment's own system timezone) - 398/398 frontend passing, tsc
  clean, real Playwright screenshots both themes confirming the
  on-screen table and the PDF now show identical IST times. No backend
  changes. See `CHECKPOINT_FRONTEND-9_SUMMARY.md`.
