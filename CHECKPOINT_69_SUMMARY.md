# CHECKPOINT 69 — Summary

Scope: apply `LIVE-4` Stream 2's confirmed `fromDate`-exclusive fix,
recover the known gap, and re-test the research gate. Market closed
throughout. No Gainz work, no migration execution.

```
part_1_fix_applied: YES (from_time widened by 2 bar-durations, was 1)
part_1_regression_test: PASS (day-start coverage returns to 72 rows via
                         HistoricalDataPreparationService, not bypass)
part_1_full_suite_regression: <FILLED IN BELOW - see §4>
part_2_gap_recovered: YES - 52 new rows (13 days x 4 symbols), 1/day,
                       zero duplicates, zero existing rows altered
part_3_gate_result: ACCEPTED (was REJECTED at LIVE-2) - all 3 strategies
                     produced real fold results through the real gate
database_write_occurred: YES (Part 2 backfill only, 52 rows,
                          HistoricalBar via the proven REST path) /
                          NO for Part 3 (BacktestResultRecord unchanged)
commit: (recorded below)
blockers: []
```

## Part 1 — The fix

`[F]` `_provider_request_envelope()`
(`historical_provider.py:261-323`): `from_time` now widened by **two**
bar-durations (`canonical_start - (one_bar * 2)`), not one. Exactly
what `LIVE-4` Stream 2 confirmed via its own controlled, zero-
persistence raw-client diagnostic: Dhan's `fromDate` comparison is
exclusive, so one bar of widening still lands `fromDate` exactly on
the *preceding* candle's own timestamp, which Dhan then also excludes
for the same reason — a second bar of widening moves `fromDate` one
candle further back, past the day-start candle's own predecessor, so
the day-start candle itself is finally included. `to_time` is
unchanged (66.8's own disproven-upper-widening finding still stands,
untouched by this checkpoint).

**Regression test** (new, `[F]` run and passing):
`tests/unit/infrastructure/market_data_providers/dhan/
test_historical_provider.py::
test_checkpoint_69_two_bar_widening_recovers_day_start_candle_via_preparation_service`
— builds a fake `fetch_intraday_candles()` that simulates Dhan's own
confirmed exclusive-boundary behavior (drops any candle whose raw
timestamp is `<= from_time`), runs the REAL, unmodified
`HistoricalDataPreparationService.prepare()` (not the raw client
bypass `LIVE-4` used for diagnosis), and asserts `bars_persisted == 72`
for RELIANCE/2026-08-04/5m, with the previously-missing day-start
canonical close (`03:50 UTC` / 09:20 IST) present, no duplication, and
exactly one `bulk_upsert()` call.

**Existing test updated in lockstep** (expected, documented
consequence, not a regression):
`test_fetch_widens_the_dhan_request_window_on_the_lower_boundary_only`
— its hardcoded assertion (`from_time == start - timedelta(minutes=5)`)
is Checkpoint 66.8's OLD one-bar constant; updated to `minutes=10`
(two bars for a 5m timeframe) to match the new envelope arithmetic,
with its docstring rewritten to explain why. Full file (34 tests)
re-run directly: **all pass**.

**Off-by-one on the last bar of the day, checked directly**: `to_time`
is untouched by this change (still the unwidened canonical `end`) —
`test_fetch_widens_the_dhan_request_window_on_the_lower_boundary_only`
still asserts `calls[0]["to_time"] == end` exactly, and
`test_raw_1510_ist_candle_canonicalizes_to_0920...`/`test_fetch_post_
filter_excludes_a_candle_past_the_canonical_end` (unmodified, both
still passing) prove the last-bar boundary is unaffected by this
lower-boundary-only fix.

## Part 2 — Gap recovery

`[F]` Credentials valid (`effective_credentials()` returned a real
`(client_id, access_token)` pair — checked directly before running).
Re-ran the exact 13 CANONICALIZED days already identified by
`68.4`/`LIVE-2` (RELIANCE/TCS/HDFCBANK/INFY,
`2026-08-03`–`2026-08-14` + `2026-08-31`–`2026-09-02`) through the
REAL, unmodified `HistoricalDataPreparationService.prepare()` path
(same wiring `tasks.py`'s `build_historical_backtest_orchestrator()`
uses — `DhanHistoricalBarProvider` + `DjangoHistoricalBarRepository`,
no bypass), requesting each day's canonical `[09:20 IST, 15:15 IST]`
window.

