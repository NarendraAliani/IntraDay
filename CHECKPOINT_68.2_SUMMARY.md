# CHECKPOINT 68.2 — Build Walk-Forward Logic (synthetic-data-tested, no API/persistence)

```
checkpoint: 68.2
verdict: BUILT_AND_TESTED
engine_py_diff_empty: YES
insufficient_data_path_tested: YES
look_ahead_boundary_tested: YES
tests_added: 10
full_sweep_result: 1017/1021 (4 pre-existing failures, unrelated to this checkpoint - see §B4)
commit: d2eb318
blockers: []
```

---

## A. What was built

New file `src/intraday/research/backtesting/walk_forward.py` — a pure,
callable orchestration module, no I/O, no Django, no network:

1. **`WalkForwardFold`** dataclass — `in_sample_start`, `in_sample_end`,
   `out_of_sample_start`, `out_of_sample_end`, `in_sample_bar_count`,
   `out_of_sample_bar_count` — exactly the fields specified in 68.1 §C.
2. **`compute_walk_forward_folds(bars, *, min_oos_days, min_folds)`** —
   pure function deriving fold boundaries from real bar timestamps.
   Raises **`InsufficientDataForWalkForwardError`** (new, mirrors the
   naming convention of `engine.errors.InsufficientHistoricalDataError`
   — `Insufficient<Noun>Error(ValueError)`) when the data cannot support
   even one fold of the requested shape.
3. **`WalkForwardResult`** dataclass — `folds`, `in_sample_results`,
   `out_of_sample_results`, `aggregate_oos_return`,
   `aggregate_oos_win_rate`, `mean_degradation_ratio`,
   `data_sufficiency_note` — exactly the fields specified in 68.1 §C.
4. **`run_walk_forward_backtest(bars, strategy, strategy_config,
   backtest_config_template, compute_feature_series, *, data_quality,
   generated_at, cost_model=None, min_oos_days=5, min_folds=1)`** — calls
   `compute_walk_forward_folds()`, then calls the existing, unmodified
   `engine.run_backtest()` **twice per fold** (once on the in-sample bar
   slice, once on the out-of-sample bar slice), assembles aggregate
   metrics. `engine.py` is imported and called verbatim; it is never
   edited, wrapped, or monkeypatched — confirmed in §C below.

### Deliberate deviations from 68.1 §C's literal wording (documented, reasoned)

1. **"Days" = distinct calendar dates observed in the bar timestamps,
   not a fixed bar-count-per-day.** This project is intraday-only
   (`Timeframe` tops out at `DAY`; bars can be 1-minute) and 68.1 §B5
   itself instructs: "computes fold boundaries from the actual bar
   timestamps (not a hardcoded calendar assumption)." `min_oos_days`
   and the "day" concept throughout are implemented as
   `bar.timestamp.date()` (UTC, matching `Bar.timestamp`'s own
   UTC-close-time convention) — never an assumed bar-count or trading
   calendar. This is the literal, closest-fit implementation of §B5's
   own instruction, not a departure from it in spirit.
2. **Exactly `min_folds` folds are produced**, not the maximum the data
   could support. 68.1 §C names `min_folds` as a parameter but does not
   specify whether the function should produce the minimum requested
   count or opportunistically maximize fold count from available data.
   I chose "produce exactly the requested count, refuse if that count
   cannot be met" — the simpler, more conservative, and more
   predictable behavior (a caller who asks for `min_folds=1` gets one
   clearly-defined fold, not a surprise larger number), and matches
   §B3's explicit warning against manufacturing false precision from
   scarce data. Rejected the alternative (maximize folds) because it
   would silently change a caller's requested fold count without them
   asking for that behavior.
3. **`mean_degradation_ratio` excludes folds where in-sample
   `return_percent == 0`** (undefined ratio) rather than raising or
   fabricating `0`/`inf` — this mirrors the established convention
   already used elsewhere in this module for `BacktestMetrics.
   profit_factor` (`None` when the denominator is zero, never reported
   as infinity or 0). If **every** fold has a zero in-sample return, the
   field is `None`.

No other deviation from 68.1 §C's specified signatures, dataclass
fields, or control flow.

---

## B. Test results — 10 tests added in `tests/unit/research/test_walk_forward.py`

Bar fixtures reuse the exact construction pattern already established in
`tests/unit/research/test_backtesting_engine.py::_bars()` (same `Bar(...)`
call shape, same instrument/timeframe convention) — only the inter-bar
time delta is parameterized (`_daily_bars()`) so bars span multiple
distinct calendar days, which walk-forward's day-based fold boundaries
require. No second, independently-invented synthetic-bar helper was
created.

### 1. Fold-boundary correctness — `[F]` PASSED
- `test_folds_have_no_overlap_and_no_look_ahead` — for every fold,
  intersects the set of bar timestamps in its in-sample window with the
  set in its out-of-sample window and asserts the intersection is empty;
  also asserts `out_of_sample_start > in_sample_end` for every fold.
- `test_folds_are_anchored_expanding_in_sample` — asserts each
  subsequent fold's in-sample window starts at the same anchor and
  strictly grows (expanding), and includes the prior fold's
  out-of-sample dates, matching 68.1 §B1's recommended anchored/rolling
  design.

