# CHECKPOINT-VWAP-A — Summary

Scope: Phase A of `VWAP_STRATEGY_ROADMAP.md` — the session-anchored
VWAP feature itself. No strategy logic, no `registry.py` change, per
this checkpoint's own scope. `gainz_compatible_research.py` and every
other strategy file untouched (paused per `CHECKPOINT_75`).

## 1. What was built

`src/intraday/signal_intelligence/feature_engine/vwap.py` —
`compute_session_vwap(definition: SessionVwapDefinition, bars: tuple[Bar, ...]) -> tuple[FeatureValue, ...]`.

**Formula** (standard, textbook VWAP — typical price, not close alone):

```
typical_price_t = (high_t + low_t + close_t) / 3
vwap_t = Σ(typical_price_i * volume_i) / Σ(volume_i)
         for i = (first bar of t's trading day) .. t
```

**Session-reset mechanism** (the genuinely new computation shape
`VWAP_STRATEGY_ROADMAP.md` §1.2 identified): iterates `bars` in
chronological order (`ensure_chronological()` — same guard every other
feature uses); whenever the current bar's `.timestamp.date()` differs
from the previous bar's, the running `Σ(price×volume)`/`Σ(volume)`
accumulators reset to zero BEFORE that bar is included. Reuses the
exact grouping key `research/backtesting/walk_forward.py` already
proved (`bar.timestamp.date()`, UTC) — no new, unproven idea. No IST
conversion, no separate session marker on `Bar` — confirmed sufficient
per the roadmap's own reasoning (NSE hours 09:15–15:30 IST = 03:45–
10:00 UTC never cross UTC midnight).

**Warm-up: NONE** — unlike every lookback-based feature in this
package (SMA/EMA/ATR/RSI/ADX/Relative-Volume/Rolling-Breakout), VWAP
produces a value from the very FIRST bar of each session (a one-bar
session already has a well-defined VWAP: that bar's own typical
price). The only skip case is a still-zero cumulative-volume
denominator (mathematically undefined) — skipped, never fabricated,
matching `candle_body_ratio.py`'s own "skip, don't fabricate" precedent
for its analogous zero-range-bar case.

**`field_id` / parameter schema, for Phase B to reference precisely**:

- `field_id`: always exactly `"vwap"` — **no numeric suffix**, unlike
  `sma_20`/`ema_9`/`rolling_breakout_20`. `SessionVwapDefinition` has
  **no constructor fields** — VWAP has no tunable lookback/multiplier,
  it is defined purely by the session-reset formula.
- `SessionVwapDefinition()` (no args) → `.feature_name == "vwap"`,
  `.feature_version == FEATURE_ENGINE_VERSION`.
- Registered in `field_registry.py` as a `_derived("vwap", "Session
  VWAP", ("high", "low", "close", "volume"), ...)` entry —
  `required_inputs` includes all 4 OHLCV fields VWAP actually reads.
- Dispatched in `compute_feature_series()` via `if kind == "vwap":
  return compute_session_vwap(SessionVwapDefinition(*params), bars)`
  — `parse_feature_name("vwap")` naturally yields `("vwap", ())`, so
  `SessionVwapDefinition(*())` == `SessionVwapDefinition()`, no special
  parsing branch needed.

**Both registry AND dispatcher wiring done** — confirmed both are
required, per `CHECKPOINT-GAINZ-A`'s own documented finding that a
registry entry alone is insufficient (the dispatcher is an explicit
if/elif chain).

## 2. Design decision: why a `SessionVwapDefinition` exists despite having no fields

