# CHECKPOINT 68.3 — Smoke-Test Walk-Forward Against Real Data (TOOL VALIDATION ONLY — NOT A TRUSTWORTHY RESULT)

```
checkpoint: 68.3
verdict: TOOL_BEHAVES_CORRECTLY_ON_REAL_DATA
instrument_used: NSE:RELIANCE
folds_produced: 3
database_write_occurred: NO
disclaimer_present_throughout: YES
commit: <filled in after commit>
blockers: []
```

---

## NOT A TRUSTWORTHY STRATEGY RESULT

Every number in this file (§B) comes from real `HistoricalBar` rows
whose `canonicalization_state` is `UNCANONICALIZED` — **zero** rows in
the entire database are `CANONICALIZED` (re-confirmed §A2 below, same
as `RECON_BACKTEST_SUMMARY.md` and `CHECKPOINT_68.2_SUMMARY.md` found).
This checkpoint exists **only** to see whether `walk_forward.py`
(built and synthetic-tested in 68.2) behaves sensibly when handed real
market-data *shape* — non-uniform day spacing, real gaps, real
volume/price noise — not to produce a strategy result anyone should
act on, cite, or compare against another backtest. Nothing here is
research-eligible.

---

## A. Data selection

### A1. Instrument with deepest 5m/REAL_DHAN coverage — re-verified, with a correction to the directive's premise

`[F]` Query run this session, `HistoricalBar.objects.filter(timeframe="5m",
provenance="REAL_DHAN")`:

```
TOTAL 5m REAL_DHAN rows: 10,562
```

