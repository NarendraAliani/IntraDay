# CHECKPOINT-GAINZ-B1 — Extend Existing Gainz Strategy: New Scoring Formula + Breakout Condition (still unregistered)

Phase B, first contained sub-step, of `GAINZ_ROADMAP.md`. Extends
`src/intraday/trading_engine/strategy_execution/strategies/gainz_compatible_research.py`
(`GainzCompatibleResearchStrategy`) IN PLACE — same `strategy_id`
(`gainz_compatible_research`), same `specification_version` (`v1`),
`code_version` bumped `"v1"` → `"v2"` — rather than creating a second,
separate strategy identity. This decision was already made by the
directive; this checkpoint implements it, not re-decides it.

## 1. `code_version` bump and its precedent

- Bumped `CODE_VERSION = "v1"` → `CODE_VERSION = "v2"`
  (`gainz_compatible_research.py:~205`, next to the module-header
  comment documenting the bump).
- **Precedent search result (honest, not a fabricated citation)**: no
  strategy in this codebase has EVER bumped its own `code_version`
  before this checkpoint. Checked via `git log -p --follow` on all
  three registered strategy files
  (`ema_crossover.py`, `sma_trend_filter.py`,
  `atr_volatility_breakout.py`) plus a `grep -rn code_version` across
  `src/intraday/trading_engine/strategy_execution/strategies/*.py`:
  every one of the four strategy files (three registered +
  `test_momentum.py`) has carried a single, unchanged `CODE_VERSION =
  "v1"` string literal since its introduction — confirmed by `git log
  -p` showing exactly one commit ever touching that assignment line
  per file, always the introducing commit
  (`ema_crossover.py`: `01b0413`, Checkpoint 26;
  `sma_trend_filter.py`: same commit;
  `atr_volatility_breakout.py`: `01b0413`). So there is no prior
  LITERAL bump-formatting precedent to follow. What this checkpoint
  followed instead is the only convention that DOES exist in the code:
  the plain `"v{N}"` string shape already used for
  `SPECIFICATION_VERSION`/`code_version` everywhere in this module and
  `contracts.py`, incrementing `N` by 1 (`"v1"` → `"v2"`).

## 2. New scoring formula

Formula implemented exactly as specified:
```
dominant_score = max(bull_score, bear_score)
separation = abs(bull_score - bear_score) / max(bull_score + bear_score, 1) * 100
setup_quality_score = 0.72 * dominant_score + 0.28 * separation
```
Implementation location: `gainz_compatible_research.py`, inside
`evaluate()` (the block immediately after `bull_true_count`/
`bear_true_count` are computed, roughly lines 636-660 post-edit —
search for `_DOMINANT_WEIGHT` / `dominant_score = max(`). Decimal
arithmetic throughout: `_DOMINANT_WEIGHT = Decimal("0.72")`,
`_SEPARATION_WEIGHT = Decimal("0.28")`, `_HUNDRED = Decimal("100")`,
`_ONE = Decimal("1")` module-level constants, matching this project's
existing `require_decimal`/`coerce_configuration_values` Decimal-only
convention (`contracts.py`).

**`bull_score`/`bear_score` — exact definition (had to be specified,
not assumed)**: the PROPORTION (0–100, as a `Decimal`) of this
strategy's 9 directional conditions satisfied in that direction —
`bull_score = (# True in bull_conditions / 9) * 100`, symmetrically for
`bear_score`. E.g. 5 of 9 bullish conditions true → `bull_score =
5/9*100 ≈ 55.56`. Implemented at `gainz_compatible_research.py` in
`evaluate()`:
```python
bull_true_count = sum(1 for c in bull_conditions if c)
bear_true_count = sum(1 for c in bear_conditions if c)
bull_score = (Decimal(bull_true_count) / Decimal(_TOTAL_ALPHA_CONDITIONS)) * _HUNDRED
bear_score = (Decimal(bear_true_count) / Decimal(_TOTAL_ALPHA_CONDITIONS)) * _HUNDRED
```
(`_TOTAL_ALPHA_CONDITIONS = 9`).

