# Task Report

## Milestone
Gainz Research Adapter Program - equity/OHLCV research track (paper-trading-only platform; no live order placement, no Dhan orders).

## Checkpoint
64.99 - GAINZ RESEARCH ADAPTER IMPLEMENTATION: SINGLE PROFILE / NO CONSENSUS / EQUITY RESEARCH ONLY. First REAL Gainz implementation checkpoint. OFFLINE (market closed). RESEARCH ONLY, not production.

## Classification
Implementation checkpoint (transition from 64.98's AUDIT to IMPLEMENTATION), scoped to exactly one strategy identity and one profile.

## Objective
Implement `GainzCompatibleResearchStrategy` (`strategy_id = "gainz_compatible_research"`, profile `alpha` only) reusing the existing `StrategyRegistry`/`Strategy` Protocol/`StrategySignal`/`TradePlan` architecture and the canonical feature engine exclusively, with no consensus, no other profiles, no parallel engines, and no live-scanner exposure.

## 64.98 Findings Carried Forward
- `TradePlan` already supports `entry_price`/`stop_loss`/`target_1`/`target_2`/`target_3`/`trailing_stop_loss` - no schema change needed (confirmed unchanged this checkpoint).
- Canonical backtest fills at NEXT-BAR-OPEN after a signal is evaluated on a CLOSED bar; the reference file's same-candle close is an entry candidate only.
- `candle_body_ratio`/`bullish_engulfing`/`bearish_engulfing`/`price_delta` are EXACT MATCHES against the reference; `EMA`/`RSI`/`ATR`/`ADX`/`+DI`/`-DI`/`Relative Volume`/`MACD Histogram` DIFFER by design (Wilder-SMA-seeded vs pandas-ewm-seeded) - accepted, permanent divergence, not reproduced.
- `breakout` and `regime` features: REQUIRED BUT UNAVAILABLE - reconfirmed this checkpoint (see Blockers).
- Consensus: DEFERRED (frozen 64.98 decision) - not implemented.
- Gainz: DISABLED throughout - remains disabled; no scanner change.

## Adapter Architecture
Canonical Market Data -> Canonical Feature Engine -> `GainzCompatibleResearchStrategy.evaluate()`/`.build_trade_plan()` -> `StrategySignal`/`TradePlan` -> (existing, unmodified) `OrderIntent` -> `RiskDecision` -> Existing Backtest/Paper Execution. No new signal engine, indicator engine, risk engine, execution engine, backtest engine, or correlation engine was created. The class conforms to the existing `Strategy` Protocol (`trading_engine/strategy_execution/strategy.py`) exactly as `ema_crossover`/`sma_trend_filter`/`atr_volatility_breakout` do.

## Strategy Identity
Exactly one: `gainz_compatible_research` (`STRATEGY_ID` in `src/intraday/trading_engine/strategy_execution/strategies/gainz_compatible_research.py`). No `gainz_alpha`/`gainz_trend`/`gainz_breakout`/`gainz_scalp`/`gainz_hybrid`/`gainz_consensus` module or identity exists anywhere in the repository.

## Profile
Exactly one implemented: `alpha` (`PROFILE_ALPHA = "alpha"`). The `profile` parameter is `ParameterType.ENUM` with `allowed_values=("alpha",)` - a single-element tuple, not a placeholder list of six.

## Strategy Parameter Schema
19 parameters, all via the existing `ParameterDefinition`/`StrategyParameterSchema` mechanism (no ad-hoc config): `profile` (ENUM, alpha-only), `ema_fast_lookback`/`ema_slow_lookback`/`ema_trend_lookback` (9/21/50, reference-artifact defaults), `rsi_lookback` (14), `rsi_alpha_threshold` (80), `price_delta_lookback` (10), `adx_lookback` (14), `adx_minimum` (20), `relative_volume_lookback` (20), `relative_volume_minimum` (0.80), `candle_body_ratio_minimum` (0.70), `macd_fast`/`macd_slow`/`macd_signal` (12/26/9), and 5 research-only TradePlan ATR multipliers. Every default is labeled a reference-artifact/conservative-research default, never a verified Gainz parameter. No weight/threshold was optimized.

## Canonical Feature Inputs
`required_features()` returns exactly: `ema_{fast}`, `ema_{slow}`, `ema_{trend}`, `rsi_{N}`, `price_delta_{N}`, `adx_{N}`, `plus_di_{N}`, `minus_di_{N}`, `relative_volume_{N}`, `macd_hist_{fast}_{slow}_{signal}`, `candle_body_ratio`, `bullish_engulfing`, `bearish_engulfing`, and `atr_{N}` (TradePlan-only, not a signal condition - see Alpha Signal Logic). All 14 are canonical field_ids dispatched through the existing `compute_feature_series`/field registry - none is computed inside this strategy, and none calls the reference file's private `_ema`/`_rsi`/`_atr`/`_adx` functions.

## Feature Evidence
Every non-NEUTRAL `StrategySignal.evidence` tuple carries the 13 real canonical `FeatureValue`s consumed by the 8 scoring conditions (EMA fast/slow/trend, RSI, price_delta, ADX, +DI, -DI, relative volume, MACD histogram, candle body ratio, bullish_engulfing, bearish_engulfing) plus one adapter-owned `FeatureValue` named `gainz_alpha_setup_quality_score` (see Setup Quality). `atr_{N}` is fetched by the coordinator (it is in `required_features()`) but deliberately excluded from `evaluate()`'s evidence tuple - it is TradePlan-only, never a scoring input.

## Alpha Signal Logic
The reference file's `_score_row()` "alpha" profile branch is literally `pass` - Alpha relies entirely on the SHARED base scoring block above it. This adapter reimplements that shared block condition-by-condition using only canonical features (see Signal Conditions), and documents three items it could NOT reproduce without fabricating semantics (see Blockers).

## Signal Conditions
Implemented (equal-weight, PROJECT RESEARCH PARAMETER scoring - see Setup Quality):
1. `bullish_engulfing`/`bearish_engulfing` == 1 (canonical, exact match per 64.98).
2. `stable_candle`: `candle_body_ratio >= candle_body_ratio_minimum` (canonical, exact match; shared by both sides, as in the reference).
3. RSI "not extremely exhausted" gate: bull `rsi < rsi_alpha_threshold`, bear `rsi > 100 - rsi_alpha_threshold` (canonical Wilder RSI - numerically differs from reference by design, accepted).
4. `price_delta_{N}` gate: bull `price_delta < 0`, bear `price_delta > 0` (canonical `price_delta_N`; `< 0` / `> 0` is the documented equivalence to the reference's `price_down_delta`/`price_up_delta`).
5. Trend confirmation: bull `close > ema_trend and ema_fast > ema_slow and ema_slow > ema_trend`; bear symmetric (canonical EMA, differs numerically by design).
6. MACD Histogram sign (canonical, differs numerically by design).
7. Relative-volume + candle-direction confirmation: `relative_volume >= relative_volume_minimum` and `bar.close > bar.open` (bull) / `< bar.open` (bear) (canonical RVOL + raw `Bar` fields already available, no new feature).
8. ADX-direction confirmation: `adx >= adx_minimum` and `+DI > -DI` (bull) / `-DI > +DI` (bear) (canonical, differs numerically by design).

Deliberately omitted, documented as blockers, never fabricated:
- 20-bar breakout/breakdown (Blocker A).
- RSI momentum vs the PRIOR bar's RSI (Blocker B - newly discovered this checkpoint, beyond breakout/regime).
- `regime` labeling (Blocker C - informational-only in the reference, not a scoring input either there or here).

## Direction
BULLISH when the count of true bull-conditions exceeds the count of true bear-conditions and is > 0; BEARISH symmetrically; NEUTRAL otherwise (including a tie, or when any required feature is unavailable - `evaluate()` returns `None`, never a fabricated signal).

## Setup Quality
`setup_quality_score` = `(winning_side_condition_count / 8) * 100`, carried as `FeatureValue(feature_name="gainz_alpha_setup_quality_score", ...)` inside `StrategySignal.evidence` - `StrategySignal` itself (a frozen, shared, multi-strategy contract since Checkpoint 26) was NOT modified; reusing its existing `evidence` tuple is the only extension point that respects that freeze. Explicitly documented in the module header and asserted by test item 11/12: NOT a probability, NOT a probability of profit, NOT a calibrated confidence estimate - a plain 0-100 count of agreeing conditions. Equal per-condition weighting is an adapter-owned, independently-chosen PROJECT RESEARCH PARAMETER (`_TOTAL_ALPHA_CONDITIONS = 8`), explicitly NOT the reference's 25/15/12/10/8/7 point scale, and not optimized/tuned this checkpoint.

## TradePlan
Produced by `build_trade_plan()`, reusing the existing `TradePlan` dataclass unmodified. Returns `None` for NEUTRAL signals or missing ATR (never fabricated). ATR-multiplier ladder mirrors `atr_volatility_breakout.py`'s existing precedent, explicitly NOT the reference's `rr1`/`rr2`/`rr3` ported as verified Gainz risk:reward math (the reference's own `min_rr` was previously found dead configuration - not resurrected here).

## Entry Candidate
`TradePlan.entry_price = signal.price` (signal-time close), documented in `calculation_method` as "an ENTRY CANDIDATE/REFERENCE PRICE ONLY" - never treated as a fill price anywhere in this checkpoint.

## Stop Loss
`entry - sign * trade_plan_stop_loss_atr_multiplier * ATR` (default multiplier 1.0x ATR); direction-consistent (below entry for BULLISH, above for BEARISH) - verified by tests 15/16/17.

## TP1
`entry + sign * trade_plan_target_1_atr_multiplier * ATR` (default 1.0x ATR).

## TP2
`entry + sign * trade_plan_target_2_atr_multiplier * ATR` (default 2.0x ATR), strictly beyond TP1 in the trade direction.

## TP3
`entry + sign * trade_plan_target_3_atr_multiplier * ATR` (default 3.0x ATR), strictly beyond TP2.

## Trailing Stop
Not populated (`trailing_stop_loss` left `None`) - the reference's Alpha branch does not produce a trailing level distinct from its fixed SL/TP ladder, and this checkpoint does not fabricate one. `TradePlan.trailing_stop_loss` remains available, unused, for future work.

## Risk Boundary
The adapter never computes position size, quantity, margin, or portfolio exposure anywhere. Confirmed by test 13 (`hasattr` checks against the strategy class and every produced `TradePlan`) and by test 14 (`run_stateful_backtest()` end-to-end, which drives the REAL `evaluate_order_risk()`). The chain remains `StrategySignal -> OrderIntent -> RiskDecision -> Existing Execution`, RiskDecision authoritative, never bypassed.

## Position Sizing Boundary
The reference's `risk_per_trade`/`max_position_value_pct`/`position_size`/`qty` fields are not read, not ported, and have no analog in this module. No production quantity is returned from `evaluate()` or `build_trade_plan()`.

## Execution Semantics
Closed-candle evaluation is treated as an architectural execution rule (every `Bar` handed to `evaluate()` is already closed, by the existing coordinator/backtest contract), not reinvented as a per-strategy `require_confirmed_bar` switch (the reference's own switch is not ported). No local `last_signal`/position-state variable exists anywhere in the class - `evaluate()` is a pure function of its arguments (verified by determinism tests 5/20).

## Next-Bar-Open Fill
Verified via `run_stateful_backtest()` (the existing, unmodified backtest engine) in test 18: entries are recorded through the real orchestration, whose own module docstring documents the entry filling at the following bar's open, never the signal bar's own close. `TradePlan.entry_price` remains a reference price only (see Entry Candidate).

## Correlation
Every `StrategySignal` carries `strategy_id`/`specification_version`/`code_version`/`configuration_version`/`instrument_id`/`timeframe`/`timestamp`, and every evidence `FeatureValue` is independently pinned to the same instrument/timeframe/timestamp (`StrategySignal.__post_init__` already enforces this; re-asserted by test 19). No correlation is inferred from symbol+timestamp alone anywhere in this checkpoint.

## Provenance
Feature evidence -> signal -> strategy/version -> (test-local) scan/backtest run -> trade -> outcome chain is preserved unchanged; no new provenance mechanism was introduced.

## Backtest Integration
Consumable by the existing engine (`research.backtesting.execution.compute_signals`, `tradeplan_execution.compute_trade_plans`, `historical_execution.run_stateful_backtest`) with zero new backtest code. No `GainzBacktestEngine`/`GainzExecutionEngine`/`GainzTradeSimulator` was created.

## Research-Only Boundary
`GainzCompatibleResearchStrategy` is deliberately NEVER registered in `registry.build_default_registry()`. Direct inspection this checkpoint confirmed `build_default_registry()` is the exact same function both `infrastructure/api/scanner_configuration_views.py` (`_registry = build_default_registry()`) and `infrastructure/api/backtesting_views.py` (`_REGISTRY = build_default_registry()`) construct their module-level registries from - there is no research-only vs. live-eligible distinction anywhere in `StrategyRegistry` (`registry.py` has no such flag/method). Per the directive, that gap was documented as a blocker rather than patched by weakening the registry (see Blockers). The only reachable-from-nowhere-live guarantee available today is to never call `.register()` on this class inside `build_default_registry()` - exactly mirroring the precedent `test_checkpoint_64_47_strategy_registry.py`'s own `TestStrategy` already established ("never registered into `build_default_registry()`... so this proof-of-concept never pollutes the real strategy suite"). `test_checkpoint_64_99_gainz_research_adapter.py` registers the class only into LOCAL `StrategyRegistry()` instances it constructs itself.

## Scanner Boundary
Live scanner code (`scanner_configuration_views.py`) was not modified. Test 22a asserts `gainz_compatible_research` is absent from `build_default_registry().list()`; test 22b parses (via `ast`) both `scanner_configuration_views.py` and `backtesting_views.py` and asserts each imports `build_default_registry` from `registry.py`, proving (not merely asserting) both endpoints share the one registry Gainz is absent from.

## Gainz Authenticity Status
Unchanged: NOT authentic GainzAlgo, NOT verified Gainz V2, NOT a proprietary Gainz implementation. Module header and class docstring both restate this "HONESTY NOTICE." The reference file remains a third-party research/rebuild artifact, not authoritative Gainz source.

## Gainz Reference Comparison
Documented per-condition in the module header and this report's "Signal Conditions" section: canonical behavior chosen (Wilder-seeded RSI/ADX/EMA, standard MACD, generic engulfing/body-ratio/price-delta) vs. reference behavior observed (pandas-ewm-seeded equivalents) vs. implication (numeric divergence accepted by design per 64.98, canonical features NOT changed to match the reference). Deterministic fixtures exercising every implemented condition live in `test_checkpoint_64_99_gainz_research_adapter.py` (tests 4, 8, 9, 11) and `test_checkpoint_64_50_strategy_integration.py`/`test_checkpoint_64_52_database_first_backtest.py` (updated this checkpoint - see Tests).

## Database Changes
None. No new Gainz-specific table/migration was created; existing persistence contracts (unused by this checkpoint's tests, which are pure unit/integration) were left untouched.

## API Changes
None.

## Frontend Changes
None. Gainz was not added to the live Scanner selector or exposed as live-ready anywhere in frontend code.

## Tests
New file: `tests/unit/research/test_checkpoint_64_99_gainz_research_adapter.py` - 26 tests covering all 22 directive-required items (some items split across 2 tests for clarity: 3/3b, 10/10b, 15-17 combined + 15b, plus explicit regression guards for reference-file-non-import and no-consensus). All 26 pass.

Updated (pre-existing, checkpoint-caused adjustments - see Testing Level):
- `tests/unit/research/test_checkpoint_64_50_strategy_integration.py`: `required_features()` expectation, evidence-shape expectation, and bar fixtures updated for the expanded Alpha condition set (adds a `_flat_then_breakout_bars()` generator, since a purely monotonic ramp pins RSI at 100 and never satisfies the new RSI-alpha gate).
- `tests/unit/research/test_checkpoint_64_52_database_first_backtest.py`: evidence-count and TradePlan-availability assertions updated for the same reason (`atr_14` is now in `required_features()`, so a TradePlan is now produced directly by the coordinator rather than requiring manual augmentation).
- `tests/unit/research/test_checkpoint_64_48_gainz_adapter_design.py` / `test_checkpoint_64_49_gainz_feature_registry.py`: honesty-guard allowlists extended with this checkpoint's own new test file (both guards scan the whole repo for the literal string "gainz" and previously had no entry for a checkpoint-64.99-named file).

## Testing Level
Targeted (new adapter test file) -> affected subsystem (`tests/unit/research/`, `tests/unit/trading_engine/`, `tests/unit/infrastructure/api/test_checkpoint_64_68_paper_session_api.py`) -> quality gates -> exactly ONE final full regression, in that order, per the directive's Full Regression Policy.

## Tests Run
- `test_checkpoint_64_99_gainz_research_adapter.py`: 26 passed.
- `tests/unit/research/`: 996 passed (includes the 4 pre-existing files updated above, plus the new file).
- `tests/unit/trading_engine/`: 95 passed.
- `tests/unit/infrastructure/api/test_checkpoint_64_68_paper_session_api.py` + `test_checkpoint_64_51_registry_regression.py`: 27 passed.
- Combined affected-subsystem run (`research` + `trading_engine` + the paper-session API file): 1105 passed.
- **Final authoritative full regression** (`poetry run pytest tests/unit -q`), run exactly once, after all fixes and quality gates: **2793 passed, 0 failed**, in 555.68s (0:09:15), exit code 0.

## Tests Skipped
None deliberately skipped. Postgres-backed tests (`@requires_postgres`/`@pytest.mark.django_db`, e.g. `test_checkpoint_64_52_database_first_backtest.py::test_j_...`) ran against the locally available Postgres instance rather than being skipped.

## Escalation Decision
Not triggered. The final full regression passed cleanly on its one permitted run - no second full-suite run was needed, so no STOP-and-report escalation was required.

## Quality Gates
- `ruff check` (adapter module + all touched/new test files): All checks passed (after fixing 2 duplicate-set-item lint errors in my own edits, 1 unused-variable, 1 import-order issue, and 2 line-length issues - all self-introduced this checkpoint, all fixed).
- `ruff format --check`: all files formatted; the new test file needed one `ruff format` pass, now clean.
- `mypy` (project-configured scope, `packages = ["intraday"]`, i.e. `src/` only - tests are outside the configured mypy scope): 5 pre-existing errors remain, in 4 files this checkpoint never touched (`scanner_configuration_views.py`, `run_market_data_worker.py`, `research_correlation.py`, `correlation_views.py`) - confirmed unrelated to 64.99 and left as-is per "fix only issues this checkpoint caused." `gainz_compatible_research.py` alone: "Success: no issues found in 1 source file."
- `lint-imports`: 6 kept, 0 broken (449 files, 2213 dependencies analyzed) - the `trading_engine`/`signal_intelligence` bounded-context-independence contract and every other contract remain intact; this adapter introduces no new cross-context import.

## BacktestTrustLevel
Unchanged. The adapter's deterministic research output is recorded above (see Testing/Reference Comparison) but does not promote the global trust gate - no code in this checkpoint touches trust-level configuration.

## Research Readiness
Remains NO. This checkpoint establishes architecture-level integration only, not research validity, profitability, or predictive value.

## Remaining Gaps
- RSI-momentum condition (Blocker B) requires a per-bar feature-history channel `Strategy.evaluate()` does not currently expose - a real architectural gap, not merely a missing feature computation.
- Breakout/regime features (Blockers A/C) remain unimplemented per explicit scope.
- No trailing-stop level is produced.
- No duplicate-alert/repeat-signal suppression exists (explicitly deferred to the scanner/signal lifecycle, per directive).
- `StrategyRegistry` still has no formal research-only vs. live-eligible flag - the only available guarantee is "not registered in `build_default_registry()`," a convention, not an enforced architectural invariant.

## Blockers
- **Blocker A (breakout)**: 20-bar prior-high/-low breakout/breakdown - REQUIRED BUT UNAVAILABLE (no canonical `breakout` feature exists; explicitly out of scope this checkpoint). Omitted, not fabricated.
- **Blocker B (RSI momentum)**: "RSI > 50 and rising vs. the PRIOR bar's RSI" - REQUIRED BUT UNAVAILABLE. `Strategy.evaluate()`/`StrategyExecutionCoordinator.run()` only ever supply the CURRENT bar's single `FeatureValue` per field_id; there is no previous-bar-feature channel. Newly discovered this checkpoint (beyond the pre-identified breakout/regime pair). Omitted, not fabricated (dropping only the "rising" half and keeping "RSI > 50" was explicitly rejected as inventing different semantics).
- **Blocker C (regime)**: ADX-threshold-bucketed regime label - REQUIRED BUT UNAVAILABLE per 64.98. Not a scoring input in the reference's own `_score_row()` either, so its absence changes no signal decision; omitted entirely, no `regime` field/feature produced anywhere.
- **Registry research-only flag**: `StrategyRegistry` has no research-only/live-eligible distinction; documented above under Research-Only Boundary, mitigated by never registering into `build_default_registry()`, not by weakening the registry.

## Next Product Milestone
65.00 - Gainz Backtest Validation (explicitly NOT started this checkpoint - see Final Directive).

## Performance Ranking
(Compare 64.98 -> 64.99.)

**Adapter Architecture** - Previous: audited only, no adapter existed. Current: one real adapter class implemented, conforming exactly to the existing `Strategy` Protocol. Change: Improved (audit -> working implementation). Evidence: `gainz_compatible_research.py`, `Strategy` Protocol conformance verified by registration into a local `StrategyRegistry()` (test 1). Remaining Gap: none for this scope.

**Canonical Feature Reuse** - Previous: contracts frozen, feature parity classified. Current: adapter consumes 13 canonical feature_ids + 1 TradePlan-only ATR, zero private reference functions imported. Change: Improved. Evidence: test 4 (dispatches every required_features() id through the real `compute_feature_series`), test 21b (AST-verified no reference import). Remaining Gap: none.

**Alpha Signal Correctness** - Previous: N/A (no implementation). Current: 8 of the reference's shared-base conditions implemented and condition-by-condition documented; 3 blockers (breakout, RSI momentum, regime) explicitly omitted rather than fabricated. Change: New capability, partial by design. Evidence: module header "CONDITIONS IMPLEMENTED"/"CONDITIONS DELIBERATELY OMITTED"; tests 8/9. Remaining Gap: Blockers A/B/C (see above).

**Determinism** - Previous: N/A. Current: `evaluate()` is a pure function, no mutable state. Change: New capability, verified. Evidence: tests 5, 20 (repeated evaluation/backtest reproducibility). Remaining Gap: none.

**No-Lookahead** - Previous: N/A. Current: truncated-series parity proven. Change: New capability, verified. Evidence: test 7. Remaining Gap: none.

**TradePlan Mapping** - Previous: N/A. Current: existing `TradePlan` contract reused unmodified; `entry_price` documented as candidate-only. Change: New capability, verified. Evidence: tests 15-17. Remaining Gap: no trailing-stop value produced.

**TP1/TP2/TP3** - Previous: N/A. Current: full 3-target ladder, direction-consistent, ATR-multiplier-based. Change: New capability, verified. Evidence: test 15-17 (target ordering assertions both directions). Remaining Gap: none.

**Risk Separation** - Previous: N/A. Current: zero sizing/quantity/margin logic anywhere in the adapter; RiskDecision remains authoritative. Change: New capability, verified. Evidence: tests 13, 14. Remaining Gap: none.

**Execution Compatibility** - Previous: N/A. Current: runs end-to-end through the unmodified `run_stateful_backtest()`, fills recorded next-bar-open. Change: New capability, verified. Evidence: test 18. Remaining Gap: none.

**Correlation** - Previous: N/A. Current: full strategy/version/instrument/timeframe/timestamp provenance on every signal and every evidence value. Change: New capability, verified. Evidence: test 19. Remaining Gap: none.

**Backtest Integration** - Previous: N/A. Current: consumed by the existing engine with zero new backtest code. Change: New capability, verified. Evidence: tests 14, 18. Remaining Gap: none.

**Research-Only Isolation** - Previous: N/A (no adapter to isolate). Current: never registered in the shared `build_default_registry()`; mechanism independently verified by AST-parsing both live-scanner and backtest API modules. Change: New capability, verified by inspection not assertion. Evidence: tests 22a, 22b. Remaining Gap: `StrategyRegistry` itself still has no formal research-only flag - isolation is a registration convention, not an enforced invariant.

**Scanner Isolation** - Previous: Gainz absent (nothing existed to expose). Current: still absent from the live scanner's registry; scanner code untouched. Change: Maintained. Evidence: test 22a/22b; `git diff --name-only` shows no `infrastructure/api/scanner_configuration_views.py` change. Remaining Gap: none.

**Testing** - Previous: 64.98 was audit-only (no new adapter tests; carried forward the unresolved 64.97 "2 failed -> corrected -> 11 passed -> full suite never rerun" history). Current: 26 new adapter tests + 4 pre-existing files updated for the behavior change, full research subsystem green (996 passed), full regression run exactly once and green (2793 passed, 0 failed). Change: Improved, and the 64.97 unresolved-history question is answered for 64.99's own baseline (see Escalation Decision / AE below) even though it remains historically true for 64.97 itself. Evidence: this report's Tests Run section. Remaining Gap: none for 64.99; 64.97's own historical gap is a permanent record, not something 64.99 can retroactively close.

**Maintainability** - Previous: N/A. Current: every non-obvious decision (blockers, scoring provenance, registry isolation mechanism) documented inline in the module header, not just in this report. Change: New capability. Evidence: `gainz_compatible_research.py` module docstring. Remaining Gap: none.

**Performance** - Previous: N/A. Current: adapter adds one linear pass over 8 boolean conditions per bar - negligible relative to existing feature computation cost; no measurable regression observed (full suite runtime dominated by pre-existing Postgres-backed tests). Change: Neutral. Evidence: full regression wall-clock (555.68s) consistent with prior checkpoints' order of magnitude. Remaining Gap: no dedicated performance benchmark was run (not required this checkpoint).

**Security** - Previous: N/A. Current: no new external I/O, no new persistence, no live network/broker call anywhere in the adapter or its tests. Change: Neutral/Maintained. Evidence: `git diff --name-only` (no infrastructure/persistence/API files touched by the adapter itself); manual confirmation no Dhan/market-worker/scanner/Telegram/Discord call was made this session. Remaining Gap: none.

## Final Product Gate

**A. Is exactly ONE Gainz research strategy identity implemented?** YES - `gainz_compatible_research` only; no other Gainz-named strategy module exists.

**B. Is profile=alpha the ONLY implemented profile?** YES - `allowed_values=("alpha",)`; no Trend/Breakout/Mean-Reversion/Hybrid/Scalp logic branch exists in the class.

**C. Are unsupported profiles unavailable?** YES - rejected at both the schema-validation layer (`validate_configuration` raises `InvalidParameterValueError` for any non-"alpha" value, since it is outside `allowed_values`) and defensively inside `evaluate()`'s own `_profile()` guard (tests 3, 3b).

**D. Does the adapter use ONLY canonical features?** YES - all 14 `required_features()` field_ids are canonical, dispatched through the existing `compute_feature_series`; `evaluate()` performs no indicator math itself beyond boolean condition composition and the adapter-owned setup-quality arithmetic.

**E. Were canonical EMA/RSI/ATR/ADX/RVOL/MACD implementations modified?** NO (as expected) - `git diff --name-only` shows zero changes under `signal_intelligence/feature_engine/`.

**F. Does the adapter use the new canonical engulfing/price_delta features?** YES - `bullish_engulfing`, `bearish_engulfing`, and `price_delta_{N}` are all in `required_features()` and used as scoring conditions.

**G. Does the adapter remain deterministic?** YES - verified by test 5 (repeated `compute_signals`) and test 20 (repeated full pipeline including TradePlan).

**H. Is closed-candle evaluation guaranteed?** YES - by the existing architecture (every `Bar` passed to `evaluate()` is already closed); verified indirectly by test 6 (signal timestamp always equals the evaluated bar's own timestamp, never a future one).

**I. Is no-lookahead guaranteed?** YES - verified by test 7 (truncating the bar series does not change an earlier-bar signal).

**J. Is every signal backed by feature evidence?** YES - verified by tests 8, 9, 19; every non-NEUTRAL signal's `evidence` tuple is non-empty and pinned to the signal's own instrument/timeframe/timestamp.

**K. Is setup_quality_score clearly distinct from probability?** YES - documented in the module header's "SCORING" section and this report's "Setup Quality" section; no field named `probability` exists anywhere on `StrategySignal` or its evidence (test 12).

**L. Is position sizing excluded from the signal path?** YES - no quantity/position_size/margin attribute or method exists on the strategy class or any produced `TradePlan` (test 13).

**M. Does RiskDecision remain authoritative?** YES - `run_stateful_backtest()` (unmodified) drives the real `evaluate_order_risk()` for every entry attempt; the adapter never bypasses it (test 14).

**N. Does TradePlan support TP1/TP2/TP3 without schema changes?** YES - `git diff --name-only` shows `trading_engine/strategy_execution/contracts.py` (where `TradePlan` is defined) was NOT touched this checkpoint; `target_1`/`target_2`/`target_3` are populated using the pre-existing fields (tests 15-17).

**O. Is the reference same-candle close treated only as an entry candidate?** YES - `TradePlan.entry_price = signal.price` is explicitly documented in `calculation_method` as "an ENTRY CANDIDATE/REFERENCE PRICE ONLY."

**P. Are actual backtest fills still next-bar-open?** YES - verified via the unmodified `run_stateful_backtest()` orchestration (test 18), whose own module docstring documents the next-bar-open fill rule; this checkpoint introduces no alternate fill path.

**Q. Is consensus NOT implemented?** YES (correctly not implemented) - verified by an explicit regression guard (`test_no_consensus_logic_anywhere_in_the_adapter_module`) scanning the module source for "consensus"/"min_votes"/"consensus_signal" - none found.

**R. Are unverified reference weights NOT presented as official Gainz weights?** YES - the adapter uses its own equal-weight (`_TOTAL_ALPHA_CONDITIONS = 8`) scheme, explicitly documented as a PROJECT RESEARCH PARAMETER, distinct from and never equal to the reference's 25/15/12/10/8/7 point scale.

**S. Is Gainz still NOT claimed authentic?** YES - the module header's "HONESTY NOTICE" and class docstring both restate this explicitly.

**T. Is the adapter equity/OHLCV only?** YES - no strike/expiry/CE/PE/premium/lot-size/OI/IV/Greeks concept appears anywhere in the module.

**U. Is NSE_FNO untouched?** YES - `git diff --name-only` shows no file under any FNO/OptionChain/OptionBar/OI/IV/Greeks module.

**V. Is the scanner unchanged?** YES - `git diff --name-only` shows no change to `infrastructure/api/scanner_configuration_views.py` or any frontend file.

**W. Is Gainz unavailable to live scanning?** YES - `gainz_compatible_research` is absent from `build_default_registry().list()` (test 22a), and both the scanner and backtest API modules are proven (by AST parse, not assertion) to construct their registries from that same function (test 22b).

**X. Was BacktestTrustLevel unchanged?** YES - no trust-level configuration file was touched.

**Y. Is Research Readiness still NO?** YES - explicitly restated; nothing in this checkpoint establishes profitability or predictive validity.

**Z. Were no live Dhan calls made?** YES - no Dhan client/API module was imported or invoked at any point this session; all bar data in tests is synthetic, in-memory, or from the local test database.

**AA. Were no live orders placed?** YES - all order/fill activity this session ran through `HistoricalExecutionSimulator`/`run_stateful_backtest()` (paper/backtest simulation), never a live broker gateway.

**AB. Does the adapter preserve Signal -> OrderIntent -> RiskDecision -> Backtest/Paper Execution?** YES - confirmed end-to-end by test 14/18 against the unmodified `run_stateful_backtest()` pipeline.

**AC. Is the adapter traceable through the correlation model?** YES - see Correlation/Provenance sections and test 19.

**AD. Did the final full regression pass? Report the exact result.** YES - `poetry run pytest tests/unit -q`, run exactly once: **2793 passed, 0 failed**, in 555.68s (0:09:15), exit code 0.

**AE. Were all 64.97 baseline testing issues resolved or explicitly carried forward?** Carried forward, explicitly: 64.97's own historical run ("2765 passed, 2 failed -> corrected -> only the affected file re-verified (11 passed) -> full suite never rerun clean") remains an unresolved, permanent historical record for that checkpoint specifically - 64.99 cannot retroactively rerun 64.97's own suite under 64.97's own code state. What 64.99 DOES report, as required: its own final, current-codebase full regression is clean (2793 passed, 0 failed), which is the strongest evidence available today that whatever caused 64.97's 2 failures is not presently reproducing across the full suite - but this is NOT the same claim as "64.97's specific 2 failures were individually re-diagnosed and fixed," which was never attempted or claimed.

**AF. What are the THREE most important limitations of this first Gainz adapter?**
1. Three genuine condition gaps versus the reference's shared-base Alpha logic (20-bar breakout, RSI-vs-prior-bar momentum, regime labeling) are structurally unavailable given the current feature engine and `Strategy.evaluate()` interface - not just missing features but, for RSI momentum, a missing per-bar-history channel in the architecture itself.
2. Every numerically-differing canonical feature (EMA/RSI/ATR/ADX/+DI/-DI/RVOL/MACD) means Alpha's condition-truth-values will genuinely diverge from the reference artifact's on the same input bars, by design - this adapter reproduces the reference's STRUCTURE, not its exact numeric behavior.
3. No outcome evidence of any kind exists yet - zero backtests have been run to evaluate this strategy's actual trade performance; `setup_quality_score`'s "8 agreeing conditions" heuristic has no empirical calibration against realized P&L.

**AG. What exact evidence is required before Alpha can be considered research-valid?**
A dedicated backtest-validation checkpoint (65.00) running `gainz_compatible_research`/alpha through the existing backtest engine over a substantial, realistic historical dataset, producing: win rate, average R-multiple, drawdown, and trade count by market regime; a documented decision on whether the 3 blocked conditions materially change outcomes when later implemented; and explicit non-claims about profitability until that evidence exists (Research Readiness stays NO until then).

**AH. What is the next checkpoint?**
65.00 - Gainz Backtest Validation (not started; this checkpoint stops here per the Final Directive).

## Git Safety
`git status --short`:
```
 M src/intraday/trading_engine/strategy_execution/strategies/gainz_compatible_research.py
 M taskReport.md
 M tests/unit/research/test_checkpoint_64_48_gainz_adapter_design.py
 M tests/unit/research/test_checkpoint_64_49_gainz_feature_registry.py
 M tests/unit/research/test_checkpoint_64_50_strategy_integration.py
 M tests/unit/research/test_checkpoint_64_52_database_first_backtest.py
?? tests/unit/research/test_checkpoint_64_99_gainz_research_adapter.py
```

`git diff --stat`:
```
 .../strategies/gainz_compatible_research.py        | 602 ++++++++++++-----
 taskReport.md                                      | 727 +++++++++------------
 .../test_checkpoint_64_48_gainz_adapter_design.py  |   9 +
 .../test_checkpoint_64_49_gainz_feature_registry.py|   4 +
 .../test_checkpoint_64_50_strategy_integration.py  |  97 ++-
 .../test_checkpoint_64_52_database_first_backtest.py| 29 +-
 6 files changed, 870 insertions(+), 598 deletions(-)
```

`git diff --name-only`:
```
src/intraday/trading_engine/strategy_execution/strategies/gainz_compatible_research.py
taskReport.md
tests/unit/research/test_checkpoint_64_48_gainz_adapter_design.py
tests/unit/research/test_checkpoint_64_49_gainz_feature_registry.py
tests/unit/research/test_checkpoint_64_50_strategy_integration.py
tests/unit/research/test_checkpoint_64_52_database_first_backtest.py
```
(plus the new, untracked `tests/unit/research/test_checkpoint_64_99_gainz_research_adapter.py`)

`git log -3 --oneline`:
```
7356ebf checkPoint 64.97
49ed106 checkpoint 64.90
dbce678 checkpoint 64.80-f3
```

All six modified files (plus the one new file) are 64.99's OWN changes - none are carried-forward, uncommitted 64.92-64.98 changes (the repo was clean at 64.97's commit before this session started, per the pre-session `git status: clean` note). NOTHING WAS COMMITTED OR PUSHED this session, per instruction.

## Final Directive Compliance
64.99 is the FIRST REAL GAINZ IMPLEMENTATION CHECKPOINT, RESEARCH ONLY. It built one clean adapter (`gainz_compatible_research`, profile `alpha`) proving the reference concepts enter the existing canonical strategy architecture without duplicating the feature/risk/execution/backtest/correlation engines. Six profiles were not implemented. Consensus was not implemented. Weights were not optimized. Breakout/regime were not implemented. Gainz was not activated. Gainz was not wired into the scanner. Live trading was not touched. STOPPING HERE per the Final Directive - awaiting review before 65.00.
