# CHECKPOINT 73 — Summary

Scope: diagnostic investigation into `CHECKPOINT_71`'s finding
(`gainz_aggressive`/`gainz_balanced` consistently unprofitable, zero
sign flips, all 4 symbols). Read-only — no strategy code changes, no
new presets, no registry change, no `RESEARCH_ACTIVE` status change,
no new backfill (reused `CHECKPOINT_70`/`71`'s exact 16-day gate-
verified RELIANCE dataset).

```
symbol_preset_investigated: RELIANCE / gainz_balanced (most data-rich)
total_trades: 72
win_rate_real_costs: 40.3% | win_rate_zero_costs: 43.1%
risk_reward_ratio_real_costs: 0.22 | zero_costs: 0.82
exit_reason_breakdown: {STOP_LOSS: 40, TARGET_1: 32} - ZERO T2/T3 hits
root_cause: (b) risk/reward structure, PRIMARY; (c) transaction costs,
            SECONDARY AMPLIFIER; (a) entry logic - NOT the primary
            driver (Gainz has the best win rate of all 4 strategies
            tested); (d) partially true too - see honest cross-
            strategy comparison below
verdict: (a) fixable design issue, narrowly scoped, precise fix
         described in §6 - NOT implemented this checkpoint
database_write_occurred: NO (BacktestResultRecord unchanged, 208->208)
memory_md_updated: YES - confirmed below
commit: (recorded below)
blockers: []
```

## 1. Trade-level detail — RELIANCE / `gainz_balanced`, full 16-day dataset

`[F]` Ran `run_backtest()` directly (never `BacktestingService.run()`)
against the same gate-verified 1,152-bar / 16-day dataset
`CHECKPOINT_70`/`71` already validated, real costs
(`verified_nse_cash_equity_intraday_cost_model()`):

| | Value |
|---|---|
| total_trades | 72 |
| winning_trades | 29 |
| losing_trades | 43 |
| win_rate_percent | 40.28% |
| average_winner | 8.47 |
| average_loser | -38.48 |
| risk_reward_ratio | 0.22 |
| expectancy | -19.57/trade |
| max_consecutive_losses | 7 |
| net_pnl | -1408.96 |
| total costs paid | 1001.36 |
| exit_reason_breakdown | `{STOP_LOSS: 40, TARGET_1: 32}` |

**The single most important structural fact, read directly from every
one of the 72 individual trades**: not ONE trade ever closed at
`TARGET_2` or `TARGET_3` — every trade closed at either `STOP_LOSS` or
`TARGET_1`. `gainz_balanced`'s TradePlan parameters (`[F]`, read
directly from the preset's persisted config):
`trade_plan_stop_loss_atr_multiplier=1.0`,
`trade_plan_target_1_atr_multiplier=1.0`,
`trade_plan_target_2_atr_multiplier=2.0`,
`trade_plan_target_3_atr_multiplier=3.0` — **the stop and the first
target are the SAME distance from entry.**

`[F]` Traced why T2/T3 are structurally unreachable directly in
`tradeplan_execution.py::simulate_tradeplan_exit()` (unmodified,
read-only — no code touched): the simulator is a **single-shot,
first-level-touched** design — it walks forward bar by bar and returns
the very first bar whose OHLC range touches ANY level (stop or any
target), closing the ENTIRE position there. Since T1 sits at the exact
same distance as the stop, price must always pass through (or touch)
the T1 level before it can ever reach T2's level — so the ONLY way T2
could ever fire is a single bar gapping cleanly past T1 straight to
T2, which the simulator's own documented conservative policy
(`_INTRABAR_POLICY_VERSION`) explicitly resolves toward the NEARER
target anyway ("the lowest-numbered target reached is used"). **T2/T3
are not a rare outcome on this dataset — they are effectively
unreachable by construction, given SL and T1 are configured at equal
distance.** This is not a Gainz-specific code bug; it is a genuine
property of how the shared `simulate_tradeplan_exit()` interacts with
this specific parameter choice (shared by BOTH TradePlan-based
strategies — confirmed in §4, `atr_volatility_breakout` shows the
exact same `{STOP_LOSS, TARGET_1}`-only pattern).

## 2. Win-rate vs. payoff structure — which one is actually broken?

