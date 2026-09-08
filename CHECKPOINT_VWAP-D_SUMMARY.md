# CHECKPOINT-VWAP-D — Summary

Scope: Phase D of `VWAP_STRATEGY_ROADMAP.md` — the mandatory walk-
forward validation gate, same discipline as every other strategy this
session. `registry.py` untouched throughout (a LOCAL
`StrategyRegistry()` was used, same pattern `CHECKPOINT-GAINZ-D`
established). No parameter changes, no new presets, no strategy code
changes — none were needed.

```
data_checked_directly: 17 real trading days per symbol (unchanged
                        since CHECKPOINT-VWAP-B's own check - no new
                        backfill has run since 2026-09-08's own daily
                        routine execution)
symbols_tested: RELIANCE, TCS, HDFCBANK, INFY (all 4)
presets_tested: vwap_tight, vwap_normal, vwap_wide (all 3)
runs: 12/12 produced real fold results
aggregate_oos_return: NEGATIVE for all 12 combinations - no
                       combination is net profitable at this sample
                       size
database_write_occurred: NO (BacktestResultRecord unchanged, 208->208)
research_active_status_change: NONE
memory_md_updated: YES - confirmed below
commit: (recorded below)
blockers: []
```

## 1. Data used — checked directly, not assumed

`[F]` Re-checked `HistoricalBar` directly before running anything:
**17 real, `CANONICALIZED` trading days per symbol**, all 4 symbols,
unchanged from `CHECKPOINT-VWAP-B`'s own figure — `CHECKPOINT_72`'s
daily backfill routine has not been re-run since `2026-09-08`'s own
execution (still the same calendar day at the time of this
checkpoint), so no new days exist to pick up. Same two gate-verified
blocks every checkpoint since `CHECKPOINT_71` has used: Block A
(`2026-08-03`–`08-14`, 10 trading days, 720 bars/symbol) and Block B
(`2026-08-31`–`09-08`, 7 trading days, 504 bars/symbol) — each
queried through the REAL `ResearchDataGateService` SEPARATELY (the
still-`UNCANONICALIZED` `2026-08-17`–`08-28` interior gap remains
untouched, unaddressed, exactly as every prior checkpoint has left
it) and concatenated for the walk-forward call, exactly the same
established pattern.

## 2. Walk-forward results — all 12 combinations, `min_oos_days=3, min_folds=3`

`run_walk_forward_backtest()` called directly (never
`BacktestingService.run()`) for every symbol × preset combination.
`[F]` Zero persistence: `BacktestResultRecord.objects.count()`: **208
before, 208 after**.

### RELIANCE

**`vwap_tight`** — `aggregate_oos_return=-0.1861`,
`mean_degradation_ratio=0.152`, **0 sign flips** (all 3 folds
IS-negative/OOS-negative):

| Fold | IS window | IS return | OOS window | OOS return | IS trades | OOS trades |
|---|---|---|---|---|---|---|
| 1 | 08-03..08-12 | -1.032 | 08-13..08-31 | -0.217 | 39 | 14 |
| 2 | 08-03..08-31 | -1.291 | 09-01..09-03 | -0.110 | 51 | 14 |
| 3 | 08-03..09-03 | -1.434 | 09-04..09-08 | -0.232 | 67 | 10 |

**`vwap_normal`** — `aggregate_oos_return=-0.1251`,
`mean_degradation_ratio=0.219`, **1 flip** (fold 2):

| Fold | IS window | IS return | OOS window | OOS return | IS trades | OOS trades |
|---|---|---|---|---|---|---|
| 1 | 08-03..08-12 | -0.489 | 08-13..08-31 | -0.192 | 24 | 9 |
| 2 | 08-03..08-31 | -0.733 | 09-01..09-03 | +0.048 | 33 | 3 |
| 3 | 08-03..09-03 | -0.704 | 09-04..09-08 | -0.231 | 38 | 8 |

**`vwap_wide`** — `aggregate_oos_return=-0.0646`,
`mean_degradation_ratio=0.135`, **1 flip** (fold 2) — the smallest
loss of the 3 RELIANCE presets:

| Fold | IS window | IS return | OOS window | OOS return | IS trades | OOS trades |
|---|---|---|---|---|---|---|
| 1 | 08-03..08-12 | -0.466 | 08-13..08-31 | -0.124 | 18 | 6 |
| 2 | 08-03..08-31 | -0.652 | 09-01..09-03 | +0.036 | 24 | 3 |
| 3 | 08-03..09-03 | -0.543 | 09-04..09-08 | -0.105 | 28 | 6 |

### TCS

