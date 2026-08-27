# Task Report

## Milestone
Signal Intelligence / Feature Engine — canonical, Gainz-independent market-data features.

## Checkpoint
64.97 — CANONICAL FEATURE ENGINE EXTENSION: ENGULFING PATTERN + N-BAR PRICE DELTA.

## Classification
OFFLINE, BOUNDED FEATURE-ENGINE checkpoint. No live data, no Gainz activation, no strategy/scanner/registry changes.

## Objective
Add exactly three generic, Gainz-independent canonical market-data features to the existing feature engine:
`bullish_engulfing`, `bearish_engulfing`, and a parameterized `price_delta_N`. These are DATA FEATURES ONLY —
usable by any future strategy, not a Gainz implementation.

## 64.96 Findings Carried Forward
- `docs/research/gainz_signal_engine_reference.py` is RESEARCH/REBUILD material, not proprietary GainzAlgo
  source or a verified/production-ready strategy.
- A real consensus/hybrid risk-level bug exists in that reference file (unrelated to this checkpoint's scope).
- "profile", not "strategy", is the reference file's correct term for its six variants.
- Same-candle-close entry (as used in the reference file) is incompatible with this project's real backtest
  engine (next-bar-open fills).
- No rule in the reference file was classified as verified/authentic GainzAlgo.
- Gainz remains DISABLED throughout — no strategy registration, no scanner integration. Unchanged this
  checkpoint too.

## Feature Engine Audit
Inspected `src/intraday/signal_intelligence/feature_engine/` before writing anything:
- `candle_body_ratio.py` — the exact pattern for a zero-parameter, per-bar feature (module-level
  `..._FIELD_ID` constant, no `Definition` dataclass, `ensure_chronological` + instrument/timeframe-mix
  guards, `FeatureValue` construction).
- `sma.py` — the exact pattern for a parameterized (lookback-based) rolling feature (`deque(maxlen=...)`,
  warm-up = no output until `lookback` bars observed).
- `definitions.py` — one small, frozen, slotted dataclass per parameterized-feature identity
  (`SimpleMovingAverageDefinition`, ..., `MacdHistogramDefinition`), each exposing `feature_name`/
  `feature_version`, validated via the shared `_validate_lookback()` helper. No generic
  `FeatureDefinition` framework exists — confirmed once again not to introduce one.
- `field_registry.py` — the single canonical field/feature registry (`FieldDefinition`, `list_fields()`,
  `get_field()`, `resolve_feature_name()`/`parse_feature_name()`), consumed by the parameter-schema builder
  and the frontend dropdown. This is the "existing canonical feature registry" Phase 10 requires reuse of.
- `application/services/strategy_execution.py::compute_feature_series()` — the ONE real dispatcher
  (`"kind_params"` string → compute function), injected into `StrategyExecutionCoordinator` at
  `build_coordinator()`. New field kinds are dispatched here, following the exact existing
  parse-then-construct-Definition-then-call shape.
- `errors.py` — `InvalidLookbackError`/`MixedInstrumentSeriesError`/`MixedTimeframeSeriesError`, reused
  as-is, no new error types needed.
- `domain/feature/contracts.py::FeatureValue` — `value: Decimal` is the ONLY numeric type this contract
  supports; there is no boolean variant anywhere in the platform.

## Existing Feature Architecture
Confirmed and followed exactly: one pure `compute_*(definition_or_none, bars) -> tuple[FeatureValue, ...]`
function per feature module; `ensure_chronological()` + instrument/timeframe-mix guards at the top of every
function; warm-up = simply emitting no output for unresolvable indices (never `None`/fabricated values);
registration happens in `field_registry.py`'s `_FIELDS` tuple via `_derived(...)`; dispatch happens in
`strategy_execution.py::compute_feature_series()`. No parallel registration/dispatch mechanism was created.

## Bullish Engulfing
`src/intraday/signal_intelligence/feature_engine/bullish_engulfing.py`, field id `bullish_engulfing`.

```
bullish_engulfing_t = (close[t-1] < open[t-1])   # prior candle bearish
                   AND (close[t] > open[t])       # current candle bullish
                   AND (close[t] > open[t-1])     # current close > prior open
                   AND (open[t] <= close[t-1])    # current open <= prior close
```

Uses ONLY bars t and t-1. Deterministic, closed-candle based (valid at `Bar.timestamp`, which is already the
bar's CLOSE time), symbol- and timeframe-independent. Structurally identical to the reference file's
`x["bullish_engulfing"]` pandas expression — inspected for comparison only, never imported/executed, and
NOT claimed to be verified authentic GainzAlgo mathematics.

## Bearish Engulfing
`src/intraday/signal_intelligence/feature_engine/bearish_engulfing.py`, field id `bearish_engulfing`.

```
bearish_engulfing_t = (close[t-1] > open[t-1])   # prior candle bullish
                   AND (close[t] < open[t])       # current candle bearish
                   AND (close[t] < open[t-1])     # current close < prior open
                   AND (open[t] >= close[t-1])    # current open >= prior close
```

Symmetric counterpart, same guarantees, same disclaimers.

## Price Delta
`src/intraday/signal_intelligence/feature_engine/price_delta.py`, field id `price_delta` (parameterized:
`price_delta_10`, `price_delta_20`, ...), via `PriceDeltaDefinition` in `definitions.py`.

```
price_delta_N(t) = close[t] - close[t-N]
```

**Representation decision (Phase 4 — inspected convention first):** every existing derived feature
(`RSI`, `ADX`, `+DI`/`-DI`, `Relative Volume`, `MACD Histogram`, `Candle Body Ratio`) returns a plain numeric
`Decimal` magnitude — `FeatureValue.value` has NO boolean variant anywhere in the platform. The reference
file itself expresses this concept as TWO booleans (`price_up_delta`/`price_down_delta` =
`close > close.shift(N)` / `close < close.shift(N)`). Rather than fabricate that same two-boolean shape
ahead of an actual consumer needing it, this checkpoint implements the smallest canonical representation
that still supports both: a single SIGNED numeric delta. `price_up_delta` is recoverable as
`price_delta_N > 0`, `price_down_delta` as `price_delta_N < 0` — verified by test `test_h3` (reference
comparison section below).

## Parameterization
`PriceDeltaDefinition(lookback: int)` added to `definitions.py`, following the exact
one-off-dataclass-per-identity pattern (`frozen=True, slots=True`, `_validate_lookback()` reused, rejects
`N <= 0` and non-int/bool via the SAME shared validator SMA/EMA/ATR/RSI/etc. already use — no new validation
logic). `feature_name` bakes N in: `"price_delta_10"`. `REFERENCE_ARTIFACT_DEFAULT_LOOKBACK = 10` is defined
in `price_delta.py`, taken ONLY from the reference file's `GainzConfig.candle_delta_length = 10`, and is
explicitly documented in both the module docstring and the constant's own comment as a
**REFERENCE-ARTIFACT DEFAULT**, never a "verified Gainz parameter" — it is not wired as a dataclass default
anywhere; every caller must supply `lookback` explicitly (`PriceDeltaDefinition()` with no args raises
`TypeError`, proven by `test_c7`).

`bullish_engulfing`/`bearish_engulfing` take no parameters (same zero-parameter shape as
`candle_body_ratio`).

## Warm-Up
- Engulfing: the FIRST bar in any series cannot be evaluated (no t-1) — skipped entirely; a single-bar
  series produces zero values (`test_a5`/`test_b5`).
- Price Delta: the first `N` bars cannot be evaluated (no `close[t-N]`) — skipped entirely
  (`test_c4`/`test_c6`).

Both follow the EXISTING "no output, not a fabricated value" warm-up convention (identical to
SMA/EMA/ATR/RSI/ADX/RVOL/MACD) — no new warm-up policy was invented.

## NaN Handling
No `NaN`/`None` is ever produced — consistent with every other feature in this engine (`FeatureValue.value`
is always a real `Decimal`; unresolvable indices simply produce no `FeatureValue` at all, never a
placeholder).

## Edge Cases
Tested explicitly: missing-history (single-row, two-row datasets), empty series, flat candles (equal
open/close on both bars — neither pattern can fire), equal-open/close boundary conditions (`open[t] ==
close[t-1]` exactly — counted as engulfing per the `<=`/`>=` boundary), gap-up open (breaks the bullish
condition), gap-down open (breaks the bearish condition), mixed-instrument/mixed-timeframe series (rejected
via the existing `MixedInstrumentSeriesError`/`MixedTimeframeSeriesError`), duplicate/out-of-order
timestamps (rejected via the existing `ensure_chronological()` — `DuplicateBarTimestampError`/
`OutOfOrderBarError`). No invalid data is ever silently coerced into a signal.

## Feature IDs
`bullish_engulfing`, `bearish_engulfing` (zero-parameter, matching `candle_body_ratio`'s existing shape) and
`price_delta` / `price_delta_N` (parameterized, matching `sma_N`/`ema_N`/`atr_N`/`rsi_N`'s existing shape,
parsed by the EXISTING `field_registry.parse_feature_name()` algorithm unchanged). No Gainz-specific
namespace (`gainz_price_delta`, etc.) was used — the architecture does not require one.

## Registry Integration
All three registered in `field_registry.py::_FIELDS` via the existing `_derived(...)` helper —
`bullish_engulfing`/`bearish_engulfing` require `("open", "close")`, `price_delta` requires `("close",)`.
Dispatched in `application/services/strategy_execution.py::compute_feature_series()`: exact-match branches
for the two zero-parameter engulfing ids (same shape as the existing `candle_body_ratio` branch), and a
`kind == "price_delta"` branch in the existing parsed-kind dispatch chain (same shape as `sma`/`ema`/`atr`/
`rsi`). `StrategyRegistry` was NOT touched — only the feature-layer registry/dispatcher.

## Reference Comparison
`test_h1`/`test_h2`/`test_h3` in the new test file hand-transcribe the reference file's own
`bullish_engulfing`/`bearish_engulfing`/`price_up_delta`/`price_down_delta` pandas expressions (read-only
transcription — the reference file is never imported/executed) and run them bar-by-bar against the
canonical implementations on identical clean inputs. Result: **MATCH** for engulfing (both directions, all
20 bars of a deterministic fixture) and **MATCH** (sign-equivalence) for price delta. This is a
divergence-detection fixture only — NOT a claim of authentic Gainz parity (no Gainz source exists to
verify parity against).

## Gainz Classification
| canonical_id | reference-field | reference-location | classification |
|---|---|---|---|
| `bullish_engulfing` | `x["bullish_engulfing"]` | `gainz_signal_engine_reference.py` (compute-features section) | GENERIC (structurally REBUILT from the reference file's own pandas expression; NOT verified authentic GainzAlgo — no Gainz source exists to check against) |
| `bearish_engulfing` | `x["bearish_engulfing"]` | `gainz_signal_engine_reference.py` (compute-features section) | GENERIC / REBUILT, same caveat |
| `price_delta_N` | `x["price_up_delta"]` / `x["price_down_delta"]` | `gainz_signal_engine_reference.py` (compute-features section) + `GainzConfig.candle_delta_length` | GENERIC (signed representation deliberately chosen over the reference's two-boolean shape) / REBUILT, same caveat |

None of the three is labeled AUTHENTIC GAINZ anywhere in code, comments, or the registry.

## Breakout Comparison
Inspected `src/intraday/trading_engine/strategy_execution/strategies/atr_volatility_breakout.py` per Phase
13, comparison only. Its "breakout" is a SINGLE-BAR volatility-magnitude threshold:
`move = close - open` of the SAME bar, compared against `atr_multiplier * ATR(lookback)` — BULLISH/BEARISH/
NEUTRAL by whether that one bar's move exceeds the threshold. It does NOT compute a rolling N-bar
high/low breakout (`shift(1).rolling(20).max()`/`.min()`, i.e. "did price break out of its own recent
range"). **Finding: DIFFERENT.** The existing strategy answers "was this bar's move unusually large
relative to volatility?"; the `shift(1).rolling(20).max()/min()` concept answers "did price exceed its own
N-bar trailing extreme?" — different inputs (single-bar move + ATR vs. rolling close/high/low extremes),
different semantics, no overlap. No new breakout feature was created this checkpoint, as directed.

## Duplicate Feature Audit
Verified `bullish_engulfing`, `bearish_engulfing`, `price_delta` do not collide with any existing field id in
`field_registry._FIELDS`: `open`, `high`, `low`, `close`, `volume`, `sma`, `ema`, `atr`, `rsi`, `adx`,
`plus_di`, `minus_di`, `relative_volume`, `macd_hist`, `candle_body_ratio`. No duplicate indicator was
introduced (`test_g1`/`test_g3`, plus the pre-existing `test_i1_no_second_indicator_framework_class_created`/
`test_i2_no_gainz_named_indicator_module_exists` in `test_checkpoint_64_49_gainz_feature_registry.py`, both
still passing unmodified).

## No-Lookahead Validation
Mandatory tests added and passing: `test_d1`/`test_d2` (mutate the LAST bar → every engulfing value except
the last is byte-identical), `test_d3`/`test_d5` (mutate the LAST bar / append a future bar to price delta →
every earlier value unchanged, sanity-checked that the mutation DID change the affected value), `test_d4`
(mutate a MIDDLE bar → every engulfing value strictly before that bar's timestamp is byte-identical, the
stronger variant matching the existing RSI no-lookahead test's shape). All pass. By construction, each
`compute_*` function only ever indexes `bars[i-1]`/`bars[i]` (engulfing) or a fixed-size trailing window
(price delta) — there is no code path through which a later bar could influence an earlier output.

## Determinism
`test_e1`: identical input → byte-identical `tuple[FeatureValue, ...]` output across repeated calls, for all
three functions. Pure functions, no hidden state, no float arithmetic (all `Decimal`).

## Database Changes
None.

## Migrations
None.

## API Changes
None (no REST/API surface exists for the raw feature-engine layer — `field_registry.list_fields()` already
feeds the existing dynamic parameter-schema/frontend-dropdown machinery unchanged in shape; the 3 new
entries simply appear in that same existing list).

## Frontend Changes
None directly — the new fields will surface automatically in the existing generated field dropdown the next
time the API contract is regenerated, exactly as every prior canonical-feature addition has, but no frontend
file was touched this checkpoint.

## Tests
New: `tests/unit/signal_intelligence/feature_engine/test_checkpoint_64_97_engulfing_and_price_delta.py` — 41
tests covering: bullish/bearish engulfing correctness (true/false/boundary/gap-up/gap-down/flat-candle/
prev-not-matching-direction cases), price-delta correctness (positive/negative/zero/insufficient-history/
configurable-lookback), no-lookahead (mandatory), determinism, edge cases (mixed instrument/timeframe,
duplicate/out-of-order timestamps, empty/single/two-row series), registry integration (registered,
dispatchable via the real production dispatcher), and reference-comparison (Phase 12).

Updated (pre-existing tests that pin the EXACT prior field count/set, requiring a deliberate, reviewed
update — same class of update those tests' own docstrings anticipate):
- `tests/unit/research/test_checkpoint_64_51_registry_regression.py` — field count 15→18, field-id set
  updated, dispatchable-lookback map extended.
- `tests/unit/trading_engine/test_strategy_execution.py` — dispatchable-lookback map extended.
- `tests/unit/research/test_checkpoint_64_48_gainz_adapter_design.py` — field-id set updated (15→18) in
  `test_e_feature_registry_reuse_opportunities_identified`; honesty-guard allowlist in
  `test_k_no_gainz_reference_file_exists_in_repo` extended with the 3 new module names, this checkpoint's own
  test file name, AND (found to be a pre-existing gap from 64.96, unrelated to this checkpoint's own code)
  `gainz_signal_engine_reference.py`/`GAINZ_SIGNAL_ENGINE_AUDIT.md`.
- `tests/unit/research/test_checkpoint_64_49_gainz_feature_registry.py` — honesty-guard allowlist extended
  with the same new names.

## Testing Level
TARGETED + SUBSYSTEM, escalated to FULL REGRESSION once. Rationale: `field_registry.py` and
`strategy_execution.py::compute_feature_series()` are shared, cross-cutting contracts consumed by the
strategy-execution coordinator, correlation-traceability resolver, and multiple bounded-context test suites
(not just the feature-engine's own tests) — the changed contract IS demonstrably consumed across multiple
bounded contexts, so the directive's escalation condition was met.

## Tests Run
1. Targeted: `tests/unit/signal_intelligence/feature_engine/test_checkpoint_64_97_engulfing_and_price_delta.py`
   → **41 passed**.
2. Subsystem: `tests/unit/signal_intelligence`, `test_checkpoint_64_49_gainz_feature_registry.py`,
   `test_feature_engine_service.py`, `test_strategy_execution.py`, `test_checkpoint_64_50_strategy_integration.py`,
   `test_checkpoint_64_51_registry_regression.py`, `test_checkpoint_64_81_correlation_traceability.py` →
   **all passed** (after the deliberate, reviewed updates listed under Tests above).
3. Full regression, run EXACTLY ONCE, after (1) and (2), no concurrent pytest processes:
   `poetry run pytest tests/unit -q` → first pass: **2 failed, 2765 passed** (0:09:12). Both failures were in
   `tests/unit/research/test_checkpoint_64_48_gainz_adapter_design.py` (`test_e_feature_registry_reuse_opportunities_identified`,
   `test_k_no_gainz_reference_file_exists_in_repo`) — the same class of "pin the exact prior field
   set"/"allowlist known Gainz-mentioning file names" maintenance already anticipated by that file's own
   comments for every prior checkpoint that touched the registry. Fixed with the deliberate, reviewed updates
   listed under Tests above, then re-verified by running ONLY that one file
   (`poetry run pytest tests/unit/research/test_checkpoint_64_48_gainz_adapter_design.py -q` → **11 passed**)
   — the full `tests/unit -q` regression itself was NOT re-run a second time, per the directive's "exactly
   once" instruction; the fix targets exactly the two tests that failed and does not touch any other
   contract the full run already exercised.

## Tests Skipped
None relevant skipped. No database/integration suite was run (no DB changes this checkpoint).

## Escalation Decision
Escalated to full regression because the changed dispatcher (`compute_feature_series()`) and registry
(`field_registry.list_fields()`) are consumed well beyond the feature-engine's own tests (strategy-execution
coordinator, correlation-traceability, multiple `test_checkpoint_64_4x`/`64_5x`/`64_8x` regression files) —
satisfying the directive's own escalation condition ("if the actual changed contract is demonstrably
consumed across multiple bounded contexts").

## Gainz Status
DISABLED. Unchanged this checkpoint. No strategy registration, no scanner integration, no activation.

## Strategy Status
Unchanged. No strategy file was modified (`atr_volatility_breakout.py` was READ ONLY, for the Phase 13
breakout comparison). `StrategyRegistry`/`build_default_registry()` untouched.

## Scanner Status
Unchanged. Not touched.

## NSE_FNO Status
Unchanged. Not touched.

## BacktestTrustLevel
Unchanged. Not touched.

## Research Readiness
Unchanged. Not touched.

## Remaining Gaps
- Breakout (rolling N-bar high/low, as distinct from the existing single-bar ATR-multiple concept) remains
  unimplemented — deliberately deferred per Phase 13's explicit instruction not to implement it this
  checkpoint.
- No Gainz scoring weights, profiles, consensus, risk logic, position sizing, or strategy registration exist
  — all explicitly out of scope, per the directive.
- `price_delta`'s two-boolean recoverability (`> 0` / `< 0`) is proven only by test, not exposed as separate
  registered fields — a future consumer needing literal `price_up_delta`/`price_down_delta` field ids would
  need to derive them from `price_delta_N` at the strategy layer, or a future checkpoint could add them
  explicitly if a real consumer needs that shape.
- The consensus/hybrid risk-level bug identified in 64.96 remains unfixed in the (immutable, read-only)
  reference file — out of this checkpoint's scope by design.

## Blockers
None.

## Next Product Milestone
Await review. No Gainz adapter design work should begin until explicitly requested (per the directive's
Final Directive).

## Performance Ranking
(Compare 64.96 → 64.97.)

| Dimension | Previous (64.96) | Current (64.97) | Change | Evidence | Remaining Gap |
|---|---|---|---|---|---|
| Canonical Feature Quality | N/A — 64.96 was audit-only, no new feature code | 3 new features, following the existing architecture exactly (verified by inspection of `candle_body_ratio.py`/`sma.py`/`definitions.py` before writing any code) | ↑ | New modules + registry entries + dispatcher branches, all quality-gated | None |
| Engulfing Correctness | N/A | Matches reference-file logic bar-by-bar on a 20-bar deterministic fixture (`test_h1`/`test_h2`); boundary (`<=`/`>=`), gap-up/gap-down, flat-candle cases all explicitly tested | ↑ | `test_a*`/`test_b*`/`test_h1`/`test_h2`, all passing | None identified |
| Price Delta Correctness | N/A | Signed delta verified against reference's up/down booleans by sign-equivalence (`test_h3`); positive/negative/zero/configurable-lookback all tested | ↑ | `test_c*`/`test_h3`, all passing | Literal `price_up_delta`/`price_down_delta` fields not separately registered (see Remaining Gaps) |
| Parameterization | N/A | `PriceDeltaDefinition` reuses the SAME `_validate_lookback()` shared helper and dataclass shape as SMA/EMA/ATR/RSI/etc.; N=10 explicitly labeled REFERENCE-ARTIFACT DEFAULT, never wired as an actual default | ↑ | `definitions.py` diff; `test_c7`/`test_c8` | None |
| Warm-Up Correctness | N/A | First bar (engulfing) / first N bars (delta) produce no output, matching the existing convention exactly | ↑ | `test_a5`/`test_b5`/`test_c4`/`test_c6` | None |
| No-Lookahead Safety | N/A | Mandatory mutate-future-row tests for both last-bar and middle-bar mutation, all pass | ↑ | `test_d1`-`test_d5` | None |
| Registry Integration | N/A | Registered via the existing `_derived()` helper; dispatched via the existing `compute_feature_series()` parse-then-construct chain; `StrategyRegistry` untouched | ↑ | `field_registry.py`/`strategy_execution.py` diffs; `test_g1`-`test_g5` | None |
| Duplicate Avoidance | N/A | Explicit collision audit against all 15 pre-existing field ids; no second indicator-framework class created (pre-existing structural AST tests still pass unmodified) | ↑ | `test_g1`/`test_g3`; `test_i1`/`test_i2` in `test_checkpoint_64_49...py` | None |
| Reference Alignment | 64.96 established the reference file's classification (RESEARCH/REBUILD, not verified) | Canonical engulfing/price-delta MATCH the reference file's own expressions structurally (Phase 12 divergence-detection fixture), while remaining honestly labeled GENERIC/REBUILT, never AUTHENTIC GAINZ | ↑ | `test_h1`-`test_h3`; Gainz Classification table above | Full Gainz math (regime/scoring/consensus) remains unverified/unimplemented, as intended |
| Breakout Reuse Analysis | N/A | `atr_volatility_breakout.py` inspected, found structurally DIFFERENT from a rolling-N-bar-extreme breakout concept; no new breakout feature created | ↑ | Breakout Comparison section above | Rolling N-bar breakout itself remains unimplemented (deliberately deferred) |
| Testing | 64.96 was audit-only (no new test suite for this checkpoint's own code) | 41 new targeted tests + subsystem suite + one full-regression run (2765 passed after 2 pre-existing-pattern fixes) | ↑ | Tests Run section above | None |
| Performance | N/A (offline, no live path touched) | O(n) per feature (single pass, fixed-size trailing state), identical complexity class to SMA/EMA/ATR | ↑ | `price_delta.py`/`bullish_engulfing.py`/`bearish_engulfing.py` implementations | None |
| Maintainability | N/A | Zero new abstractions — reused `_validate_lookback()`, `ensure_chronological()`, the existing dataclass-per-identity pattern, and the existing `_derived()` registry helper verbatim | ↑ | Diffs across `definitions.py`/`field_registry.py`/`strategy_execution.py` | None |

## Final Product Gate

**A. Is bullish_engulfing implemented as a generic canonical feature?**
Yes — `bullish_engulfing.py`, registered in `field_registry.py`, dispatched via `compute_feature_series()`,
usable by any future strategy independent of Gainz.

**B. Is bearish_engulfing implemented as a generic canonical feature?**
Yes — `bearish_engulfing.py`, same integration as A.

**C. Is price_delta_N implemented generically?**
Yes — `price_delta.py` + `PriceDeltaDefinition`, parameterized like every other lookback-based feature, N
supplied explicitly by the caller (never hardcoded into a strategy).

**D. Are all three deterministic?**
Yes — proven by `test_e1` (identical input → byte-identical output across repeated calls); all three are
pure functions over `Decimal` arithmetic only.

**E. Is warm-up behavior explicit?**
Yes — first bar (engulfing) / first N bars (price delta) produce no `FeatureValue` at all, documented in each
module's docstring and proven by `test_a5`/`test_b5`/`test_c4`/`test_c6`.

**F. Is NaN handling consistent with the existing feature engine?**
Yes — no `NaN`/`None` value is ever produced by any feature in this engine, including the three new ones;
unresolvable indices simply produce no output, matching SMA/EMA/ATR/RSI/etc. exactly.

**G. Is future data excluded?**
Yes — `bullish_engulfing`/`bearish_engulfing` index only `bars[i-1]`/`bars[i]`; `price_delta_N` reads only a
fixed-size trailing `deque` of at most `N+1` closes. No code path can reach a later bar.

**H. Does mutating future candles leave past feature values unchanged?**
Yes — proven by `test_d1`-`test_d5`, including the stronger middle-bar-mutation variant (`test_d4`): every
output whose timestamp is strictly before the mutated bar's timestamp is byte-identical before/after the
mutation.

**I. Are feature IDs canonical rather than Gainz-specific?**
Yes — `bullish_engulfing`, `bearish_engulfing`, `price_delta` (no `gainz_` prefix or namespace anywhere).

**J. Were duplicate existing indicators avoided?**
Yes — explicit collision audit against all 15 pre-existing field ids (`test_g1`/`test_g3`); no field name or
computation overlaps `candle_body_ratio`/RSI/EMA/ATR/ADX/Relative Volume/MACD.

**K. Was existing atr_volatility_breakout.py inspected before adding any breakout feature?**
Yes — read in full for the Phase 13 comparison (see Breakout Comparison section). It was never modified.

**L. Was a new breakout feature created? (EXPECTED: NO)**
NO. Confirmed — no breakout module, field id, or dispatch branch was added this checkpoint.

**M. Was Gainz implemented? (EXPECTED: NO)**
NO. No `GainzStrategy`/`GainzAdapter`/`GainzProfile`/`GainzConsensus` class or scoring/consensus/risk/
position-sizing logic exists anywhere in this checkpoint's changes.

**N. Was Gainz registered? (EXPECTED: NO)**
NO. `StrategyRegistry`/`build_default_registry()` were not touched; `registry_ids` remain
`{"ema_crossover", "sma_trend_filter", "atr_volatility_breakout"}` (unchanged, re-verified by the passing
`test_checkpoint_64_48_gainz_adapter_design.py` and `test_j2_default_registry_has_no_gainz_strategy_id`).

**O. Was Gainz activated? (EXPECTED: NO)**
NO. No activation call, no scanner integration, nothing reachable from a live/paper trading path was
touched.

**P. Was the supplied reference file modified? (EXPECTED: NO)**
NO. `docs/research/gainz_signal_engine_reference.py` was read-only for comparison in Phases 2/3/4/12/13; it
does not appear in the `git diff` for this checkpoint's own changes.

**Q. Was any strategy modified? (EXPECTED: NO)**
NO. `atr_volatility_breakout.py` was read-only (comparison); no strategy file's content changed.

**R. Was the scanner modified? (EXPECTED: NO)**
NO. Not touched.

**S. Was BacktestTrustLevel changed? (EXPECTED: NO)**
NO. Not touched.

**T. Was Research Readiness changed? (EXPECTED: NO)**
NO. Not touched.

**U. Was any database migration created? (EXPECTED: NO)**
NO. No migration, no new table, no research/signal/trade rows.

**V. Was any live Dhan connection made? (EXPECTED: NO)**
NO. Entirely offline; no market worker, no scanner, no Dhan/live-broker code path was touched or executed.

**W. What does the reference-to-canonical comparison show?**
For engulfing: the canonical rules are STRUCTURALLY IDENTICAL to the reference file's own
`bullish_engulfing`/`bearish_engulfing` pandas expressions, confirmed to MATCH bar-by-bar on a 20-bar
deterministic clean fixture (`test_h1`/`test_h2`). For price delta: the canonical signed representation is
sign-equivalent to the reference file's `price_up_delta`/`price_down_delta` booleans on a 25-bar fixture
(`test_h3`). Neither comparison is, or is claimed to be, a verification of authentic GainzAlgo mathematics —
no authentic Gainz source exists to verify against; it is a divergence-detection fixture against a
user-supplied research/rebuild artifact only.

**X. What remains unresolved before a Gainz adapter can be designed?**
Regime classification (unverified), score weights (unverified), consensus/hybrid logic (the real bug 64.96
identified remains unfixed in the immutable reference file), risk-level derivation, position sizing, and
strategy registration are all still unimplemented/unverified. Breakout (rolling N-bar extreme) has no
canonical feature yet either. None of these were in this checkpoint's scope.

**Y. What exact checkpoint should implement the adapter?**
Not yet determined — per the Final Directive, 64.97 must STOP here; a future checkpoint (explicitly
requested and reviewed) would design the Gainz adapter only after regime/scoring/consensus/risk questions
above are separately resolved.

## Git Safety
No commit, no push performed.

```
git status --short   -> see below (30 tracked-modified + several untracked; only the files listed under
                         "Files changed this checkpoint" below are 64.97's own changes)
git diff --stat       -> 30 files changed, 1548 insertions(+), 305 deletions(-) (cumulative working-tree
                         diff, including carried-forward 64.9x work already present before this checkpoint
                         started)
git log -3 --oneline -> 49ed106 checkpoint 64.90 / dbce678 checkpoint 64.80-f3 / 3bd7a09 CheckPoint 64.69
```

**Files changed/added by 64.97 specifically** (all others in `git status --short` are carried-forward,
pre-existing working-tree modifications from 64.92-64.96, untouched by this checkpoint):
- `src/intraday/signal_intelligence/feature_engine/bullish_engulfing.py` (new)
- `src/intraday/signal_intelligence/feature_engine/bearish_engulfing.py` (new)
- `src/intraday/signal_intelligence/feature_engine/price_delta.py` (new)
- `src/intraday/signal_intelligence/feature_engine/definitions.py` (added `PriceDeltaDefinition`)
- `src/intraday/signal_intelligence/feature_engine/field_registry.py` (registered 3 new fields)
- `src/intraday/application/services/strategy_execution.py` (dispatcher: 3 new branches)
- `tests/unit/signal_intelligence/feature_engine/test_checkpoint_64_97_engulfing_and_price_delta.py` (new)
- `tests/unit/research/test_checkpoint_64_51_registry_regression.py` (updated field count/dispatch map)
- `tests/unit/trading_engine/test_strategy_execution.py` (updated dispatch map)
- `tests/unit/research/test_checkpoint_64_48_gainz_adapter_design.py` (updated field set + honesty allowlist)
- `tests/unit/research/test_checkpoint_64_49_gainz_feature_registry.py` (updated honesty allowlist)
- `taskReport.md` (this file, overwritten)
