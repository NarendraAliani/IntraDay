# CHECKPOINT 71 — Summary

Scope: cross-symbol walk-forward (TCS/HDFCBANK/INFY) using data
`CHECKPOINT_70` already backfilled and gate-verified, plus a read-only
recon into why `2026-08-17`–`08-28` is still `UNCANONICALIZED`. Market
closed. Zero code changes, zero persistence in Part 1, zero fix
attempted in Part 2, no `RESEARCH_ACTIVE`/status change for anything.

```
part_1_symbols: TCS, HDFCBANK, INFY (RELIANCE already covered by 70)
part_1_new_backfill: NONE - all 3 symbols already had both gate-
                     verified blocks (720 + 432 bars each) from
                     CHECKPOINT_70's own Part 1 backfill
part_1_runs: 18 (3 symbols x 6 strategy/preset combinations), 18/18
             produced real fold results
database_write_occurred: NO (BacktestResultRecord unchanged, 208->208)
part_2_finding: ALREADY-KNOWN migration gap, CONFIRMED not a new/
                different issue (see Part 2 below)
memory_md_updated: YES - confirmed below
commit: (recorded below)
blockers: []
```

## Part 1 — Cross-symbol walk-forward

Same `run_walk_forward_backtest()` direct-call discipline as
`CHECKPOINT_70`, `min_oos_days=3, min_folds=3`, same saved configs
(`ema_conservative`, `sma_conservative`, `atr_aggresive`, and all 3
Gainz presets via a local `StrategyRegistry()` — `registry.py`
confirmed untouched). Each symbol's data was already backfilled and
individually gate-accepted by `CHECKPOINT_70`'s own Part 1 (no new
fetch was needed or performed): Block A (`08-03`–`08-14`) 720/720
bars, Block B (`08-31`–`09-07`) 432/432 bars, re-confirmed by
`get_research_eligible_bars()` directly this run for all 3 symbols —
same acceptance, same counts.

### TCS

**`ema_crossover`** — `aggregate_oos_return=-0.3987`,
`mean_degradation_ratio=0.411`:

| Fold | IS window | IS return | OOS window | OOS return |
|---|---|---|---|---|
| 1 | 08-03..08-11 | -1.108 | 08-12..08-14 | -0.638 |
| 2 | 08-03..08-14 | -0.935 | 08-31..09-02 | -0.657 |
| 3 | 08-03..09-02 | -2.167 | 09-03..09-07 | 0.099 |

**`sma_trend_filter`** — `aggregate_oos_return=-0.2466`,
`mean_degradation_ratio=-0.902`:

| Fold | IS window | IS return | OOS window | OOS return |
|---|---|---|---|---|
| 1 | 08-03..08-11 | 0.152 | 08-12..08-14 | -0.112 |
| 2 | 08-03..08-14 | 0.633 | 08-31..09-02 | -0.385 |
| 3 | 08-03..09-02 | 0.178 | 09-03..09-07 | -0.244 |

**`atr_volatility_breakout`** — `aggregate_oos_return=-0.2522`,
`mean_degradation_ratio=-1.366`:

| Fold | IS window | IS return | OOS window | OOS return |
|---|---|---|---|---|
| 1 | 08-03..08-11 | 0.133 | 08-12..08-14 | -0.623 |
| 2 | 08-03..08-14 | -0.231 | 08-31..09-02 | -0.121 |
| 3 | 08-03..09-02 | -0.183 | 09-03..09-07 | -0.013 |

**`gainz_conservative`** — `aggregate_oos_return=-0.0274` — **NOT
zero-signal** (see Part 3, this diverges from every other symbol):

| Fold | IS window | IS return | OOS window | OOS return |
|---|---|---|---|---|
| 1 | 08-03..08-11 | -0.041 | 08-12..08-14 | -0.082 |
| 2 | 08-03..08-14 | -0.123 | 08-31..09-02 | 0 |
| 3 | 08-03..09-02 | -0.123 | 09-03..09-07 | 0 |

**`gainz_balanced`** — `aggregate_oos_return=-0.2044`,
`mean_degradation_ratio=0.391`:

| Fold | IS window | IS return | OOS window | OOS return |
|---|---|---|---|---|
| 1 | 08-03..08-11 | -0.432 | 08-12..08-14 | -0.429 |
| 2 | 08-03..08-14 | -1.042 | 08-31..09-02 | -0.075 |
| 3 | 08-03..09-02 | -1.029 | 09-03..09-07 | -0.109 |

**`gainz_aggressive`** — `aggregate_oos_return=-0.6475`,
`mean_degradation_ratio=0.263`:

