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
