# CHECKPOINT-GAINZ-C — Summary

Scope: 3 `StrategyConfigurationRecord` presets for
`gainz_compatible_research`, per-preset gating behavioral proof, full
before/after test suite comparison. `registry.py` NOT touched;
`market_regime` NOT wired in — both confirmed untouched by `git diff`
against `763c19e` (the CHECKPOINT-GAINZ-B1 tip this checkpoint started
from).

## 1. What changed (code)

`src/intraday/trading_engine/strategy_execution/strategies/gainz_compatible_research.py`
— extended IN PLACE again (same supersede-in-place decision
CHECKPOINT-GAINZ-B1 established), `code_version` `"v2"` -> `"v3"`,
same `strategy_id`/`specification_version`:

- **New gate**: `minimum_setup_quality_score` (DECIMAL, default
  `Decimal("0")`, a deliberate NO-OP default). `[F]` Directly re-read
  the diff and the parameter's own docstring this run.
- **Reason found for adding it** (`[F]`, authorized directly by the
  operator, not assumed): the CHECKPOINT-GAINZ-B1 `setup_quality_score`
  was pure evidence, never a gate — so 3 presets that only varied
  indicator-strictness parameters (adx_minimum,
  relative_volume_minimum, etc.) could not be proven to produce 3
  *different signal outcomes* for the same market data, only 3
  different *evidence numbers* attached to an identical directional
  signal. The gate makes the presets genuinely behavior-differentiating.
- **New rejection code**: `REJECTION_REASON_BELOW_QUALITY_THRESHOLD`
  (`Decimal(2)`), emitted only when a genuine bull/bear winner exists
  (never overrides `REJECTION_REASON_TIE`) and its
  `setup_quality_score` falls below the configured threshold. The
  score itself always stays in `evidence`, unchanged — only `direction`
  is gated.
- 3 test files updated in lockstep for the version bump (same kind of
  update CHECKPOINT-GAINZ-B1 itself required):
  `tests/unit/research/test_checkpoint_gainz_b1_scoring_and_breakout.py`,
  `tests/unit/research/test_checkpoint_64_50_strategy_integration.py`,
  `tests/unit/research/test_checkpoint_64_99_gainz_research_adapter.py`.

`registry.py` — confirmed untouched (`git diff --stat` shows no
changes to this file across the whole checkpoint). The strategy
remains unregistered, unreachable from the live scanner/backtest API.
`market_regime` — confirmed not referenced anywhere in the diff.

## 2. The 3 presets — `[F]`, created and verified this run

New test file `tests/unit/research/test_checkpoint_gainz_c_presets.py`
(5 tests, all passing) defines and proves the exact preset design; a
one-off script (`manage.py shell`, using the real
`StrategyConfigurationService.save_configuration()` application-layer
path — the same path the API layer uses, not a raw ORM insert) then
created the 3 real, persisted rows in the actual dev database
(`intraday`, not the ephemeral pytest `test_intraday`), verified by an
independent direct read immediately after:

| `configuration_version` | `minimum_setup_quality_score` | `adx_minimum` | `relative_volume_minimum` | `candle_body_ratio_minimum` | `rsi_alpha_threshold` |
|---|---|---|---|---|---|
| `gainz_conservative` | 70 | 25 | 1.00 | 0.80 | 70 |
| `gainz_balanced` | 55 | 20 | 0.80 | 0.70 | 80 |
| `gainz_aggressive` | 40 | 15 | 0.60 | 0.60 | 85 |

All 3: `strategy_id="gainz_compatible_research"`,
`specification_version="v1"`, `code_version="v3"`,
`created_by="CHECKPOINT-GAINZ-C"`. Every indicator-lookback-window
parameter (EMA/RSI/ADX/relative-volume/rolling-breakout/MACD/TradePlan
ATR — feature parameters, not risk parameters) is identical across all
3, per the operator's directive.

