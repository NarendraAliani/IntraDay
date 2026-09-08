# CHECKPOINT 75 — Summary

Scope: Maximum Favorable Excursion (MFE) diagnostic — the final Gainz-
tuning-related checkpoint before pausing. Read-only/diagnostic only:
no parameter changes, no new preset rows, no strategy code changes, no
new backfill. Reused `CHECKPOINT_74`'s exact RELIANCE /
`gainz_balanced_t1_widened` trade set (68 trades) plus a fresh
`atr_volatility_breakout` comparison run, both against the same
gate-verified 16-day dataset.

```
gainz_mfe_>=1.5x_ATR (current T1): 42.6% (29/68)
gainz_mfe_>=2.0x_ATR (T2):         17.6% (12/68)
gainz_mfe_>=3.0x_ATR (T3):          1.5% (1/68)
atr_mfe_>=1.5x_ATR (its own T1):   50.0% (23/46)
atr_mfe_>=2.0x_ATR (T2):           34.8% (16/46)
atr_mfe_>=3.0x_ATR (T3):            4.3% (2/46)
losing_trades_with_notable_favorable_excursion: real, non-trivial
    (16.7% of Gainz losers, 25.0% of ATR losers reached >=1.0x ATR
    favorably before reversing into a loss)
verdict: raising T1 further has THIN, NOT clearly favorable room -
         the dominant constraint is entry-timing/holding-period, NOT
         target placement in isolation - REFINES (not overturns)
         CHECKPOINT_73/74's diagnosis
database_write_occurred: NO (BacktestResultRecord unchanged, 208->208)
parameter_changes_this_checkpoint: NONE
memory_md_updated: YES - confirmed below, includes explicit tuning-
                   pause decision
commit: (recorded below)
gainz_tuning_status: PAUSED - see final section for resumption
                     criterion
```

## 1. Method

`SimulatedTrade.mfe` (already computed by the existing, unmodified
backtest engine — "Maximum Favorable Excursion over the holding
period, in price terms from entry") was read directly for every trade
in `CHECKPOINT_74`'s own RELIANCE / `gainz_balanced_t1_widened` run (68
trades, re-run identically this checkpoint, same real costs, same
16-day gate-verified dataset), then divided by that trade's own
`atr_14` value at entry (computed independently via
`compute_feature_series("atr_14", bars)` — the SAME feature the
strategy's own `build_trade_plan()` uses to size SL/T1/T2/T3, read
here, never recomputed differently) to express MFE as a multiple of
ATR — the same units the SL/T1/T2/T3 parameters themselves use, making
the comparison direct and apples-to-apples. `[F]` All 68 trades had a
computable ATR value at entry (`missing_atr: 0`). Zero persistence:
`BacktestResultRecord` **208 before, 208 after**.

## 2. MFE distribution — RELIANCE / `gainz_balanced_t1_widened`

| MFE threshold | Trades reaching it | % of 68 |
|---|---|---|
| ≥ 1.0x ATR (original SL/T1 level, pre-`CHECKPOINT_74`) | 33 | 48.5% |
| ≥ 1.5x ATR (CURRENT T1, post-`CHECKPOINT_74`) | 29 | 42.6% |
| ≥ 2.0x ATR (T2) | 12 | 17.6% |
| ≥ 3.0x ATR (T3) | 1 | 1.5% |

**Directly answers the question `CHECKPOINT_73` raised but couldn't
answer without this data**: T2/T3 are not merely unreachable because
of the single-shot exit mechanism — **price itself genuinely rarely
travels that far** on this instrument/timeframe/dataset. Only 1 trade
out of 68 (1.5%) ever reached 3.0x ATR in the favorable direction at
all, regardless of what the exit rule would have done with that
movement. T2 (2.0x) is reached by a real but modest minority (17.6%).

## 3. Losing trades — did any show real favorable excursion first?

**Yes, a real and non-trivial fraction — this is a genuine finding,
not noise:**

| MFE threshold | Losing trades reaching it | % of 42 losers |
|---|---|---|
| ≥ 1.0x ATR | 7 | 16.7% |
| ≥ 1.5x ATR (current T1) | 3 | 7.1% |
| ≥ 2.0x ATR | 0 | 0.0% |

