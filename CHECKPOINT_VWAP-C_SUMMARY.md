# CHECKPOINT-VWAP-C — Summary

Scope: Phase C of `VWAP_STRATEGY_ROADMAP.md` — 3 config presets
(tight/normal/wide) for `vwap_mean_reversion`. `registry.py`
untouched, no live/scanner exposure. Zero strategy-code changes were
needed — confirmed (`git status --short` shows only this summary,
`MEMORY.md`, and the new test file; no `src/` diff at all).

## 1. The 3 presets — real DB rows, created via the real service path

Created via `StrategyConfigurationService.save_configuration()` (never
a raw ORM insert — the same real, application-layer path
`CHECKPOINT-GAINZ-C`'s own presets used):

| `configuration_version` | N (`vwap_deviation_atr_multiplier`) | M (`stop_loss_atr_multiplier`) | `atr_lookback` | `target_reversion_fraction` |
|---|---|---|---|---|
| `vwap_tight` | 1.0 | 2.0 | 14 | 1.0 |
| `vwap_normal` | 1.5 | 2.5 | 14 | 1.0 |
| `vwap_wide` | 2.0 | 3.0 | 14 | 1.0 |

`atr_lookback`/`target_reversion_fraction` deliberately identical
across all 3 (feature-completeness/target-completeness parameters,
not deviation-band parameters) — no reason found to vary them, so they
weren't.

`[F]` Verified directly, not assumed: `StrategyConfigurationRecord`
count for `vwap_mean_reversion` went `0 → 3`, all 3 retrievable and
distinct, `vwap_normal` uses the exact same N/M values as
`parameter_schema()`'s own defaults (`1.5`/`2.5`, confirmed against
`CHECKPOINT-VWAP-B`'s own default table) — the intended default
research profile.

## 2. M > N runtime guard — verified directly per preset

`CHECKPOINT-VWAP-B` built an explicit runtime guard
(`build_trade_plan()` returns `None` when `stop_loss_atr_multiplier
<= vwap_deviation_atr_multiplier`). This checkpoint's own table
satisfies M > N by construction for all 3 presets, but this was
**verified directly, not assumed**: ran `evaluate()` +
`build_trade_plan()` for each preset's real persisted config against a
deviation far beyond any of their own N values (10× ATR, isolating the
test to the guard itself, not the deviation threshold) —

```
vwap_tight  N=1.0 M=2.0  ->  plan produced, target=1000.0 stop=880.0
vwap_normal N=1.5 M=2.5  ->  plan produced, target=1000.0 stop=875.0
vwap_wide   N=2.0 M=3.0  ->  plan produced, target=1000.0 stop=870.0
```

All 3 produce a genuine, non-`None` plan — the guard is satisfied for
every preset, confirmed directly against real persisted rows (not just
the values table).

## 3. Real behavioral divergence — the actual point of this checkpoint

`tests/unit/research/test_checkpoint_vwap_c_presets.py` — 8 tests, all
passing. Follows `test_checkpoint_gainz_c_presets.py`'s own structure:
each preset's canonical values live in one shared module-level
function, used BOTH to persist a real DB row (`test_1`/`test_2`, real
`@pytest.mark.django_db` tests) AND to construct an in-memory
`StrategyConfigurationValues` directly for the divergence proofs
(`test_5`–`test_8`, no database dependency — mirroring the Gainz
precedent's own `_config_from()` helper, which never assumes a preset
created by an earlier, separate process happens to survive into
pytest's own ephemeral test database).

**The actual proof, same hand-computed feature values fed to all 3
presets** (`vwap=1000, atr=10` throughout — only the entry price
changes):

- **Small deviation** (price=988, −1.2× ATR): **only `vwap_tight`
  signals** (BULLISH); `vwap_normal`/`vwap_wide` both stay NEUTRAL —
  isolates `vwap_tight`'s own, smaller N=1.0 threshold as the cause.
- **Medium deviation** (price=983, −1.7× ATR): **`vwap_tight` AND
  `vwap_normal` both signal**; `vwap_wide` alone stays NEUTRAL —
  isolates `vwap_wide`'s own N=2.0 threshold.
- **Large deviation** (price=975, −2.5× ATR, beyond even `vwap_wide`'s
  band): **all 3 presets agree** (BULLISH) — a control case proving
  the divergence above is genuinely caused by each preset's own
  threshold, not a broken or miswired preset.
- **Symmetric check on the BEARISH side** (price=1012, +1.2× ATR):
  same small-deviation-only-tight-signals pattern confirmed mirrored
  above VWAP, not just below it.

This is the exact same rigor `CHECKPOINT-GAINZ-C` established: 3
presets proven to change a signal's actual `direction`, not merely an
attached evidence number.

## 4. Full suite

`.venv/Scripts/python.exe -m pytest -q --reuse-db`, run directly.

**Result: 5 failed, 3337 passed**, 652.48s. Exact names — the SAME 5
pre-existing failures documented at every checkpoint this session,
none touching this checkpoint's diff:

1. `test_checkpoint_64_52_database_first_backtest.py::test_f_partial_gap_fetches_only_the_missing_range`
2. `test_checkpoint_64_52_database_first_backtest.py::test_g_data_completeness_is_enforced_not_row_existence`
3. `test_api_boundaries.py::test_application_services_and_contracts_stay_infrastructure_free`
4. `test_checkpoint_64_48_gainz_adapter_design.py::test_k_no_gainz_reference_file_exists_in_repo`
5. `test_checkpoint_64_49_gainz_feature_registry.py::test_zz_no_real_gainz_source_file_exists`

**Zero new failures, zero genuine regressions** — consistent with this
checkpoint's zero-`src/`-diff scope.

## `MEMORY.md` update — confirmed made

`[F]` Appended (never rewrote) a new entry to `MEMORY.md` §3 recording:
the 3 real preset values, the M > N guard verification, and the
behavioral-divergence proof structure/results. Matches the file's
existing structure and tone. **Confirmed explicitly here, as this
checkpoint's own instruction required.**

## Governance compliance

- P3: the only DB writes this checkpoint were the 3 new, explicitly-
  authorized `StrategyConfigurationRecord` rows — no other table
  touched, no existing row mutated.
- P9: no strategy code touched — zero `src/` diff of any kind.
- `registry.py`: confirmed untouched.
- No `RESEARCH_ACTIVE` status change.
- P11/P16: this summary, `MEMORY.md`, and the new test file committed
  to `active-development` only. `VWAP_STRATEGY_ROADMAP.md` remains
  uncommitted per its own established convention.
