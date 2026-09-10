# CHECKPOINT-SCANNER-A — Pure Condition-Evaluation Logic (no UI, no persistence)

Scope: Phase A of `SCANNER_BUILDER_ROADMAP.md`. No UI, no new API
endpoint, no new persistence — pure logic and tests only.

```
relocation: compute_feature_series moved to
            signal_intelligence/feature_engine/dispatch.py (pure move,
            not a rewrite) — decided against the roadmap's own
            first-suggested application/services/feature_computation.py,
            documented why (see below)
new domain types: ScreeningCondition, RuleCombinator, ScreeningRule,
            ScreeningMatch (domain/screening/contracts.py) — never
            reuses Strategy's ParameterDefinition/signal types
new logic: evaluate_condition() (field-vs-constant, field-vs-field,
            + a categorical-constant fallback found necessary mid-
            checkpoint), AdhocScreeningService.screen()
            (application/services/adhoc_screening.py)
architecture boundary: mechanically proven
            (tests/unit/architecture/test_adhoc_screening_boundary.py,
            4 tests) — zero imports of Strategy/StrategyRegistry/
            StrategyExecutionCoordinator/PaperBroker/
            ScannerConfiguration anywhere in the new code
tests_new: 20 (16 adhoc_screening + 4 architecture-boundary)
relocation_proof: 49 + 1523 pre-existing tests pass unmodified
                   (strategy_execution/trading_engine/signal_intelligence/
                   research suites)
full_suite: 3412 passed / 7 failed — identical failure set to
            CHECKPOINT_90, +20 net passing tests, zero new failures
importlinter: confirmed unaffected (pre-existing "Application must not
            depend on infrastructure" violations, unrelated to this
            checkpoint, verified present on the baseline too)
commit: (recorded below)
```

## Part 0 — Pre-flight

`[F]` Confirmed via `ls`/`git status`: `CHECKPOINT_SCANNER-A_SUMMARY.md`
did not already exist. Git tree was clean apart from the deliberately-
uncommitted `SCANNER_BUILDER_ROADMAP.md` before this checkpoint's own
edits began.

## Step 1 — Mechanical relocation of `compute_feature_series`

`[F]` Read `compute_feature_series`'s own full body and every import it
actually used, directly — confirmed it depends on exactly two things:
`intraday.domain.feature.contracts`/`intraday.domain.market_data.contracts`
(domain) and `intraday.signal_intelligence.feature_engine.*` (its own
package siblings). **It never depended on
`intraday.trading_engine.strategy_execution`, `StrategyRegistry`, or
any other bounded-context type** — `strategy_execution.py`'s own prior
module comment already said this precisely, in different words
("composition is architecturally permitted [in application]" — true
for CROSS-bounded-context composition, but this function never
crosses one).

`[F]` **Chose `signal_intelligence/feature_engine/dispatch.py`
over the roadmap's own first-suggested
`application/services/feature_computation.py`, decided and documented
directly in both files' own headers**: `.importlinter` contract 3/4
only restrict cross-bounded-context composition; a dispatcher composed
entirely of `feature_engine`'s own compute functions needs no special
application-layer permission at all. `field_registry.py` (same
package) already houses `parse_feature_name()` — the exact parsing
algorithm this dispatcher's own multi-word-kind branch uses, for the
identical "LIFTED, not duplicated" reason. Placing the dispatcher here
too closes that same distance rather than widening it, and lets BOTH
`strategy_execution.py` (existing) and the new `adhoc_screening.py`
import it identically, with zero new exception and zero new
application-layer file needed just to hold a pass-through.

`[F]` **Pure move, verbatim body, every comment preserved** — confirmed
by diff: the new `dispatch.py` contains the exact same branches, in the
exact same order, with only the imports it actually needs (no
`domain.shared_kernel`/`DiagnosticStrategyExecutionService`/
`StrategyExecutionCoordinator` machinery, which never belonged to this
function). `strategy_execution.py` now imports `compute_feature_series`
from the new location; its own `build_coordinator()` (the actual
INJECTION point into `StrategyExecutionCoordinator`) is unchanged.

`[F]` **Zero other files needed touching, confirmed directly**: grepped
every real import of `compute_feature_series` across `src/` and
`tests/` (25 files) — every single one imports it via
`from intraday.application.services.strategy_execution import
compute_feature_series`, which still transparently re-exports the name
(Python resolves `from module import name` against whatever `name`
currently binds to in that module's namespace, regardless of where it
was originally defined). No caller needed a single line changed.

