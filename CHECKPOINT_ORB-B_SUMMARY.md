# CHECKPOINT-ORB-B — Summary

Scope: Phase B of `ORB_STRATEGY_ROADMAP.md` — the strategy itself,
using the `opening_range_high`/`opening_range_low` features
`CHECKPOINT-ORB-A` built. `registry.py` untouched, still unregistered.
The paused multi-condition-scorer strategy and the mean-reversion
strategy (Phase D complete, also paused) both untouched.

## 1. What was built

New file
`src/intraday/trading_engine/strategy_execution/strategies/orb_breakout.py`
— `OrbBreakoutStrategy`, matching the real `Strategy` Protocol
structurally identically to `ema_crossover.py` (cited directly as this
file's own structural reference).

**5 parameters** (one more than the mean-reversion strategy's own 4 —
justified below):

| `parameter_id` | Type | Default | Meaning |
|---|---|---|---|
| `opening_range_minutes` | INTEGER | `15` | Opening-window duration |
| `target_range_multiplier` | DECIMAL | `1.0` | Target distance, as a multiple of the range's own size |
| `stop_range_fraction` | DECIMAL | `1.0` | Stop distance as a fraction of range size — `1.0` = opposite boundary itself |
| `minimum_range_atr_multiplier` | DECIMAL | `0` (no-op) | Optional filter: minimum range size, in ATR multiples |
| `atr_lookback` | INTEGER | `14` | ATR period, used only by the filter above |

**`evaluate()`**: `BULLISH` when `close > opening_range_high`,
`BEARISH` when `close < opening_range_low`, a real `NEUTRAL` signal
object otherwise (matching `ema_crossover`'s own convention) or
`None` only during genuine warm-up (window incomplete, per
`CHECKPOINT-ORB-A`'s own no-output rule).

**`build_trade_plan()`**: single target only —
`target = entry + sign × target_range_multiplier × range_size`;
`stop = opposite_boundary - sign × stop_range_fraction × range_size`
(the fraction=1.0 case reduces exactly to the opposite boundary
itself, confirmed algebraically in the module's own docstring and
tested directly). **A structural safety property, not a runtime
guard**: unlike `vwap_mean_reversion.py`'s own M > N cross-parameter
guard, ORB's design makes a degenerate stop-on-the-wrong-side-of-entry
IMPOSSIBLE by construction for any valid parameter combination — since
entry only ever fires strictly beyond a range boundary, and the stop
is always strictly between that boundary and the opposite one. Tested
directly (`test_18`) across the full valid range of
`stop_range_fraction`.

## 2. The `atr_lookback` decision — made explicitly, not by inertia

Per the roadmap's own open question: chose **option (b)** — ATR
included as an OPTIONAL, DEFAULT-DISABLED range-size filter
(`minimum_range_atr_multiplier`, default `0` — a deliberate no-op
default, the same convention this codebase has already established
elsewhere for a comparable quality-gate parameter). **Reasoning**: a
very narrow opening range on a quiet day can produce a "breakout"
that's really just ordinary chop crossing a tiny threshold — not a
meaningfully different market condition from any other small move.
Requiring the range's own size to exceed some ATR-relative minimum
before a breakout is even considered is a real, well-motivated filter
for that specific case — but it's not part of ORB's own core
hypothesis (which is about a session-relative range, not volatility
per se), so it defaults OFF rather than being force-enabled.

**A real design consequence, tested directly**: `atr_{atr_lookback}`
is NOT added to `required_features()` at all when the filter is
disabled (the default) — a configuration that never uses the filter
never needs ATR to warm up (`test_2c`).

## 3. Testing — 21 unit tests, all passing

`tests/unit/research/test_checkpoint_orb_b_breakout_strategy.py`:

- Schema shape, `required_features()`'s exact `opening_range_high_N`/
  `opening_range_low_N` field_id shape (matching `CHECKPOINT-ORB-A`'s
  own exact naming), and the conditional-ATR-requirement behavior
  (`test_1`–`test_2c`).
- Clear BUY/SELL, in-range NEUTRAL (a real signal object, not `None`),
  exact-boundary-is-not-yet-a-breakout, missing/partial range-feature
  warm-up (`test_3`–`test_7b`).
- **The ATR filter, both filtered-out and pass-through cases,
  explicitly**: disabled-by-default lets a narrow range breakout
  through (`test_8`); enabled + narrow range gets filtered to NEUTRAL
  (`test_9`); enabled + wide range passes through (`test_10`); enabled
  but ATR not yet warmed up correctly returns `None`, not a fabricated
  pass/fail (`test_11`).
- Evidence auditability: range high/low always present; range size,
  breakout distance, target/stop price only for non-NEUTRAL
  (`test_12`/`test_13`, hand-computed and verified exactly).
- `build_trade_plan()` arithmetic: BULLISH/BEARISH stop at the
  opposite boundary by default, a tighter stop fraction moving the
  stop inside the range, `None` for NEUTRAL (`test_14`–`test_17`), and
  the structural safety property confirmed directly across the full
  valid parameter range (`test_18`).

## 4. First real backtest — RELIANCE, default parameters, gate-verified dataset

**Explicitly a first look, NOT a validation gate** — Phase D is the
mandatory gate; reported honestly as early evidence only.

`[F]` Data re-checked directly before running (not assumed unchanged):
**still 17 real gate-verified trading days**, unchanged since
`CHECKPOINT-VWAP-B`'s own last check. `run_backtest()` called directly
(never `BacktestingService.run()`), via a LOCAL `StrategyRegistry()`
(`registry.py` untouched), real costs
(`verified_nse_cash_equity_intraday_cost_model()`), default parameter
values, against the full 1,224-bar / 17-day gate-verified dataset (two
blocks, same as every prior Phase B/D this session).

| Metric | Value |
|---|---|
| total_trades | 18 |
| win_rate_percent | **77.78%** |
| average_winner | 76.35 |
| average_loser | -243.78 |
| risk_reward_ratio | 0.31 |
| expectancy/trade | **+5.21** |
| net_pnl | **+93.82** |
| return_percent | **+0.094%** |
| exit_reason_breakdown | `{TARGET_1: 14, STOP_LOSS: 3, EOD: 1}` |

**The most notable finding of this checkpoint**: this is the FIRST
strategy in this entire session to show a genuinely POSITIVE first-look
result at UNMODIFIED default parameters — reported honestly, not
oversold. The high win rate (77.8%, 14/18 trades hitting the single
target) more than compensates for a real risk/reward ratio well below
1.0 (average losers are ~3x larger than average winners) — this is
NOT a "strong R:R" result, it is a "wins far more often than it
loses" one, a materially different profile from every strategy tested
so far this session. `[F]` Zero persistence:
`BacktestResultRecord` **208 before, 208 after**.

## 5. MFE distribution — reused directly, same method `CHECKPOINT_75`/`CHECKPOINT-VWAP-B` both used

| MFE threshold | Trades reaching it | % of 17 |
|---|---|---|
| ≥ 0.5x ATR | 16 | 94.1% |
| ≥ 1.0x ATR | 16 | 94.1% |
| ≥ 1.5x ATR | 15 | 88.2% |
| ≥ 2.0x ATR | 15 | 88.2% |

**By far the most favorable MFE distribution of any strategy tested
this session** — 88.2% of trades reach ≥2.0x ATR favorably (vs. VWAP's
own 42.6% and Gainz's 17.6% at the equivalent threshold, both cited
directly from their own checkpoints). **Losing trades**: 3/4 (75.0%)
had genuine favorable excursion (≥0.5x/≥1.0x ATR, identical count at
both thresholds) before reversing into a loss — a small sample (only
4 losing trades total), so this specific fraction should be read with
real caution, but the underlying pattern (real favorable movement
before some losses) is consistent with what `CHECKPOINT_75`/
`CHECKPOINT-VWAP-B` both already flagged as a trailing-stop candidate
for a future checkpoint — not investigated further here.

**Read honestly, not as a validated edge**: 18 trades on 17 real days,
one symbol, unmodified default parameters, no walk-forward split yet
(that's Phase D). A genuinely encouraging first look — the first one
this session — but a small sample that could easily look very
different on more data or other symbols. Phase D must test this
directly, not assume it holds.

## 6. Full suite

`.venv/Scripts/python.exe -m pytest -q --reuse-db`, full suite, run
directly. **Result: 5 failed, 3377 passed**, 654.75s — exact names
identical to the same 5 pre-existing failures documented at every
checkpoint this session (`test_f_partial_gap_fetches_only_the_missing_
range`, `test_g_data_completeness_is_enforced_not_row_existence`,
`test_application_services_and_contracts_stay_infrastructure_free`,
`test_k_no_gainz_reference_file_exists_in_repo`,
`test_zz_no_real_gainz_source_file_exists`), none touching this
checkpoint's diff. **Zero new failures, zero genuine regressions** —
confirms, among other things, that `orb_breakout.py`'s own "gainz"
mentions were successfully avoided (the strict per-strategy-file scan
`test_j_gainz_remains_unintegrated` passed clean).

## `MEMORY.md` update — confirmed made

`[F]` Appended (never rewrote) a new entry to `MEMORY.md` §3 recording:
the strategy's parameter schema and design, the `atr_lookback`
decision and its reasoning, the 21-test result, and the first real
backtest + MFE distribution (explicitly labeled "first look, not a
validation gate," with the positive result stated plainly but not
oversold). Matches the file's existing structure and tone. **Confirmed
explicitly here, as this checkpoint's own instruction required.**

## Governance compliance

- P3: zero DB writes — the only backtest call was `run_backtest()`
  direct, never `BacktestingService.run()` (`BacktestResultRecord`
  unchanged, 208→208, confirmed directly).
- P9: no strategy other than `orb_breakout.py` touched — every other
  strategy file confirmed untouched (`git status --short` shows only
  the new strategy file and its test).
- `registry.py`: confirmed untouched.
- No `RESEARCH_ACTIVE` status change, no new backfill.
- P11/P16: this summary, `MEMORY.md`, the new strategy file, and the
  new test file committed to `active-development` only.
  `ORB_STRATEGY_ROADMAP.md` remains uncommitted per its own
  established convention.