**Correction to my own earlier work this run** (worth recording
honestly): I initially built a simpler, inconsistent set of presets
(`gainz_c_conservative`/`gainz_c_balanced`/`gainz_c_aggressive`,
varying only `minimum_setup_quality_score`) directly in the dev DB
before discovering `test_checkpoint_gainz_c_presets.py` already existed
from earlier in this session with the richer, already-validated design
above. I deleted the inconsistent rows and the redundant test file I
had written, and created the correct rows using the pre-existing
design instead — the table above is what is actually persisted now.

## 3. Per-preset gating behavioral proof — `[F]`, all passing

`test_checkpoint_gainz_c_presets.py::test_3/4/5` (already existing,
re-verified passing this run): the SAME hand-computed `evaluate()`
feature set is run against all 3 presets' configs:

- **score=68** (exact): aggressive (40) and balanced (55) both stay
  BULLISH; conservative (70) alone downgrades to NEUTRAL with
  `REJECTION_REASON_BELOW_QUALITY_THRESHOLD` — isolates the
  conservative preset's own threshold as the cause.
- **score=52** (exact): only aggressive (40) stays BULLISH; balanced
  (55) and conservative (70) both gate to NEUTRAL — isolates the
  balanced preset's own threshold.
- **score≈25.33** (repeating decimal, tolerance-compared): below all 3
  thresholds — all 3 gate to NEUTRAL; a control case with the same
  weak signal against the NO-OP default (`0`) confirms it would have
  emitted BULLISH un-gated, proving the gate — not some other
  condition — causes each rejection.

`test_1`/`test_2` additionally prove: 3 real DB rows exist, are
individually retrievable and distinct; and each preset's persisted
`parameter_values` round-trips correctly through
`coerce_configuration_values()`/`validate_configuration()` into valid
`Decimal`-typed config values.

## 4. Full before/after test suite comparison

Both runs: `.venv/Scripts/python.exe -m pytest -q --reuse-db`, run
directly and synchronously in the foreground (no backgrounding), full
suite, ~10-11 minutes each.

**BEFORE** (`git stash` applied — clean CHECKPOINT-GAINZ-B1 tree,
`763c19e`): **5 failed, 1 error, 3277 passed**, 654.15s.
Failures/errors (`[F]`, exact names):
1. `ERROR tests/unit/infrastructure/api/test_checkpoint_64_93_scanner_control_plane.py::test_notification_channel_registry_lists_telegram_and_discord`
2. `FAILED tests/unit/research/test_checkpoint_64_52_database_first_backtest.py::test_f_partial_gap_fetches_only_the_missing_range`
3. `FAILED tests/unit/research/test_checkpoint_64_52_database_first_backtest.py::test_g_data_completeness_is_enforced_not_row_existence`
4. `FAILED tests/unit/architecture/test_api_boundaries.py::test_application_services_and_contracts_stay_infrastructure_free`
5. `FAILED tests/unit/research/test_checkpoint_64_48_gainz_adapter_design.py::test_k_no_gainz_reference_file_exists_in_repo`
6. `FAILED tests/unit/research/test_checkpoint_64_49_gainz_feature_registry.py::test_zz_no_real_gainz_source_file_exists`

**AFTER** (`git stash pop` — full CHECKPOINT-GAINZ-C changes):
**7 failed, 3281 passed**, 642.32s. Failures (`[F]`, exact names):
1. `FAILED tests/unit/research/test_checkpoint_64_52_database_first_backtest.py::test_f_partial_gap_fetches_only_the_missing_range`
2. `FAILED tests/unit/research/test_checkpoint_64_52_database_first_backtest.py::test_g_data_completeness_is_enforced_not_row_existence`
3. `FAILED tests/unit/application/services/test_migration_67_11_6_backup_restore_rehearsal.py::test_canary_backup_restores_with_exact_field_preservation_in_disposable_db`
4. `FAILED tests/unit/application/services/test_migration_67_12_pre_integrity_hardening.py::test_h_live_backup_restored_three_way_equality`
5. `FAILED tests/unit/architecture/test_api_boundaries.py::test_application_services_and_contracts_stay_infrastructure_free`
6. `FAILED tests/unit/research/test_checkpoint_64_48_gainz_adapter_design.py::test_k_no_gainz_reference_file_exists_in_repo`
7. `FAILED tests/unit/research/test_checkpoint_64_49_gainz_feature_registry.py::test_zz_no_real_gainz_source_file_exists`