### 2. Insufficient-data refusal path — `[F]` PASSED
- `test_insufficient_data_raises_dedicated_error_not_a_tiny_fold` — 20
  bars spanning only 2 distinct days, requesting `min_oos_days=5,
  min_folds=1` (needs 6 days) → raises
  `InsufficientDataForWalkForwardError`, not a misleading tiny fold.
- `test_insufficient_data_error_is_not_the_engines_own_error_type` —
  confirms the raised exception is **not** an instance of
  `engine.errors.InsufficientHistoricalDataError` (a distinct type, per
  the naming-convention mirror, not a reuse).
- `test_zero_bars_raises_insufficient_data_for_walk_forward` — the
  degenerate zero-bar case.

### 3. End-to-end run — aggregate metrics from known per-fold inputs — `[F]` PASSED
- `test_end_to_end_walk_forward_aggregates_known_per_fold_results` —
  runs `run_walk_forward_backtest()` on 120 synthetic bars over 10 days
  (`min_oos_days=2, min_folds=2`), then **independently recomputes**
  `aggregate_oos_return`, `aggregate_oos_win_rate`, and
  `mean_degradation_ratio` directly from the SAME run's own
  `in_sample_results`/`out_of_sample_results` and asserts exact equality
  — proving the aggregation arithmetic, not just that the call
  completes.
- `test_data_sufficiency_note_flags_small_fold_counts` — confirms the
  mandatory data-sufficiency disclosure (68.1 §B3) is present and flags
  a small (<3) fold count explicitly, never presented with silent
  confidence.

### 4. `run_backtest()` is the real, unmodified function — `[F]` PASSED
- `test_run_backtest_used_by_walk_forward_is_the_real_unmodified_function`
  — asserts `walk_forward.run_backtest is engine.run_backtest` by
  identity (not merely equal behavior) — proves no wrapper/monkeypatch
  was substituted.
- `test_walk_forward_and_direct_engine_call_produce_identical_result_for_one_fold`
  — calls `engine.run_backtest()` **directly** on a fold's own
  in-sample bar slice/config, then asserts the `BacktestResult` produced
  by `run_walk_forward_backtest()` for that same fold's in-sample side is
  bit-identical (`backtest_id`, `trades`, `metrics` all equal) — proves
  the orchestration invokes the real engine with the real inputs, not a
  stand-in, and produces the exact same deterministic output.

Plus one dataclass-shape smoke test
(`test_walk_forward_fold_has_the_documented_fields`).

**All 10 new tests: PASSED.**

---

## C. `engine.py` is untouched — proof

```
$ git status --porcelain
?? RECON_BACKTEST_SUMMARY.md
?? src/intraday/research/backtesting/walk_forward.py
?? tests/unit/research/test_walk_forward.py

$ git diff --stat -- src/intraday/research/backtesting/engine.py
(no output - zero diff)

$ git status -- src/intraday/research/backtesting/engine.py
nothing to commit, working tree clean
```

`engine.py` does not appear in `git status` at all — it was never opened
for writing this checkpoint, only read (to confirm `run_backtest()`'s
real signature/return type before calling it). The only new files this
checkpoint adds are `walk_forward.py` and its test file; `git diff` on
`engine.py` is empty by direct command output, not merely a claim.

---

## D. Full sweep — `tests/unit/research/`

```
$ .venv/Scripts/python.exe -m pytest tests/unit/research/ -q
10 passed  (test_walk_forward.py, all new)
1017 passed, 4 failed  (full directory, 1021 collected)
```

The 4 failures are **pre-existing and unrelated to this checkpoint**:

- `test_checkpoint_64_52_database_first_backtest.py::test_f_partial_gap_fetches_only_the_missing_range`
- `test_checkpoint_64_52_database_first_backtest.py::test_g_data_completeness_is_enforced_not_row_existence`
- `test_checkpoint_64_48_gainz_adapter_design.py::test_k_no_gainz_reference_file_exists_in_repo`
- `test_checkpoint_64_49_gainz_feature_registry.py::test_zz_no_real_gainz_source_file_exists`

The first two are database-backed tests (one also logs a teardown error
— `database "test_intraday" is being accessed by other users`),
unrelated to `walk_forward.py`, which touches no database. The latter
two assert no "Gainz" string appears outside an allow-listed set of
files and are failing on `src/intraday/application/services/
backtesting.py` — a pre-existing file this checkpoint did not touch
(confirmed: it does not appear in `git status`). All four are
independently reproducible with **zero** relation to any file this
checkpoint added — `walk_forward.py` and `test_walk_forward.py` are the
only new files, and neither imports, is imported by, nor shares any
runtime path with `application/services/backtesting.py` or the DB-backed
test fixtures. **Zero regression attributable to this checkpoint.**

---

## Next steps — explicitly out of scope for this checkpoint

Per 68.1 §D and this checkpoint's own directive: **no API endpoint, no
persistence model, and no real-`HistoricalBar` test were built or
attempted here.** `run_walk_forward_backtest()` remains a plain,
script/test-callable Python function — nothing wires it to
`infrastructure/api/`, and no new Django model exists for a
`WalkForwardRunRecord` or equivalent. That wiring explicitly waits until
the checkpoint 67.x canonicalization migration is re-attempted and
actually produces a non-zero research-eligible row count (still zero
today, confirmed unchanged this checkpoint) — so the first real use of
this tool is against genuine data, not another fixture-only exercise.