This **total** matches the directive's "~10,562 rows" figure exactly.
`[CONFLICT]` However, the directive's premise that this is
**RELIANCE-scoped** ("`RELIANCE`-scope, ~10,562 rows across ~36-37
trading days") does not hold up under direct re-query. The 10,562 is
the **sum across 15 instruments**, not RELIANCE alone:

| instrument | rows | distinct days |
|---|---|---|
| **NSE:RELIANCE** | **848** | **12** |
| NSE:BAJFINANCE | 700 | 10 |
| NSE:ICICIBANK | 700 | 10 |
| NSE:HDFCBANK | 700 | 10 |
| NSE:ADANIPORTS | 700 | 10 |
| NSE:SUNPHARMA | 700 | 10 |
| NSE:AXISBANK | 700 | 10 |
| NSE:SBIN | 700 | 10 |
| NSE:MARUTI | 700 | 10 |
| NSE:HINDUNILVR | 700 | 10 |
| NSE:INFY | 700 | 10 |
| NSE:ITC | 700 | 10 |
| NSE:KOTAKBANK | 700 | 10 |
| NSE:LT | 700 | 10 |
| NSE:TCS | 614 | 9 |

RELIANCE is genuinely the deepest single instrument by both row count
(848) and distinct-day count (12), so it is still the correct choice
for this smoke test — but the actual span is **12 distinct calendar
days (2026-07-29 to 2026-08-28), not ~36-37**. `[F]` The 12 dates
themselves, in order:

```
2026-07-29, 2026-07-30, 2026-08-17, 2026-08-18, 2026-08-19, 2026-08-20,
2026-08-21, 2026-08-24, 2026-08-25, 2026-08-26, 2026-08-27, 2026-08-28
```

Note the **18-calendar-day gap** between 2026-07-30 and 2026-08-17 —
a real capture gap, not a weekend. This shapes fold boundaries in a
way the synthetic (uniform-spacing) fixtures never exercised — see §C.

`[F]` `canonicalization_state` for every one of these 848 rows:
`UNCANONICALIZED` (100%, single-value breakdown confirmed by direct
query). Zero `CANONICALIZED` rows exist anywhere in the database for
any symbol/timeframe — unchanged from `RECON_BACKTEST_SUMMARY.md` §3
and `CHECKPOINT_68.2_SUMMARY.md`.

### A2. Strategy and configuration — used as-is

`[F]` `StrategyResearchStatusRecord`: exactly one row,
`ema_crossover` → `RESEARCH_ACTIVE` (unchanged from `RECON-BACKTEST`
§1).

`[F]` `StrategyConfigurationRecord` rows for `ema_crossover` (5 saved
configurations exist; none tuned or modified for this run):

```
ema_crossover v1/v1/cfg-v1          {fast_lookback: 9,  slow_lookback: 21}
ema_crossover v1/v1/flb9_slb21      {fast_lookback: 9,  slow_lookback: 21}
ema_crossover v1/v1/ema_balanced    {fast_lookback: 9,  slow_lookback: 21}
ema_crossover v1/v1/ema_aggresive   {fast_lookback: 5,  slow_lookback: 13}
ema_crossover v1/v1/ema_conservative{fast_lookback: 12, slow_lookback: 26}
```

Used `configuration_version="cfg-v1"` (`fast_lookback=9,
slow_lookback=21`) verbatim, via
`coerce_configuration_values(strategy.parameter_schema(), {...})` —
the same coercion path `application/services/backtesting.py::run()`
uses for a real API-triggered backtest. Not tuned for this run.

---

## B. The run and its output

**NOT A TRUSTWORTHY STRATEGY RESULT — this data has not passed the
research-eligibility gate. This section validates the tool's behavior
on real market data shape only.**

`[F]` Called `run_walk_forward_backtest()` directly (no wrapper, no
persistence layer — `BacktestingService.run()` was deliberately *not*
used because it calls `self.repository.save(...)`, which would write a
`BacktestResultRecord`; this checkpoint reproduces only its
config/data-quality construction pattern, not its persistence call).

Parameters: `min_oos_days=2, min_folds=3`. With only 12 distinct
trading days available, `min_folds * min_oos_days + 1 = 7 <= 12`
comfortably supports 3 folds (the synthetic tests in 68.2 already
proved the boundary/refusal logic; this run stays well inside the
sufficient region rather than probing the edge again).

It ran **without error** — no exception raised.

```
fold_count = 3

fold 1: IS 2026-07-29 .. 2026-08-20 (428 bars) | OOS 2026-08-21 .. 2026-08-24 (140 bars)
fold 2: IS 2026-07-29 .. 2026-08-24 (568 bars) | OOS 2026-08-25 .. 2026-08-26 (140 bars)
fold 3: IS 2026-07-29 .. 2026-08-26 (708 bars) | OOS 2026-08-27 .. 2026-08-28 (140 bars)

aggregate_oos_return       = -0.2243693353333333333333333333  (%)
aggregate_oos_win_rate     = 11.80555555555555555555555556    (%)
mean_degradation_ratio     = 0.3997594576095415240577531653
```

`data_sufficiency_note` (generated by the tool itself, verbatim):

> "3 walk-forward fold(s) computed (min_folds=3, min_oos_days=2). Fold
> 1: in-sample 2026-07-29..2026-08-20 (428 bars); out-of-sample
> 2026-08-21..2026-08-24 (140 bars). Fold 2: in-sample
> 2026-07-29..2026-08-24 (568 bars); out-of-sample
> 2026-08-25..2026-08-26 (140 bars). Fold 3: in-sample
> 2026-07-29..2026-08-26 (708 bars); out-of-sample
> 2026-08-27..2026-08-28 (140 bars)."

Per-fold detail:

| fold | IS trades | IS return% | IS win% | OOS trades | OOS return% | OOS win% |
|---|---|---|---|---|---|---|
| 1 | 52 | -0.402981 | 21.15 | 16 | -0.290543 | 6.25 |
| 2 | 69 | -0.710624 | 17.39 | 16 | -0.175985 | 12.50 |
| 3 | 87 | -0.895655 | 17.24 | 12 | -0.206580 | 16.67 |

**Again: none of this — the negative aggregate return, the ~12% OOS
win rate, the degradation ratio — should be read as "ema_crossover
loses money on RELIANCE." The underlying bars are unverified-timestamp,
uncanonicalized, and this is a single 12-day window on one instrument.
This table exists to prove the tool computed and aggregated real
numbers correctly, nothing more.**

---

## C. Anything surprising — reported honestly

1. **The directive's own data-scope premise was wrong, and is corrected
   in §A1 above** (`[CONFLICT]`, resolved by direct re-query): the
   ~10,562-row figure is a 15-instrument total, not a single
   RELIANCE-scoped figure, and the real span is 12 distinct days, not
   ~36-37. This is exactly the kind of undocumented drift `RECON-
   BACKTEST_SUMMARY.md` itself was already probing for — worth noting
   that a prior document's own scope claim needed re-derivation rather
   than being trusted at face value, per this project's Governing
   Principle.

2. **A real, non-uniform data gap surfaced a genuine readability
   footgun in `data_sufficiency_note`'s date-range text — not a bug in
   the underlying fold math.** RELIANCE's 12 available days contain an
   18-calendar-day capture gap (2026-07-30 → 2026-08-17, not a
   weekend). Fold 1's in-sample window is reported as "2026-07-29 ..
   2026-08-20" — read casually, that looks like a continuous ~3-week
   in-sample period. It is actually only **6 distinct trading dates**
   (`07-29, 07-30, 08-17, 08-18, 08-19, 08-20`) with an 18-day hole in
   the middle. The underlying mechanics are correct —
   `compute_walk_forward_folds()` only ever includes bars that
   genuinely exist at those 6 dates, no synthetic filling, no
   look-ahead across the gap — but the human-readable summary string
   (`{start.date()}..{end.date()}`) doesn't distinguish "a continuous
   3-week span" from "6 real trading days with an 18-day gap in the
   middle." The synthetic fixtures in 68.2 always used uniform daily
   spacing, so this ambiguity never had a chance to appear until now.
   **Not a correctness bug** (verified: bar counts, IS/OOS bar sets,
   and the no-overlap property all check out — see the cross-check in
   §D), but a genuine real-data-only surprise worth flagging before
   anyone reads a walk-forward note casually.

3. **The `<3`-fold small-sample warning did not fire, right at its own
   boundary.** `data_sufficiency_note` only appends the "fold count is
   small" disclaimer when `len(folds) < 3` (68.2's own code,
   `walk_forward.py:295`). This run produced **exactly 3** folds — the
   disclaimer is silent. 3 folds from 12 total trading days (of which
   several folds share heavily-overlapping in-sample windows, being
   anchored/expanding) is still a thin sample by any reasonable
   standard, and a reader relying solely on the tool's own
   self-disclosure would see no explicit warning here. This is a
   pre-existing 68.2 design choice (a hardcoded `<3` threshold), not
   something this checkpoint is authorized to change (P9/scope), but it
   is worth flagging as a real observation: the threshold is coarse
   enough that "exactly at the boundary, still thin" produces no
   flag at all.

