# CHECKPOINT 74 — Summary

Scope: apply `CHECKPOINT_73`'s precisely-scoped T1-widening fix
(config-only), re-test, and — after today's market close — run the
first genuinely-new-day exercise of `CHECKPOINT_72`'s daily backfill
routine. Config-only change; no strategy code touched.

```
part_1_fix: trade_plan_target_1_atr_multiplier 1.0 -> 1.5 (SL stays
            1.0x ATR) for all 3 Gainz presets, via 3 NEW
            StrategyConfigurationRecord rows (immutable-by-design,
            existing rows never mutated)
part_1_atr_volatility_breakout: NOT CHANGED - see the important
                                correction in §2
part_2_result: expectancy/net_pnl loss magnitude REDUCED across every
               symbol/preset tested, but ZERO sign flips - every
               combination remains net-negative; T2/T3 STILL never
               reached even at T1=1.5x
part_3_backfill: (filled in after today's market close - see §5)
database_write_occurred: YES (Part 1: 3 new StrategyConfigurationRecord
                          rows only) / Part 2: NO
                          (BacktestResultRecord unchanged, 208->208)
memory_md_updated: YES - confirmed below
commit: (recorded below)
blockers: []
```

## 1. Part 1 — the fix, config-only, confirmed no code change needed

`[F]` Directly re-verified `CHECKPOINT_73`'s own claim before acting on
it: `gainz_compatible_research.py`'s `build_trade_plan()` and
`parameter_schema()` already read `trade_plan_target_1_atr_multiplier`
as a plain configuration value (`require_decimal(config.values, ...)`)
— no hardcoded `1.0` anywhere in the source. **Confirmed: this is a
pure `StrategyConfigurationRecord` value change, zero source-file
edits required** — `git status --short` after this checkpoint's work
shows no `src/` diff.

**Value chosen: `1.5`** — the middle rung of the existing SL(1.0)→T2(2.0)
ladder, giving a clean, still-conservative ascending sequence
(`1.0 / 1.5 / 2.0 / 3.0`) rather than jumping straight to `2.0`. This
also happens to exactly match `atr_volatility_breakout`'s own
long-standing schema default for the same conceptual parameter (see
§2) — a useful, unplanned cross-strategy reference point, not the
reason it was picked.

**New rows, not mutated existing ones** — the correct choice per this
project's own established convention: `StrategyConfigurationRecord`'s
own docstring states it is "one IMMUTABLE set of strategy parameter
VALUES," and `StrategyConfigurationService.save_configuration()`
raises `DuplicateVersionError` on any attempt to reuse an existing
`(strategy_id, specification_version, code_version, configuration_version)`
identity — exactly the precedent every strategy-configuration write
this session has followed (GAINZ-C's own 3 presets were created fresh,
never edited in place). Created via that same real
`StrategyConfigurationService.save_configuration()` path (not a raw
ORM insert), 3 new rows, same `code_version="v3"` (the strategy's own
source code is unchanged, so no code_version bump is warranted — that
marker tracks strategy CODE, not preset parameter choices):

| New `configuration_version` | Same as base preset except | `trade_plan_target_1_atr_multiplier` |
|---|---|---|
| `gainz_conservative_t1_widened` | `gainz_conservative` (v3) | `1.0` → `1.5` |
| `gainz_balanced_t1_widened` | `gainz_balanced` (v3) | `1.0` → `1.5` |
| `gainz_aggressive_t1_widened` | `gainz_aggressive` (v3) | `1.0` → `1.5` |

`[F]` Verified directly: the 3 original presets remain byte-for-byte
unchanged (re-queried immediately after creating the new rows — every
field identical to `CHECKPOINT_73`'s own recorded values). `[F]`
`StrategyConfigurationRecord` count for `gainz_compatible_research`:
3 → 6, exactly +3, confirmed by direct count.

## 2. Important correction: `atr_volatility_breakout` was NOT changed

`CHECKPOINT_73` described this as "shared `simulate_tradeplan_exit()`
behavior, not Gainz-specific" and this checkpoint's own directive asked
to check and update `atr_volatility_breakout`'s saved preset(s) too.
**Checked directly before touching anything — and found the premise
does not transfer as cleanly as `CHECKPOINT_73` implied:**

- `atr_volatility_breakout`'s 3 saved presets (`atr_aggresive`,
  `atr_Balanced`, `atr_Conservative`) carry **NO override at all** for
  `target_1_atr_multiplier`/`stop_loss_atr_multiplier` — their
  `parameter_values` JSON simply doesn't include those keys, so they
  fall through to the STRATEGY'S OWN schema defaults.