| Fold | IS window | IS return | OOS window | OOS return |
|---|---|---|---|---|
| 1 | 08-03..08-11 | -1.863 | 08-12..08-14 | -0.776 |
| 2 | 08-03..08-14 | -2.844 | 08-31..09-02 | -0.749 |
| 3 | 08-03..09-02 | -3.776 | 09-03..09-07 | -0.417 |

### HDFCBANK

**`ema_crossover`** — `aggregate_oos_return=-0.1868`,
`mean_degradation_ratio=0.363`:

| Fold | IS window | IS return | OOS window | OOS return |
|---|---|---|---|---|
| 1 | 08-03..08-11 | -0.431 | 08-12..08-14 | -0.355 |
| 2 | 08-03..08-14 | -0.777 | 08-31..09-02 | -0.015 |
| 3 | 08-03..09-02 | -0.776 | 09-03..09-07 | -0.190 |

**`sma_trend_filter`** — `aggregate_oos_return=-0.0271`,
`mean_degradation_ratio=4.138` (near-zero IS bases in folds 1/3 make
this ratio unstable — see §note):

| Fold | IS window | IS return | OOS window | OOS return |
|---|---|---|---|---|
| 1 | 08-03..08-11 | 0 | 08-12..08-14 | -0.009 |
| 2 | 08-03..08-14 | -0.009 | 08-31..09-02 | -0.073 |
| 3 | 08-03..09-02 | -0.132 | 09-03..09-07 | 0 |

**`atr_volatility_breakout`** — `aggregate_oos_return=-0.0588`,
`mean_degradation_ratio=0.493`:

| Fold | IS window | IS return | OOS window | OOS return |
|---|---|---|---|---|
| 1 | 08-03..08-11 | -0.080 | 08-12..08-14 | -0.073 |
| 2 | 08-03..08-14 | -0.175 | 08-31..09-02 | 0.025 |
| 3 | 08-03..09-02 | -0.181 | 09-03..09-07 | -0.128 |

**`gainz_conservative`** — zero OOS signal, but note the small
non-zero IS-only figure (all 3 folds identical, `-0.0157`, all from the
same IS-only trade never repeated in any OOS window — still
functionally silent for any OOS-based conclusion, unlike TCS above
which had genuine OOS-relevant trading):

| Fold | IS window | IS return | OOS window | OOS return |
|---|---|---|---|---|
| 1 | 08-03..08-11 | -0.016 | 08-12..08-14 | 0 |
| 2 | 08-03..08-14 | -0.016 | 08-31..09-02 | 0 |
| 3 | 08-03..09-02 | -0.016 | 09-03..09-07 | 0 |

**`gainz_balanced`** — `aggregate_oos_return=-0.0240`,
`mean_degradation_ratio=0.137`:

| Fold | IS window | IS return | OOS window | OOS return |
|---|---|---|---|---|
| 1 | 08-03..08-11 | -0.168 | 08-12..08-14 | -0.044 |
| 2 | 08-03..08-14 | -0.227 | 08-31..09-02 | 0.033 |
| 3 | 08-03..09-02 | -0.206 | 09-03..09-07 | -0.061 |

**`gainz_aggressive`** — `aggregate_oos_return=-0.2200`,
`mean_degradation_ratio=0.311`:

| Fold | IS window | IS return | OOS window | OOS return |
|---|---|---|---|---|
| 1 | 08-03..08-11 | -0.520 | 08-12..08-14 | -0.237 |
| 2 | 08-03..08-14 | -0.814 | 08-31..09-02 | -0.302 |
| 3 | 08-03..09-02 | -1.127 | 09-03..09-07 | -0.122 |

### INFY

**`ema_crossover`** — `aggregate_oos_return=-0.2550`,
`mean_degradation_ratio=0.215`:

| Fold | IS window | IS return | OOS window | OOS return |
|---|---|---|---|---|
| 1 | 08-03..08-11 | -1.116 | 08-12..08-14 | -0.472 |
| 2 | 08-03..08-14 | -1.428 | 08-31..09-02 | -0.348 |
| 3 | 08-03..09-02 | -2.376 | 09-03..09-07 | 0.055 |

**`sma_trend_filter`** — `aggregate_oos_return=-0.0473`,
`mean_degradation_ratio=0.267`:

| Fold | IS window | IS return | OOS window | OOS return |
|---|---|---|---|---|
| 1 | 08-03..08-11 | -0.167 | 08-12..08-14 | -0.034 |
| 2 | 08-03..08-14 | -0.249 | 08-31..09-02 | -0.196 |
| 3 | 08-03..09-02 | -0.464 | 09-03..09-07 | 0.088 |

**`atr_volatility_breakout`** — `aggregate_oos_return=-0.0663`,
`mean_degradation_ratio=0.616`:

