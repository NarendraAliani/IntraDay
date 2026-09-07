# CHECKPOINT-GAINZ-D — Summary

Scope: walk-forward validation of `gainz_compatible_research`
(`code_version="v3"`) for all 3 real config presets, via
`run_walk_forward_backtest()` called directly (never
`BacktestingService.run()`). Zero code changes. `registry.py`
untouched — confirmed by `git status --short` before and after: the
only change is the pre-existing, deliberately-uncommitted
`GAINZ_ROADMAP.md`.

## 1. Authorization confirmation (asked for directly)

`[F]` **Yes — plainly, this came from the operator directly, mid-
session, not from any written checkpoint directive.** At
CHECKPOINT-GAINZ-C, a delegated agent halted on discovering that
`setup_quality_score` was pure evidence, never a gate, and 3 presets
that only varied indicator-strictness parameters could not be proven
to produce different signal *outcomes*. I verified that gap myself
independently (read `evaluate()` directly, confirmed `direction` was
decided purely by `bull_score > bear_score`), then used
`AskUserQuestion` presenting three options: (a) authorize adding the
threshold parameter + gating now, (b) redefine presets around
parameters that already gate today, (c) stop, no presets yet. **The
operator selected option (a)** — that is the authorization
`minimum_setup_quality_score` and its gating logic were built under. I
then implemented that specific code change myself directly (not
delegated), given its sensitivity as a real strategy-logic change.

## 2. `MEMORY.md` check

`[F]` Re-read `MEMORY.md` lines ~195-254 directly this checkpoint:
GAINZ-C's preset work and the quality-threshold gate addition **are
already present**, in full — the gate's parameter/default, the
authorization narrative, all 3 preset values, the gating behavioral
proof, and the exact-name before/after test suite comparison. It had
been appended correctly at GAINZ-C time; CHECKPOINT-GAINZ-C_SUMMARY.md
simply didn't mention the update in its own text. No append was
needed or made this checkpoint.

## 3. Data used — `[F]`, same real range as `68.4`/`LIVE-2`