About 1 in 6 losing trades were genuinely "right" for a while (moved
at least a full ATR in the favorable direction) before reversing all
the way into a stop-out, and 3 of the 42 losers had ALREADY passed the
current T1 level before still ending up a net loss. Top examples
(entry timestamp, direction, MFE multiple, net P&L, exit reason):

```
2026-09-03 03:50 BULLISH mfe=1.97x net_pnl=-24.36  STOP_LOSS
2026-08-31 03:50 BEARISH mfe=1.94x net_pnl=-294.24 TARGET_1  <- see note below
2026-08-11 07:55 BULLISH mfe=1.90x net_pnl=-28.95  STOP_LOSS
2026-08-13 07:30 BULLISH mfe=1.20x net_pnl=-28.84  STOP_LOSS
2026-09-07 04:25 BEARISH mfe=1.13x net_pnl=-34.11  STOP_LOSS
```

**Honest, unresolved anomaly, flagged rather than explained away**:
the `2026-08-31` trade (`BEARISH`, `mfe=1.94x`, `reason=TARGET_1`,
large loss `-294.24`) looks internally inconsistent at a glance — a
bearish position's target should be BELOW entry, and this trade's exit
price is well ABOVE entry. This is the same trade `CHECKPOINT_73`'s
raw dump also showed (as the T1=1.0 version, `gross_pnl=-287.03`) and
was not investigated then either. It is the FIRST bar of the
`2026-08-31` block — immediately after the multi-day
`2026-08-28`→`2026-08-31` weekend/gap boundary — so a large real price
gap at that boundary is a plausible explanation, but this checkpoint
did not trace the exact mechanism in `tradeplan_execution.py` further
(that would mean reading deep into exit-simulation code to explain one
outlier trade, arguably crossing from "diagnostic read" into
"debugging," and is explicitly out of this checkpoint's read-only
scope). **Flagged honestly as an unresolved, single-trade anomaly
worth a dedicated future look — not asserted as explained, not
silently ignored either.**

**This DOES suggest a trailing-stop or partial-exit design might help
more than moving T1 alone** — `TradePlan.trailing_stop_loss` already
exists as a field (referenced in `simulate_tradeplan_exit()`, currently
unused by Gainz's own `build_trade_plan()` — confirmed by re-reading
`gainz_compatible_research.py`'s `build_trade_plan()` directly, it
never sets `trailing_stop_loss`). A meaningful minority of losses were
real, favorable trades that were never protected once they moved in
Gainz's favor — a candidate direction for a FUTURE checkpoint, not
this one.

## 4. Comparison — `atr_volatility_breakout` (already T1=1.5x by default)

Same method, same 16-day dataset, `atr_aggresive` preset, 46 trades:

| MFE threshold | Trades reaching it | % of 46 |
|---|---|---|
| ≥ 1.0x ATR | 25 | 54.3% |
| ≥ 1.5x ATR (its own T1) | 23 | 50.0% |
| ≥ 2.0x ATR (T2) | 16 | 34.8% |
| ≥ 3.0x ATR (T3) | 2 | 4.3% |

| MFE threshold | Losing trades reaching it | % of 28 losers |
|---|---|---|
| ≥ 1.0x ATR | 7 | 25.0% |
| ≥ 1.5x ATR | 5 | 17.9% |
| ≥ 2.0x ATR | 1 | 3.6% |