**`vwap_tight`** — `aggregate_oos_return=-0.3790`, **1 flip** (fold 2):
fold1 IS -1.813/OOS -0.547 (32/13 trades); fold2 IS -2.268/OOS +0.039
(45/9); fold3 IS -2.656/OOS -0.629 (56/9).

**`vwap_normal`** — `aggregate_oos_return=-0.1312`, **1 flip** (fold
2): fold1 IS -1.235/OOS -0.267 (24/7); fold2 IS -1.407/OOS +0.305
(31/6); fold3 IS -1.171/OOS -0.432 (38/6).

**`vwap_wide`** — `aggregate_oos_return=-0.0779`, **1 flip** (fold 2),
smallest TCS loss: fold1 IS -1.522/OOS -0.096 (18/5); fold2 IS
-0.900/OOS +0.250 (21/5); fold3 IS -0.823/OOS -0.388 (26/4).

### HDFCBANK

**`vwap_tight`** — `aggregate_oos_return=-0.0985`, **1 flip** (fold
2): fold1 IS -0.284/OOS -0.259 (35/21); fold2 IS -0.493/OOS +0.067
(57/9); fold3 IS -0.512/OOS -0.103 (68/12).

**`vwap_normal`** — `aggregate_oos_return=-0.0327`, **1 flip** (fold
2) — the third-smallest loss of the 12 combinations tested:
fold1 IS -0.184/OOS -0.120 (23/10); fold2 IS -0.263/OOS +0.055
(33/6); fold3 IS -0.288/OOS -0.032 (39/8).

**`vwap_wide`** — `aggregate_oos_return=-0.0388`, **1 flip** (fold 2):
fold1 IS -0.122/OOS -0.145 (18/8); fold2 IS -0.225/OOS +0.052 (26/5);
fold3 IS -0.262/OOS -0.024 (31/6).

### INFY

**`vwap_tight`** — `aggregate_oos_return=-0.1137`, **2 flips** (folds
1 and 2): fold1 IS -0.160/OOS +0.095 (32/16); fold2 IS -0.152/OOS
+0.023 (49/11); fold3 IS -0.275/OOS -0.460 (61/11).

**`vwap_normal`** — `aggregate_oos_return=-0.0197`,
`mean_degradation_ratio=-0.036` (the only NEGATIVE mean-degradation
figure of the 12 — the aggregate ratio's own sign flips, though 2 of
3 individual folds still do too), **2 flips** (folds 1 and 2) —
**the smallest loss of all 12 combinations tested**: fold1 IS -0.207/OOS +0.204 (20/10);
fold2 IS -0.118/OOS +0.045 (30/7); fold3 IS -0.245/OOS -0.308 (38/8).

**`vwap_wide`** — `aggregate_oos_return=-0.0322`, **2 flips** (folds 1
and 2): fold1 IS -0.120/OOS +0.096 (12/5); fold2 IS -0.144/OOS +0.062
(17/3); fold3 IS -0.117/OOS -0.255 (20/5).

## 3. Cross-cutting observations

**No combination is net profitable at the aggregate level — all 12
`aggregate_oos_return` values are negative.** Ranked smallest-to-
largest loss: `INFY/vwap_normal` (-0.020, the smallest loss overall) <
`INFY/vwap_wide` (-0.032) < `HDFCBANK/vwap_normal` (-0.033) <
`HDFCBANK/vwap_wide` (-0.039) < `RELIANCE/vwap_wide` (-0.065) <
`TCS/vwap_wide` (-0.078) < `HDFCBANK/vwap_tight` (-0.099) <
`INFY/vwap_tight` (-0.114) < `RELIANCE/vwap_normal` (-0.125) <
`TCS/vwap_normal` (-0.131) < `RELIANCE/vwap_tight` (-0.186) <
`TCS/vwap_tight` (-0.379, the worst).

**A consistent, dataset-specific pattern, flagged honestly rather than
read as strategy skill**: fold 2's out-of-sample window
(`2026-09-01`–`09-03`, a short 3-day window) flips POSITIVE in **11 of
the 12 combinations** — every single one except `RELIANCE/vwap_tight`.
This is far too consistent across every symbol and every preset to be
a strategy-specific effect — it almost certainly reflects a genuinely
favorable short-term price-reversion character of that particular
3-day real market window (a market-regime observation), not something
any of these 12 configurations "learned" to exploit. Reported plainly
rather than credited to the strategy.