`CHECKPOINT_69` (the canonicalization coverage-gap fix) has **not**
landed — confirmed via `git log --oneline --all | grep 69` (no
matches). Per this checkpoint's own instruction, used the same real
bar range `68.4` used: `NSE:RELIANCE`, `5m`, `HistoricalBar` table
directly, **1,842 bars**, `2026-07-29 03:50 UTC` to `2026-09-02 09:45
UTC` (unchanged row count from `68.4` — no new RELIANCE 5m rows were
added by `LIVE-3`/`LIVE-4`, which captured other symbols/streams).
This mixes genuinely-`CANONICALIZED` days (per `68.4`'s own finding)
with still-`UNCANONICALIZED` ones, and does not go through
`ResearchDataGateService` — **not a trustworthy strategy result**, the
same caveat `68.4`/`LIVE-2` carried, stated here with the same
weight, not softened.

All 3 runs used each preset's real, persisted
`StrategyConfigurationRecord` (`gainz_conservative` min-score 70,
`gainz_balanced` 55, `gainz_aggressive` 40 — same rows GAINZ-C
created), unmodified, loaded via `coerce_configuration_values()` +
`validate_configuration()`, the same application-layer path production
code uses. `min_oos_days=3, min_folds=3` — identical to every prior
walk-forward checkpoint, for direct comparability.

## 4. Per-preset fold tables — `[F]`

**`gainz_conservative`** (min_score=70) — 3 folds, **zero signals of
any kind across the entire dataset** (`aggregate_oos_return=0`,
`aggregate_oos_win_rate=0`, `mean_degradation_ratio=None`):

| Fold | IS window | IS return | OOS window | OOS return | IS win% | OOS win% |
|---|---|---|---|---|---|---|
| 1 | 07-29..08-20 | 0 | 08-21..08-25 | 0 | 0.0 | 0.0 |
| 2 | 07-29..08-25 | 0 | 08-26..08-28 | 0 | 0.0 | 0.0 |
| 3 | 07-29..08-28 | 0 | 08-31..09-02 | 0 | 0.0 | 0.0 |

Investigated directly, not assumed benign: re-ran `compute_signals()`
against the full 1,842-bar set under this preset's real config
outside the walk-forward tool — `total_signals=0` (not just
"zero non-neutral"; the strategy never emitted a `StrategySignal`
object at all across the whole dataset). Threshold=70 is simply too
strict for the `setup_quality_score` values this real market data
actually produces at this instrument/period. This is a genuine,
data-driven finding about the conservative preset's real behavior on
this specific dataset — not a bug, not an error in the walk-forward
tool, and consistent with `mean_degradation_ratio=None`'s own
documented meaning ("`None` only when every fold's in-sample return
was 0").

**`gainz_balanced`** (min_score=55) — 3 folds,
`aggregate_oos_return=-0.1519`, `aggregate_oos_win_rate=27.19`,
`mean_degradation_ratio=0.1318`:

| Fold | IS window | IS return | OOS window | OOS return | IS win% | OOS win% |
|---|---|---|---|---|---|---|
| 1 | 07-29..08-20 | -0.917 | 08-21..08-25 | -0.140 | 44.93 | 11.11 |
| 2 | 07-29..08-25 | -1.186 | 08-26..08-28 | -0.158 | 38.55 | 25.00 |
| 3 | 07-29..08-28 | -1.438 | 08-31..09-02 | -0.158 | 36.84 | 45.45 |

**`gainz_aggressive`** (min_score=40) — 3 folds,
`aggregate_oos_return=-0.3927`, `aggregate_oos_win_rate=35.56`,
`mean_degradation_ratio=0.1365`:

| Fold | IS window | IS return | OOS window | OOS return | IS win% | OOS win% |
|---|---|---|---|---|---|---|
| 1 | 07-29..08-20 | -2.442 | 08-21..08-25 | -0.465 | 45.60 | 18.75 |
| 2 | 07-29..08-25 | -3.029 | 08-26..08-28 | -0.349 | 40.95 | 37.93 |
| 3 | 07-29..08-28 | -3.503 | 08-31..09-02 | -0.364 | 40.74 | 50.00 |

## 5. Degradation, sign flips — no averaging across presets

Each preset reported distinctly, as instructed (deliberately different
risk profiles):

- **`gainz_conservative`**: no ratio computable — every fold's
  in-sample return was exactly 0 (no trades were ever taken to have a
  return). Not "degradation," a total absence of activity under this
  preset's threshold on this dataset.
- **`gainz_balanced`** (0.132): **no fold flipped sign** — IS return
  was negative in all 3 folds, and OOS stayed negative in all 3 too.
  Never "profitable in-sample, lost out-of-sample" — both sides
  consistently unprofitable on this real data/period, shrinking toward
  zero out-of-sample (ratio ~0.13, i.e. OOS loss ~13% the magnitude of
  IS loss on average).
- **`gainz_aggressive`** (0.137): same pattern — **no fold flipped
  sign**, IS and OOS both negative throughout, OOS again shrinking to
  roughly a similar ~14% of IS magnitude.

**Honest reading**: neither `gainz_balanced` nor `gainz_aggressive`
showed a profit-to-loss flip (unlike `sma_trend_filter`/
`atr_volatility_breakout` in `68.4`, which did) — but that is because
neither showed any in-sample profit to begin with on this dataset;
both were unprofitable in-sample and stayed unprofitable
out-of-sample. This is not evidence of robustness — it is evidence of
consistent unprofitability at this instrument/period under both
non-conservative presets, on data this checkpoint has already flagged
as not trustworthy for any real comparison.

## 6. Zero-persistence confirmation — `[F]`

`BacktestResultRecord.objects.count()`: **208 before, 208 after** —
unchanged, queried directly both times in the same script run.
`run_walk_forward_backtest()` was the only backtest entry point
invoked; `BacktestingService.run()` (the only method with a
`self.repository.save(...)` call) was never called.
`git status --short` before and after this checkpoint's work: only the
pre-existing, already-known, uncommitted `GAINZ_ROADMAP.md` — no
source-file diff of any kind, confirming no code changes were needed
or made.

## 7. What this does and does not prove

**Does not prove**: any of the 3 presets is trustworthy for real or
paper trading. The data itself carries the same caveat as
`68.4`/`LIVE-2` — mixed canonicalized/uncanonicalized real bars for a
single instrument over ~5 weeks, not gated through
`ResearchDataGateService`. `gainz_conservative` producing literally
zero signals on this dataset says more about this specific
threshold/data combination than about the preset's design.

**Does prove**: the walk-forward tool runs cleanly, without
persistence, against all 3 real Gainz presets using the same real data
and parameters as every other strategy's walk-forward checkpoint this
session, and surfaces a genuinely different result per preset (not a
copy-pasted number) — exactly what this checkpoint was scoped to
produce. Per the roadmap's own §1.5 finding ("the code itself won't
block registry/active-status promotion — the discipline must be
manual"), **no `RESEARCH_ACTIVE` or status change was made or implied
by this checkpoint.**

## 8. Governance compliance

- P3/P5/P9/P10: no DB write of any kind this checkpoint (confirmed
  §6); no strategy other than `gainz_compatible_research` touched; no
  scanner/live-market interaction.
- `registry.py`: confirmed untouched.
- P11/P16: this summary + `MEMORY.md` (unchanged, per §2) committed to
  `active-development` only.