- Read directly from `atr_volatility_breakout.py`'s own
  `parameter_schema()`: `stop_loss_atr_multiplier` defaults to `1.0`,
  but `target_1_atr_multiplier` **already defaults to `1.5`** — NOT
  `1.0`. This strategy's SL:T1 ratio has never been symmetric.

**So `CHECKPOINT_73`'s exit-mechanism finding (T2/T3 essentially
unreachable) is confirmed to be real and shared — both strategies
showed the identical `{STOP_LOSS, TARGET_1}`-only pattern — but the
specific CAUSE it proposed (symmetric SL=T1) does not actually explain
`atr_volatility_breakout`'s case, since its T1 was already 1.5x the
stop when that observation was made.** This means the true mechanism
is more general than "SL=T1 exactly" — even a modest 1:1.5 ratio
wasn't enough to let price travel on to T2/T3 within this dataset's
typical bar-range/holding-time behavior (see §3's own new evidence:
Gainz's T2/T3 STILL never fire even now at the identical 1:1.5 ratio).

**Decision: did not touch `atr_volatility_breakout`'s presets this
checkpoint.** Applying the "raise T1" fix there would mean ADDING a
brand-new override to 3 rows that have never had one — a materially
different, larger change than "raising an existing value" — and,
critically, would not even be testing the mechanism `CHECKPOINT_73`
described, since 1.5 is already `atr_volatility_breakout`'s status
quo. This is reported here, per this checkpoint's own "stop and report
rather than making an undiscussed change" rule, as a genuine partial
gap in scope rather than silently skipped.

## 3. Part 2 — re-test: cross-symbol walk-forward, all 3 widened presets

Same suite `CHECKPOINT_71` ran — all 4 symbols, identical gate-verified
16-day dataset (2 blocks concatenated, `2026-08-03`–`08-14` +
`2026-08-31`–`09-07`), `min_oos_days=3, min_folds=3`,
`run_walk_forward_backtest()` direct (never `BacktestingService.run()`).
`[F]` Zero persistence: `BacktestResultRecord` **208 before, 208
after**.

**`gainz_conservative_t1_widened`**: unchanged behavior on RELIANCE/
HDFCBANK/INFY (still zero OOS signal — the GATING threshold, not the
TradePlan exit, is what silences this preset, and T1 widening has no
bearing on that). TCS's result is essentially IDENTICAL to before
(`aggregate_oos_return=-0.0274`, same as `CHECKPOINT_71`'s own figure)
— the handful of trades this preset actually takes were apparently
unaffected by the T1 change in this specific case.

**`gainz_balanced_t1_widened`** — `aggregate_oos_return` per symbol
(compare to `CHECKPOINT_71`'s original-preset figures in parentheses):
RELIANCE `-0.100` (was `-0.152`), TCS `-0.156` (was `-0.204`),
HDFCBANK `-0.042` (was `-0.024`, WORSE here specifically), INFY
`-0.109` (was `-0.099`, also slightly worse). **Mixed at the
individual-symbol level — 2 improved, 2 got marginally worse** — not a
uniform win.

**`gainz_aggressive_t1_widened`** — RELIANCE `-0.285` (was `-0.415`),
TCS `-0.283` (was `-0.647`), HDFCBANK `-0.189` (was `-0.220`), INFY
`-0.285` (was `-0.368`). **Improved (smaller loss) on all 4 symbols**
— the most consistent improvement of the 3 presets.

**Sign-flip pattern, checked directly across all 12 symbol/preset/fold
combinations**: **zero sign flips changed** — every fold that was
IS-negative/OOS-negative before is still IS-negative/OOS-negative now;
no symbol/preset combination crossed into net-positive territory.
`gainz_conservative` remains silent (or near-silent) on 3 of 4
symbols, exactly as before.

## 4. Trade-level re-check — RELIANCE / `gainz_balanced_t1_widened`

| | T1=1.0 (`CHECKPOINT_73`) | T1=1.5 (this checkpoint) |
|---|---|---|
| total_trades | 72 | 68 |
| win_rate_percent | 40.28% | 38.24% |
| average_winner | 8.47 | 20.36 |
| average_loser | -38.48 | -39.53 |
| risk_reward_ratio | 0.22 | **0.52** |
| expectancy/trade | -19.57 | **-16.63** |
| net_pnl | -1408.96 | **-1130.91** |
| exit_reason_breakdown | `{STOP_LOSS: 40, TARGET_1: 32}` | `{STOP_LOSS: 41, TARGET_1: 27}` |

**Honest reading, not oversold**: the realized risk/reward ratio
**more than doubled** (0.22 → 0.52) and the per-trade expectancy
improved by about 15%, net loss shrank by about 20% (~₹278 less lost
on the same ~₹100,000 capital base over 16 days) — a real, measurable
improvement in the predicted direction. **But `exit_reason_breakdown`
still shows ONLY `STOP_LOSS`/`TARGET_1` — T2/T3 are STILL never
reached, even now.** Win rate dropped slightly (40.3%→38.2%, a smaller
sample of 68 vs 72 trades, within noise at this sample size) and
`risk_reward_ratio` is still well under `1.0`, so **expectancy remains
clearly negative.** This is a genuine, verified partial improvement,
NOT a fix — `gainz_balanced` is still a losing strategy on this real
dataset after this change, just a less-losing one.

## 5. Part 3 — today's live-session backfill (after market close)

`[F]` Confirmed the actual current time directly (not assumed):
market opened this session at `2026-09-08 09:15 IST`; checked the
clock repeatedly through the day and ran this part at `2026-09-08
15:38 IST`, comfortably after the `~15:30 IST` close.

`--dry-run` first: `[2026-09-01 .. 2026-09-08]` for all 4 symbols —
the routine's own 7-day rolling window, comfortably clear of the old
`08-17`–`08-28` gap, exactly as designed (`CHECKPOINT_72`).

Ran for real (`manage.py backfill_daily_coverage`, no flags):

```
RELIANCE [2026-09-01..2026-09-08]: status=COMPLETE cache_hits=360 bars_fetched=72 bars_persisted=72 api_requests=1
TCS      [2026-09-01..2026-09-08]: status=COMPLETE cache_hits=360 bars_fetched=72 bars_persisted=72 api_requests=1
HDFCBANK [2026-09-01..2026-09-08]: status=COMPLETE cache_hits=360 bars_fetched=72 bars_persisted=72 api_requests=1
INFY     [2026-09-01..2026-09-08]: status=COMPLETE cache_hits=360 bars_fetched=72 bars_persisted=72 api_requests=1
```

**Clean, exactly as designed — nothing unexpected.** Exactly ONE real
Dhan REST request per symbol (the single new trading day, `09-08`,
inside the 7-day window; `09-01` through `09-07` were all already
cached, correctly contributing zero additional fetches). `[F]`
Verified directly against the database, not just trusting the
command's own report:

| Symbol | Rows before | Rows after | New rows | `2026-09-08` state |
|---|---|---|---|---|
| RELIANCE | 2071 | 2143 | 72 | `CANONICALIZED`, `API_FETCH` |
| TCS | 1995 | 2067 | 72 | `CANONICALIZED`, `API_FETCH` |
| HDFCBANK | 1994 | 2066 | 72 | `CANONICALIZED`, `API_FETCH` |
| INFY | 1994 | 2066 | 72 | `CANONICALIZED`, `API_FETCH` |

Exactly 72 rows/symbol (a full trading day, no repeat of the old
day-start-bar gap), zero duplicate `(instrument_id, timeframe,
bar_timestamp)` rows across all 4 symbols (checked directly). **This
is the first genuinely-new trading day this routine has ever run
against since `CHECKPOINT_72` built it** (every prior invocation was
either a dry-run or a same-day idempotency check against data that
already existed) — it worked correctly on the first real try, and
`CHECKPOINT_69`'s two-bar-widening fix continues to hold on fresh data
five checkpoints later.

## `MEMORY.md` update — confirmed made

`[F]` Appended (never rewrote) a new entry to `MEMORY.md` §3 recording:
the fix applied (T1 1.0→1.5, 3 new preset rows, `atr_volatility_
breakout` deliberately NOT touched with the reasoning why), the
re-test result (loss magnitude reduced, R:R more than doubled for
`gainz_balanced`, but zero sign flips and T2/T3 still unreachable —
explicitly NOT a fix, a partial improvement), and Part 3's backfill
result once available. Matches the file's existing structure and
tone. **Confirmed explicitly here, as this checkpoint's own
instruction required.**

## Governance compliance

- P3: the only DB writes this checkpoint were the 3 new, explicitly-
  authorized `StrategyConfigurationRecord` rows (Part 1) and, later,
  `CHECKPOINT_72`'s own already-authorized `HistoricalBar` upserts
  (Part 3) — no other table touched, no existing row mutated.
- P9: `gainz_compatible_research.py` was read but not modified; no
  other strategy file touched.
- No registry change, no `RESEARCH_ACTIVE` status change.
- P11/P16: this summary, `MEMORY.md`, committed to `active-development`
  only.