**This is a REAL, DELIBERATE BEHAVIOR CHANGE, not a silent
reframing.** 64.99's original scheme: `setup_quality_score =
winning_side_condition_count / 8 * 100` — a flat linear count, and the
NEUTRAL/tie case always scored the *losing* side at 0 regardless of how
close the tie was. GAINZ-B1's scheme is a genuinely different function
of the same underlying counts: it always rewards the DOMINANT side's
raw proportion (72% weight) but *also* rewards how decisively it won
over the other side (28% weight on separation) — so the SAME
`bull_true_count`/`bear_true_count` pair now produces a numerically
different `setup_quality_score` than under 64.99's formula in every
case except the two trivial edges (0 true both sides, or 9 true one
side / 0 the other). Verified directly in
`tests/unit/research/test_checkpoint_gainz_b1_scoring_and_breakout.py`
(hand-computed arithmetic shown in test docstrings, e.g. `test_1`: 6/9
bull, 1/9 bear → old formula would have scored `6/8*100 = 75`; new
formula scores exactly `68`).

## 3. `rolling_breakout` wired in as a real condition (BLOCKER A closed for real)

- `required_features()` (`gainz_compatible_research.py`, in the
  `required_features` method): added
  `f"rolling_breakout_{rolling_breakout_lookback}"` to the returned
  tuple (new parameter `rolling_breakout_lookback`, default `20`,
  min `1`, max `400`, added to `parameter_schema()` just before
  `macd_fast`).
- `evaluate()`: `rolling_breakout` is fetched from `feature_values`
  alongside every other required feature, participates in the
  standard "any required feature is `None` → return `None`" warm-up
  guard (`assert rolling_breakout is not None`), and is added as the
  9th element of BOTH `bull_conditions` (`rolling_breakout.value ==
  1`) and `bear_conditions` (`rolling_breakout.value == -1`) —
  search for `rolling_breakout.value == 1` / `== -1` in the
  `bull_conditions`/`bear_conditions` tuples.
- It is ALSO appended to the `evidence` tuple (so it is real,
  inspectable `FeatureValue` evidence on every emitted signal, not
  just an internal boolean).

**Specific test proving it genuinely changes behavior**
(`tests/unit/research/test_checkpoint_gainz_b1_scoring_and_breakout.py`):
- `test_4_rolling_breakout_zero_leaves_the_old_condition_set_tied_neutral`:
  a feature configuration with exactly 3-of-8 non-breakout conditions
  true on BOTH sides, `rolling_breakout=0` → tie → **NEUTRAL**.
- `test_5_rolling_breakout_equals_1_flips_the_same_tie_to_bullish`:
  the IDENTICAL feature configuration, only `rolling_breakout=1` →
  bull_true becomes 4 vs bear_true 3 → **BULLISH**. Direct proof: a
  configuration that would NOT have produced a directional signal
  under the OLD (pre-B1, 8-condition) set now DOES, purely because of
  `rolling_breakout`.
- `test_5b_rolling_breakout_equals_negative_1_flips_the_same_tie_to_bearish`:
  the symmetric case, `rolling_breakout=-1` → **BEARISH**.
- `test_5c_removing_rolling_breakout_by_zeroing_it_reverts_to_neutral`:
  the "vice versa" direction explicitly required by the directive —
  starts from the BULLISH `rolling_breakout=1` configuration, zeroes
  only `rolling_breakout`, and confirms the signal reverts to NEUTRAL.
- `test_6b_missing_rolling_breakout_feature_value_yields_no_signal`:
  confirms the existing warm-up/missing-data safety convention is
  respected for the new feature too (deleting `rolling_breakout_20`
  from `feature_values` → `evaluate()` returns `None`, never a
  fabricated signal that silently ignores the missing condition).

## 4. Evidence / rejection-reason-code extension point

- **Extension point used**: `StrategySignal.evidence: tuple[FeatureValue,
  ...]` — the EXACT same mechanism 64.99 already used for
  `setup_quality_score` (`gainz_compatible_research.py` module header,
  "SCORING" section; `contracts.py`'s `StrategySignal` dataclass,
  confirmed frozen: `@dataclass(frozen=True, slots=True)`,
  `contracts.py` ~line 308). No new field was added to
  `StrategySignal` itself — confirmed both by inspection (`evidence`
  is the only tuple-typed extension field, everything else is a
  scalar) and by a direct test:
  `test_7_evidence_carries_both_adapter_owned_fields_signal_schema_unchanged`
  in the new test file asserts
  `{f.name for f in dataclasses.fields(signal)}` equals the exact
  pre-existing 10-field set (`strategy_id`, `specification_version`,
  `code_version`, `configuration_version`, `instrument_id`,
  `timeframe`, `timestamp`, `direction`, `price`, `evidence`).
- **New evidence entry**: `gainz_alpha_rejection_reason_code`
  (`REJECTION_REASON_CODE_FEATURE_NAME` constant,
  `gainz_compatible_research.py`), a `Decimal` code (`FeatureValue.value`
  is Decimal-only — `domain/feature/contracts.py`, so no string enum
  is possible at this extension point): `0` =
  `REJECTION_REASON_NOT_REJECTED` (a directional BULLISH/BEARISH signal
  was emitted), `1` = `REJECTION_REASON_TIE` (the only way
  `evaluate()`'s direction-selection logic can produce NEUTRAL, since
  `bull_score > bear_score` always implies `bull_score > 0`
  symmetrically for bear — re-derived, not merely asserted, in
  `test_3`/`test_3b`/`test_4` of the new test file). Appended to
  `evidence` alongside `setup_quality_score`:
  `evidence=evidence + (setup_quality_score, rejection_reason)` in
  `evaluate()`'s `return StrategySignal(...)` call.
- `market_regime` was explicitly NOT wired in anywhere in this
  checkpoint (no import, no reference, no evidence entry) — deferred
  per the roadmap's own "honest complication #3".

## 5. `StrategyConfigurationRecord` before/after check

Directly queried the testing-settings Postgres database (Django
`.shell -c`, `DJANGO_SETTINGS_MODULE=intraday.settings.testing`):
```
StrategyConfigurationRecord.objects.filter(strategy_id='gainz_compatible_research').count()
```
- **Before this checkpoint's changes**: `0`.
- **After this checkpoint's changes**: `0`.

No `StrategyConfigurationRecord` row exists for
`gainz_compatible_research` at either point, because this strategy has
never been registered/exposed for live configuration persistence
(`registry.py` untouched — see below). The `code_version` bump
therefore has **zero effect on any existing row** — nothing to orphan
or silently migrate. This was checked directly, not assumed, per the
directive's explicit "STOP and report honestly" instruction — the
honest report here is that the scenario the directive was guarding
against (a real orphaning) simply did not arise, because there was no
data to orphan.

## 6. Testing

New dedicated file:
`tests/unit/research/test_checkpoint_gainz_b1_scoring_and_breakout.py`
— **12/12 passed**. Covers:
- `test_1`/`test_2`: bull-heavy (6/9 vs 1/9) and bear-heavy (mirror)
  cases, full hand-computed arithmetic in the docstring, exact `Decimal`
  equality assertions (`== Decimal(68)`).
- `test_3`/`test_3b`: balanced/tie cases (1/9 vs 1/9 from the RSI=50
  default trap, and an explicit 3/9 vs 3/9 case), hand-computed
  arithmetic, NEUTRAL direction, `REJECTION_REASON_TIE` code.
- `test_4`/`test_5`/`test_5b`/`test_5c`: the required direct behavioral
  proof that `rolling_breakout` changes the outcome (see §3 above).
- `test_6`/`test_6b`: required-feature wiring and missing-data safety.
- `test_7`: evidence extension point + frozen `StrategySignal` schema
  check.
- `test_8`: `code_version` bump sanity.

Existing test files updated as an EXPECTED, DOCUMENTED consequence
(same pattern CHECKPOINT-GAINZ-A used for its own field-registry
regression tests) — every change is either (a) a `code_version`
literal `"v1"` → `"v2"`, (b) `rolling_breakout_20` added to an expected
`required_features()` set/tuple, or (c) an evidence-tuple
size/membership assertion updated for the 2 new evidence entries
(`rolling_breakout_20` FeatureValue + `gainz_alpha_rejection_reason_code`):
- `tests/unit/research/test_checkpoint_64_99_gainz_research_adapter.py`
  — `test_4`'s expected `required_features()` set; `test_19`'s
  `code_version == "v2"`; `test_21` renamed/rewritten
  (`test_21_required_features_include_rolling_breakout_but_never_regime`)
  since its old premise ("breakout is never a required field") is now
  the opposite of correct behavior — BLOCKER A being closed is the
  point of this checkpoint, not a regression to hide.
- `tests/unit/research/test_checkpoint_64_50_strategy_integration.py`
  — `test_a1`'s `code_version == "v2"`; `test_b1`'s expected
  `required_features()` tuple (added `"rolling_breakout_20"` before
  `"atr_14"`); `test_efgh`'s `expected_names` evidence set (added
  `gainz_alpha_rejection_reason_code`).
- `tests/unit/research/test_checkpoint_64_52_database_first_backtest.py`
  — `test_j`'s `len(signal.evidence) == 14` → `== 16` (14 real
  canonical FeatureValues including the new `rolling_breakout_20`,
  plus 2 adapter-owned evidence entries).

## 7. Full test suite — before/after

Both runs: `.venv/Scripts/python.exe -m pytest -q` from `d:\IntraDay`,
full `tests/` tree, no scoping, this environment's testing-settings
Postgres database.

**BEFORE** (this checkpoint's changes not yet applied — the working
tree at the start of this checkpoint, i.e. immediately after
CHECKPOINT-GAINZ-A / `1af77bb`):
```
5 failed, 3266 passed, 2 warnings in 649.52s (0:10:49)
```
Failures:
- `tests/unit/research/test_checkpoint_64_52_database_first_backtest.py::test_f_partial_gap_fetches_only_the_missing_range`
- `tests/unit/research/test_checkpoint_64_52_database_first_backtest.py::test_g_data_completeness_is_enforced_not_row_existence`
- `tests/unit/architecture/test_api_boundaries.py::test_application_services_and_contracts_stay_infrastructure_free`
- `tests/unit/research/test_checkpoint_64_48_gainz_adapter_design.py::test_k_no_gainz_reference_file_exists_in_repo`
- `tests/unit/research/test_checkpoint_64_49_gainz_feature_registry.py::test_zz_no_real_gainz_source_file_exists`

**AFTER** (this checkpoint's changes applied, full unrestricted
`pytest -q`, whole `tests/` tree):
```
5 failed, 3278 passed, 2 warnings in 662.30s (0:11:02)
```
Failures — the IDENTICAL 5 test names as the before-run, same files,
same test functions:
- `tests/unit/research/test_checkpoint_64_52_database_first_backtest.py::test_f_partial_gap_fetches_only_the_missing_range`
- `tests/unit/research/test_checkpoint_64_52_database_first_backtest.py::test_g_data_completeness_is_enforced_not_row_existence`
- `tests/unit/architecture/test_api_boundaries.py::test_application_services_and_contracts_stay_infrastructure_free`
- `tests/unit/research/test_checkpoint_64_48_gainz_adapter_design.py::test_k_no_gainz_reference_file_exists_in_repo`
- `tests/unit/research/test_checkpoint_64_49_gainz_feature_registry.py::test_zz_no_real_gainz_source_file_exists`

**3266 → 3278 passed = +12**, exactly the 12 new tests in
`test_checkpoint_gainz_b1_scoring_and_breakout.py`. **5 failed → 5
failed, identical names** — confirmed pre-existing, not introduced by
this diff. Also independently re-ran the targeted research/trading-
engine/signal-intelligence scope alone (before writing this section):
`4 failed, 1529 passed` (same 4 of the 5 failures that fall inside that
narrower scope — the 5th, `test_api_boundaries.py`, is outside it).

## 8. Scope confirmation

- `registry.py` (strategy registry): **NOT touched** — confirmed by
  `git diff --stat` (not listed) and by
  `tests/unit/research/test_checkpoint_64_50_strategy_integration.py::test_l1_default_registry_unchanged_by_this_checkpoint`
  and
  `tests/unit/research/test_checkpoint_64_99_gainz_research_adapter.py::test_22_gainz_is_absent_from_the_shared_default_registry`
  both passing unchanged.
- `market_regime`: **NOT wired in** — no import, no reference anywhere
  in the diff.
- No scanner/backtest-API exposure change — this strategy remains
  registrable only via a local, test-constructed `StrategyRegistry()`.

## 9. Files changed

Modified:
- `src/intraday/trading_engine/strategy_execution/strategies/gainz_compatible_research.py`
- `tests/unit/research/test_checkpoint_64_99_gainz_research_adapter.py`
- `tests/unit/research/test_checkpoint_64_50_strategy_integration.py`
- `tests/unit/research/test_checkpoint_64_52_database_first_backtest.py`
- `MEMORY.md` (appended)

New:
- `tests/unit/research/test_checkpoint_gainz_b1_scoring_and_breakout.py`
- `CHECKPOINT_GAINZ-B1_SUMMARY.md` (this file)
