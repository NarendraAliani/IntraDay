# Project Strategy Status

Living, committed reference — unlike the roadmap documents
(`GAINZ_ROADMAP.md`, `VWAP_STRATEGY_ROADMAP.md`,
`ORB_STRATEGY_ROADMAP.md`), this file is meant to be kept current and
IS committed. Consolidates everything this session established about
all 6 strategies that exist in this codebase. Written by
`CHECKPOINT_76` — see that checkpoint's own summary for process notes;
this document is the actual deliverable. Updated by `CHECKPOINT_79` to
add `orb_breakout` and consolidate all 3 research-strategy pauses.

## 0. Current state — read this first

Three research strategies exist outside the original registered roster:
`gainz_compatible_research`, `vwap_mean_reversion`, and
`orb_breakout`. **All 3 are now paused for tuning** (§5) — Gainz per
`CHECKPOINT_75`, VWAP per `CHECKPOINT_76`'s analogy-extension, ORB per
this checkpoint (`CHECKPOINT_79`) — and **all 3 share the identical
resumption criterion**: the real dataset reaching 30+ trading days
beyond the 17 already used as of `2026-09-08`, a concrete number
checkable directly against `HistoricalBar`. **None of the 3 is
registered in `registry.py`**; none is selectable from the live
scanner today, by deliberate design in every checkpoint of all 3
threads. Of the 3, **ORB has produced the single most promising real
result of the whole session** — RELIANCE positive across all 3 presets
simultaneously, a clear step up from anything Gainz or VWAP produced
on any symbol (§1, §4 below) — but it remains just as unvalidated
cross-symbol as Gainz and VWAP: HDFCBANK and INFY are negative across
all 3 ORB presets too. Read this paragraph, not every individual
checkpoint, to get oriented on where the 3 research strategies stand.

## 1. All 6 strategies, one table

