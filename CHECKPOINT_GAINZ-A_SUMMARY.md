# CHECKPOINT-GAINZ-A — Rolling N-Bar Breakout/Breakdown Feature

Closes BLOCKER A from `GAINZ_ROADMAP.md` ("20-bar breakout/breakdown -
no canonical rolling-high/low feature existed at Checkpoint 64.99").
Pure feature-engine addition. No strategy logic, no
`gainz_compatible_research.py`, no `registry.py` (strategy registry)
change.

## Field identity

- **`field_id`**: `rolling_breakout` (registered in `field_registry.py`
  as a `DERIVED_FEATURE`, `required_inputs=("high","low","close")`).
  Chosen by inspecting the existing convention: `field_registry.py`'s
  entries use the base, un-parameterized "kind" as the `field_id`
  (`"relative_volume"`, `"price_delta"`, `"market_regime"`), with the
  lookback baked into the concrete `feature_name` at construction time
  (`"relative_volume_20"`, `"market_regime_20_9_20"`) via
  `RollingBreakoutDefinition.feature_name` — never a separate
  "configured elsewhere" lookback. `parse_feature_name()`
  (`field_registry.py:453-473`, unmodified) already strips any trailing
  run of integer parameters, so `"rolling_breakout_20"` resolves to
  kind `"rolling_breakout"` with no changes needed to that parser.
- **Module/file name**: `rolling_breakout.py` — matches the directory's
  adjective+noun naming convention (`price_delta.py`, `market_regime.py`,
  `ma_divergence.py`), chosen over the bare `breakout.py` alternative to
  read unambiguously as "the rolling-window breakout feature" (there is
  no other `breakout` concept in the codebase to disambiguate from, but
  the more descriptive name matches sibling files' specificity, e.g.
  `candle_body_ratio.py` over `body.py`).

## Parameter schema

`RollingBreakoutDefinition` (`definitions.py`, appended after
`MarketRegimeDefinition`):

| field | type | default |
|---|---|---|
| `lookback` (N) | `int` | `20` |

- `feature_name` property: `f"rolling_breakout_{lookback}"`.
- Validated via the shared `_validate_lookback()` helper (positive int,
  not bool) — raises `InvalidLookbackError` otherwise, identical to
  every other lookback-based `Definition`.
- Default of 20 is baked directly into the dataclass field (like
  `MacdHistogramDefinition`'s 12/26/9 defaults), not left unset like
  `PriceDeltaDefinition` — because 20 is a genuinely conventional
  breakout-window size (classic Donchian-channel convention), not an
  unverified reference-artifact number. Documented in `definitions.py`
  as a "conventional default," never claimed to be a verified Gainz
  parameter.

## Formula and representation

```
prior_high_t = max(high[t-N..t-1])   (N bars strictly BEFORE t)
prior_low_t  = min(low[t-N..t-1])

rolling_breakout_N(t) =  1  if close_t > prior_high_t   (breakout)
                       = -1  if close_t < prior_low_t   (breakdown)
                       =  0  otherwise (in-range)
```

Signed single-field representation (`1`/`-1`/`0`), chosen following
`price_delta.py`'s established "smallest canonical representation"
precedent over a two-boolean-column shape — breakout/breakdown are
mutually exclusive by construction (`prior_high_t >= prior_low_t`
always), so no information is lost.

## Warm-up convention (matched to `relative_volume.py`)

Cited: `relative_volume.py:36-44` (module docstring) and
`compute_relative_volume` at `relative_volume.py:97-111`. Both features
use a fixed-size trailing `deque(maxlen=N)` that only sees bars
STRICTLY PRIOR to the current one, checked via `len(window) == lookback`
BEFORE the current bar is appended to the window. First possible output
is at `bars[lookback]` (0-indexed) — the first `lookback` bars produce
**no output at all**, never a fabricated `0`/breakout-false value. I
cross-checked this against a second feature (`atr.py`'s Wilder-seed
warm-up, `atr.py:71-85`) to confirm "no output before enough history"
is the platform-wide convention, not an artifact of one file — ATR uses
a different mechanism (a seed-then-recurrence, because it needs a seed
value rather than a rolling window) but the same underlying rule: no
value is ever produced before genuine history exists.

`rolling_breakout.py`'s own implementation
(`compute_rolling_breakout`) uses two parallel `deque(maxlen=lookback)`
windows (`high_window`, `low_window`), identical structure to
`relative_volume.py`'s single `window` deque.

## Files created / modified

New:
- `src/intraday/signal_intelligence/feature_engine/rolling_breakout.py`
- `tests/unit/signal_intelligence/feature_engine/test_checkpoint_gainz_a_rolling_breakout.py`

Modified (all additive — no existing feature computation touched):
- `src/intraday/signal_intelligence/feature_engine/definitions.py` —
  appended `RollingBreakoutDefinition` after `MarketRegimeDefinition`.
- `src/intraday/signal_intelligence/feature_engine/field_registry.py` —
  appended one `_derived("rolling_breakout", ...)` entry before the
  `market_regime` categorical entry.
- `src/intraday/application/services/strategy_execution.py` — added
  the `RollingBreakoutDefinition` import, the
  `compute_rolling_breakout` import, one `if kind == "rolling_breakout"`
  dispatch branch (mirrors every existing lookback-based branch
  exactly, e.g. `market_regime`'s `if kind == "market_regime":
  return compute_market_regime(MarketRegimeDefinition(*params), bars)`),
  and a docstring update listing the new field_id shape. **This branch
  was necessary** — `compute_feature_series()`'s dispatch is an
  explicit if/elif chain keyed by `kind` (`field_registry.py`'s
  `_FIELDS` entries only describe a field for selection/validation;
  they carry no compute-function reference), so registry wiring alone
  is NOT sufficient, confirmed by reading the dispatcher's actual logic
  (`strategy_execution.py:109-186`) before writing the branch.
- Three EXISTING test files updated as an expected, documented
  consequence of adding a 25th registered field (not a strategy-logic
  or dispatcher-behavior change): `test_checkpoint_64_51_registry_regression.py`
  (bumped its explicitly-pinned field count 24→25 and its literal
  field_id set — that test's own docstring says the count "is pinned
  so a future accidental field removal/addition is caught," i.e. this
  update is its designed self-maintenance, the same pattern 65.08 did
  for `market_regime`), `test_strategy_execution.py`
  (`test_field_registry_every_field_has_a_real_dispatchable_implementation`
  needed one new `elif` branch mapping `"rolling_breakout"` to a
  concrete `"rolling_breakout_20"` field_id, matching its existing
  per-field branches), and `test_checkpoint_64_48_gainz_adapter_design.py`
  (added `"rolling_breakout"` to its own real-registry-ids equality set;
  `GAINZ_FEATURE_MAPPING` itself is unchanged — no `"Breakout"` entry
  exists in it).

`git diff --stat` (verbatim):
```
 .../application/services/strategy_execution.py     | 11 ++++--
 .../feature_engine/definitions.py                  | 41 ++++++++++++++++++++++
 .../feature_engine/field_registry.py               | 22 ++++++++++++
 .../test_checkpoint_64_48_gainz_adapter_design.py  |  7 ++++
 .../test_checkpoint_64_51_registry_regression.py   | 20 ++++++-----
 .../unit/trading_engine/test_strategy_execution.py |  2 ++
 6 files changed, 93 insertions(+), 10 deletions(-)
```
(plus the 3 new untracked files: `rolling_breakout.py`, its test file,
and this summary — `GAINZ_ROADMAP.md` is pre-existing untracked content
from the prior recon checkpoint, not touched or committed by this one.)

`gainz_compatible_research.py` and `registry.py` (strategy registry):
confirmed untouched — neither appears in `git status --short` /
`git diff --stat` above.

## Test results

New tests: `test_checkpoint_gainz_a_rolling_breakout.py` — **25/25
passed** (breakout, breakdown, in-range/no-breakout, insufficient-warmup,
boundary-equality cases for both high and low, default-lookback,
no-lookahead, determinism, series-integrity, and registry/dispatcher
integration cases).

Full-suite comparison (this environment's Postgres test database showed
contention/flakiness under concurrent pytest invocations during this
checkpoint's own investigation — unrelated to this diff, see below):

- **Targeted, clean, serial run** (`tests/unit/signal_intelligence
  tests/unit/trading_engine tests/unit/research tests/unit/application
  tests/unit/architecture`), AFTER this change: **1924 passed, 3
  failed, 54 errors**. All 54 errors are DB/credential-provisioning
  tests unrelated to the feature engine (Dhan credential flow, worker
  runtime status, live-data-integrity — none touch
  `field_registry`/`strategy_execution`/feature-engine code). All 3
  failures (`test_k_no_gainz_reference_file_exists_in_repo`,
  `test_zz_no_real_gainz_source_file_exists`,
  `test_application_services_and_contracts_stay_infrastructure_free`)
  were independently reproduced with this checkpoint's changes
  `git stash`ed (i.e. against a clean baseline) — **confirmed
  pre-existing, not caused by this diff**.
- **Baseline check specifically for the registry/dispatcher tests this
  change could plausibly break** (`test_checkpoint_64_51_registry_regression.py`,
  `test_strategy_execution.py`): with changes stashed, **54 passed, 0
  failed**. With changes applied and the 3 documented test-file updates
  above, the same scope now runs alongside
  `test_checkpoint_64_48_gainz_adapter_design.py`,
  `test_checkpoint_gainz_a_rolling_breakout.py`: **89 passed, 1 failed**
  (the 1 failure is the pre-existing, unrelated `test_k_no_gainz_reference_file_exists_in_repo`).
- The registry-count test
  (`test_a_canonical_registry_field_count_is_the_current_15_not_the_stale_8`)
  and the two "every field has a real dispatchable implementation"
  tests (`test_b_every_registered_field_is_dispatchable_through_the_real_dispatcher`,
  `test_field_registry_every_field_has_a_real_dispatchable_implementation`)
  — the three tests genuinely sensitive to adding a 25th field — all
  **pass** after the documented, minimal, expected updates described
  above.
- A full unrestricted `pytest tests/` run was attempted twice earlier in
  this checkpoint; both showed elevated DB-related error counts
  (18-137) that did NOT reproduce consistently between runs and did NOT
  reproduce with changes stashed either — traced to multiple concurrent
  pytest/Postgres test-DB processes accumulating in this Windows
  environment during this checkpoint's own iterative testing (confirmed
  via `tasklist`: 7 stray `python.exe` processes found). Environmental
  test-database contention, not a code regression from this diff.
- **A subsequent single, clean, full `pytest -q` run (whole `tests/`
  tree, this checkpoint's changes applied) completed successfully**:
  **3242 passed, 16 failed, 14 errors, 2 warnings, in 1087.06s
  (0:18:07)**. All 16 failures and all 14 errors are in files this
  diff never touches (`test_active_loop_end_to_end.py`,
  `test_checkpoint_64_81_correlation_traceability.py`,
  `test_checkpoint_64_55_live_market_data_validation.py`,
  `test_market_data_sync_api.py`, `test_reports_views.py`,
  `test_risk_api.py`, `test_checkpoint_64_52_database_first_backtest.py`,
  `test_migration_67_11_6_backup_restore_rehearsal.py`,
  `test_migration_67_12_pre_integrity_hardening.py`,
  `test_api_boundaries.py`, plus the two Gainz-honesty-guard tests
  below) — none reference `field_registry`, `definitions.py`,
  `strategy_execution.py`, or `rolling_breakout.py`. Two of the
  failures — `test_k_no_gainz_reference_file_exists_in_repo` and
  `test_zz_no_real_gainz_source_file_exists` — were independently
  re-confirmed pre-existing on this run too: both flag
  `src/intraday/application/services/backtesting.py` (an existing
  code comment mentioning a hypothetical "future Gainz backtest entry
  point," not this checkpoint's file) as an unlisted Gainz reference,
  and `git stash` + re-running just those two tests against the
  unmodified tree reproduces the identical two failures verbatim
  (confirmed this run, not merely asserted). This full-suite run is
  now the authoritative before/after comparison, superseding the
  targeted-scope numbers above as the primary evidence; the targeted
  numbers remain accurate and are kept for their finer-grained
  per-file breakdown.

## Scope confirmation

`git status --short` (verbatim, before this commit):
```
 M src/intraday/application/services/strategy_execution.py
 M src/intraday/signal_intelligence/feature_engine/definitions.py
 M src/intraday/signal_intelligence/feature_engine/field_registry.py
 M tests/unit/research/test_checkpoint_64_48_gainz_adapter_design.py
 M tests/unit/research/test_checkpoint_64_51_registry_regression.py
 M tests/unit/trading_engine/test_strategy_execution.py
?? GAINZ_ROADMAP.md
?? src/intraday/signal_intelligence/feature_engine/rolling_breakout.py
?? tests/unit/signal_intelligence/feature_engine/test_checkpoint_gainz_a_rolling_breakout.py
```

No `gainz_compatible_research.py`, no strategy `registry.py`, no
`HistoricalDataCoverageService`, no strategy-logic file of any kind
touched. `GAINZ_ROADMAP.md` is pre-existing untracked content from a
prior recon checkpoint (not authored or modified by this checkpoint)
and is left as-is per that checkpoint's own note not to commit it.