Two precedents existed in this codebase: `RollingBreakoutDefinition`-style
(a dataclass carrying the tunable parameter, consumed via
`Definition(*params)` in the dispatcher) and `candle_body_ratio.py`-style
(no Definition object at all — a bare `..._FIELD_ID` module constant,
dispatched via an exact-match branch). VWAP has no tunable parameter,
so either shape was technically viable. **Chose the `Definition`-object
shape** (a `SessionVwapDefinition` with zero constructor fields) because
this checkpoint's own task explicitly specified
`compute_session_vwap(definition, bars)` — matching the parse-then-
construct-a-Definition-then-call-the-pure-function dispatch pattern
every OTHER derived feature in `field_registry.py` follows, keeping
`vwap` consistent with the majority shape rather than extending the
`candle_body_ratio`/`bullish_engulfing`/`bearish_engulfing` "exact
match, no Definition" minority pattern to a fourth case. Documented
explicitly in `SessionVwapDefinition`'s own docstring so a future
reader sees the reasoning, not just the choice.

## 3. Testing

New file `tests/unit/signal_intelligence/feature_engine/
test_checkpoint_vwap_a_session_vwap.py` — **16 tests, all passing**:

- **A (hand-computed arithmetic)**: single bar = its own typical price;
  2-bar and 3-bar running averages verified against manually computed
  fractions (e.g. `155000/1500`, `290000/3000`).
- **B (session-reset — the most important tests for this feature)**:
  two consecutive trading days in one `bars` tuple, day 2's first bar
  priced at a WILDLY different level (2000 vs ~100) — proven to equal
  EXACTLY its own typical price, not a blend with day 1's accumulators
  (`test_b1`). Three consecutive days, each an independent single-bar
  session, each producing exactly its own typical price
  (`test_b2`). Confirmed the boundary is detected purely from
  `.timestamp.date()` changing, not from any gap-size heuristic
  (`test_b3`).
- **C (no look-ahead)**: appending a huge later bar never changes an
  earlier bar's already-computed VWAP value.
- **D (zero-volume edge case)**: a zero-volume bar at session start is
  skipped, not a crash, not a fabricated value; the next real bar's
  VWAP is computed correctly from its own contribution alone.
- **E (mixed-instrument/timeframe guard)**: existing precedent,
  reused verbatim — both rejections raise the correct existing error
  types.
- **F (definition identity)**, **G (registry + dispatcher
  integration, including through the REAL `compute_feature_series()`
  path, not just the pure function directly)**.

**One test-writing correction made along the way, reported honestly**:
`test_g2` initially asserted `is_parameterized_feature("vwap") is
False`, assuming that function meant "takes a numeric parameter." Read
its actual implementation directly: it means "is this a
`DERIVED_FEATURE` (vs. raw OHLCV)" — `candle_body_ratio` (also
parameter-free) returns `True` from it too, confirmed directly. Fixed
the test to assert the correct, verified behavior rather than the
initial wrong assumption.

## 4. Full suite — 4 pre-existing tests needed a documented, expected update