**`atr_volatility_breakout`'s entries travel further in the favorable
direction, at every threshold, than Gainz's do** — a real, measurable
difference in entry-signal character (consistent with its
volatility-breakout entry logic tending to catch stronger initial
moves than Gainz's multi-condition scoring entry), not merely a
coincidence of the same T1 level. Even so, T3 (3.0x) is reached by
only 4.3% of its trades — confirming the "price rarely travels 3x ATR
on this timeframe/instrument regardless of strategy" finding is not
Gainz-specific either.

## 5. Honest conclusion

**Raising `target_1_atr_multiplier` further (e.g. to `2.0`) does NOT
have clearly favorable room, based on this data — the dominant
constraint is entry-timing/holding-period behavior, not target
placement in isolation.** This REFINES, not overturns,
`CHECKPOINT_73`/`74`'s diagnosis: the single-shot exit mechanism IS
real and does structurally prevent T2/T3 from ever firing once T1 is
touched — but this checkpoint's direct MFE evidence shows that even
WITHOUT that mechanism, the vast majority of trades' actual price
movement never reaches 2.0x ATR (82.4% of Gainz trades, 65.2% of ATR
trades never do), and almost none ever reach 3.0x ATR (98.5%/95.7%
never do). The T2/T3 rungs are not merely blocked by exit-ordering
logic — **they are aimed at a price movement that, on this real
instrument/timeframe/dataset, this strategy's typical trade simply
does not produce.**

Concretely, raising T1 to `2.0` would only preserve the 12 trades
(17.6%) whose MFE already reaches that far as winners — it would
**convert the 17 trades (25%) currently between 1.5x and 2.0x MFE from
winners into probable losers or smaller wins**, since their best
excursion never reaches the new, higher bar. This is a real trade-off,
not a free improvement, and the data does not support it as an
obviously good next move — hence the decision below to stop tuning
this parameter further against this same dataset.

**Secondary, genuinely promising direction for a FUTURE checkpoint**
(not evaluated further here, no code touched): a meaningful minority
of losing trades (16.7% Gainz, 25.0% ATR) showed real favorable
excursion before reversing — a trailing-stop (the `TradePlan.
trailing_stop_loss` field already exists and is already read by
`simulate_tradeplan_exit()`, just never populated by Gainz's own
`build_trade_plan()`) could plausibly convert some of these into
smaller losses or breakeven exits, independent of where T1/T2/T3 sit.
This is a design idea for a future checkpoint to evaluate, not a
conclusion this diagnostic proves.

## `MEMORY.md` update — confirmed made

`[F]` Appended (never rewrote) a new entry to `MEMORY.md` §3 recording:
the MFE distribution findings (T2/T3 genuinely rarely reached
regardless of exit mechanism; raising T1 further has thin/unfavorable
room; the trailing-stop idea as a real but unevaluated future
direction; the unresolved single-trade anomaly), AND the explicit
"Gainz tuning is now PAUSED" decision with its concrete resumption
criterion, so a future checkpoint does not restart tuning prematurely
against the same small sample. Matches the file's existing structure
and tone. **Confirmed explicitly here, as this checkpoint's own
instruction required.**

## Governance compliance

- P3: zero DB writes — pure read/compute against already-computed
  trade data and the real, gate-verified `HistoricalBar` rows
  (`BacktestResultRecord` unchanged, 208→208, confirmed directly).
- P9: no strategy code touched. `git status --short` after this
  checkpoint's work shows no `src/` diff of any kind.
- No parameter changes, no new preset rows, no registry change, no
  `RESEARCH_ACTIVE` status change, no new backfill — all as instructed.
- P11/P16: this summary + `MEMORY.md` committed to `active-development`
  only.

---

## GAINZ TUNING: PAUSED

**Effective immediately, per this checkpoint's own explicit
instruction.** Reason, stated plainly for the record: three
consecutive checkpoints (`73`, `74`, `75`) have now tuned and/or
diagnosed Gainz's TradePlan parameters against the exact SAME 16–17
real trading day walk-forward dataset. Continuing to iterate a
parameter and re-test against that same sample is not genuine
out-of-sample validation — it is the textbook overfitting risk this
project's own `GAINZ_ROADMAP.md` Phase D was built to guard against.

**Resumption criterion**: do not resume Gainz parameter tuning (T1/T2/
T3/SL multipliers, thresholds, or any other `StrategyConfigurationRecord`
value) until the real, gate-verified dataset — now growing daily via
`CHECKPOINT_72`'s `backfill_daily_coverage` routine — reaches **at
least 30 real trading days** of genuinely NEW data beyond the
`16` days this checkpoint (and `70`/`71`/`73`/`74`) already used (i.e.
roughly double the current sample, giving room for a real held-out
test split rather than re-using the same fold windows yet again). As
of this checkpoint (`2026-09-08`), the real dataset stands at 17 days
(16 gate-verified + `2026-09-08`, added by `CHECKPOINT_74`'s Part 3) —
this is a concrete, checkable number a future checkpoint can verify
directly against `HistoricalBar` before deciding whether resuming is
appropriate.
