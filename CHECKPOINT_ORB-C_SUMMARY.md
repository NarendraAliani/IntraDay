# CHECKPOINT-ORB-C — Summary

Scope: Phase C of `ORB_STRATEGY_ROADMAP.md` — 3 config presets
(classic/tight/wide) for `orb_breakout`. `registry.py` untouched, no
live/scanner exposure. Zero strategy-code changes were needed —
confirmed (`git status --short` shows only this summary, `MEMORY.md`,
and the new test file; no `src/` diff at all).

## 1. The 3 presets — real DB rows, created via the real service path

Created via `StrategyConfigurationService.save_configuration()` (never
a raw ORM insert), following the suggested design as-is — no
better-motivated split was found:

| `configuration_version` | `opening_range_minutes` | `target_range_multiplier` | `stop_range_fraction` |
|---|---|---|---|
| `orb_classic` | 15 | 1.0 | 1.0 |
| `orb_tight` | 5 | 1.0 | 1.0 |
| `orb_wide` | 30 | 1.5 | 0.75 |

`minimum_range_atr_multiplier=0` (filter disabled) and
`atr_lookback=14` kept identical across all 3 — no reason found to
vary them: the filter question is orthogonal to the window/target/stop
design axis this checkpoint's own presets exist to explore, and
varying `atr_lookback` with the filter disabled would have no
observable effect at all (it isn't even read — `CHECKPOINT-ORB-B`'s
own conditional `required_features()` finding).

`[F]` Verified directly, not assumed: `StrategyConfigurationRecord`
count for `orb_breakout` went `0 → 3`, all 3 retrievable and distinct,
`orb_classic` uses the exact same values as `parameter_schema()`'s own
defaults — the intended default research profile.

## 2. Internal validity — verified directly against the real persisted rows

`CHECKPOINT-ORB-B`'s own module docstring claims a degenerate
stop-on-the-wrong-side-of-entry is structurally impossible by
construction. **Checked directly against each preset's REAL persisted
values anyway, not assumed from the design claim alone**: fed an
identical breakout scenario (range `[100, 110]`, entry `112`) through
each preset's real config —

```
orb_classic  ->  entry=112  target=122.0  stop=100.0   (stop < entry < target: True)
orb_tight    ->  entry=112  target=122.0  stop=100.0   (stop < entry < target: True)
orb_wide     ->  entry=112  target=127.0  stop=102.50  (stop < entry < target: True)
```

All 3 produce a genuine, internally consistent plan — confirmed for
every preset, not just the schema defaults.

## 3. Real behavioral divergence — the actual point of this checkpoint

`tests/unit/research/test_checkpoint_orb_c_presets.py` — 6 tests, all
passing on the first run. Follows `test_checkpoint_vwap_c_presets.py`'s
own structure: each preset's canonical values live in one shared
module-level function, used BOTH to persist a real DB row
(`test_1`/`test_2`) AND to construct an in-memory
`StrategyConfigurationValues` directly for the divergence proofs
(`test_3`–`test_6`, no database dependency).

**The actual proof — a genuinely stronger form of divergence than a
gating threshold, since it's about WHEN a signal becomes possible at
all, not just whether one fires** (`test_5`): the SAME 3-bar real bar
sequence fed through the real `compute_feature_series()` dispatcher —

- `orb_tight`'s 5-minute window (1 bar) is already CLOSED by the 2nd
  bar — a real `opening_range_high`/`opening_range_low` value exists,
  and a genuine `BULLISH` breakout signal fires at that same bar.
- `orb_classic`'s 15-minute window (3 bars) has produced **zero**
  output at all on this same 3-bar series — `CHECKPOINT-ORB-A`'s own
  warm-up rule means its first possible output is the 4th bar, which
  this fixture doesn't even reach yet. `orb_classic` genuinely has no
  opinion (`evaluate()` returns `None`) at the exact bar `orb_tight`
  already produced a real, actionable signal.

**A second, complementary proof** (`test_6`): on the IDENTICAL range
and entry price, `orb_wide`'s own `target_range_multiplier=1.5`/
`stop_range_fraction=0.75` produces a genuinely different target
(`127` vs. `orb_classic`'s `122`) and stop (`102.50` vs. `100`),
hand-computed and verified exactly — isolating the target/stop math
itself as the source of divergence, independent of the window-timing
difference `test_5` already covers.

## 4. Full suite

`.venv/Scripts/python.exe -m pytest -q --reuse-db`, run directly.

**Result: 5 failed, 3383 passed**, 650.05s — the SAME 5 pre-existing
failures documented at every checkpoint this session, none touching
this checkpoint's diff:

1. `test_checkpoint_64_52_database_first_backtest.py::test_f_partial_gap_fetches_only_the_missing_range`
2. `test_checkpoint_64_52_database_first_backtest.py::test_g_data_completeness_is_enforced_not_row_existence`
3. `test_api_boundaries.py::test_application_services_and_contracts_stay_infrastructure_free`
4. `test_checkpoint_64_48_gainz_adapter_design.py::test_k_no_gainz_reference_file_exists_in_repo`
5. `test_checkpoint_64_49_gainz_feature_registry.py::test_zz_no_real_gainz_source_file_exists`

**Zero new failures, zero genuine regressions** — consistent with this
checkpoint's zero-`src/`-diff scope.

## `MEMORY.md` update — confirmed made

`[F]` Appended (never rewrote) a new entry to `MEMORY.md` §3 recording:
the 3 real preset values, the internal-validity verification, and the
behavioral-divergence proof structure/results (including the
window-timing divergence, a genuinely different proof shape from the
threshold-gating divergence Gainz/VWAP's own presets demonstrated).
Matches the file's existing structure and tone. **Confirmed explicitly
here, as this checkpoint's own instruction required.**

## Governance compliance

- P3: the only DB writes this checkpoint were the 3 new, explicitly-
  authorized `StrategyConfigurationRecord` rows — no other table
  touched, no existing row mutated.
- P9: no strategy code touched — zero `src/` diff of any kind.
- `registry.py`: confirmed untouched.
- No `RESEARCH_ACTIVE` status change.
- P11/P16: this summary, `MEMORY.md`, and the new test file committed
  to `active-development` only. `ORB_STRATEGY_ROADMAP.md` remains
  uncommitted per its own established convention.