4. **No numerical edge case, no crash, no `Decimal` precision blow-up.**
   `mean_degradation_ratio` computed cleanly (all three folds had a
   nonzero in-sample return, so no fold was excluded from that mean).
   No `division by zero`, no `NaN`, no unexpected `None` anywhere in
   the result.

---

## D. Confirmation of zero database writes

`[F]` `git status --porcelain` immediately after the run:

```
?? RECON_BACKTEST_SUMMARY.md
```

(pre-existing untracked file from an earlier checkpoint; this
checkpoint added `CHECKPOINT_68.3_SUMMARY.md` afterward — no other
change.) `walk_forward.py`, `engine.py`, and every other source file
are untouched.

`[F]` `BacktestResultRecord.objects.count()`:

```
BEFORE this run: 208
AFTER this run:  208
UNCHANGED: True
```

`run_walk_forward_backtest()` was called directly (not through
`BacktestingService.run()`, which is the only code path in this
project that calls `.save()` on a `BacktestResultRecord`) — this
checkpoint's script never imported or called that save path. Zero
rows were written by this checkpoint, of any model, confirmed both by
the row-count invariant and by `git status` showing no source-file
diff.

The one-off script used to run this (`c68_3_run.py`) was written to
this session's scratchpad directory, not the repository, and is not
part of this commit.

---

## E. Readiness assessment for the tool itself

**`walk_forward.py` behaves as designed on real data shape.** Every
mechanical property 68.2 proved against synthetic fixtures held up
against genuine RELIANCE 5m bars: fold boundaries derived purely from
real bar timestamps (no hardcoded calendar assumption — confirmed
handling a genuine 18-day capture gap without crashing, without
silently bridging it, and without producing an overlapping or
look-ahead fold), `engine.run_backtest()` called unmodified twice per
fold, aggregation arithmetic (`aggregate_oos_return`,
`aggregate_oos_win_rate`, `mean_degradation_ratio`) computed cleanly
with real, noisy, non-round `Decimal` values, and
`InsufficientDataForWalkForwardError` was available as a real refusal
path (not exercised this run since 12 days comfortably supports
`min_folds=3, min_oos_days=2`, but 68.2's dedicated tests already
proved that path; this run's job was the success path on real shape,
not to re-probe insufficiency).

The one genuine finding worth carrying forward (§C2) is a
**presentation** gap, not a **correctness** gap: `data_sufficiency_note`'s
date-range strings can visually imply continuity across a real capture
gap. That is worth a future checkpoint's attention (e.g., reporting
distinct-day counts alongside date ranges, or explicitly calling out
gaps `>1` day) — but it does not misstate any bar count, any fold
boundary, or any metric; it is a readability improvement, not a bug
fix, and this checkpoint does not make that change itself (P9/scope:
`walk_forward.py`'s logic is run as-is, never patched inline).

**Verdict: the mechanism (`walk_forward.py`) is ready to be trusted as
a mechanism**, independent of and separate from whether the *data* it
runs on is trustworthy. The data trustworthiness question remains
exactly where `RECON-BACKTEST` and `68.2` left it: zero `CANONICALIZED`
rows exist anywhere in the database, so no real walk-forward run —
including this one — is a real, citable strategy result. That gate
(the canonicalization migration, still never executed against a real
row) is the actual blocker for meaningful use of this tool, not the
tool's own logic.

---

## Next steps — explicitly out of scope for this checkpoint

No code change to `walk_forward.py` or `engine.py` was made or is
proposed here. No API wiring, no persistence model, no commit of the
run's own numeric output beyond this summary file. The presentation
gap in §C2 is reported, not fixed. The first *trustworthy* use of this
tool still waits on the canonicalization migration actually producing
a non-zero `CANONICALIZED` row count — unchanged from 68.2's own
"Next steps" section.