| Fold | IS window | IS return | OOS window | OOS return |
|---|---|---|---|---|
| 1 | 08-03..08-11 | -0.133 | 08-12..08-14 | -0.271 |
| 2 | 08-03..08-14 | -0.366 | 08-31..09-02 | 0.080 |
| 3 | 08-03..09-02 | -0.296 | 09-03..09-07 | -0.008 |

**`gainz_conservative`** — zero signal in every fold, IS and OOS both
exactly 0 throughout — matches RELIANCE and HDFCBANK.

**`gainz_balanced`** — `aggregate_oos_return=-0.0988`,
`mean_degradation_ratio=0.157`:

| Fold | IS window | IS return | OOS window | OOS return |
|---|---|---|---|---|
| 1 | 08-03..08-11 | -0.536 | 08-12..08-14 | -0.083 |
| 2 | 08-03..08-14 | -0.687 | 08-31..09-02 | -0.057 |
| 3 | 08-03..09-02 | -0.674 | 09-03..09-07 | -0.157 |

**`gainz_aggressive`** — `aggregate_oos_return=-0.3685`,
`mean_degradation_ratio=0.223`:

| Fold | IS window | IS return | OOS window | OOS return |
|---|---|---|---|---|
| 1 | 08-03..08-11 | -1.349 | 08-12..08-14 | -0.517 |
| 2 | 08-03..08-14 | -1.943 | 08-31..09-02 | -0.374 |
| 3 | 08-03..09-02 | -2.274 | 09-03..09-07 | -0.214 |

`[F]` Zero persistence across all 18 runs:
`BacktestResultRecord.objects.count()`: **208 before, 208 after**.

## Part 3 — Does `CHECKPOINT_70`'s RELIANCE picture hold across symbols?

**Question 1 — does `ema_crossover` stay consistently unprofitable
in-sample?** **YES, for ALL 4 symbols now** — every single in-sample
return, every fold, every symbol (RELIANCE from `70`; TCS, HDFCBANK,
INFY here) is negative. This is now a genuinely cross-symbol-confirmed
finding, not a RELIANCE artifact: `ema_conservative`, on this real
gate-verified data, has never once shown an in-sample profit across
4 symbols x 3 folds = 12 data points.

**Question 2 — does `gainz_conservative` stay zero-signal on other
symbols?** **NO — this is the one place the pattern did NOT fully
hold.** RELIANCE, HDFCBANK, and INFY all show genuinely zero OOS
signal (HDFCBANK has a tiny, OOS-irrelevant IS-only trade, functionally
still silent for any real conclusion). **TCS is different**: it
produced real, non-zero trades in 2 of 3 in-sample windows and one
non-zero OOS return (fold 1, `-0.082`) — the `minimum_setup_quality_score=70`
threshold was NOT prohibitively strict for TCS's specific real price
action over this period, even though it was for the other 3 symbols.
**This is an important, honestly-reported instrument-dependence
finding**: `gainz_conservative`'s "too strict to ever fire" read from
`CHECKPOINT-GAINZ-D`/`CHECKPOINT_70` was RELIANCE-specific (and,
coincidentally, also held for HDFCBANK/INFY) — it does not generalize
to "this preset never fires on real data," and should not be
represented that way going forward.

