# CHECKPOINT-ORB-A — Summary

Scope: Phase A of `ORB_STRATEGY_ROADMAP.md` — the opening-range
feature itself. No strategy logic, no `registry.py` change, per this
checkpoint's own scope. `gainz_compatible_research.py` (paused) and
`vwap_mean_reversion.py` (Phase D complete, also paused) untouched.

## 1. What was built

`src/intraday/signal_intelligence/feature_engine/opening_range.py` —
`compute_opening_range_high(definition, bars)` /
`compute_opening_range_low(definition, bars)`.

**Formula**: per trading day, `range_high = max(high)` /
`range_low = min(low)` across every bar whose timestamp falls within
`[market_open, market_open + opening_range_minutes]`. Once that
window closes, every subsequent bar in the same session emits the
SAME frozen pair — a single fixed fact about the day, not a moving
window.

**Representation, decided and documented per the roadmap's own
open question**: TWO parallel fields (`opening_range_high`,
`opening_range_low`), not one signed value like `rolling_breakout`'s.
Confirmed the reasoning directly: high and low are genuinely
independent numbers a strategy needs separately (testing `close >
high` and `close < low` are two different conditions, and `high -
low` is a real, separate derived quantity) — unlike `rolling_
breakout`'s breakout/breakdown, which are mutually exclusive by
construction. Followed `directional_movement.py`'s own precedent
instead (`+DI`/`-DI` as two independent compute functions sharing one
`Definition`), not `rolling_breakout.py`'s signed-value shape.

