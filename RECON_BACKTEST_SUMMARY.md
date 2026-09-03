# RECON-BACKTEST — Strategy & Backtest Engine Reconnaissance

## 1. What strategies exist

`[F]` Exactly **3 registered strategies**
(`registry.py:87-90`, `build_default_registry()`):

| `strategy_id` | Class | Saved configs | Research status |
|---|---|---|---|
| `ema_crossover` | `EmaCrossoverStrategy` | present (multiple) | **`RESEARCH_ACTIVE`** |
| `sma_trend_filter` | `SmaTrendFilterStrategy` | present | no `StrategyResearchStatusRecord` row at all |
| `atr_volatility_breakout` | `AtrVolatilityBreakoutStrategy` | present | no `StrategyResearchStatusRecord` row at all |

`[F]` `StrategyResearchStatusRecord` table has exactly **1 row total**
(`ema_crossover` → `RESEARCH_ACTIVE`). The other two strategies have
never had a research-status record created — not `PAUSED`, not
`DISABLED`, genuinely absent. `[I]` Whatever gate reads this table
needs to define a default for "no record exists" — worth confirming
that default is fail-closed, not assumed permissive.

`[F]` `StrategyConfigurationRecord`: **12 total rows** across the 3
strategies (`ema_crossover` most, `sma_trend_filter`/
`atr_volatility_breakout` fewer) — every strategy has at least one
saved configuration.

## 2. What the backtest engine actually guarantees

`[F]` **Look-ahead bias**: a real, named test exists —
`tests/unit/research/test_backtesting_engine.py::test_future_bars_do_not_affect_earlier_signals`
— plus `test_checkpoint_64_53_backtest_trust.py::test_e_no_signal_before_the_strategy_lookback_is_satisfied`.
Code-level comments (`engine.py:204-205,518`) reference "no look-ahead"
as a deliberate, load-bearing design property (deterministic given
`entry_index + bars`), matching `tradeplan_execution.py`'s own
independent proof.

`[F]` **Cost model scope**: confirmed unchanged —
`cost_model.py:237`, `name: str = "INDIAN_CASH_EQUITY_INTRADAY"`;
`cost_model.py:270`, `verified_nse_cash_equity_intraday_cost_model()`.
NSE cash-equity intraday only, as this session's earlier findings
already established.

`[F]` **Walk-forward / out-of-sample**: `[F]` no file, function, or
test anywhere in `src/` matches `walk.forward|walk_forward|out.of.sample|in.sample`.
**No mechanism exists to separate parameter-fitting from evaluation —
every run is a single in-sample pass.** This is a real, structural gap
in the engine, not merely an unused feature.

`[F]` **Risk engine wiring**: genuinely wired into execution, not
evaluated separately — `engine.py:87` imports
`risk_gate_adapter.build_backtest_risk_context()`, used directly in
the execution loop (`engine.py:410,420`), with its own dedicated test
`test_checkpoint_64_30_risk_gate_wiring.py` (referenced in-code).

## 3. What data is actually research-eligible right now

`[F]` Single query,
`WHERE provenance='REAL_DHAN' AND canonicalization_state='CANONICALIZED'`:

```
TOTAL_GROUPS: 0
TOTAL_ROWS: 0
```

**Zero.** Not "small." Zero, of any symbol, any timeframe, any date.

`[F]` Full breakdown, to explain why:

| provenance | canonicalization_state | timeframe | count |
|---|---|---|---|
| `REAL_DHAN` | `UNCANONICALIZED` | `1m` | 880 |
| `REAL_DHAN` | `UNCANONICALIZED` | `5m` | 10,562 |
| `REAL_DHAN` | `UNKNOWN` | `1m` | 20,880 |
| `UNKNOWN` | `NOT_APPLICABLE` | `5m` | 5,100 |