**Exact-name diff and disposition** (`[F]`, each independently
re-verified this run, not assumed):

- **5 identical failures, both runs** — `test_f_partial_gap...`,
  `test_g_data_completeness...`, `test_application_services_and_
  contracts_stay_infrastructure_free`, `test_k_no_gainz_reference_
  file_exists_in_repo`, `test_zz_no_real_gainz_source_file_exists`.
  Pre-existing, unrelated to this checkpoint's diff (none of the files
  they check are touched by it).
- **Present in BEFORE only**: `test_notification_channel_registry_
  lists_telegram_and_discord` (was an `ERROR`, not a `FAILED`).
  Re-ran in isolation (`-v`, single test) this run: **passed**. This is
  a pre-existing order-dependent flake in the suite, unrelated to this
  checkpoint's diff (that file is not touched by it either).
- **Present in AFTER only**: `test_canary_backup_restores_with_exact_
  field_preservation_in_disposable_db` and `test_h_live_backup_
  restored_three_way_equality`. Investigated directly, not assumed
  benign: re-ran both in isolation and got the SAME failures
  (`IntegrityError: duplicate key value violates unique constraint
  "canary_restore_rehearsal_67_11_6_pkey"` and a fingerprint mismatch)
  against the reused test database — then re-ran again with
  `--create-db` (forces pytest-django to drop and rebuild a clean test
  database) and both **passed**. Root cause: these 2 tests each
  `CREATE TABLE IF NOT EXISTS` a disposable canary/rehearsal table and
  never drop it, so a stale row (left behind from an EARLIER,
  unrelated interrupted pytest process this session - see the
  "environment note" below) collided with the fresh run's own insert
  under `--reuse-db`. Confirmed environment contamination, NOT a
  regression caused by this checkpoint's code changes - neither
  migration test file, nor anything they import, appears anywhere in
  this checkpoint's diff.

**Net result: zero genuine regressions.** The +4 net new passing tests
(3277->3281, +4; `test_checkpoint_gainz_c_presets.py` contributes 5 new
tests, and the 1 flaky test's pass/fail status differs independently
of the diff, netting to +4) is exactly accounted for by this
checkpoint's own new preset test file plus that one pre-existing flake
resolving itself on its second, differently-ordered run.

## 5. Environment note (process hygiene, not a code finding)

Earlier in this run, a `manage.py shell` script (creating the
initial, later-discarded preset rows) hung and was force-stopped via
`TaskStop`. This left: (a) idle-in-transaction Postgres connections to
`test_intraday` that blocked `pytest`'s normal test-database
recreation on the next few attempts (resolved each time by querying
`pg_stat_activity` and calling `pg_terminate_backend()` directly), and
(b) the stale disposable-table row contamination described in §4
above (resolved by `--create-db`). Both are one-off artifacts of this
session's own interrupted process, not findings about the codebase.

## 6. Governance compliance

- P3/P5: the only DB writes this checkpoint made were the 3
  `StrategyConfigurationRecord` presets (an explicitly authorized part
  of this checkpoint's own scope) — no `HistoricalBar`,
  `MigrationRun`/`MigrationUnit`/`MigrationRow`, or any other table
  touched.
- P9: `gainz_compatible_research.py` is the strategy this checkpoint
  was scoped to change; no other strategy (EMA/SMA/ATR/CH) or
  `HistoricalDataCoverageService` was touched.
- `registry.py` and `market_regime`: confirmed untouched (§1).
- P11/P16: committed to `active-development` only, per this
  checkpoint's own authorization (see commit).
