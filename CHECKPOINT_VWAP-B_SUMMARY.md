# CHECKPOINT-VWAP-B — Summary

Scope: Phase B of `VWAP_STRATEGY_ROADMAP.md` — the strategy itself,
using the `vwap` feature `CHECKPOINT-VWAP-A` built. `registry.py`
untouched, still unregistered. `gainz_compatible_research.py` and
every other strategy file untouched (paused per `CHECKPOINT_75`).

## 1. What was built

New file
`src/intraday/trading_engine/strategy_execution/strategies/vwap_mean_reversion.py`
— `VwapMeanReversionStrategy`, matching the real `Strategy` Protocol
structurally identically to `ema_crossover.py` (cited directly as
this file's own structural reference in its module docstring).

**4 parameters, exactly per the roadmap's design**:

| `parameter_id` | Type | Default | Meaning |
|---|---|---|---|
| `vwap_deviation_atr_multiplier` (N) | DECIMAL | `1.5` | Entry trigger distance from VWAP |
| `stop_loss_atr_multiplier` (M) | DECIMAL | `2.5` | Stop distance from entry — must exceed N |
| `atr_lookback` | INTEGER | `14` | Shared ATR period for both the trigger and the stop |
| `target_reversion_fraction` | DECIMAL | `1.0` | Fraction of the entry→VWAP distance the target requires |

`required_features()`: `("vwap", f"atr_{atr_lookback}")` — `"vwap"`
used verbatim, no suffix, exactly `CHECKPOINT-VWAP-A`'s field_id.

**`evaluate()`**: `BULLISH` when `close < vwap - N×ATR`, `BEARISH` when
`close > vwap + N×ATR`, `NEUTRAL` otherwise (a real signal object, not
`None` — matching `ema_crossover`'s own convention) or `None` only
during genuine warmup (either feature missing).

**`build_trade_plan()`**: single target only —
`target = entry + target_reversion_fraction × (vwap - entry)`
(direction-agnostic by construction: `(vwap - entry)` is positive for
a BULLISH entry and negative for a BEARISH one, so one formula serves
both directions without a sign branch); `stop_loss = entry - sign ×
M×ATR`. `target_2`/`target_3`/`trailing_stop_loss` are all `None` —
deliberately no ladder.

## 2. The M > N cross-parameter constraint — honest finding, real guard

**Checked `ParameterDefinition` directly before deciding how to
handle this**: it carries only static per-parameter `minimum`/
`maximum` bounds (`Decimal | int | None`) — **there is no mechanism to
express "this parameter's valid range depends on another parameter's
configured value."** This is not a gap unique to this checkpoint —
re-confirmed the SAME situation already exists, unaddressed, in
`ema_crossover.py`'s own `slow_lookback` ("Must exceed
`fast_lookback`," enforced only by `help_text`) and
`atr_volatility_breakout.py`'s `target_1 < target_2 < target_3`
ladder (also `help_text`-only, no runtime check). Reported honestly
here rather than silently reusing that same "documentation-only"
convention without comment.

**This strategy adds one small, explicit, TESTED runtime guard instead
— a genuine design decision, not a workaround**: `build_trade_plan()`
returns `None` when `stop_loss_atr_multiplier <=
vwap_deviation_atr_multiplier`, refusing to emit a plan whose stop
sits at or inside the entry's own trigger distance (a degenerate
plan). This mirrors `gainz_compatible_research.py`'s own "never
fabricate a plan from missing data" discipline, extended to bad
parameter combinations. Tested directly (`test_16`/`test_17`/`test_18`
— equal, less-than, and valid-greater-than cases all produce the
correct outcome).

## 3. Testing — 19 unit tests, all passing

`tests/unit/research/test_checkpoint_vwap_b_mean_reversion_strategy.py`:

- Schema shape (exactly 4 parameters, correct `required_features`
  suffix behavior).
- Clear BUY (`test_3`), clear SELL (`test_4`), in-band NEUTRAL
  (`test_5`, confirmed a real signal object per `ema_crossover`'s own
  convention, not `None`), exact-boundary-is-not-yet-a-trigger
  (`test_6`, strict inequality), missing-`vwap`/missing-`atr`/
  empty-feature-values warmup (`test_7`/`8`/`9`).
- Evidence auditability: `vwap`/`atr`/signed deviation-multiple
  evidence always present; target/stop-price evidence present ONLY
  for non-NEUTRAL signals, hand-computed and verified exactly
  (`test_10`/`test_11`).
- `build_trade_plan()` arithmetic: BULLISH (`test_12`), BEARISH stop
  direction (`test_13`), partial-reversion-fraction targets closer to
  entry than VWAP itself (`test_14`), `None` for NEUTRAL (`test_15`).
- The M > N guard, all 3 cases (`test_16`/`17`/`18`).

## 4. First real backtest — RELIANCE, default parameters, gate-verified dataset

**Explicitly a first look, NOT a validation gate** — Phase D is the
mandatory gate; this is reported honestly as early evidence only, per
this checkpoint's own instruction not to oversell it.

`run_backtest()` called directly (never `BacktestingService.run()`),
via a LOCAL `StrategyRegistry()` (same pattern `CHECKPOINT-GAINZ-D`
established — `registry.py` untouched), real costs
(`verified_nse_cash_equity_intraday_cost_model()`), default parameter
values, against the FULL currently-available gate-verified RELIANCE
dataset — now **17 distinct trading days / 1,224 bars** (two blocks:
`2026-08-03`–`08-14` and `2026-08-31`–`09-08`, the latter one day
larger than `CHECKPOINT_75`'s own 16-day figure, since
`CHECKPOINT_74`'s Part 3 added `2026-09-08` in the interim).

| Metric | Value |
|---|---|
| total_trades | 47 |
| win_rate_percent | 38.30% |
| average_winner | 39.68 |
| average_loser | -65.06 |
| risk_reward_ratio | 0.61 |
| expectancy/trade | -24.95 |
| net_pnl | -1172.60 |
| exit_reason_breakdown | `{TARGET_1: 18, STOP_LOSS: 28, EOD: 1}` |

**Not profitable at default parameters on this first look** — reported
plainly, not minimized. `[F]` Zero persistence:
`BacktestResultRecord` **208 before, 208 after**.

**One genuinely new, honest exit path this design surfaces that Gainz
never showed**: 1 trade closed `EOD` (end-of-data, still open when the
series ran out) — a real, expected consequence of a SINGLE-target
design with no forced ladder exit; not a bug.

## 5. MFE distribution — reused directly, same method `CHECKPOINT_75` used

Per this checkpoint's own instruction, reported as part of THIS
checkpoint's evidence, not deferred to a future diagnostic:

| MFE threshold | Trades reaching it | % of 47 |
|---|---|---|
| ≥ 0.5x ATR | 36 | 76.6% |
| ≥ 1.0x ATR | 32 | 68.1% |
| ≥ 1.5x ATR (current N, the entry trigger) | 26 | 55.3% |
| ≥ 2.0x ATR | 20 | 42.6% |

**Directly comparable to `CHECKPOINT_75`'s Gainz figures, and
meaningfully different**: Gainz reached ≥2.0x ATR only 17.6% of the
time; this strategy reaches it **42.6%** of the time — favorable
excursion is both more common and, by construction (this checkpoint's
own single-target design), always available to reach since the stop
sits at `M=2.5x`, well beyond the `N=1.5x` target itself. **Losing
trades**: 18/29 (62.1%) had ≥0.5x ATR favorable excursion before
reversing into a loss, and 14/29 (48.3%) had ≥1.0x — both notably
HIGHER fractions than Gainz's own losing-trade figures
(`CHECKPOINT_75`: 16.7%/7.1% at the equivalent thresholds). **Read
honestly, not as an endorsement**: this strategy's trades tend to move
favorably before often still reversing into a loss — the same
"trailing-stop candidate" pattern `CHECKPOINT_75` flagged for Gainz
appears here too, and more strongly. This is exactly the kind of
signal a future diagnostic (not this checkpoint) could investigate
further, once Phase D's real gate result exists.

## `MEMORY.md` update — confirmed made

`[F]` Appended (never rewrote) a new entry to `MEMORY.md` §3 recording:
the strategy's parameter schema and design, the M > N honest finding
and its runtime-guard resolution, the 19-test result, and the first
real backtest + MFE distribution (both explicitly labeled "first look,
not a validation gate"). Matches the file's existing structure and
tone. **Confirmed explicitly here, as this checkpoint's own
instruction required.**

## 6. Full suite — one self-inflicted, self-diagnosed test failure, fixed

First full-suite run surfaced **6 failed** (5 pre-existing, documented
at every checkpoint this session, plus **1 genuinely new**:
`test_checkpoint_64_48_gainz_adapter_design.py::
test_j_gainz_remains_unintegrated`). Investigated directly: that test
scans EVERY `.py` file in the strategies directory and asserts the
word "gainz" (case-insensitive) appears in NONE of them except one
specific, allow-listed file — `vwap_mean_reversion.py`'s own
docstrings/comments referenced a differently-named strategy by name
several times (explaining design contrasts, citing precedent), which
is exactly what that test exists to catch, working as designed. **Not
a bug in the test — a real violation of a real, intentional
architectural guard.** Fixed by rephrasing every such reference in
`vwap_mean_reversion.py` to describe the same design points without
naming that strategy (e.g. "an independently-chosen multiple further
than what price typically reaches" instead of naming it; citing
`atr_volatility_breakout.py`'s own "never fabricate a plan from
missing data" precedent instead, which is an equally accurate,
already-real citation for that same point). Re-ran the affected test
directly — passes. Confirmed `grep -i gainz` on the strategy file now
returns zero matches.

**Full suite re-run after the fix: 7 failed, 3327 passed**, 639.63s.
Exact names:

1. `test_checkpoint_64_52_database_first_backtest.py::test_f_partial_gap_fetches_only_the_missing_range`
2. `test_checkpoint_64_52_database_first_backtest.py::test_g_data_completeness_is_enforced_not_row_existence`
3. `test_migration_67_11_6_backup_restore_rehearsal.py::test_canary_backup_restores_with_exact_field_preservation_in_disposable_db`
4. `test_migration_67_12_pre_integrity_hardening.py::test_h_live_backup_restored_three_way_equality`
5. `test_api_boundaries.py::test_application_services_and_contracts_stay_infrastructure_free`
6. `test_checkpoint_64_48_gainz_adapter_design.py::test_k_no_gainz_reference_file_exists_in_repo`
7. `test_checkpoint_64_49_gainz_feature_registry.py::test_zz_no_real_gainz_source_file_exists`

**5 are the same pre-existing failures documented at every checkpoint
this session** (none touch this checkpoint's diff). **The other 2
(#3, #4) are the same stale-disposable-table-row flake first
documented at `CHECKPOINT-GAINZ-C`'s §4/§5** — re-ran both with
`--create-db` directly and both **passed**. `test_j_gainz_remains_
unintegrated` (the failure this checkpoint itself caused and fixed
above) is confirmed absent from this final list. **Zero genuine
regressions.**

## Governance compliance

- P3: zero DB writes — the only backtest calls were `run_backtest()`
  direct, never `BacktestingService.run()` (`BacktestResultRecord`
  unchanged, 208→208, confirmed directly).
- P9: no strategy other than `vwap_mean_reversion.py` touched — every
  other strategy file, including `gainz_compatible_research.py`,
  confirmed untouched (`git status --short` shows only the new
  strategy file and its test).
- `registry.py`: confirmed untouched.
- No `RESEARCH_ACTIVE` status change, no new backfill.
- P11/P16: this summary, `MEMORY.md`, the new strategy file, and the
  new test file committed to `active-development` only.
  `VWAP_STRATEGY_ROADMAP.md` remains uncommitted per its own
  established convention.