| Symbol | CANONICALIZED rows before | after | New rows |
|---|---|---|---|
| RELIANCE | 923 | 936 | 13 |
| TCS | 923 | 936 | 13 |
| HDFCBANK | 923 | 936 | 13 |
| INFY | 923 | 936 | 13 |

**52 total new rows** — exactly 1 per day per symbol, exactly the
previously-missing day-start bar, nothing more. `[F]` Verified
directly, not assumed:
- Every one of the 13 days, for all 4 symbols, is now **72 rows**
  (`all_days_now_72: True`, checked via `Count("id")` grouped by date).
- **Zero duplicate `(instrument_id, timeframe, bar_timestamp)` rows**
  across all 4 symbols (`dupe_check.count() == 0`) — the existing 71
  rows/day were not touched, only the missing one was added, exactly
  as `HistoricalBar`'s own upsert-by-identity uniqueness constraint
  guarantees.
- RELIANCE/2026-08-04's newly-recovered bar:
  `O=1315.0 H=1315.0 L=1306.0 C=1306.5 V=394116`,
  `canonicalization_state=CANONICALIZED`, `source=API_FETCH` — **byte-
  for-byte identical** to the exact candle `LIVE-4` Stream 2's raw-
  client diagnostic already found and reported (its own §"Two calls,
  direct comparison" item 2), confirming this is the SAME real Dhan
  data being persisted for real this time, not a different or
  synthesized value.

`[F]` P4 respected: no existing `HistoricalBar` row was mutated,
relabeled, or deleted — only new rows were inserted (upsert-by-
identity, and the duplicate check above independently confirms no
collision occurred).

## Part 3 — Research gate re-test

`[F]` Constructed `ResearchDataGateService` identically to
`backtesting_views.py`'s real production wiring
(`repository=DjangoHistoricalBarRepository()`,
`coverage_service=HistoricalDataCoverageService(...)`, default
migration-status resolver — no override), and called
`get_research_eligible_bars()` directly for RELIANCE's first
CANONICALIZED block, this time at the TRUE canonical boundary
(`2026-08-03T03:50Z`–`2026-08-14T09:45Z` — the actual `09:20 IST` day-
start close, not `LIVE-2`'s `03:55Z` workaround boundary that
deliberately excluded the known-missing bar).

**Result: the gate ACCEPTED — 720 bars (10 days x 72, exactly
complete), zero missing sub-ranges.** This is the first time this
session the real, unmodified gate has accepted a genuine multi-day
CANONICALIZED request. `LIVE-2`'s `INCOMPLETE_COVERAGE` rejection is
resolved by this checkpoint's Part 1/2 work, confirmed by directly
re-running the identical gate call that rejected it before.

All 3 strategies then ran real walk-forward folds through this
gate-accepted data, `run_walk_forward_backtest()` called directly
(never `BacktestingService.run()`), same saved configs as
`68.4`/`LIVE-2` (`ema_conservative`, `sma_conservative`,
`atr_aggresive`), `min_oos_days=3, min_folds=3`:

**`ema_crossover`** (`ema_conservative`) — 3 folds,
`aggregate_oos_return=-0.2803`, `aggregate_oos_win_rate=14.96`,
`mean_degradation_ratio=37.27`:

| Fold | IS window | IS return | OOS window | OOS return | IS win% | OOS win% |
|---|---|---|---|---|---|---|
| 1 | 08-03..08-03 | -0.163 | 08-04..08-06 | 0.049 | 0.0 | 26.67 |
| 2 | 08-03..08-06 | -0.005 | 08-07..08-11 | -0.510 | 18.18 | 8.70 |
| 3 | 08-03..08-11 | -0.524 | 08-12..08-14 | -0.379 | 14.58 | 9.52 |

**`sma_trend_filter`** (`sma_conservative`) — 3 folds,
`aggregate_oos_return=0.0296`, `aggregate_oos_win_rate=11.11`,
`mean_degradation_ratio=-0.073`:

| Fold | IS window | IS return | OOS window | OOS return | IS win% | OOS win% |
|---|---|---|---|---|---|---|
| 1 | 08-03..08-03 | 0 | 08-04..08-06 | 0.104 | 0.0 | 33.33 |
| 2 | 08-03..08-06 | 0.104 | 08-07..08-11 | -0.015 | 33.33 | 0.0 |
| 3 | 08-03..08-11 | 0.107 | 08-12..08-14 | 0 | 50.0 | 0.0 |

**`atr_volatility_breakout`** (`atr_aggresive`) — 3 folds,
`aggregate_oos_return=-0.0552`, `aggregate_oos_win_rate=50.00`,
`mean_degradation_ratio=0.810`:

| Fold | IS window | IS return | OOS window | OOS return | IS win% | OOS win% |
|---|---|---|---|---|---|---|
| 1 | 08-03..08-03 | -0.078 | 08-04..08-06 | -0.040 | 0.0 | 44.44 |
| 2 | 08-03..08-06 | -0.106 | 08-07..08-11 | -0.227 | 36.36 | 22.22 |
| 3 | 08-03..08-11 | -0.431 | 08-12..08-14 | 0.102 | 27.27 | 83.33 |

**Honest reading — this is a materially different, much smaller
dataset than `68.4`'s** (10 real, gate-verified trading days on one
CANONICALIZED block vs. `68.4`'s 25-day mixed/bypassed range), so the
two are not directly comparable numbers. `ema_crossover` degrades
sharply here (`mean_degradation_ratio=37.27`, driven by fold 1's
near-zero in-sample base flipping the ratio's magnitude — the same
"mean-of-ratios is fragile with 3 folds" caveat `68.4` itself already
flagged); `sma_trend_filter` shows a small net positive OOS return
driven almost entirely by fold 1; `atr_volatility_breakout` is
consistently negative IS with one large positive OOS outlier in fold
3. **None of this is a trading recommendation** — it is the first
real, gate-verified result this strategy family has ever produced, on
a still-small (10-day) dataset, and should be read as exactly that:
a first data point, not a conclusion.

`[F]` Zero persistence: `BacktestResultRecord.objects.count()`: **208
before, 208 after** — confirmed directly, `run_walk_forward_backtest()`
was the only backtest entry point called.

## Part 4 — Full suite regression check

`.venv/Scripts/python.exe -m pytest -q --reuse-db`, full suite, run
directly (backgrounded due to runtime — ~11 minutes — result awaited
before this section was written, not assumed).

**Result: 5 failed, 3284 passed**, 657.83s. `[F]` Exact failure names:

1. `test_checkpoint_64_52_database_first_backtest.py::test_f_partial_gap_fetches_only_the_missing_range`
2. `test_checkpoint_64_52_database_first_backtest.py::test_g_data_completeness_is_enforced_not_row_existence`
3. `test_api_boundaries.py::test_application_services_and_contracts_stay_infrastructure_free`
4. `test_checkpoint_64_48_gainz_adapter_design.py::test_k_no_gainz_reference_file_exists_in_repo`
5. `test_checkpoint_64_49_gainz_feature_registry.py::test_zz_no_real_gainz_source_file_exists`

**All 5 are the SAME 5 pre-existing failures already documented as
unrelated at `CHECKPOINT-GAINZ-C`** (that checkpoint's own BEFORE run
against a clean tree showed these identical 5, plus a since-resolved
flaky 6th). None of the files these 5 tests check
(`historical_data_preparation.py`'s partial-gap fetch logic, the
architecture boundary rule, and the two Gainz-reference-scan tests)
appear anywhere in this checkpoint's diff — confirmed directly via
`git status --short`/`git diff --stat`: this checkpoint touched
exactly 2 files,
`historical_provider.py` and its own test file. **Zero genuine
regressions from Checkpoint 69's fix.**

## Governance compliance

- P3: DB writes this checkpoint were limited to Part 2's 52
  `HistoricalBar` INSERTs (upsert-by-identity, real REST fetch, the
  same proven path `67.12.2-F`/`68.4` already used) — no other table
  touched.
- P4: confirmed — zero existing `HistoricalBar` rows mutated,
  relabeled, or deleted (duplicate check + before/after row counts
  both independently confirm this).
- P5: no migration execution.
- P6: real Dhan network calls in Part 2 only (the explicitly authorized
  backfill), matching the same REST path prior checkpoints used.
- P9: no strategy logic (EMA/SMA/ATR/CH/Gainz) touched — this
  checkpoint's only source change is `historical_provider.py`'s
  envelope arithmetic, outside strategy execution entirely. No Gainz
  work in this checkpoint, per its own rule.
- P11/P16: this summary + the code/test changes committed to
  `active-development` only.