`[F]` **Byte-identical-behavior proof**: re-ran every existing test
file touching `compute_feature_series` unmodified —
`test_strategy_execution.py`/`test_strategy_extensibility.py`/
`test_strategy_execution_service.py`/
`test_strategy_execution_sample_bar_boundary.py` (**49 passed**), and
the full `signal_intelligence`/`research` suites (**1523 passed**, 4
failed — the same 4 pre-existing failures already in this session's
own baseline, none touching this relocation).

## Step 2 — New domain types (`domain/screening/contracts.py`)

`[F]` `ComparisonOperator` (`>`, `<`, `>=`, `<=`, `==`),
`ScreeningCondition(field_id, operator, comparison)`, `RuleCombinator`
(`AND`/`OR`), `ScreeningRule(conditions, combinator)`, `ScreeningMatch
(instrument_id, matched_condition_details)`. Deliberately NOT reusing
`Strategy`'s own `ParameterDefinition`/signal-decision types, per the
roadmap's own explicit instruction — no `parameter_id`, no schema
metadata, no `status`/`strategy_id`/`side`/`order_id`/`signal_id`
field anywhere (mechanically checked, see Step 4).

`[F]` **A real design gap found and fixed mid-checkpoint, not glossed
over**: the first draft of `comparison: Decimal | str` treated EVERY
`str` as a field-vs-field reference to resolve. This broke the
obviously-needed case of comparing a categorical field to a literal
constant (`market_regime == "BULL"` — `"BULL"` is not a registered
field_id). Fixed by resolving a `str` as a field reference ONLY when
it names a real, registered field_id
(`field_registry.resolve_feature_name(name).field_id is not None`);
otherwise it is taken as a literal categorical constant. Caught by the
new test suite itself (`test_categorical_field_with_non_equal_operator_raises`
initially failed with the wrong exception - "unrecognized computed
field_id 'BULL'" instead of the intended categorical-operator error),
not discovered later — documented in both the domain type's own
docstring and `evaluate_condition`'s own docstring, not silently
patched around.

## Step 3 — Pure evaluation function + orchestrator

`[F]` `evaluate_condition(field_id, operator, value, bars) -> bool`
(`application/services/adhoc_screening.py`), reusing the relocated
`compute_feature_series` directly:
- Raw OHLCV fields (`open`/`high`/`low`/`close`/`volume`) read straight
  off the last bar — matching `field_registry.py`'s own documented
  convention that these are "read straight off Bar, never computed."
- Derived fields dispatched through `compute_feature_series`, taking
  the LAST entry of the returned series as "the current reading" —
  several feature functions (RSI, EMA, MACD, ...) skip not-yet-warmed-
  up bars and return a series shorter than the input, so the last
  entry is deliberately the most recent COMPUTED value, not
  necessarily aligned to the very last bar's own timestamp.
- **Graceful missing-data handling** (a real Phase A testing
  requirement): an empty `bars` tuple, or an indicator whose warm-up
  requirement the supplied bars don't meet, resolves to `None` on
  either side and `evaluate_condition` returns `False` — "does not
  currently match," never an exception. Proven directly:
  `test_insufficient_warmup_data_returns_false_not_an_exception`
  (EMA(20) against only 3 bars) and
  `test_empty_bars_returns_false_not_an_exception`.
- **Type-mismatch handling, deliberately distinct from missing data**:
  comparing a categorical value with a non-`EQUAL` operator, or a
  categorical value against a numeric one, raises `ValueError` loudly
  — a condition-authoring mistake, never silently swallowed into a
  `False`. Proven directly:
  `test_categorical_field_with_non_equal_operator_raises`,
  `test_categorical_vs_numeric_type_mismatch_raises`.

`[F]` `AdhocScreeningService.screen(rule, instrument_ids, timeframe,
bars_by_instrument) -> tuple[ScreeningMatch, ...]` — combines
conditions via the rule's own `AND`/`OR` combinator, per instrument,
using bars supplied by the caller (never fetching them itself — Phase
B's own concern, per the roadmap). `timeframe` is accepted but not
consulted by this pure step, kept in the signature exactly as
specified so Phase B's real data-fetch wiring can be added behind the
same call shape without changing it again (documented directly in the
method's own docstring, not left unexplained).

## Step 4 — Architecture-boundary test

`[F]` `tests/unit/architecture/test_adhoc_screening_boundary.py` (4
tests), matching `test_api_boundaries.py`/
`test_strategy_execution_sample_bar_boundary.py`'s own established
ast-based static-import-scan style:
1. Both new files exist.
2. Neither imports anything from `trading_engine.strategy_execution`,
   `application.services.strategy_execution`,
   `application.services.paper_signal_execution`,
   `infrastructure.brokers.paper`, any `ScannerConfiguration`
   contract/repository, or `domain.signal`.
3. **Positive check**: `adhoc_screening.py`'s only compute dependency
   is the relocated `feature_engine.dispatch` — proving the relocation
   is actually being USED, not merely available (a caller could have
   imported the OLD `strategy_execution.compute_feature_series` path
   instead; this test confirms it did not).
4. **Positive check on the domain type itself**, not just imports:
   `ScreeningMatch` carries no `status`/`strategy_id`/`side`/`order_id`/
   `signal_id` field — mechanically confirmed, not merely asserted in
   a comment.

## Testing — full results

`[F]` `tests/unit/application/services/test_adhoc_screening.py`: **16
passed** — field-vs-constant (true/false/`==`/`>=`/`<=`, a real
indicator not just raw OHLCV), field-vs-field (`close` vs `ema_20`,
both directions), graceful warm-up/empty-bars handling, categorical
field equal/raise cases, `AdhocScreeningService` AND/OR combination
across multiple instruments, an instrument with no bars at all, and
domain-contract validation (`ScreeningCondition`/`ScreeningRule`
reject empty inputs).

`[F]` `tests/unit/architecture/test_adhoc_screening_boundary.py`: **4
passed**.

`[F]` Relocation's own byte-identical-behavior proof: **49 + 1523
pre-existing tests pass unmodified** (see Step 1).

`[F]` Broader sweep
(`tests/unit/application/services/`, `tests/unit/trading_engine/`,
`tests/unit/architecture/`): **551 passed, 3 failed** — the exact same
3 pre-existing failures already in this session's own baseline
(2 known `--reuse-db` flakes + `test_api_boundaries.py`'s own known
infrastructure-free failure, unrelated to this checkpoint).

`[F]` **Full test suite**: `.venv/Scripts/python.exe -m pytest -q
--reuse-db` — **3412 passed, 7 failed** (662.55s). Exact failure
names, identical to `CHECKPOINT_90`'s own list (same 5 pre-existing +
2 known `--reuse-db` flakes):

1. `test_checkpoint_64_52_database_first_backtest.py::test_f_partial_gap_fetches_only_the_missing_range`
2. `test_checkpoint_64_52_database_first_backtest.py::test_g_data_completeness_is_enforced_not_row_existence`
3. `test_migration_67_11_6_backup_restore_rehearsal.py::test_canary_backup_restores_with_exact_field_preservation_in_disposable_db`
4. `test_migration_67_12_pre_integrity_hardening.py::test_h_live_backup_restored_three_way_equality`
5. `test_api_boundaries.py::test_application_services_and_contracts_stay_infrastructure_free`
6. `test_checkpoint_64_48_gainz_adapter_design.py::test_k_no_gainz_reference_file_exists_in_repo`
7. `test_checkpoint_64_49_gainz_feature_registry.py::test_zz_no_real_gainz_source_file_exists`

Pass count is up by exactly **20** from `CHECKPOINT_90`'s own baseline
(3392 → 3412), matching the 16 + 4 new tests this checkpoint added.
**Zero new/unexplained failures, zero regressions.**

`[F]` **`.importlinter` contracts, checked directly**: `lint-imports`
run before and after this checkpoint's changes (`git stash`/`pop`) —
the ONE pre-existing "Application must not depend on infrastructure"
break (migration-related files: `migration_dry_run.py`,
`migration_execute.py`, `migration_research_gate_integration.py`,
`market_data_worker_supervisor.py` — none touched this checkpoint) is
**identical on both runs**, confirmed not introduced or worsened by
this checkpoint. None of the new files (`dispatch.py`,
`adhoc_screening.py`, `domain/screening/`) appear in any broken
contract, checked by direct grep of the `lint-imports` output.

## Governance compliance

- P3: zero DB writes — pure logic and tests only, exactly this
  checkpoint's own stated scope.
- P9: no strategy code touched — `strategy_execution.py`'s own logic
  is unchanged (only its import source for one function moved);
  `Strategy`/`StrategyRegistry`/`StrategyExecutionCoordinator`/
  `PaperBroker`/`ScannerConfiguration` are never imported by any new
  file, mechanically proven.
- P15: `domain/screening/` was created in the same step as the
  specific named files it holds (`__init__.py`, `contracts.py`) — no
  speculative directory creation.
- No UI change, no new API endpoint, no new persistence, per this
  checkpoint's own explicit rule.
- P11/P16: this summary, the relocation, the new domain/application/
  test files, and `MEMORY.md` committed to `active-development` only.

`CHECKPOINT_SCANNER-A_SUMMARY.md` — this file — committed alongside
the code and tests. `MEMORY.md` updated in the same commit (see
below). `SCANNER_BUILDER_ROADMAP.md` remains deliberately uncommitted,
per its own originating convention.