**Preset ordering, mostly consistent**: within every symbol,
`vwap_wide` (or `vwap_normal` for INFY/HDFCBANK) loses LESS than
`vwap_tight` — fewer, larger-deviation entries produced smaller
aggregate losses in 4 of 4 symbols when comparing tight vs. wide
directly. This is directionally consistent with `CHECKPOINT-VWAP-B`'s
own first-look finding (default `N=1.5` was already not clearly
favorable) and suggests, tentatively, that even wider deviations might
help further — but this is exactly the kind of iterative parameter
conclusion the Gainz arc's own overfitting lesson warns against
drawing from a single 17-day sample; not acted on here.

## 4. Honest cross-strategy comparison

**Does the MFE-distribution advantage translate into a better
walk-forward result? No — not into net profitability, though the
losses are generally smaller than several other strategies' own worst
combinations.**

Comparing RELIANCE directly (`CHECKPOINT_70`'s own figures, same
family of gate-verified data):

| Strategy/preset | `aggregate_oos_return` |
|---|---|
| `atr_volatility_breakout`/`atr_aggresive` | **+0.0114** (the only positive result in this entire session) |
| `sma_trend_filter`/`sma_conservative` | -0.0519 |
| `vwap_wide` (this checkpoint) | -0.0646 |
| `gainz_balanced` | -0.1434 |
| `vwap_normal` (this checkpoint) | -0.1251 |
| `vwap_tight` (this checkpoint) | -0.1861 |
| `ema_crossover`/`ema_conservative` | -0.2904 |
| `gainz_aggressive` | -0.4152 |

**VWAP lands squarely in the middle of the pack** — every VWAP preset
beats `ema_crossover` and `gainz_aggressive`, but every VWAP preset
also underperforms `atr_volatility_breakout` (the session's one
genuinely positive real result) and `sma_trend_filter`. `vwap_wide`
comes close to `sma_trend_filter`'s figure but does not beat it.

**On INFY specifically**, `vwap_normal`'s -0.0197 is one of the
smallest losses observed anywhere in this session's cross-symbol work
(`CHECKPOINT_71`'s own legacy-strategy INFY figures were all
meaningfully more negative) — a genuinely encouraging single data
point, but one data point on 17 real days, not a pattern to act on.

**The honest answer to the MFE question directly**: `CHECKPOINT-VWAP-B`
found VWAP's trades reach ≥2.0x ATR favorably 42.6% of the time versus
Gainz's 17.6% — a real, measurable difference in how far price moves
favorably before a trade closes. **This did NOT translate into net
profitability anywhere** — all 12 combinations here are still
aggregate-negative, exactly the same "MFE reaching further does not
by itself create an edge" lesson `CHECKPOINT_75` already established
for Gainz. What it DID plausibly contribute to is VWAP's generally
SMALLER losses relative to `ema_crossover` and `gainz_aggressive` (both
of which never showed VWAP's kind of favorable-excursion frequency) —
a real but modest difference, not a validated edge.

## 5. What this does and does not prove

**Does not prove**: `vwap_mean_reversion`, at any of its 3 presets, is
ready for real or paper trading, or should be preferred over any other
strategy tested this session. The dataset remains 17 real trading
days on 4 symbols — the same small-sample caveat every walk-forward
checkpoint this session has carried, restated here at full weight, not
softened because this is a "fresh" strategy without Gainz's own
tuning-overfitting history.

**Does prove**: the walk-forward tool runs cleanly for
`vwap_mean_reversion` against real, gate-verified data across all 3
presets and all 4 symbols, surfacing genuinely different (not
copy-pasted) results per combination — exactly what this checkpoint
was scoped to produce. Per every prior Phase D's own established
discipline, **no `RESEARCH_ACTIVE` or status change was made or
implied.**

## `MEMORY.md` update — confirmed made

`[F]` Appended (never rewrote) a new entry to `MEMORY.md` §3 recording:
the 17-day dataset confirmation, the "all 12 combinations
aggregate-negative" headline finding, the fold-2 market-regime
observation, the tight<wide loss-magnitude pattern, and the honest
cross-strategy comparison (VWAP lands mid-pack, beats `ema_crossover`/
`gainz_aggressive`, underperforms `atr_volatility_breakout`/
`sma_trend_filter`; the MFE advantage did not translate into
profitability). Matches the file's existing structure and tone.
**Confirmed explicitly here, as this checkpoint's own instruction
required.**

## Governance compliance

- P3: zero DB writes this checkpoint (read + compute only against
  already-backfilled, already gate-verified data;
  `BacktestResultRecord` unchanged, 208→208, confirmed directly).
- P9: no strategy code touched — `vwap_mean_reversion.py` was read but
  not modified; no other strategy file touched.
- `registry.py`: confirmed untouched.
- No `RESEARCH_ACTIVE` status change, no new backfill, no new presets,
  no parameter changes — all as instructed.
- P11/P16: this summary + `MEMORY.md` committed to `active-development`
  only.