Adding a new registered field is a KNOWN class of change that some
existing tests intentionally pin against (the same situation
`CHECKPOINT-GAINZ-A` and every `rolling_breakout` addition before it
went through) — the first full-suite run surfaced exactly this, and
each was fixed the same way the codebase's own established precedent
already does it (bump a hardcoded count/set, or remove a name from a
"still unimplemented" list once it's genuinely implemented):

1. `test_checkpoint_64_51_registry_regression.py::
   test_a_canonical_registry_field_count_is_the_current_15_not_the_stale_8`
   — pinned field count `25 → 26`, added `"vwap"` to the expected set
   (mirrors `rolling_breakout`'s own prior `24 → 25` update).
2. `test_checkpoint_64_51_registry_regression.py::
   test_b_every_registered_field_is_dispatchable_through_the_real_dispatcher`
   — added a `vwap` branch (`concrete = "vwap"`, no numeric suffix),
   mirroring the existing `candle_body_ratio` branch.
3. `test_strategy_execution.py::
   test_field_registry_every_field_has_a_real_dispatchable_implementation`
   — same kind of branch addition.
4. `test_strategy_execution.py::
   test_field_registry_never_lists_unimplemented_indicators` — removed
   `"vwap"` from the "still genuinely unimplemented" tuple, exactly
   mirroring how `rsi`/`macd` were removed from this same list at
   Checkpoint 64.49/64.51 once they were genuinely, correctly
   implemented.
5. `test_checkpoint_64_48_gainz_adapter_design.py::
   test_e_feature_registry_reuse_opportunities_identified` — added
   `"vwap"` to the real-registry-ids set this test compares against
   `GAINZ_FEATURE_MAPPING`; confirmed directly (grepped) that no
   "VWAP" entry exists in that Gainz-directive-derived table, so the
   mapping table itself needed no change — only the real-registry-ids
   set, exactly the same class of update `rolling_breakout`'s own
   addition required there.

**Before this checkpoint's fixes**: 10 failed, 3305 passed (5
genuinely new, all explained above; 5 the same pre-existing failures
every checkpoint this session has documented). **After the 5 fixes**:
re-ran all 4 affected files directly — 80 passed, 1 failed (the SAME
pre-existing `test_k_no_gainz_reference_file_exists_in_repo` failure,
unrelated to this checkpoint's diff).

**Full suite re-run at the end: 7 failed, 3308 passed**, 653.09s.
Exact names:

1. `test_checkpoint_64_52_database_first_backtest.py::test_f_partial_gap_fetches_only_the_missing_range`
2. `test_checkpoint_64_52_database_first_backtest.py::test_g_data_completeness_is_enforced_not_row_existence`
3. `test_migration_67_11_6_backup_restore_rehearsal.py::test_canary_backup_restores_with_exact_field_preservation_in_disposable_db`
4. `test_migration_67_12_pre_integrity_hardening.py::test_h_live_backup_restored_three_way_equality`
5. `test_api_boundaries.py::test_application_services_and_contracts_stay_infrastructure_free`
6. `test_checkpoint_64_48_gainz_adapter_design.py::test_k_no_gainz_reference_file_exists_in_repo`
7. `test_checkpoint_64_49_gainz_feature_registry.py::test_zz_no_real_gainz_source_file_exists`

**5 are the same pre-existing failures documented at every checkpoint
this session. The other 2 (#3, #4) are the same stale-disposable-
table-row flake first documented at `CHECKPOINT-GAINZ-C`'s §4/§5 and
seen again since** — investigated directly again here: re-ran both
with `--create-db` (forces a clean test database) and both **passed**.
Neither migration test file, nor anything either imports, appears
anywhere in this checkpoint's diff. **Zero genuine regressions.**

## 5. `MEMORY.md` update — confirmed made, including the missing recon entry

`[F]` Checked directly: `RECON-VWAP-STRATEGY` had NOT updated
`MEMORY.md` (confirmed via direct grep — zero matches for "VWAP"
before this checkpoint's own edit). **Backfilled that recon's own
entry now, alongside this checkpoint's**, both appended (never
rewrote) to `MEMORY.md` §3 — the VWAP design summary and Part 1
findings from the recon, and this checkpoint's feature build/test
results. Matches the file's existing structure and tone. **Confirmed
explicitly here.**

## Governance compliance

- P9: no strategy logic touched (`gainz_compatible_research.py` and
  every other strategy file confirmed untouched — this checkpoint's
  diff is entirely feature-engine/dispatcher/test files).
- `registry.py`: confirmed untouched — this checkpoint's scope
  explicitly excluded it.
- No `RESEARCH_ACTIVE` status change, no new backfill.
- P11/P16: this summary, `MEMORY.md`, the new feature module, the
  `definitions.py`/`field_registry.py`/dispatcher wiring, the new test
  file, and the 3 updated pre-existing test files are all committed to
  `active-development` only. `VWAP_STRATEGY_ROADMAP.md` remains
  uncommitted per its own established convention (matching
  `GAINZ_ROADMAP.md`'s precedent throughout this session).