**Both, but not equally.** Win rate (40.3%) is genuinely below 50%,
but it is the BEST win rate of all 4 strategy/preset combinations
tested on this dataset (see §4) — Gainz's entry signal is not
obviously worse at picking direction than the others. The real problem
is the PAYOFF: with `risk_reward_ratio` at just `0.22` (real costs) —
average winners are barely a fifth the size of average losers — even a
40% win rate cannot come close to break-even
(`expectancy = win_rate*avg_winner + (1-win_rate)*avg_loser`, and here
the loser term dominates by roughly 4.5x per trade). **Even at ZERO
cost** (§3), `risk_reward_ratio` is only `0.82` — still below the
`~1.0` a 40-43% win rate would need to approach break-even. **This
points primarily at (b): the risk/reward structure (SL/T1 both at
1.0x ATR) is the dominant issue, not (a) noisy/wrong entry timing.**

## 3. Cost sensitivity — cleanly separable this time, and material

`run_backtest()` accepts an explicit `cost_model` parameter, and
passing `cost_model=None` with `brokerage_percent=0`/
`slippage_percent=0` on the `BacktestConfiguration` cleanly produces a
genuine zero-cost control run (`FlatPercentageCostModel(0, 0)`) against
the IDENTICAL 72 trades (same entries/exits — cost model has no bearing
on TradePlan-driven exit timing) — a clean natural experiment, no code
change needed:

| | Real costs | Zero costs |
|---|---|---|
| win_rate_percent | 40.28% | 43.06% |
| average_winner | 8.47 | 21.71 |
| average_loser | -38.48 | -26.36 |
| risk_reward_ratio | 0.22 | 0.82 |
| expectancy/trade | -19.57 | -5.66 |
| net_pnl | -1408.96 | -407.60 |

**Costs roughly TRIPLE the average per-trade loss** (-5.66 → -19.57)
and are large enough, relative to the small T1 target size (1.0x ATR,
inherently a small dollar move), to flip 2 trades from marginal
winners to net losers outright (win count 31→29, comparing zero-cost
to real-cost on the identical 72 trades). Real per-trade cost averaged
~₹13.9 on a ~₹13,000 notional position (10 shares × ~₹1,310) — roughly
0.11% round-trip, the SAME verified NSE cash-equity cost model every
other checkpoint this session has used, not an inflated or unusual
assumption.

**Honest conclusion on cost sensitivity**: costs are a REAL, material
AMPLIFIER (roughly 3x the per-trade loss) but NOT the root cause — the
zero-cost run is STILL net-negative (`expectancy=-5.66`,
`risk_reward_ratio=0.82 < 1`). Even a costless version of this exact
signal/exit combination does not have a real edge on this dataset; costs
make an already-losing setup meaningfully worse, they do not create
the loss from a break-even baseline.

## 4. Cross-strategy comparison — same real data, same real costs

`[F]` Ran all 3 legacy strategies through `run_backtest()` against the
IDENTICAL 16-day gate-verified RELIANCE dataset, real costs, their own
saved configs:

| Strategy (config) | trades | win_rate | avg_winner | avg_loser | R:R | expectancy | net_pnl |
|---|---|---|---|---|---|---|---|
| `ema_crossover` (`ema_conservative`) | 114 | 16.67% | 49.40 | -29.15 | 1.69 | -16.06 | -1830.84 |
| `sma_trend_filter` (`sma_conservative`) | 11 | 27.27% | 55.29 | -33.52 | 1.65 | -9.30 | -102.32 |
| `atr_volatility_breakout` (`atr_aggresive`) | 46 | 39.13% | 35.56 | -37.94 | 0.94 | -9.18 | -422.28 |
| `gainz_balanced` (this checkpoint) | 72 | 40.28% | 8.47 | -38.48 | 0.22 | -19.57 | -1408.96 |

