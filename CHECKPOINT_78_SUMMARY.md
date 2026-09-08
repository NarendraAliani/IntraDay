# CHECKPOINT 78 — Summary

Fixes the precise, narrowly-scoped bug `CHECKPOINT_77` found, closes
the ATR preset gap, and re-verifies readiness end-to-end. **Still does
NOT launch a live session** — no `ScannerConfiguration` was activated,
no broker-order code path was called. That remains the operator's own
separate, explicit decision. Gainz/VWAP untouched, both remain paused.

```
part_1_fix: signal_pipeline_runtime.py's empty StrategyConfigurationValues
            fixed - reuses default_configuration_values() +
            coerce_configuration_values() (both pre-existing, no new
            mechanism invented)
part_1_second_finding: default_configuration_values() alone is
                       INSUFFICIENT for DECIMAL-typed parameters
                       (returns bare floats, require_decimal() rejects
                       them) - found via direct verification, fixed in
                       the same narrow scope (not escalated as a
                       separate gap - it's the other half of an
                       already-established, paired mechanism)
part_2_fix: new atr_baseline preset created, exact documented-baseline
            values, existing 3 ATR presets untouched
part_3_verdict: READY (all infrastructure + the code gap now closed,
                confirmed by actually invoking the real pipeline)
regression_tests_added: 3 (test_signal_pipeline_runtime.py)
database_write_occurred: YES (1 new StrategyConfigurationRecord only)
memory_md_updated: YES - confirmed below
project_strategy_status_updated: YES - confirmed below
commit: (recorded below)
blockers: []
```

## Part 1 — The empty-configuration fix

`signal_pipeline_runtime.py::promote_bars_and_trigger_signals()`'s
`configuration = StrategyConfigurationValues(strategy_id, "v1", "v1",
"v1", {})` line replaced with a call to a new, small
`_configuration_values_for(strategy_id)` helper — built from two
EXISTING, already-proven functions, no new mechanism invented:

```python
def _configuration_values_for(strategy_id: str) -> dict[str, object]:
    strategy = build_default_registry().get(strategy_id)
    schema = strategy.parameter_schema()
    return coerce_configuration_values(schema, default_configuration_values(schema))
```

`default_configuration_values()` is the exact helper `CHECKPOINT_77`
identified — the same one `replay_paper_session_runtime.py`'s own
`configuration_values_for()` already established for this exact
purpose.

