# CHECKPOINT 70 — Summary

Scope: widen the real backfill using `CHECKPOINT_69`'s corrected
`_provider_request_envelope()`, then run the first proper gate-verified
walk-forward comparison across all 4 strategies. Market closed
throughout. No new strategy code, no registry change, no
`RESEARCH_ACTIVE`/status change for anything.

```
part_1_new_days: 3 (2026-09-03, 2026-09-04, 2026-09-07), all 4 symbols
part_1_new_rows: 216/symbol (864 total), every new day a complete
                 72-bar day - the fix holds on fresh data
part_1_gate_full_range: REJECTED (pre-existing, already-documented
                         2026-08-17..08-28 UNCANONICALIZED interior
                         gap - not a new issue, not touched here)
part_1_gate_per_block: Block A (08-03..08-14) 720/720 ACCEPTED,
                       Block B (08-31..09-07, widened) 432/432 ACCEPTED
part_2_dataset: 1,152 bars / 16 gate-verified trading days (2 blocks
                concatenated around the untouched interior gap)
part_2_strategies_run: [ema_crossover, sma_trend_filter,
                        atr_volatility_breakout,
                        gainz_conservative, gainz_balanced,
                        gainz_aggressive] - 6/6 produced fold results
database_write_occurred: YES (Part 1 backfill only, 864 rows, real
                          REST path) / NO for Part 2
                          (BacktestResultRecord unchanged, 208->208)
memory_md_updated: YES - confirmed below, see "MEMORY.md update"
commit: (recorded below)
blockers: []
```

## Part 1 — Widened backfill

`[F]` Credentials valid, checked directly before running. Extended the
same 4 symbols (RELIANCE/TCS/HDFCBANK/INFY) forward from the existing
data's last date (`2026-09-02`) through the most recent closed trading
day, confirmed directly against the real environment clock
(`2026-09-07 20:15 IST` — well past the 15:30 IST close) rather than
assumed from this checkpoint's own wording: `2026-09-03` and
`2026-09-04` (both `is_trading_day() == True`), `2026-09-05`/`09-06`
skipped (`is_trading_day() == False` — a weekend), `2026-09-07`
included. Ran through the REAL, unmodified
`HistoricalDataPreparationService.prepare()` path (same wiring
`68.4`/`CHECKPOINT_69` used — `DhanHistoricalBarProvider` +
`DjangoHistoricalBarRepository`, no bypass), one `prepare()` call per
symbol spanning `2026-09-03`–`2026-09-07`.

| Symbol | CANONICALIZED rows before | after | New rows |
|---|---|---|---|
| RELIANCE | 936 | 1152 | 216 |
| TCS | 936 | 1152 | 216 |
| HDFCBANK | 936 | 1152 | 216 |
| INFY | 936 | 1152 | 216 |

**864 total new rows** — exactly 3 days x 72 bars x 4 symbols, `[F]`
verified directly:
- All 3 new days, for all 4 symbols, land as **complete 72-bar days**
  (`all_72: True` for all 16 now-CANONICALIZED days per symbol,
  checked via grouped `Count`) — **the fix holds on data it was never
  diagnosed against**, not just the originally-gapped range. RELIANCE
  2026-09-03's day-start bar (`03:50 UTC` / 09:20 IST) is present,
  `canonicalization_state=CANONICALIZED`, `source=API_FETCH`.
- **Zero duplicate** `(instrument_id, timeframe, bar_timestamp)` rows
  across all 4 symbols after the backfill.

