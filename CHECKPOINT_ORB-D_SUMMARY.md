# CHECKPOINT-ORB-D — Summary

Scope: Phase D of `ORB_STRATEGY_ROADMAP.md` — the mandatory walk-
forward validation gate, same discipline as every other strategy this
session. `registry.py` untouched throughout (a LOCAL
`StrategyRegistry()` was used). No parameter changes, no new presets,
no strategy code changes — none were needed.

```
data_checked_directly: 17 real trading days per symbol (unchanged
                        since CHECKPOINT-ORB-B's own check)
symbols_tested: RELIANCE, TCS, HDFCBANK, INFY (all 4)
presets_tested: orb_classic, orb_tight, orb_wide (all 3)
runs: 12/12 produced real fold results
central_question_answer: PARTIALLY SURVIVES - RELIANCE stays
                          aggregate-positive across ALL 3 presets (the
                          BEST single-symbol result of the whole
                          session), but 2 of 3 RELIANCE presets show
                          real fold-level sign instability; does NOT
                          generalize to HDFCBANK/INFY (both negative
                          across all 3 presets there)
database_write_occurred: NO (BacktestResultRecord unchanged, 208->208)
research_active_status_change: NONE
memory_md_updated: YES - confirmed below
commit: (recorded below)
blockers: []
```

## 1. Data used — checked directly, not assumed

`[F]` Re-checked `HistoricalBar` directly before running anything:
**still 17 real, `CANONICALIZED` trading days per symbol**, unchanged
since `CHECKPOINT-ORB-B`'s own last check — `CHECKPOINT_72`'s daily
routine has not been re-run since. Same two gate-verified blocks every
Phase D since `CHECKPOINT_71` has used.

**An honest caveat specific to ORB, stated up front**: ORB fires at
most once per session (one breakout opportunity per day), so its own
per-fold trade counts are genuinely SMALLER than every other strategy
tested this session — several OOS folds below have only 2–5 trades.
This is on TOP of the small-real-day-count caveat every Phase D
already carries, not a separate new problem, but worth naming
explicitly: these specific numbers carry even less statistical weight
than the other 4 strategies' own walk-forward figures did.

## 2. RELIANCE / `orb_classic` — the central question, answered directly

`CHECKPOINT-ORB-B`'s own first look: RELIANCE, default (`orb_classic`)
params, 18 trades, 77.8% win rate, net_pnl **+93.82**, return **+0.094%**.

**Walk-forward split result**:

| Fold | IS window | IS return | OOS window | OOS return | IS trades | OOS trades |
|---|---|---|---|---|---|---|
| 1 | 08-03..08-12 | +0.244 | 08-13..08-31 | +0.259 | 9 | 4 |
| 2 | 08-03..08-31 | -0.054 | 09-01..09-03 | +0.059 | 12 | 2 |
| 3 | 08-03..09-03 | +0.096 | 09-04..09-08 | -0.123 | 14 | 4 |

`aggregate_oos_return=+0.0650`, `mean_degradation_ratio=-0.439`.

**Honest answer: PARTIALLY survives, not cleanly.** The AGGREGATE OOS
return stays positive (+0.065%) — a genuine, direct continuation of
`CHECKPOINT-ORB-B`'s own encouraging first look, and (per §4 below)
the best single-symbol walk-forward result of this entire session.
**But 2 of the 3 individual folds show a real sign flip** (fold 2:
IS slightly negative, OOS positive; fold 3: IS positive, OOS
negative) — this is NOT a clean, non-flipping validation. The
aggregate figure is being carried by fold 1's own large positive OOS
result on a small (4-trade) sample, exactly the kind of single-fold-
driven aggregate `CHECKPOINT_70`'s own §3 already warned is fragile at
`min_folds=3`. Reported plainly, not softened because the first look
was encouraging: **this is a real, positive, but fold-unstable
result** — genuine evidence in ORB's favor, not proof of a validated
edge.

## 3. Full results — all 12 combinations

### RELIANCE

**`orb_classic`** — `aggregate_oos_return=+0.0650`,
`mean_degradation_ratio=-0.439`, **2/3 folds flip** (table above).

**`orb_tight`** — `aggregate_oos_return=+0.0587`,
`mean_degradation_ratio=+0.260`, **1/3 folds flip** — the MOST STABLE
of the 3 RELIANCE presets, and notably high win rates throughout
(72–80% IS, 50–80% OOS):

| Fold | IS return | OOS return | IS trades | OOS trades |
|---|---|---|---|---|
| 1 | +0.249 | +0.176 | 11 | 5 |
| 2 | +0.369 | +0.122 | 16 | 5 |
| 3 | +0.472 | -0.121 | 20 | 4 |

**`orb_wide`** — `aggregate_oos_return=+0.0890`,
`mean_degradation_ratio=-1.072`, **2/3 folds flip** (folds 1, 3), very
small OOS trade counts (1–3 trades/fold) — the largest aggregate
number of the 3, but on the thinnest, noisiest sample.

### TCS

**`orb_classic`** — `aggregate_oos_return=+0.1047`, **2/3 folds flip**;
notably, IS return is consistently NEGATIVE across all 3 folds here
(-1.83 to -1.78) while OOS swings both directions — a different
pattern than RELIANCE's (where IS itself was mostly positive).

**`orb_tight`** — `aggregate_oos_return=-0.0323`, **2/3 folds flip**.

**`orb_wide`** — `aggregate_oos_return=+0.2309`, **2/3 folds flip**, on
an even thinner sample (6 IS trades, 1–2 OOS trades/fold) — the
largest single aggregate number across all 12 combinations, but also
the least statistically meaningful given the trade counts involved.

### HDFCBANK — consistently negative, all 3 presets