`[F]` **Even the 10,562 `5m` rows — the one empirically-proven scope
`(NSE_EQ, FIVE_MINUTE, CAS_ERA)` — are `UNCANONICALIZED`, not
`CANONICALIZED`.** `[F]` `MigrationRun`/`MigrationUnit`/`MigrationRow`
counts are all **0** — confirmed directly. This is the actual
mechanism: `canonicalization_state` is written raw at capture time and
only ever flips to `CANONICALIZED` via a separately-authorized,
one-unit-at-a-time migration execution (the entire control plane built
across checkpoints 67.7-67.12.2 this session). **That migration has
never successfully run, not once, against any real row.** The 67.12
attempt HARD_STOPPED (DB-name mismatch); every subsequent checkpoint
(67.12-PRE through 67.12.2-V) hardened the tooling and safety
guarantees around that migration but never re-attempted the real
execution. The entire multi-week canonicalization-safety arc has
produced a fully-proven, fully-tested, zero-times-executed mechanism.

## 4. Has any strategy ever completed a real backtest

`[F]` **No.** `BacktestResultRecord`: 208 total rows, **every single
one** stamped `data_quality.data_source = "HistoricalMarketDataRepository
(fixture/historical only)"` and `trust_level = "POC"`. Confirmed by
querying all 208, not a sample. Several use realistic-looking real
symbol names (`NSE:ADANIGREEN`, `NSE:RELIANCE`-style tickers) via the
fixture repository — **this could visually read as real-data results
to a casual viewer of the results table; it is not.** No human/
checkpoint review record was found tied to any of these results beyond
their own generation (no separate "reviewed" flag or table found).

## 5. The 64.25 convergence-audit question

`[F]` Checkpoint 64.25 (`3104f39`, 2026-08-21): read `run_backtest()`
(`engine.py`) and `run_stateful_backtest()`/`HistoricalExecutionSimulator`
(`historical_execution.py`) in full, attempting to converge them into
one canonical path.

**The actual bug**: the two engines are **P&L-representation-
incompatible**, not merely code-duplication. `engine.py`'s equity-
curve/mark-to-market model is **single-fill-per-position**, baked into
`compute_metrics()` and every downstream caller.
`HistoricalExecutionSimulator` is **fill-granular** and already
correctly handles partial-exit cost-basis accounting, but has **no
per-bar equity curve or mark-to-market curve at all**. Converging them
naively would either lose partial-exit correctness or silently
misrepresent equity/mark-to-market for any strategy that partially
exits a position.

`[F]` 64.25's own commit: **zero files modified besides
`taskReport.md`** — deliberately, per its own documented "stop and
design explicitly rather than corrupt existing results" escape hatch.
Full backend suite re-run, reproduced the same passing count, to prove
nothing regressed while writing zero fix code.

`[F]` **Was it ever fixed later? No.** `git log` on both
`engine.py`/`historical_execution.py`: no commit since 64.25
(`3104f39`, Aug 21) has touched either file. The two engines remain
today exactly as 64.25 left them — `run_backtest()` and
`run_stateful_backtest()` both still exist, both still separate, both
still P&L-model-incompatible.

**This is unresolved and is this recon's single most important
finding.** `[I]` Given `BacktestResultRecord` (§4) shows only
`ema_crossover`-family fixture runs so far, and the strategies with
partial-exit-relevant configurations haven't been run against real
data yet, this bug has not yet caused a real reported number to be
wrong — but the underlying capability to safely represent a
partial-exit strategy's equity curve on real data does not exist, and
nothing since 64.25 has closed that gap.

## 6. Two-line self-assessment

- **Most surprising**: despite this session's entire multi-week focus
  on Dhan timestamp canonicalization safety, the actual count of
  research-eligible `HistoricalBar` rows is **zero** — not because the
  proof or the data don't exist, but because the migration that would
  flip the switch was never executed even once.
- **What determines readiness**: two independent, both-necessary gaps
  block real strategy evaluation today — (1) executing the
  already-proven, already-safe one-unit canonicalization migration
  against real `5m` `REAL_DHAN` data (a data-availability problem,
  solvable by re-attempting 67.12's own already-built process), and
  (2) resolving 64.25's equity-curve/partial-exit engine-convergence
  gap (an engine-correctness problem, requiring real design work, not
  yet started). Foundational backtest-engine work — specifically (2) —
  needs to happen before any strategy formulation that could exit a
  position partially is trustworthy; (1) is closer to done and could
  be re-attempted independently.