`[F]` **Gate against the FULL now-widened range**
(`2026-08-03`–`2026-09-07`) was tried first, as instructed: **REJECTED**
— `INCOMPLETE_COVERAGE: 20 missing sub-range(s); 1852/1872 bars
(98.93%) cached`. This is **not a new or different issue** — it is the
already-documented, pre-existing `2026-08-17`–`2026-08-28`
`UNCANONICALIZED` interior gap first found in `68.4`/`LIVE-2`, entirely
untouched by `CHECKPOINT_69`'s fix (which only ever addressed the
1-bar/day day-start gap, not whole-range canonicalization state). Per
this checkpoint's own rule ("if Part 1's backfill surfaces any new,
different data-quality issue... stop and report" — this is neither new
nor different, so no stop was warranted), this was reported honestly
and the two genuinely CANONICALIZED contiguous blocks were queried
through the gate SEPARATELY instead:

- **Block A** (`2026-08-03`–`2026-08-14`, unchanged from
  `CHECKPOINT_69`): gate **ACCEPTED — 720/720 bars**.
- **Block B** (`2026-08-31`–`2026-09-07`, WIDENED this checkpoint from
  `CHECKPOINT_69`'s 3-day `08-31`–`09-02` span to 6 trading days):
  gate **ACCEPTED — 432/432 bars** (6 days x 72, exactly complete).

Both individually gate-accepted; concatenated (sorted by timestamp) for
Part 2 below — `compute_walk_forward_folds()` builds folds purely from
the distinct calendar dates actually present in the supplied bars
(confirmed by direct code reading, not assumed), so a concatenation
across the untouched interior gap is safe and correct: fold boundaries
simply skip from `2026-08-14` straight to `2026-08-31` without
fabricating or interpolating any day in between, which the fold tables
below show directly.

## Part 2 — Gate-verified walk-forward, all 4 strategies

`run_walk_forward_backtest()` called directly (never
`BacktestingService.run()`) for all 4 strategies against the combined
**1,152-bar / 16-day** gate-verified dataset, `min_oos_days=3,
min_folds=3` throughout. Legacy 3 strategies via `build_default_
registry()`; Gainz via a LOCAL `StrategyRegistry()` (same pattern
`CHECKPOINT-GAINZ-D` used) — `registry.py` confirmed untouched
(`git diff --stat` empty for that file, and for every source file: the
only diff this checkpoint produces is this summary +
`MEMORY.md`).

**`ema_crossover`** (`ema_conservative`) — 3 folds,
`aggregate_oos_return=-0.2904`, `aggregate_oos_win_rate=20.05`,
`mean_degradation_ratio=0.373`:

| Fold | IS window | IS return | OOS window | OOS return | IS win% | OOS win% |
|---|---|---|---|---|---|---|
| 1 | 08-03..08-11 | -0.524 | 08-12..08-14 | -0.379 | 14.58 | 9.52 |
| 2 | 08-03..08-14 | -0.832 | 08-31..09-02 | -0.050 | 14.49 | 31.58 |
| 3 | 08-03..09-02 | -1.319 | 09-03..09-07 | -0.442 | 16.67 | 19.05 |

**`sma_trend_filter`** (`sma_conservative`) — 3 folds,
`aggregate_oos_return=-0.0519`, `aggregate_oos_win_rate=11.11`,
`mean_degradation_ratio=0.221`:

| Fold | IS window | IS return | OOS window | OOS return | IS win% | OOS win% |
|---|---|---|---|---|---|---|
| 1 | 08-03..08-11 | 0.107 | 08-12..08-14 | 0 | 50.0 | 0.0 |
| 2 | 08-03..08-14 | 0.107 | 08-31..09-02 | -0.094 | 50.0 | 0.0 |
| 3 | 08-03..09-02 | -0.040 | 09-03..09-07 | -0.062 | 25.0 | 33.33 |

**`atr_volatility_breakout`** (`atr_aggresive`) — 3 folds,
`aggregate_oos_return=0.0114`, `aggregate_oos_win_rate=56.94`,
`mean_degradation_ratio=0.0029`:

| Fold | IS window | IS return | OOS window | OOS return | IS win% | OOS win% |
|---|---|---|---|---|---|---|
| 1 | 08-03..08-11 | -0.431 | 08-12..08-14 | 0.102 | 27.27 | 83.33 |
| 2 | 08-03..08-14 | -0.369 | 08-31..09-02 | 0.029 | 35.71 | 50.0 |
| 3 | 08-03..09-02 | -0.299 | 09-03..09-07 | -0.097 | 40.54 | 37.50 |

**`gainz_compatible_research` / `gainz_conservative`** — 3 folds,
**zero signals across the entire dataset again**
(`aggregate_oos_return=0`, `aggregate_oos_win_rate=0`,
`mean_degradation_ratio=None`) — every fold's IS and OOS return is
exactly 0. Consistent with `CHECKPOINT-GAINZ-D`'s identical finding on
a different (mixed, larger) real dataset: this preset's threshold (70)
is simply too strict for the `setup_quality_score` values real market
data at this instrument produces, not a bug.

**`gainz_compatible_research` / `gainz_balanced`** — 3 folds,
`aggregate_oos_return=-0.1434`, `aggregate_oos_win_rate=42.88`,
`mean_degradation_ratio=0.200`:

| Fold | IS window | IS return | OOS window | OOS return | IS win% | OOS win% |
|---|---|---|---|---|---|---|
| 1 | 08-03..08-11 | -0.488 | 08-12..08-14 | -0.044 | 45.16 | 63.64 |
| 2 | 08-03..08-14 | -0.554 | 08-31..09-02 | -0.178 | 50.0 | 40.0 |
| 3 | 08-03..09-02 | -1.108 | 09-03..09-07 | -0.208 | 45.61 | 25.0 |

**`gainz_compatible_research` / `gainz_aggressive`** — 3 folds,
`aggregate_oos_return=-0.4152`, `aggregate_oos_win_rate=39.41`,
`mean_degradation_ratio=0.369`:

| Fold | IS window | IS return | OOS window | OOS return | IS win% | OOS win% |
|---|---|---|---|---|---|---|
| 1 | 08-03..08-11 | -0.809 | 08-12..08-14 | -0.465 | 52.11 | 32.14 |
| 2 | 08-03..08-14 | -1.263 | 08-31..09-02 | -0.381 | 49.06 | 48.15 |
| 3 | 08-03..09-02 | -1.723 | 09-03..09-07 | -0.400 | 49.29 | 37.93 |

`[F]` Zero persistence: `BacktestResultRecord.objects.count()`: **208
before, 208 after**, confirmed directly. `run_walk_forward_backtest()`
was the only backtest entry point invoked across all 6 runs.

## Part 3 — Honest cross-strategy read

**Is there now enough signal for more than "a first data point"? No —
still not enough, and this run's own internal inconsistency is part of
why, stated plainly rather than glossed over.**

**Sign-flip comparison across all 3 dataset versions, per legacy
strategy** (a "flip" = an in-sample profit becoming an out-of-sample
loss, or vice versa, within one fold):

- **`ema_crossover`**: `68.4` (25-day mixed) — **0 flips**, and
  *consistently profitable* in-sample every fold. `CHECKPOINT_69`
  (10-day gate-verified) — **1 flip** (fold 1), and *consistently
  unprofitable* in-sample. `CHECKPOINT_70` (16-day gate-verified) —
  **0 flips**, and *consistently unprofitable* in-sample. **The
  qualitative picture does NOT hold up**: `68.4`'s "ema is the most
  consistent of the three" reading was built on a dataset where ema
  was actually profitable in-sample; on both gate-verified real
  datasets since, it has been consistently UNPROFITABLE in-sample
  instead. This is the clearest example this session of why `68.4`'s
  own explicit caveat ("not a basis for any real or paper trading
  decision") was correct — the earlier qualitative lean toward
  `ema_crossover` does not survive contact with real, gate-verified
  data.
- **`sma_trend_filter`**: `68.4` — 2/3 flips. `69` — 1 flip (fold 2).
  `70` — 1 flip (fold 2; fold 1 is degenerate, zero OOS trades). All
  three runs show the same qualitative shape (a real in-sample edge
  that does not survive out-of-sample, at least once per run) — this
  IS a consistent pattern, though the magnitude/fold-location varies.
- **`atr_volatility_breakout`**: `68.4` — 2/3 flips (folds 1,2).
  `69` — 1 flip (fold 3). `70` — 2/3 flips (folds 1,2), but the
  DIRECTION of those flips is now the OPPOSITE of `68.4`'s (in `70`,
  IS is negative and OOS flips positive; in `68.4`, IS was positive
  and OOS flipped negative). Combined with `mean_degradation_ratio`
  landing suspiciously close to 0 or 1 in different runs purely from
  outlier folds, this strategy's walk-forward signal is the least
  trustworthy of the three across every version of this dataset run
  so far — the aggregate ratio number should not be read as meaningful
  for this strategy at this sample size, a caveat `68.4` already
  raised and this checkpoint's data reinforces rather than resolves.

**Gainz presets — the one place this checkpoint DOES have slightly
firmer ground**: `gainz_conservative`'s zero-signal outcome and
`gainz_balanced`/`gainz_aggressive`'s consistently-unprofitable,
zero-sign-flip pattern reproduced **identically** across two
genuinely independent real datasets (`CHECKPOINT-GAINZ-D`'s mixed
25-day/1,842-bar set and this checkpoint's gate-verified 16-day/
1,152-bar set) — the same qualitative story on two different real
samples is modestly stronger evidence than either run alone, though
still nowhere near enough for a trust/validation decision (same single
instrument, same short real trading history, no other symbol has ever
been walk-forward-tested for this strategy).

**Bottom line, stated as plainly as `68.4`/`CHECKPOINT_69` themselves
were**: the underlying real dataset is still small (16 trading days,
one instrument), still has an unaddressed interior canonicalization
gap, and — now demonstrably — different real slices of it produce
materially different qualitative conclusions for the 3 legacy
strategies. This is evidence AGAINST treating any single walk-forward
run (including this one) as conclusive, not evidence FOR any
particular strategy. No `RESEARCH_ACTIVE`/status change was made or
implied for any strategy.

## `MEMORY.md` update — confirmed made

`[F]` Appended (never rewrote) a new entry to `MEMORY.md` §3, inserted
directly before the pre-existing `LIVE-2-FINALIZE` bullet, explicitly
marking the prior `LIVE-2` Stream 2 coverage-gap bullet and the "no
genuinely research-eligible walk-forward result exists yet" bullet as
now-stale/resolved, with the fix's mechanism, the recovered
row/day counts, the gate-acceptance proof, and this checkpoint's
cross-strategy finding (including the Gainz-pattern reproduction and
the legacy-strategy inconsistency) — matching the file's existing
structure and concise tone, as every prior append this session did.
**Confirmed explicitly here, as this checkpoint's own instruction
required** (the prior two checkpoints, `CHECKPOINT_69` and
`CHECKPOINT-GAINZ-D`, did not need a `MEMORY.md` update per their own
scope and did not claim one).

## Governance compliance

- P3: DB writes limited to Part 1's 864 `HistoricalBar` INSERTs
  (upsert-by-identity, real REST fetch, the same proven path prior
  checkpoints used) — no other table touched.
- P4: zero existing rows mutated/relabeled/deleted (duplicate check +
  before/after counts both confirm this directly).
- P5: no migration execution.
- P6: real Dhan network calls in Part 1 only (the explicitly
  authorized backfill).
- P9: no strategy logic (EMA/SMA/ATR/CH/Gainz) touched — this
  checkpoint made zero source-code changes of any kind (`git diff
  --stat` against `HEAD~0` for any `src/` file is empty; only this
  summary and `MEMORY.md` are new/changed).
- `registry.py`: confirmed untouched.
- P10: no scanner activation, no live-market interaction.
- P11/P16: this summary + `MEMORY.md` committed to `active-development`
  only.