**The one genuinely new piece beyond `CHECKPOINT-VWAP-A`'s own
pattern, confirmed exactly as the roadmap anticipated**: VWAP's
`bar.timestamp.date()` grouping alone is not sufficient — ORB needs
each session's own `market_open` instant too, to know whether a bar
falls inside the opening window. Supplied by `domain.session.calendar.
build_session_for()` — an EXISTING function, not new resolver logic.
`as_of` is passed as the bar's own timestamp, per `historical_data_
coverage.py`'s own established comment ("session status classification
is irrelevant here; only the shape matters") — `market_open` itself
doesn't depend on which instant is passed as `as_of`.

**Warm-up**: no output for the window's own bars. `[F]` Confirmed
directly (per the roadmap's own §1.3 finding): the classic 15-minute
window on this project's `5m`/close-anchored grain covers exactly 3
bars (09:20/09:25/09:30 IST closes) — the first possible output is the
4th bar (09:35 IST). No output at all for a day whose supplied bars
never cover a complete window — never fabricated from a partial one.

**`field_id`s / parameter schema, for Phase B to reference precisely**:

- `OpeningRangeDefinition(opening_range_minutes: int = 15)` — a REAL
  tunable parameter (unlike `SessionVwapDefinition`'s zero fields),
  following `RollingBreakoutDefinition`'s dispatch shape instead.
- Two field_ids: `opening_range_high_{N}` / `opening_range_low_{N}`
  (e.g. `opening_range_high_15`), both sharing one
  `OpeningRangeDefinition(N)`.
- Registered in `field_registry.py` as two `_derived(...)` entries.
- Dispatched in `compute_feature_series()` via two branches:
  `if kind == "opening_range_high": return compute_opening_range_high(
  OpeningRangeDefinition(*params), bars)` (and the `_low` counterpart).

**Both registry AND dispatcher wiring done** — confirmed both required,
per `CHECKPOINT-GAINZ-A`'s own documented finding, cited again by
`CHECKPOINT-VWAP-A`, cited a third time here.

## 2. Testing

New file `tests/unit/signal_intelligence/feature_engine/
test_checkpoint_orb_a_opening_range.py` — **16 tests, all passing**:

- **A (hand-computed arithmetic)**: first 3 bars produce no output
  (`test_a1`); the 4th bar emits the correctly hand-computed frozen
  `(high, low)` (`test_a2`); the range stays frozen for every
  subsequent bar even against wildly different later highs/lows
  (`test_a3`).
- **B (session-reset)**: day 2 gets its own independent range, proven
  against a wildly different price level and shape (`test_b1`); a day
  whose bars never cover a complete window produces NO output at all,
  not a partial/fabricated one (`test_b2`).
- **C (market-open resolution — the one genuinely new piece)**: the
  window boundary is proven relative to the session's REAL resolved
  `market_open` (boundary-inclusive at exactly bar 3, first emission
  at bar 4 — `test_c1`); a non-default window duration (10 minutes)
  correctly moves the boundary to cover only 2 bars instead of 3,
  proving the boundary genuinely derives from `opening_range_minutes`
  against the real `market_open`, not a hardcoded "always 3 bars"
  assumption (`test_c2`).
- **D (no look-ahead)**: an already-emitted value is unaffected by a
  later, huge 5th bar.
- **E (mixed-instrument/timeframe guard)**: existing precedent, reused
  verbatim.
- **F (definition identity)**, **G (registry + dispatcher
  integration, including a non-default window duration dispatched
  through the real `compute_feature_series()` path)**.

## 3. Full suite

`.venv/Scripts/python.exe -m pytest -q --reuse-db`, full suite, run
directly.

**Result: 7 failed, 3354 passed**, 647.35s. Exact names:

1. `test_checkpoint_64_52_database_first_backtest.py::test_f_partial_gap_fetches_only_the_missing_range`
2. `test_checkpoint_64_52_database_first_backtest.py::test_g_data_completeness_is_enforced_not_row_existence`
3. `test_migration_67_11_6_backup_restore_rehearsal.py::test_canary_backup_restores_with_exact_field_preservation_in_disposable_db`
4. `test_migration_67_12_pre_integrity_hardening.py::test_h_live_backup_restored_three_way_equality`
5. `test_api_boundaries.py::test_application_services_and_contracts_stay_infrastructure_free`
6. `test_checkpoint_64_48_gainz_adapter_design.py::test_k_no_gainz_reference_file_exists_in_repo`
7. `test_checkpoint_64_49_gainz_feature_registry.py::test_zz_no_real_gainz_source_file_exists`

**5 are the same pre-existing failures documented at every checkpoint
this session.** The other 2 (#3, #4) are the same stale-disposable-
table-row flake first documented at `CHECKPOINT-GAINZ-C`'s §4/§5 —
re-ran both directly with `--create-db` (forces a clean test database)
and both **passed**. Neither migration test file, nor anything either
imports, appears anywhere in this checkpoint's diff. **Zero genuine
regressions.**

## 4. `MEMORY.md` update — confirmed made, including the missing recon entry

`[F]` Checked directly: `RECON-ORB-STRATEGY` had NOT updated
`MEMORY.md` (confirmed via direct grep — zero matches for "ORB"
before this checkpoint's own edit). **Backfilled that recon's own
entry now, alongside this checkpoint's**, both appended (never
rewrote) to `MEMORY.md` §3 — matching `CHECKPOINT-VWAP-A`'s own
precedent for backfilling its own recon's identical gap. **Confirmed
explicitly here.**

## Governance compliance

- P9: no strategy logic touched — `gainz_compatible_research.py` and
  `vwap_mean_reversion.py` confirmed untouched. This checkpoint's diff
  is entirely feature-engine/dispatcher/test files.
- `registry.py`: confirmed untouched — this checkpoint's scope
  explicitly excluded it.
- No `RESEARCH_ACTIVE` status change, no new backfill.
- P11/P16: this summary, `MEMORY.md`, the new feature module, the
  `definitions.py`/`field_registry.py`/dispatcher wiring, the new test
  file, and the 3 updated pre-existing test files are all committed to
  `active-development` only. `ORB_STRATEGY_ROADMAP.md` remains
  uncommitted per its own established convention.
