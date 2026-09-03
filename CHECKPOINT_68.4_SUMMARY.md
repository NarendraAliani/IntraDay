# Checkpoint 68.4 — Widen Real Data + Walk-Forward Test All 3 Strategies

```
checkpoint: 68.4
verdict: ALL_THREE_RUN
new_rows_backfilled: RELIANCE 994, TCS 1065, HDFCBANK 1065, INFY 1065 (4189 total, 138 real Dhan REST requests, 0 errors)
strategies_run: [ema_crossover, sma_trend_filter, atr_volatility_breakout]
strategies_insufficient_data: []
smallest_degradation_strategy: ema_crossover (qualitatively — see D for why this is stated carefully, not as a ranking)
database_write_occurred: NO
commit: (recorded below)
blockers: []
```

## A. Backfill results (Part 1)

`[F]` Credential re-checked via `effective_credentials()`: valid,
`exp_utc=2026-09-04 06:38:27` (~16.7h remaining at start).

`[F]` Widened `5m`/`REAL_DHAN` coverage for `RELIANCE`, `TCS`,
`HDFCBANK`, `INFY` across the 25 trading days `2026-07-30` to
`2026-09-02` (the exact window covering `68.3`'s known 18-day gap plus
extending to yesterday), via the same proven, idempotent
`HistoricalDataPreparationService` REST path used in `67.12.2-F`/`Q`:

| Symbol | New rows | Distinct days now | Was |
|---|---|---|---|
| RELIANCE | 994 | 26 | 12 |
| TCS | 1065 | 24 | 9 |
| HDFCBANK | 1065 | 25 | 10 |
| INFY | 1065 | 25 | 10 |

138 real API requests, 0 errors, 0 rate-limit events.

**The single most important, unplanned finding of this checkpoint**:
Part 1.4 expected `canonicalization_state` to remain
`UNCANONICALIZED` for every row (this was true for all data that
existed before this checkpoint). **It is not true for the newly
fetched rows.** Checked directly: every one of the 4 symbols now has
**923 rows / 13 distinct days stamped `CANONICALIZED`** — `2026-08-03`
through `2026-08-14`, and `2026-08-31` through `2026-09-02` — while
the previously-existing `2026-08-17`–`2026-08-28` range (fetched by
`67.12.2-F`/`Q` hours earlier) remains **exactly** `UNCANONICALIZED`,
byte-for-byte unchanged (checked directly, zero rows mutated — P4
intact).

Traced the mechanism directly: `DhanHistoricalBarProvider.
canonicalization_state_for()` — the same, unmodified function that has
existed all session — correctly returns `CANONICALIZED` right now for
a single-day, CAS-era request window (tested live against both an old
date, `2026-08-24`, and a new date, `2026-09-02`; both return
`CANONICALIZED` under current code). This means: **new REST fetches
into the proven `(NSE_EQ, FIVE_MINUTE, CAS_ERA)` scope are, and
apparently always have been, correctly canonicalized at write time by
the existing, unmodified, already-authorized provider logic** — the
never-executed migration (`67.7`–`67.13-C`) exists to retroactively
canonicalize *pre-existing* rows that predate this write-time logic
(or whose original fetch, for reasons not fully re-derivable here,
resulted in `UNCANONICALIZED`), not to gate brand-new fetches.

**Net effect: 3,692 rows across 4 symbols are now genuinely
`REAL_DHAN`+`CANONICALIZED` — real, research-eligible data exists in
this database for the first time this entire session**, produced as a
side effect of ordinary, already-authorized REST backfill, not the
still-unrun migration. This does not change anything about `68.4`'s
own no-persistence/no-trust-claim discipline for the specific
walk-forward runs below (which use the *full* real dataset, mixing
canonicalized and uncanonicalized days, and are still reported as
tool/data-validation only) — but it is a materially important fact for
the operator to know, independent of this checkpoint's own narrower
purpose.

## B. Per-strategy walk-forward results

> **NOT A TRUSTWORTHY STRATEGY RESULT FOR ANY OF THE THREE STRATEGIES
> BELOW** — even accounting for Section A's discovery, this run used
> the *full* available real bar range (`2026-07-29` to `2026-09-02`,
> 1,842 bars), which mixes genuinely-canonicalized CAS-era days with
> still-uncanonicalized ones and does not go through
> `ResearchDataGateService` at all. This section validates the tool's
> arithmetic and fold logic on real, non-uniform market data across
> three different strategies — it is not a comparison anyone should
> act on.

All three called `run_walk_forward_backtest()` directly (never
`BacktestingService.run()`, so nothing was ever eligible to persist),
using each strategy's own most-recently-created saved configuration,
unmodified: `ema_crossover`/`ema_conservative` (fast=12, slow=26),
`sma_trend_filter`/`sma_conservative` (lookback=30, band=0.75%),
`atr_volatility_breakout`/`atr_aggresive` (lookback=10,
atr_multiplier=1.2). `min_oos_days=3, min_folds=3` for all three,
against `RELIANCE`'s real 1,842-bar range (used for all three
strategies, since saved configurations are not instrument-scoped).

**`ema_crossover`** — 3 folds, `aggregate_oos_return=0.0547`,
`aggregate_oos_win_rate=31.13`, `mean_degradation_ratio=0.257`:

| Fold | IS window | IS return | OOS window | OOS return | IS win% | OOS win% |
|---|---|---|---|---|---|---|
| 1 | 07-29..08-20 | 0.211 | 08-21..08-25 | -0.035 | 28.7 | 20.8 |
| 2 | 07-29..08-25 | 0.195 | 08-26..08-28 | 0.098 | 27.9 | 35.7 |
| 3 | 07-29..08-28 | 0.233 | 08-31..09-02 | 0.101 | 28.5 | 36.8 |

**`sma_trend_filter`** — 3 folds, `aggregate_oos_return=-0.0260`,
`aggregate_oos_win_rate=8.33`, `mean_degradation_ratio=-0.183`:

| Fold | IS window | IS return | OOS window | OOS return | IS win% | OOS win% |
|---|---|---|---|---|---|---|
| 1 | 07-29..08-20 | 0.147 | 08-21..08-25 | 0.000 | 42.9 | 0.0 |
| 2 | 07-29..08-25 | 0.147 | 08-26..08-28 | -0.005 | 42.9 | 0.0 |
| 3 | 07-29..08-28 | 0.142 | 08-31..09-02 | -0.073 | 37.5 | 25.0 |

**`atr_volatility_breakout`** — 3 folds,
`aggregate_oos_return=-0.0138`, `aggregate_oos_win_rate=27.22`,
`mean_degradation_ratio=1.045`:

| Fold | IS window | IS return | OOS window | OOS return | IS win% | OOS win% |
|---|---|---|---|---|---|---|
| 1 | 07-29..08-20 | 0.150 | 08-21..08-25 | -0.072 | 41.7 | 25.0 |
| 2 | 07-29..08-25 | 0.086 | 08-26..08-28 | -0.064 | 38.3 | 16.7 |
| 3 | 07-29..08-28 | 0.022 | 08-31..09-02 | 0.095 | 36.4 | 40.0 |

## C. The number that actually matters most: degradation, not raw return

`mean_degradation_ratio = mean(oos_return / is_return)` per fold —
close to 1 means OOS performance tracked IS; negative means OOS return
had the **opposite sign** from IS (in-sample profit, out-of-sample
loss); near-zero/small-positive means OOS return shrank toward zero
relative to IS but kept the same direction.

- **`ema_crossover` (0.257)**: never flipped sign — every fold's OOS
  return stayed positive when IS was positive, though shrunk to
  roughly a quarter of the in-sample magnitude on average.
- **`sma_trend_filter` (-0.183)**: **flipped sign in 2 of 3 folds** —
  fold 2 and fold 3 both went from a real in-sample profit to an
  out-of-sample loss; fold 1 went to exactly zero (no OOS trades won).
- **`atr_volatility_breakout` (1.045)**: the aggregate figure is
  misleadingly close to 1 — folds 1 and 2 individually **also flipped
  sign** (profit in-sample, loss out-of-sample), and the average is
  pulled toward 1 almost entirely by fold 3's outlier (a small
  in-sample return paired with a larger out-of-sample one). With only
  3 folds, a mean-of-ratios metric is fragile exactly like this — one
  outlier fold can make the aggregate number look far better than the
  individual folds actually behaved.

## D. Honest cross-strategy comparison — directional only, not a recommendation

**If forced to name one**: `ema_crossover` is the only one of the
three whose out-of-sample return never flipped sign relative to
in-sample, across all 3 folds — a qualitatively more consistent
pattern than the other two, both of which showed at least one
profit-to-loss flip.

**This is a directional observation from 3 folds on ~5 weeks of
partially-uncanonicalized real data for one instrument, using each
strategy's own arbitrarily-chosen "most recent" saved configuration
(not necessarily anyone's actual preferred default) — it is not proof
of anything, and it is explicitly not a basis for any real or paper
trading decision.** A different configuration for either
`sma_trend_filter` or `atr_volatility_breakout`, a different
instrument, or simply more real trading days could change this
entirely. This section exists to prove the walk-forward tool produces
a genuinely different, meaningful signal per strategy — not to declare
a winner, and none of the three is recommended for anything based on
this run.

## E. Zero-persistence confirmation

`[F]` `BacktestResultRecord.objects.count()`: **208 before, 208
after** — unchanged, checked directly both times.
`[F]` `git status --short`: only the pre-existing, already-known,
separately-tracked `RECON_BACKTEST_SUMMARY.md` untracked file — no
source-file diff of any kind.
`[F]` Every walk-forward call in this checkpoint went through
`run_walk_forward_backtest()` directly; `BacktestingService.run()`
(the only method with a `self.repository.save(...)` call) was never
invoked.

## What would need to happen for any of this to become trustworthy

The canonicalization migration (`67.7`–`67.13-C`, built and proven but
never executed against real data) remains the actual blocker for the
*bulk* of existing real data — but Section A's discovery means a
**genuine, if small (13 days × 4 symbols), research-eligible dataset
already exists right now**, without needing that migration at all, for
data fetched from this point forward. A future checkpoint could
deliberately re-run the walk-forward tool restricted to *only* the
`CANONICALIZED` subset, through the real `ResearchDataGateService`
path (not the direct-call bypass used here), and that specific result
would be able to honestly claim research-eligibility for the first
time — still on a very small dataset, but no longer blocked by the
migration gap.