| Strategy | Registered in `registry.py`? | `RESEARCH_ACTIVE`? | Saved presets | Best `aggregate_oos_return` seen | Worst `aggregate_oos_return` seen | Ever net-positive? | Verdict |
|---|---|---|---|---|---|---|---|
| `ema_crossover` | **Y** | Y (explicit `StrategyResearchStatusRecord` row) | 5 | **+0.0547** (`CHECKPOINT_68.4`, 25-day MIXED/bypassed data — not gate-verified) | -0.3987 (TCS, `CHECKPOINT_71`) | Only on non-gate-verified data | Registered and nominally active, but **every gate-verified real-data run this session has been net-negative** (`CHECKPOINT_69`: -0.2803; `70`: -0.2904; `71`: -0.1868 to -0.3987 across 3 more symbols). Its one positive number came only from `68.4`'s mixed/bypassed dataset, before the gate fix existed — not a validated edge. |
| `sma_trend_filter` | **Y** | Y (default — no explicit status row, defaults apply per `StrategyResearchStatusRecord`'s own contract) | 4 | **+0.0296** (`CHECKPOINT_69`, gate-verified, 10-day RELIANCE) | -0.2466 (TCS, `CHECKPOINT_71`) | **Yes, on gate-verified data** | The only strategy besides `atr_volatility_breakout` with a genuine gate-verified positive result — but every other real run (`68.4`: -0.0260; `70`: -0.0519; `71`'s HDFCBANK/INFY: -0.0271/-0.0473) is negative. Inconsistent across symbols/datasets, not a validated edge. |
| `atr_volatility_breakout` | **Y** | Y (default) | 3 | **+0.0114** (`CHECKPOINT_70`, gate-verified, 16-day RELIANCE — **the session's single strongest, most-cited gate-verified positive result**) | -0.2522 (TCS, `CHECKPOINT_71`) | **Yes, on gate-verified data** | Has this session's best credible positive number, but `CHECKPOINT_71`'s cross-symbol runs (TCS/HDFCBANK/INFY) were all negative, and `CHECKPOINT_73`'s trade-level diagnosis found a real structural exit-design issue (T2/T3 essentially unreachable) shared with Gainz. One good symbol, not a validated edge across the universe. |
| `gainz_compatible_research` | **N** (deliberately unregistered every checkpoint) | Y (default — no explicit row) | 6 (3 original + 3 `_t1_widened` from `CHECKPOINT_74`) | **0** (silent — `gainz_conservative`, most symbols; not a positive return, a non-signal) | -0.6475 (TCS `gainz_aggressive`, `CHECKPOINT_71`) | **No, never** | **Tuning explicitly PAUSED** (`CHECKPOINT_75`). Root cause of consistent losses diagnosed precisely (`CHECKPOINT_73`: symmetric SL/T1 + single-shot exit design; `CHECKPOINT_75`'s MFE analysis: T2/T3 genuinely rarely reachable regardless of exit mechanism). One real, tested improvement applied (`CHECKPOINT_74`: T1 1.0→1.5) reduced loss magnitude but never flipped any combination positive. |
| `vwap_mean_reversion` | **N** (deliberately unregistered) | Y (default — no explicit row) | 3 | -0.0197 (INFY `vwap_normal`, `CHECKPOINT-VWAP-D` — the **least-bad** result, still negative) | -0.3790 (TCS `vwap_tight`, `CHECKPOINT-VWAP-D`) | **No, never** | Just completed Phase D (`CHECKPOINT-VWAP-D`) — all 12 symbol×preset combinations gate-verified-negative. A genuinely more favorable MFE distribution than Gainz's (`CHECKPOINT-VWAP-B`'s own finding) did **not** translate into profitability. No parameter tuning has been attempted yet. |
| `orb_breakout` | **N** (deliberately unregistered every checkpoint, A through D) | Y (default — no explicit row) | 3 (`orb_classic`/`orb_tight`/`orb_wide`, `CHECKPOINT-ORB-C`) | **+0.0890** (RELIANCE `orb_wide`, `CHECKPOINT-ORB-D` — the **best `aggregate_oos_return` this entire session has produced**, on any strategy, any symbol) | -0.1096 (INFY `orb_wide`, `CHECKPOINT-ORB-D`) | **Yes, on gate-verified data — RELIANCE only, all 3 presets** | Just completed Phase D (`CHECKPOINT-ORB-D`). RELIANCE is positive across all 3 presets simultaneously — this session's single strongest walk-forward signal — but `orb_classic`/`orb_wide` both show 2-of-3 fold sign flips despite the positive aggregate; only `orb_tight` (1/3 flips, `mean_degradation_ratio=+0.260`) comes close to genuinely fold-stable. Does **not** generalize: HDFCBANK and INFY are negative across all 3 presets, and TCS's own larger `orb_wide` number (+0.2309) is explicitly the least statistically meaningful of the 12 combinations (1–2 OOS trades/fold). Honest verdict: the most promising single result of the session, not a validated edge. |

**Reading this table honestly**: `atr_volatility_breakout` and
`sma_trend_filter` each have exactly ONE genuine gate-verified positive
result, both single-symbol (RELIANCE), both from a smaller (10–16
day) dataset than what now exists. `ema_crossover`'s only positive
number predates the `fromDate` fix (`CHECKPOINT_69`) and used
bypassed, mixed-quality data — it should not be read as comparable to
the other two. `gainz_compatible_research` and `vwap_mean_reversion`
have never once produced a net-positive gate-verified result, on any
symbol, in any checkpoint this session ran. `orb_breakout` is the one
exception to that pattern among the unregistered research strategies:
it produced this session's single largest `aggregate_oos_return`
(RELIANCE, all 3 presets), but — per its own §4 comparison
(`CHECKPOINT-ORB-D`) — that result is RELIANCE-only and fold-unstable
on 2 of its 3 presets, so it should be read as the most promising
result, not a validated one.

## 2. What this project's OWN documented procedure actually requires

`docs/architecture/FIRST_LIVE_PAPER_VALIDATION_PROCEDURE.md`
(Checkpoint 64.19) was read directly in full for this checkpoint — it
had been cited but never actually read in detail this session
(`RECON-GAINZ-ARCHITECTURE`'s own citation only referenced it).

**The single most important finding: this procedure's own Success
Criteria (§5) are entirely about SYSTEM/INFRASTRUCTURE health, and
contain ZERO backtest-performance requirement.** Quoted directly from
its own §5 header: *"system health is a SEPARATE question from
whether a strategy produced a signal — a session with zero signals is
still a fully successful validation if every item below is real and
correct."* Its 15-row Success Criteria table (§5) covers: Dhan
connectivity, token validity, market-open state, scanner reconciliation
state, scanner progress advancing, at least one complete scan cycle,
no stale progress, signal-evidence pairing (if any signal occurs), risk
decisions persisted (if any), paper orders/fills persisted (if any),
Telegram/Discord delivery status visible, a real Daily Session Report,
confirmation `PaperBroker` is the only broker in the codebase, and
`real_trading_state` remaining structurally `DISABLED`. **Not one row
mentions `aggregate_oos_return`, win rate, walk-forward folds, or any
other backtest metric.**

Its §3 "Recommended First Session Configuration" names the 3 ORIGINAL
strategies (`ema_crossover`/`sma_trend_filter`/`atr_volatility_breakout`)
at their **Checkpoint 64.17 conservative baseline defaults** (12/26
EMA, 30/0.75% SMA, 14/2.0/... ATR) — *"never a custom, unvalidated
parameter set for the first session"* — and a small 3-5 symbol
universe (RELIANCE/TCS/HDFCBANK/INFY/ICICIBANK). This document predates
both `gainz_compatible_research` and `vwap_mean_reversion` entirely; it
has no opinion on either.

**The gap, stated honestly**: this session's entire walk-forward
validation arc (`68.x` through `CHECKPOINT-VWAP-D`) is genuinely
valuable research work, but **it is not something `FIRST_LIVE_PAPER_
VALIDATION_PROCEDURE.md` itself requires as a gate before paper
trading can start.** It is a separate, additional research-quality
bar this session's own checkpoints (the Gainz and VWAP roadmaps'
"Phase D mandatory gate" language) imposed on themselves — a sensible
discipline, but not the documented product requirement. The project's
OWN procedure is satisfied by infrastructure readiness
(credential/connectivity/worker/market-state), not by any strategy's
walk-forward number.

## 3. Data status

`[F]` Current real, gate-verified `HistoricalBar` coverage, updated by
`CHECKPOINT_81`: **18 `CANONICALIZED` trading days per symbol**
(RELIANCE/TCS/HDFCBANK/INFY) — up from 17, `2026-09-09` newly added.
Two contiguous blocks, unchanged in shape: `2026-08-03`–`08-14`
(10 days) and `2026-08-31`–`09-09` (8 days). The `fromDate`-exclusive
fix (`CHECKPOINT_69`) continues to hold — spot-checked directly on
`2026-09-09` and on the new pre-CAS rows below (both show the full
72-bar day, first bar at the correct day-open timestamp, no missing
day-start bar).

**`CHECKPOINT_81`'s own central finding, stated plainly**: an attempt
to widen this to ~50-60 real trading days found a **hard, structural
ceiling this session had not previously quantified**.
`CAS_EFFECTIVE_DATE = 2026-08-03` (`domain/session/calendar.py`) means
`_PROVEN_INTRADAY_SCOPES` only certifies `(NSE_EQ, FIVE_MINUTE,
CAS_ERA)` — any fetch window entirely BEFORE `2026-08-03` resolves to
the unproven `PRE_CAS` era and can never produce a `CANONICALIZED` row,
no matter how it's requested. `[F]` A real backfill of
`2026-06-01`–`08-02` (44 real trading days, confirmed via
`HistoricalDataCoverageService`) was executed and persisted
successfully (12,319 new rows across the 4 symbols, real Dhan REST
calls, `status=COMPLETE`) — but **all of it landed as
`UNCANONICALIZED`/`UNKNOWN`, not `CANONICALIZED`**, exactly as this
scope rule predicts. `[F]` Zero existing rows mutated (0 duplicate
`(instrument, bar_timestamp)` pairs found across all 4 symbols; a
spot-checked pre-existing row's own values are byte-identical). The
data itself is real, valid, and left in place (P4: never mutate/delete
a `HistoricalBar` row) — it is simply not, and structurally cannot be,
gate-verified.

**The actual reachable ceiling today**: only **28 real trading days
total** have occurred since `CAS_EFFECTIVE_DATE` (`2026-08-03`)
through today (`2026-09-09`), of which **10 fall inside the
deliberately untouched interior gap** (`2026-08-17`–`08-28`) — leaving
a maximum of **18 canonicalizable days available in the entire real
calendar right now**, which this checkpoint reached exactly (17→18,
`2026-09-09` fetched). **Reaching 50-60 gate-verified days is not
achievable by backfilling at all** — it requires real calendar time to
pass (roughly 6-7 more real trading weeks beyond today, holidays
notwithstanding), not a wider fetch window. See
`CHECKPOINT_81_SUMMARY.md` for the full trace.

**The 30-new-real-day resumption criterion for Gainz/VWAP/ORB tuning
(`CHECKPOINT_75`/`76`/`79`) is NOT met** — this checkpoint added
exactly **1** new gate-verified day (17→18), not 30. Stated plainly,
not buried: tuning resumption remains unauthorized: the dataset needs
to reach **47 gate-verified days** (18 + 29 more) before that
criterion is satisfied, at the current real-calendar pace of at most 1
new day per real trading day (minus any future interior-gap-style
losses).

The daily backfill routine itself (`CHECKPOINT_72`,
`manage.py backfill_daily_coverage`) is built, tested, and proven —
but remains **operator-triggered only**, deliberately not auto-
scheduled (Celery Beat was considered and explicitly rejected — see
`CHECKPOINT_72`'s own §1 — because an unconditional daily Dhan call
with no per-run operator action would conflict with this project's own
P6/"no surprise automation" discipline). It has now been run for real
twice (`CHECKPOINT_74`, and implicitly superseded by `CHECKPOINT_81`'s
own direct `HistoricalDataPreparationService.prepare()` calls for the
`2026-09-09` extension). **The interior `2026-08-17`–`08-28` gap
remains open**, deferred, unfixed, and untouched by `CHECKPOINT_81`
(the backward extension stopped at `08-02`, strictly before it) —
confirmed (`CHECKPOINT_71`'s recon, refined by `CHECKPOINT_72`'s
incidental finding) to be rows written before the write-time
canonicalization logic existed, exactly the class of row the
still-unexecuted migration (`67.7`–`67.13-C`) was built to
retroactively fix. Migration execution remains the operator's own
deferred decision, not re-litigated by any checkpoint since.

## 4. When can paper trading realistically start?

> **SUPERSEDED BY `CHECKPOINT_77` — see §6 below.** The "technically
> ready" reading directly below was written before `CHECKPOINT_77`
> traced the actual live signal-evaluation code path and found a real,
> blocking gap. Read §6 first; this section is kept for its still-valid
> secondary points (the preset-vs-baseline gap, the stricter-bar
> criteria) but its own headline conclusion is no longer current.

**Direct answer**: per the project's OWN documented procedure, paper
trading could technically start as soon as the infrastructure
readiness items are met — a valid Dhan credential (`[F]` confirmed
present via `DhanSettingsService.effective_credentials()` as of this
checkpoint), a running `manage.py run_market_data_worker` process, and
market genuinely open — using the 3 ALREADY-REGISTERED strategies
(`ema_crossover`/`sma_trend_filter`/`atr_volatility_breakout`) at their
conservative baseline defaults, exactly as `FIRST_LIVE_PAPER_
VALIDATION_PROCEDURE.md` §3 recommends. **This is a real, honest
answer, not a hedge**: the document's own Success Criteria do not
require any backtest result at all.

**But that same document also explicitly forbids a custom, unvalidated
parameter set** — and every one of this session's own SAVED presets
for the 3 registered strategies (`ema_conservative`/`sma_conservative`/
`atr_aggresive`, etc.) is exactly that: a custom set this session
created for walk-forward testing, distinct from — though in most cases
numerically similar to — Checkpoint 64.17's own original baseline
defaults. **Concrete, checkable requirement before a FIRST session,
stated plainly**: confirm each of the 3 registered strategies'
`parameter_schema()` DEFAULT values (not a saved preset) are what
actually gets used, OR deliberately choose to use `ema_conservative`/
`sma_conservative`/`atr_aggresive` and document that as a conscious
deviation from §3's own literal instruction — this is a real, small,
checkable gap between the document's letter and what this session's
presets actually contain, not investigated further here (out of this
checkpoint's own read-only, no-new-code scope).

**`gainz_compatible_research`, `vwap_mean_reversion`, and
`orb_breakout` cannot be selected for a live paper session at all
today** — all 3 remain unregistered in `registry.py`, unreachable from
the live scanner/Strategy Selection checklist item, by deliberate
design every checkpoint in all 3 threads has confirmed
(`CHECKPOINT-ORB-D` re-confirmed `registry.py` untouched, same as
every prior ORB checkpoint). This is not a gap to close before paper
trading starts — it is the CORRECT current state: Gainz and VWAP have
never produced a validated positive result, and ORB's own best result
(RELIANCE, this checkpoint's §1 row) is real but neither cross-symbol
nor fully fold-stable.

**`CHECKPOINT_79` update, stated plainly, not assumed**: ORB's Phase D
result does **NOT** change this section's answer in any way.
`CHECKPOINT_78`'s READY verdict (§6 below) concerns only the 3
strategies actually registered in `registry.py`
(`ema_crossover`/`sma_trend_filter`/`atr_volatility_breakout`) — their
infrastructure readiness (credential validity, `PaperBroker`
confirmation, `real_trading_state` DISABLED, default-config wiring)
has no dependency on any unregistered research strategy's existence or
performance, since `orb_breakout` (like Gainz and VWAP) cannot even
appear in `selected_strategy_ids` while unregistered. Confirmed
directly against `registry.py`'s own `build_default_registry()`, not
assumed: it registers exactly 3 strategies, unchanged throughout the
entire ORB thread.

**If the operator wants "at least one strategy with a real edge"
before starting** (a stricter, self-imposed bar this session's own
research suggests is warranted, even though the documented procedure
doesn't require it): **not met today.** The closest candidates —
`atr_volatility_breakout` (`CHECKPOINT_70`'s +0.0114) and
`sma_trend_filter` (`CHECKPOINT_69`'s +0.0296) — are each single-
symbol, single-dataset positive results that did NOT replicate across
the other 3 symbols (`CHECKPOINT_71`). Concrete, checkable criteria
for closing this gap, derived directly from this session's own
established discipline (`CHECKPOINT_75`'s explicit Gainz resumption
rule, the same logic applied here): **at least one strategy
maintaining a positive `aggregate_oos_return`, with zero sign flips
across all folds, on AT LEAST 2 of the 4 tested symbols
simultaneously, on a real dataset of 30+ real trading days** (roughly
double the current 17) — a concrete, checkable bar, not an invented
one, extrapolated from the same standard `CHECKPOINT_75` already set
for Gainz specifically.

## 5. What's paused, and why

- **`gainz_compatible_research` tuning**: explicitly **PAUSED**
  (`CHECKPOINT_75`). Resumption criterion: the real dataset reaches at
  least 30 real trading days beyond the 17 already used as of
  `2026-09-08` — a concrete, checkable number, verifiable directly
  against `HistoricalBar` before any future checkpoint resumes tuning.
- **`vwap_mean_reversion` tuning**: no tuning has been attempted yet
  (only the 3 tight/normal/wide presets from `CHECKPOINT-VWAP-C`, all
  parameter CHOICES made once, up front, never iteratively re-tested
  against the same sample). **Should follow the identical pause
  discipline, for the identical reason**: iterating this strategy's own
  parameters against the SAME 17-day dataset that just produced its
  Phase D result would create exactly the same overfitting risk
  `CHECKPOINT_75` flagged for Gainz. No checkpoint has formally
  declared this pause for VWAP yet — this document does so explicitly,
  applying the same resumption criterion (30+ new real trading days)
  by direct analogy, not a new, independently-derived rule.
- **`orb_breakout` tuning**: explicitly **PAUSED**, declared by
  `CHECKPOINT_79` on completion of Phase D (`CHECKPOINT-ORB-D`), for
  the identical reason as Gainz and VWAP: `orb_classic`/`orb_tight`/
  `orb_wide` were each a parameter CHOICE made once, up front
  (`CHECKPOINT-ORB-C`), never iteratively re-tested — but any further
  tuning pass would now be iterating against the SAME 17-day dataset
  Phase D's own result was just measured on, the exact overfitting
  risk `CHECKPOINT_75` first flagged. **Resumption criterion: the
  identical bar as Gainz and VWAP** — 30+ real trading days beyond the
  17 already used as of `2026-09-08`, checkable directly against
  `HistoricalBar`.

  **ORB-specific nuance, considered explicitly rather than copied
  verbatim**: `CHECKPOINT-ORB-D` found `orb_tight` notably more
  fold-stable than `orb_classic`/`orb_wide` on RELIANCE (1/3 fold flips
  vs. 2/3 for the other two, plus a positive `mean_degradation_ratio`
  where the other two were negative). Does this warrant changing the
  resumption criterion itself? **Reasoned conclusion: no — keep the
  same generic 30-day dataset-size criterion**, because the criterion
  exists to bound overfitting risk from re-tuning against a small
  sample, a concern that is orthogonal to which preset happened to look
  best this round; narrowing the GATING criterion to one preset would
  itself be a form of fitting to this round's own result. **But the
  finding is real and worth keeping**, so it is recorded here as
  operational guidance for whoever resumes ORB tuning, not as a new
  gate: when tuning resumes, `orb_tight`-style shorter opening-range
  windows should be the first variants re-tested and possibly the
  starting point for any new presets, given this is the one preset that
  came close to genuinely stable rather than merely aggregate-positive.

## 6. Paper-trading readiness — `CHECKPOINT_78`, current as of `2026-09-08`

> **UPDATED BY `CHECKPOINT_78` — verdict is now READY.** The `NOT
> READY` finding below is `CHECKPOINT_77`'s own original discovery,
> kept for its full trace; `CHECKPOINT_78` fixed the gap it found (plus
> one more, related gap found while verifying the fix) and re-confirmed
> readiness by actually invoking the real pipeline. See the "RESOLVED"
> block at the end of this section for the current state.

**`CHECKPOINT_77`'s original verdict: NOT READY.** Every infrastructure precondition checks
out — Dhan credential `VALID` (expires `2026-09-09 10:17:40 UTC`),
`PaperBroker` confirmed the only broker implementation in the
codebase, `real_trading_state` confirmed structurally `DISABLED`,
universe/timeframe/strategy selection all configurable today with zero
new code, Telegram/Discord already configured AND enabled. **None of
that is why this is NOT READY.**

**The actual blocker, traced directly in code**: the live signal-
evaluation path (`signal_pipeline_runtime.py::promote_bars_and_
trigger_signals()`) constructs an EMPTY `StrategyConfigurationValues`
(`{}`) for every strategy, every tick — no default-fill happens
anywhere downstream (`validate_configuration()` tolerates a missing
key but never injects the schema default; `require_int`/
`require_decimal` do a raw, un-defaulted dict subscript). **A live
session started today would run, connect, and ingest bars — but would
never produce a single real signal for any of the 3 registered
strategies**, since the first parameter lookup inside any of their
`evaluate()` methods raises `KeyError`, silently caught as a
`StrategyExecutionFailure` by the coordinator's own isolation
boundary. No existing test in this codebase exercises this exact
real, empty-`{}` path — every test that touches `run_active_loop_tick()`
supplies its own real values instead.

**Also found, secondary to the above**: none of `atr_volatility_
breakout`'s 3 saved presets (`atr_aggresive`/`atr_Balanced`/
`atr_Conservative`) matches `FIRST_LIVE_PAPER_VALIDATION_PROCEDURE.md`
§3's own documented baseline exactly — only the strategy's raw schema
DEFAULTS do (`ema_crossover`'s and `sma_trend_filter`'s defaults also
match exactly). A first session should use raw schema defaults, not
any currently-saved preset, for `atr_volatility_breakout` specifically.

**What closing this gap requires** (a future checkpoint's own decision
— NOT fixed by `CHECKPOINT_77`, which stayed read-only per its own
scope): wire real parameter values into `promote_bars_and_trigger_
signals()`'s configuration construction — `default_configuration_
values()` (the existing helper `replay_paper_session.py` already uses
for exactly this purpose) is the most direct, already-proven fit.

See `CHECKPOINT_77_SUMMARY.md` for the full trace and every file/line
this finding is based on.

### RESOLVED — `CHECKPOINT_78`: verdict is now READY

Both gaps above are fixed. `signal_pipeline_runtime.py::promote_bars_
and_trigger_signals()` now constructs each strategy's configuration via
`coerce_configuration_values(schema, default_configuration_values(schema))`
— reusing both existing, already-proven functions, no new mechanism.
**A second, related gap was found while verifying the fix, not
assumed away**: `default_configuration_values()` alone returns bare
Python floats for DECIMAL-typed parameters, which `require_decimal()`
rejects — `sma_trend_filter`/`atr_volatility_breakout` would have
raised `InvalidParameterValueError` without `coerce_configuration_
values()` applied too (the exact pairing `StrategyConfigurationService.
save_configuration()` already uses). Fixed in the same narrow scope.

**Re-verified by actually invoking the real pipeline** (not just
re-reading code): `promote_bars_and_trigger_signals()` called against
a real, open-market bar returns `SignalPipelineOutcome(promoted_count=1,
active_loop_invocations=1)` with no exception, for all 3 registered
strategies' real configuration values confirmed correctly-typed
(`Decimal` where required, real ints/values throughout, matching the
documented baseline exactly).

**ATR preset gap also closed**: new `atr_baseline` preset created
(`14/2.0/1.0/1.5/2.5/3.5/1.0`, exact match to the documented baseline),
via the real `save_configuration()` path. The existing `atr_aggresive`/
`atr_Balanced`/`atr_Conservative` presets are untouched, kept for their
own already-completed research purposes.

3 new regression tests added (`test_signal_pipeline_runtime.py`),
including the deep one `CHECKPOINT_77` identified as missing — spying
on the REAL, registered `EmaCrossoverStrategy.evaluate` to confirm it
genuinely receives non-empty, correctly-typed config in production-
shaped code, not a test-only helper's own hand-built one.

**The system is genuinely ready for a first live paper session
today.** See `CHECKPOINT_78_SUMMARY.md` for the full fix trace and the
restated (not executed) operator command sequence.

### `LIVE-PAPER-1` — the project's first completed live paper session (`2026-09-09`)

`[F]` Two earlier attempts on `2026-09-08` (20:24/20:30 IST) halted at
Part 0 pre-flight, market closed — see prior entry below, unchanged.
**A third attempt on `2026-09-09`, during genuine NSE market hours,
ran the full session** (worker launch → operator-driven UI start →
Part 2 monitoring → Part 3 clean stop). Full detail in
`LIVE_PAPER-1_SUMMARY.md`; summarized here as this project's first
real paper-trading data point.

**Outcome: zero signals, but a fully successful validation** — per
this document's own §2, the documented procedure's Success Criteria
are entirely infrastructure-based, and every infrastructure item was
real and correct: `ScannerConfiguration` genuinely active (15
instruments, `5m`, the 3 registered strategies, operator-set via the
real UI), scanner completed dozens of full cycles (15/15 instruments,
3/3 strategies) across the session, `drift=False` throughout,
`SignalRecord`/`PaperOrderRecord`/`CommunicationLedgerRecord` counts
for the day all genuinely `0` (a real all-zero Daily Session Report,
not a missing one).

**Two genuine crash/recovery cycles, both handled correctly** — the
market-data worker hit the same intermittent Dhan `close_code=1006`
WebSocket disconnect `LIVE-1`/`LIVE-3`/`LIVE-4` already diagnosed as
real and external, not a code defect. The first bounded supervisor run
(`--max-restarts 40`) genuinely exhausted its budget (a today-specific
crash burst, 40 restarts in ~90 minutes — busier than those prior
checkpoints' own observed cadence) and stopped itself exactly as
designed, leaving a real, honestly-reported ~7-minute data gap before
this session's own monitoring caught it and relaunched with a larger
budget (`--max-restarts 200`, matching `LIVE-4`'s own precedent); the
second run used only 4 restarts and reached session-end cleanly.
**This does not affect the READY verdict above** — it demonstrates the
existing crash-recovery mechanism working as intended under real,
unusually heavy reconnect pressure, not a new infrastructure gap.

**`CHECKPOINT_80` update — crash-rate diagnostic + a real fix, not just
a documented quirk**:

- **Crash-rate diagnostic**: pulled precise timestamps from today's
  worker logs. `[F]` **66% of the day's 44 crashes (29 of them)
  clustered in one ~10-minute window** (`08:13:14`–`08:23:30 UTC` /
  `13:43`–`13:53 IST`), spaced almost exactly 22 seconds apart, and
  **26 of the first supervisor run's 40 crashes received zero quotes**
  before failing — a qualitatively different, tighter, more severe
  signature than the sparser (7–17 minute gaps, real data streamed
  first) pattern surrounding it. This reads as a genuine, temporary
  Dhan-side or network-path outage for that ~10-minute window, layered
  on top of the ordinary intermittent `close_code=1006` pattern
  `LIVE-1`/`LIVE-3`/`LIVE-4` already diagnosed as real and external —
  not a new or different root cause, and (per this checkpoint's own
  rule) not something a code fix can address. No fix attempted; the
  existing bounded-restart supervisor already responded correctly.
- **A real bug found and fixed**: `derive_live_paper_session_state()`
  never checked for a genuinely, cleanly stopped worker
  (`worker_state == "STOPPED"`) — it fell through to the
  `desired.enabled`/version-match logic, which could report `RUNNING`
  for a worker that had already exited (exactly what `LIVE-PAPER-1`
  observed after the supervisor's own session-end stop, which by
  design never touches `ScannerConfiguration.enabled`). This is a
  narrow, one-clause fix (treating `STOPPED` with the same
  top-priority short-circuit `FAILED` already has), proven by a
  regression test that fails on the reverted code with the exact live
  symptom and passes with the fix. **The same fix also resolves the
  "STOPPING forever" nuance** originally reported as a documentation-
  only item — confirmed directly (a dedicated regression test
  reproduces `LIVE-PAPER-1`'s exact stale-version scenario and now
  correctly reports `STOPPED`, not `STOPPING`), since both were the
  same missing case. See `CHECKPOINT_80_SUMMARY.md` for the full trace.
- **The two-independent-controls design itself (`ScannerConfiguration.
  enabled` = operator intent vs. the worker process's own runtime
  state) was confirmed correct-as-designed, not a gap** — the module's
  own docstring already states this intentionally ("adds NOTHING to
  what happens after that write... the already-running worker process
  picks up the change on its own"). The bug was narrower: the STATE-
  REPORTING function's own blind spot for one specific worker state,
  not the two-controls architecture itself.

Needs a fresh Dhan credential check before any future session (today's
token was `VALID`→`EXPIRING_SOON` by session end, `2026-09-09
10:17:40 UTC` expiry — do not reuse).

### `LIVE-PAPER-1` — two earlier halted attempts, `2026-09-08`

`[F]` Two live paper session attempts were made the same day —
`2026-09-08 20:24 IST` and, after `RECON-FRONTEND-LAUNCH` narrowed the
checkpoint's own scope to worker-launch-only, again at `20:30 IST` —
both halted immediately at Part 0 pre-flight, since real time checked
directly (`date`) both times was well past NSE's 15:30 IST close. No
worker was launched, no `ScannerConfiguration` changed, zero DB
writes, either time. This did not affect the READY verdict above —
nothing about infrastructure readiness was tested, changed, or
contradicted; the session simply never reached a point where readiness
would matter.