**The single most important honest finding of this checkpoint:
EVERY ONE of the 4 strategies lost money on this exact real dataset.**
None is a Gainz-specific failure in the sense of "the other 3 work
fine here and Gainz doesn't" — this 16-day real window appears to be
genuinely difficult to trade profitably for all 4 tested
strategy/config combinations, a real possibility explicitly worth
naming rather than dismissed (option (d) from the task's own framing).

That said, the MECHANISM differs meaningfully by strategy family:

- **`ema_crossover`/`sma_trend_filter`** (direction-flip exits, no
  TradePlan): a genuinely FAVORABLE realized `risk_reward_ratio`
  (1.65–1.69 — winners nearly twice as large as losers on average) is
  completely overwhelmed by a very LOW win rate (16.7%/27.3%) — these
  two are entry-signal-quality-limited, not payoff-structure-limited.
- **`atr_volatility_breakout`/`gainz_balanced`** (both TradePlan-based,
  sharing the SAME `simulate_tradeplan_exit()` single-shot mechanism
  and the same `{STOP_LOSS, TARGET_1}`-only exit pattern): both show
  `risk_reward_ratio` at or below `1.0` (0.94, 0.22) despite decent
  win rates (39.1%, 40.3%) — these two are payoff-structure-limited,
  the exact §1/§2 finding, and it is shared infrastructure behavior
  affecting BOTH strategies, not something unique to Gainz's scoring
  formula.

## 5. Honest conclusion

**(a) A fixable design issue, worth a future checkpoint's attention —
but it is an infrastructure/parameter issue shared by both TradePlan-
based strategies, not a Gainz-specific scoring-formula flaw.** The
`gainz_aggressive`/`gainz_balanced` consistent-loss finding from
`CHECKPOINT_71` is real and reproducible at the trade level, and its
mechanism is now understood with high confidence: a symmetric SL/T1
distance (both 1.0x ATR) combined with `simulate_tradeplan_exit()`'s
single-shot-first-touch design makes T2/T3 structurally unreachable,
forcing the REALIZED risk/reward ratio down near 1.0 (and, with real
costs, well below it) regardless of the strategy's actual entry
signal quality — which, for Gainz specifically, is not obviously worse
than the other 3 strategies (its 40.3% win rate is the best of the 4).
This is NOT "inconclusive at this sample size" (option (c)) — the
mechanism is clear and directly traceable in the code, not a
statistical artifact — and it is NOT "an inherent property that would
need a fundamentally different design" (option (b) in the task's own
menu) — the fix is a parameter/configuration change to an EXISTING,
unmodified mechanism, not a redesign.

## 6. Precisely-scoped fix for a future checkpoint (NOT implemented here)

Widen the gap between the stop-loss and target-1 ATR multipliers so a
sub-50% win rate can still produce positive expectancy — e.g. keep
`trade_plan_stop_loss_atr_multiplier` at `1.0` and raise
`trade_plan_target_1_atr_multiplier` to something in the `1.5`–`2.0`
range (a pure config/preset value change, no code change) for all 3
Gainz presets AND `atr_volatility_breakout`'s own preset (since this is
shared `simulate_tradeplan_exit()` behavior, not Gainz-specific, a real
fix likely belongs at the shared-parameter level, not only inside
`gainz_compatible_research.py`). This is a LOW-RISK, narrowly-scoped
change (touches only persisted `StrategyConfigurationRecord` parameter
values, or at most the strategies' own `ParameterDefinition` defaults —
never `simulate_tradeplan_exit()` itself, never `StrategySignal`'s
schema) that a future checkpoint could implement and then re-run
exactly this same walk-forward suite to test directly whether it
changes the sign-flip/consistency pattern `CHECKPOINT_71` found. Not
attempted here, per this checkpoint's own read-only rule.

## `MEMORY.md` update — confirmed made

`[F]` Appended (never rewrote) a new entry to `MEMORY.md` §3 recording
this diagnosis: the trade-level mechanism (symmetric SL/T1 + single-
shot exit simulator making T2/T3 unreachable), the cost-sensitivity
finding (costs triple the loss but are not the root cause), the honest
cross-strategy finding (all 4 strategies lose money on this exact
dataset — a possible data/period effect, not Gainz-specific), and the
precisely-scoped, not-yet-implemented fix candidate for a future
checkpoint. Matches the file's existing structure and tone.
**Confirmed explicitly here, as this checkpoint's own instruction
required.**

## Governance compliance

- P3: zero DB writes this checkpoint — pure read + compute against
  already-backfilled data (`BacktestResultRecord` unchanged, 208→208,
  confirmed directly).
- P9: no strategy logic touched — `gainz_compatible_research.py`,
  `tradeplan_execution.py`, and every other strategy/execution file
  were read but not modified (`git status --short` shows no `src/`
  diff from this checkpoint).
- No registry change, no new presets, no `RESEARCH_ACTIVE` status
  change, no new backfill — all as instructed.
- P11/P16: this summary + `MEMORY.md` committed to `active-development`
  only.