`orb_classic` `aggregate_oos_return=-0.0708`; `orb_tight` `-0.0495`;
`orb_wide` `-0.0748`. Unlike TCS's noisy swings, HDFCBANK shows a
MORE stable (if unprofitable) pattern — IS returns consistently
negative across every fold, every preset.

### INFY — consistently negative, all 3 presets

`orb_classic` `aggregate_oos_return=-0.1077`; `orb_tight` `-0.0905`;
`orb_wide` `-0.1096`. A recurring pattern across all 3 presets: folds
1–2 are consistently negative both IS and OOS, while fold 3's OOS
flips positive — 1 flip typically, in the same fold, across all 3
INFY presets.

`[F]` Zero persistence across all 12 runs: `BacktestResultRecord.
objects.count()`: **208 before, 208 after**.

## 4. Honest cross-strategy comparison

**Direct RELIANCE comparison, every figure cited from its own source
checkpoint**:

| Strategy/preset | RELIANCE `aggregate_oos_return` |
|---|---|
| `orb_wide` (this checkpoint) | **+0.0890** |
| `orb_classic` (this checkpoint) | **+0.0650** |
| `orb_tight` (this checkpoint) | **+0.0587** |
| `atr_volatility_breakout`/`atr_aggresive` (`CHECKPOINT_70`) | +0.0114 |
| `sma_trend_filter`/`sma_conservative` (`CHECKPOINT_70`) | -0.0519 |
| `vwap_wide` (`CHECKPOINT-VWAP-D`) | -0.0646 |
| `gainz_balanced` (`CHECKPOINT_70`) | -0.1434 |
| `vwap_normal` (`CHECKPOINT-VWAP-D`) | -0.1251 |
| `vwap_tight` (`CHECKPOINT-VWAP-D`) | -0.1861 |
| `ema_crossover`/`ema_conservative` (`CHECKPOINT_70`) | -0.2904 |
| `gainz_aggressive` (`CHECKPOINT_70`) | -0.4152 |

**All 3 ORB presets are the best RELIANCE results of this entire
session — clearly, not marginally** (the next-best, `atr_volatility_
breakout`'s own +0.0114, is roughly 5–8× smaller than any ORB
preset's own figure). Stated as plainly as the checkpoint's own rule
requires: **this is the first strategy this session where the
favorable MFE distribution (`CHECKPOINT-ORB-B`'s own 88.2% ≥2.0x ATR
finding) is genuinely reflected in a better walk-forward outcome** —
on RELIANCE specifically. This does NOT fully escape `CHECKPOINT_75`/
`CHECKPOINT-VWAP-D`'s own "MFE doesn't guarantee profitability"
lesson, though: `orb_classic`/`orb_wide` both still show real
fold-level sign instability (2/3 flips each) despite their positive
aggregate — a favorable MFE distribution correlating with a better
OUTCOME is not the same as it producing a STABLE one. `orb_tight`
alone comes closest to genuinely stable (1/3 flips, consistently high
win rate) — the most encouraging single result in this checkpoint.

**Does NOT generalize cross-symbol** — the same pattern
`CHECKPOINT_71` already established for every other strategy this
session: a real RELIANCE-specific edge does not automatically transfer
to other symbols. HDFCBANK and INFY are both negative across all 3
ORB presets, exactly mirroring how the legacy strategies' own
RELIANCE strengths (`atr_volatility_breakout`'s positive result,
`sma_trend_filter`'s) also failed to replicate cross-symbol in that
same checkpoint. TCS is genuinely mixed (2/3 presets positive, but on
the thinnest, noisiest samples of any symbol here).

## 5. What this does and does not prove

**Does not prove**: `orb_breakout`, at any preset, is ready for real
or paper trading. The dataset remains 17 real trading days on 4
symbols, ORB's own per-fold trade counts are the smallest of any
strategy tested this session, and even RELIANCE's own best result
(`orb_tight`) still shows one real fold-level flip.

**Does prove**: (a) the walk-forward tool runs cleanly for
`orb_breakout` against real, gate-verified data across all 3 presets
and all 4 symbols; (b) RELIANCE specifically shows this session's
single strongest, most consistent positive walk-forward signal across
ALL 3 presets simultaneously — a genuinely notable, first-of-its-kind
result this checkpoint reports plainly rather than either oversells or
buries; (c) that result does not (yet) generalize beyond RELIANCE, and
even on RELIANCE is not fully fold-stable. Per every prior Phase D's
own established discipline, **no `RESEARCH_ACTIVE` or status change
was made or implied.**

## `MEMORY.md` update — confirmed made

`[F]` Appended (never rewrote) a new entry to `MEMORY.md` §3 recording:
the 17-day dataset confirmation, the RELIANCE/`orb_classic` central-
question answer (partial survival, aggregate positive but fold-
unstable), the full 12-combination picture (RELIANCE uniformly
positive, TCS mixed, HDFCBANK/INFY uniformly negative), and the honest
cross-strategy comparison (ORB's RELIANCE results are this session's
best by a clear margin, `orb_tight` the most fold-stable, none of it
generalizing cross-symbol). Matches the file's existing structure and
tone. **Confirmed explicitly here, as this checkpoint's own
instruction required.**

## Governance compliance

- P3: zero DB writes this checkpoint (read + compute only against
  already-backfilled, already gate-verified data;
  `BacktestResultRecord` unchanged, 208→208, confirmed directly).
- P9: no strategy code touched — `orb_breakout.py` was read but not
  modified; no other strategy file touched.
- `registry.py`: confirmed untouched.
- No `RESEARCH_ACTIVE` status change, no new backfill, no new presets,
  no parameter changes — all as instructed.
- P11/P16: this summary + `MEMORY.md` committed to `active-development`
  only.