**Question 3 — does `atr_volatility_breakout`'s flip instability
repeat?** **YES, and the specific fold/direction pattern is different
every time — reinforcing that it's noise, not signal.** Sign-flip
count (IS profit -> OOS loss or vice versa) per symbol: RELIANCE
(`70`) — 2 flips (folds 1, 2, both positive OOS against negative IS).
TCS — 1 flip (fold 1, but in the OPPOSITE direction: positive IS,
negative OOS). HDFCBANK — 1 flip (fold 2, positive OOS again).
INFY — 1 flip (fold 2, positive OOS again). No two symbols flip in the
same fold with the same direction consistently; `mean_degradation_ratio`
swings from `0.003` (RELIANCE) to `-1.366` (TCS, actually negative —
the ratio's sign itself flipped) to `0.493`/`0.616` (HDFCBANK/INFY).
**Confirms the existing caveat rather than adding new confidence**:
this strategy's walk-forward aggregate number is not meaningful at
this fold count, on any symbol tested so far.

**Additional, unprompted-but-relevant observations**:
- **`sma_trend_filter`** flip counts also vary sharply by symbol: TCS
  flipped in **all 3 folds** (the worst of any strategy/symbol
  combination this session); HDFCBANK's folds are mostly near-zero/
  degenerate; RELIANCE and INFY each flip once. No stable cross-symbol
  story here either.
- **`gainz_balanced`/`gainz_aggressive`**: `gainz_aggressive` is now
  the single most cross-symbol-consistent result of this entire
  session — **zero sign flips, on every fold, on all 4 symbols** (12/12
  IS/OOS pairs same-signed, always negative). `gainz_balanced` is
  nearly as consistent — zero flips on RELIANCE/TCS/INFY, one small
  flip on HDFCBANK (fold 2, a near-zero `+0.033` OOS return against a
  `-0.227` IS return). Both presets are consistently unprofitable
  real-data findings across all 4 symbols tested — the closest thing
  to a validated (though still not "trustworthy" per the roadmap's own
  gate) directional read this session has produced.

**Honest bottom line**: this checkpoint strengthens two specific
findings to genuine cross-symbol status (`ema_crossover`'s in-sample
unprofitability; `gainz_aggressive`/`gainz_balanced`'s consistent,
non-flipping unprofitability) while explicitly WEAKENING a third
(`gainz_conservative`'s "zero signal" was not a universal property —
it's data/instrument-dependent, and TCS disproves the stronger claim).
`atr_volatility_breakout` and `sma_trend_filter` remain unstable and
symbol-dependent with no consistent story. **Still not enough for any
`RESEARCH_ACTIVE` or trading decision** — same single 16-day real
window, same small fold count, now just tested on 4 symbols instead of
1, which is more coverage but not more history.

## Part 2 — Recon: why `2026-08-17`–`08-28` is still `UNCANONICALIZED`

**Confirmed: this is the ALREADY-KNOWN migration gap (`67.7`–`67.13-C`),
not a new or different issue.** `[F]` Directly verified, not assumed:

- `HistoricalBar` query: all 700 rows in this range (RELIANCE, 5m) are
  `UNCANONICALIZED`, `source=API_FETCH`, `ingested_at` between
  `2026-08-30 10:09 UTC` and `2026-08-31 11:12 UTC`.
- **Decisive test**: called `DhanHistoricalBarProvider.
  canonicalization_state_for()` — the SAME, unmodified, pure function
  that determines write-time canonicalization state — directly, for
  this EXACT date range, RIGHT NOW, using today's current code (which
  includes `CHECKPOINT_69`'s fix, though that fix is unrelated to this
  particular function). Result: **`CANONICALIZED`**, for both the
  single-day (`2026-08-17`) and the full multi-day
  (`2026-08-17`–`2026-08-28`) window. `CAS_EFFECTIVE_DATE` is
  `2026-08-03` — this entire range is comfortably inside the proven
  `(NSE_EQ, FIVE_MINUTE, CAS_ERA)` scope, exactly like the two blocks
  either side of it that ARE correctly `CANONICALIZED`.

**Conclusion**: if these exact 700 rows were fetched today, through
today's code, they would be persisted `CANONICALIZED`. The fact that
the actually-persisted rows are `UNCANONICALIZED` means they were
written under an EARLIER processing state that did not yet correctly
stamp this scope as canonicalized at write time — exactly the class of
row the still-unexecuted migration (`67.7`–`67.13-C`) was purpose-built
to retroactively reclassify. **No new explanation was found; nothing
further was investigated beyond confirming this directly** (per this
checkpoint's own rule not to re-litigate the already-documented
migration-execution decision, which remains the operator's own
deferred choice). No fix was attempted — this was read-only recon
only, as instructed.

## `MEMORY.md` update — confirmed made

`[F]` Appended (never rewrote) a new entry to `MEMORY.md` §3 recording:
(1) the cross-symbol walk-forward finding — which `CHECKPOINT_70`
patterns generalized (`ema_crossover` in-sample unprofitability,
Gainz aggressive/balanced consistency) and which did not
(`gainz_conservative`'s zero-signal behavior is TCS-dependent, not
universal); (2) the interior-gap recon conclusion (already-known
migration gap, confirmed via `canonicalization_state_for()` called
directly against today's code, no new explanation). Matches the
file's existing structure and tone. **Confirmed explicitly here, as
this checkpoint's own instruction required.**

## Governance compliance

- P3: zero DB writes this checkpoint (Part 1 was read+compute only,
  using data already backfilled by `CHECKPOINT_70`; Part 2 was a pure
  read-only function call).
- P4: no `HistoricalBar` row touched at all.
- P5: no migration execution — Part 2 was recon only, and explicitly
  did not re-litigate the migration-execution decision.
- P9: no strategy logic touched — zero source-code changes this
  checkpoint (`git diff --stat` for any `src/` file is empty; only
  this summary and `MEMORY.md` changed).
- `registry.py`: confirmed untouched.
- P10: no scanner activation, no live-market interaction.
- P11/P16: this summary + `MEMORY.md` committed to `active-development`
  only.