**A second, real gap found while verifying the fix, not assumed to
work because it compiled** (per this checkpoint's own "same rigor
`CHECKPOINT_77` used" instruction): `default_configuration_values()`
alone returns a `ParameterDefinition.default` VERBATIM — a plain
Python literal (e.g. `2.0`, a `float`), never a `Decimal`. `require_
decimal()` (`contracts.py`) does a strict `isinstance(value, Decimal)`
check that a bare float fails. Direct verification (not assumption)
confirmed this: calling `sma_trend_filter`/`atr_volatility_breakout`'s
real `evaluate()` with a genuine, warmed-up feature value present (an
empty `feature_values` dict short-circuits BEFORE reaching
`require_decimal()`, which is exactly why this was missed on a first,
too-shallow check) raised `InvalidParameterValueError`.

**Fixed within the same narrow scope, not escalated as a separate
gap**: `coerce_configuration_values()` — the SAME function `Strategy
ConfigurationService.save_configuration()` already pairs with
`validate_configuration()` for this exact reason (its own docstring:
*"a value ... can NEVER satisfy that isinstance(value, Decimal) check
by any client-side encoding choice"*) — applied to the defaults dict
before it reaches `StrategyConfigurationValues`. This is the other
half of an already-established, paired mechanism, not a new one; kept
in scope rather than reported as a blocker, per the checkpoint's own
"same narrowly-scoped fix" framing — `default_configuration_values`/
`coerce_configuration_values` were never meant to be used alone in
this codebase's own existing precedent.

**Re-traced the fixed call path directly** (`[F]`, not assumed): for
all 3 registered strategies, `_configuration_values_for()` now returns
real, non-empty, correctly-typed values —

```
ema_crossover:             {fast_lookback: 12, slow_lookback: 26}
sma_trend_filter:          {lookback: 30, band_percent: Decimal('0.75')}
atr_volatility_breakout:   {lookback: 14, atr_multiplier: Decimal('2.0'),
                             stop_loss_atr_multiplier: Decimal('1.0'),
                             target_1_atr_multiplier: Decimal('1.5'),
                             target_2_atr_multiplier: Decimal('2.5'),
                             target_3_atr_multiplier: Decimal('3.5'),
                             trailing_stop_atr_multiplier: Decimal('1.0')}
```

— all matching the schema defaults / documented baseline exactly,
with real `Decimal` instances where required.

## New regression tests — 3, in `test_signal_pipeline_runtime.py`

1. `test_checkpoint_78_configuration_values_are_no_longer_empty` —
   monkeypatches `evaluate_bar_promotion`/`run_active_loop_tick`
   (matching this file's own existing style) and asserts the
   `configuration` kwarg passed to `run_active_loop_tick` is non-empty,
   has the exact expected keys, and contains no bare `float` for any of
   the 3 registered strategies.
2. `test_checkpoint_78_decimal_typed_strategies_pass_real_decimal_
   defaults` — the direct regression for the SECOND gap: asserts every
   DECIMAL-typed parameter for `sma_trend_filter`/`atr_volatility_
   breakout` is a genuine `Decimal` instance.
3. `test_checkpoint_78_real_evaluate_receives_non_empty_config_never_a_
   keyerror` (`@pytest.mark.django_db`) — the deep regression **this
   is the test `CHECKPOINT_77` identified as missing**: does NOT fake
   `run_active_loop_tick`, spies on the REAL, registered
   `EmaCrossoverStrategy.evaluate` bound method to prove the `config`
   argument it genuinely receives (not a test-only `_config()` helper's
   own hand-built one) has real values — using a genuinely open-market
   instant (`2026-08-03 05:00 UTC`, not the file's own module-level
   `NOW`, which is deliberately "session-neutral" and would have made
   `run_active_loop_tick`'s own real session-open gate skip evaluation
   entirely, silently passing for the wrong reason).

All 10 tests in the file pass (7 pre-existing + 3 new).

**Full suite re-run at the end: 5 failed, 3340 passed**, 649.48s —
exact names identical to the same 5 pre-existing failures documented
at every checkpoint this session (`test_f_partial_gap_fetches_only_
the_missing_range`, `test_g_data_completeness_is_enforced_not_row_
existence`, `test_application_services_and_contracts_stay_
infrastructure_free`, `test_k_no_gainz_reference_file_exists_in_repo`,
`test_zz_no_real_gainz_source_file_exists`), none touching this
checkpoint's diff. **Zero genuine regressions.**

## Part 2 — ATR preset gap resolved

**Decision**: created a NEW preset (`atr_baseline`) matching the
documented baseline exactly, rather than relying on "select no preset"
— for consistency with how `ema_conservative`/`sma_conservative` can
already be selected by name, and because a named, selectable preset is
the more operator-friendly, discoverable choice on the Strategy
Configuration screen than an implicit "leave it blank" convention.
Created via the real `StrategyConfigurationService.save_configuration()`
path (never a raw ORM insert), matching every prior preset-creation
checkpoint's own discipline:

```
atr_baseline: {lookback: 14, atr_multiplier: "2.0", stop_loss_atr_multiplier: "1.0",
               target_1_atr_multiplier: "1.5", target_2_atr_multiplier: "2.5",
               target_3_atr_multiplier: "3.5", trailing_stop_atr_multiplier: "1.0"}
```

`[F]` Verified directly: `StrategyConfigurationRecord` count for
`atr_volatility_breakout` went `3 → 4`; the existing 3 presets
(`atr_aggresive`/`atr_Balanced`/`atr_Conservative`) re-queried and
confirmed byte-for-byte unchanged — this checkpoint does not touch
them, per its own explicit rule; they remain exactly as they are for
their own already-completed walk-forward research purposes.

## Part 3 — Readiness re-verified: **READY**

`[F]` Re-ran the exact readiness trace, this time confirming the fix
by actually invoking the real `promote_bars_and_trigger_signals()`
path (not just re-reading code) against a real, genuinely open-market
bar:

```
SignalPipelineOutcome(promoted_count=1, active_loop_invocations=1)
```

No exception, no silent `StrategyExecutionFailure`. Combined with
`CHECKPOINT_77`'s own already-confirmed infrastructure checks (Dhan
credential `VALID`, `PaperBroker` the sole broker implementation,
`real_trading_state` structurally `DISABLED`, universe/timeframe/
strategy selection configurable, Telegram/Discord configured and
enabled) — re-confirmed unchanged this checkpoint (none of those were
touched) — **the system is genuinely ready for a first live paper
session today.**

**For the operator's reference** (restated from `CHECKPOINT_77`'s own
§2, NOT executed by this checkpoint):
1. Confirm/refresh the Dhan credential (Settings → Dhan) — currently
   `VALID` as of `CHECKPOINT_77`'s check (expires `2026-09-09 10:17:40
   UTC` — re-check before actually starting, since real time has
   passed since that check).
2. `manage.py run_market_data_worker --provider dhan` (a separate,
   manual OS process).
3. Confirm Provider Connectivity/Watchdog read `READY`.
4. Confirm Market State reads `READY`.
5. Set `ScannerConfiguration.universe_mode="SELECTED"` with a 3-5
   symbol universe (e.g. RELIANCE/TCS/HDFCBANK/INFY/ICICIBANK).
6. Set `timeframe="5m"`.
7. Set `selected_strategy_ids` to the 3 registered strategies, using
   their schema defaults / the `ema_conservative`/`sma_conservative`/
   `atr_baseline` presets (all 3 now exact matches to the documented
   baseline).
8. Press **START LIVE PAPER SESSION** on the Live Paper Operations
   Console.

**This checkpoint did none of the above** — no `ScannerConfiguration`
activated, no session started, no broker-order code path called.

## `MEMORY.md` and `PROJECT_STRATEGY_STATUS.md` — confirmed updated

`[F]` Appended (never rewrote) a new entry to `MEMORY.md` §3 recording
both fixes (the empty-dict gap and the float-vs-Decimal gap), the 3
new regression tests, the new `atr_baseline` preset, and the final
READY verdict. `[F]` `PROJECT_STRATEGY_STATUS.md` §6 updated in place
(this document's own established "living reference" convention) to
reflect READY, superseding `CHECKPOINT_77`'s own NOT READY finding —
both confirmed explicitly here, as this checkpoint's own instruction
required.

## Governance compliance

- P3: the only DB write this checkpoint was the 1 new, explicitly-
  authorized `atr_baseline` `StrategyConfigurationRecord` — no other
  table touched, no existing row mutated.
- P9: no strategy LOGIC touched (`ema_crossover.py`/`sma_trend_filter.py`/
  `atr_volatility_breakout.py` themselves are unmodified — only the
  wiring in `signal_pipeline_runtime.py` that constructs their
  configuration changed).
- No Gainz/VWAP tuning, no registry change — confirmed
  (`git status --short` shows only the 2 expected files plus this
  summary/`MEMORY.md`/`PROJECT_STRATEGY_STATUS.md`).
- No live session launch, no `ScannerConfiguration` activation, no
  broker-order code path called.
- P11/P16: this summary, `MEMORY.md`, `PROJECT_STRATEGY_STATUS.md`, the
  fix, and the new test file changes committed to `active-development`
  only.
