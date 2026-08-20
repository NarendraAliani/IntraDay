# Strategy Extensibility & Research Architecture Audit

Checkpoint 64.20. A full audit of whether this platform can absorb a new
strategy without touching its core engines, and a formal accounting of
the backtesting/research architecture's current capabilities versus
genuine, disclosed gaps. No new engine was built to satisfy this
document — every claim below is either a direct cross-reference to
existing, passing code/tests, or an explicit, honest "not yet built."

## 1. Strategy Contract — Audited, Confirmed Sufficient

The existing `Strategy` Protocol (`trading_engine/strategy_execution/
strategy.py`, Checkpoint 26) already expresses every element §4 of this
checkpoint's directive asks for:

| Requirement | Existing mechanism |
|---|---|
| identity | `strategy_id: str` |
| name | `display_name: str` |
| version | `specification_version`/`code_version: str` |
| metadata | `display_name` + the module's own docstring (no separate free-form metadata dict exists — not needed; nothing in this codebase currently reads one) |
| parameter schema | `parameter_schema() -> StrategyParameterSchema` |
| default parameters | `ParameterDefinition.default` |
| validation | `validate_configuration()` (`contracts.py`), enforcing `required`/`minimum`/`maximum` |
| required market data | `required_features(config) -> tuple[str, ...]` |
| evaluation | `evaluate(bar, feature_values, config) -> StrategySignal \| None` |
| signal | `StrategySignal` |
| evidence | `StrategySignal.evidence: tuple[FeatureValue, ...]` (Checkpoint 26, populated by every strategy since day one, only wired to persistence/API/UI at Checkpoint 64.18) |

**No new abstraction was introduced.** This audit's conclusion: the
existing contract is already the correct, minimal, generic shape.

## 2. Strategy Registry — Audited, Confirmed Sufficient

`StrategyRegistry` (`registry.py`) already supports every §7 requirement:
`list()`, `get(strategy_id)`, `register()`/`activate()`/`deactivate()`
(lifecycle/status), and `validate_configuration()` (parameter schema
access via the strategy itself). `build_default_registry()` is the ONE
place production strategy classes are imported and registered — adding
a strategy there is the entire "registration" step; nothing else reads
the concrete strategy list.

## 3. Dynamic Parameter Schema — Audited, Confirmed Generic

`ParameterDefinition` (`contracts.py`) already carries `parameter_id`,
`parameter_type`, `default`, `minimum`, `maximum`, `required`,
`help_text` (description; units are conventionally embedded in
`help_text`/`label` text rather than a separate `unit` field — a real,
minor, honest gap, not a blocker). The frontend's `ParameterSchemaFields.tsx`
renders purely from this list — confirmed by grep: zero
`strategy_id === "..."` branches exist anywhere in that component or in
`StrategyConfigurationPage.tsx`.

**Conservative defaults reconfirmed unchanged** (Checkpoint 64.17, not
modified this checkpoint):

| Strategy | Parameter | Default |
|---|---|---|
| EMA Crossover | fast_lookback / slow_lookback | 12 / 26 |
| SMA Trend Filter | lookback / band_percent | 30 / 0.75 |
| ATR Volatility Breakout | lookback / atr_multiplier / stop_loss / target_1 / target_2 / target_3 / trailing_stop | 14 / 2.0 / 1.0 / 1.5 / 2.5 / 3.5 / 1.0 |

Re-verified passing: `test_strategy_schema_endpoint_exposes_the_
conservative_baseline_defaults` (Checkpoint 64.17, unmodified) and
`test_changing_a_strategys_default_does_not_mutate_an_existing_
configuration_record` (existing-configuration immutability, unmodified).

## 4. Generic Signal Evidence — Audited, Confirmed Generic

`build_signal_evidence()` (`evidence.py`) dispatches by `strategy_id`
through one dict (`_DESCRIBERS`) — adding a new strategy's evidence
support is ONE dict entry + one small formatter function, never a
frontend component. The frontend's "Why This Signal?" panel
(`LiveMarketDataMonitor.tsx`, Checkpoint 64.18) renders
`evidence.fields` generically via `.map()` — zero strategy-specific
branches, confirmed by grep. A hypothetical future `VWAP Reversal`
strategy returning `VWAP`/`Price`/`Distance`/`Reversal State`/`Volume
Ratio` fields would render on the EXISTING panel with no frontend
change — this is a direct, mechanical consequence of the generic
`(label, value)` shape, not a claim requiring separate proof.

## 5. Proof-of-Extensibility: TEST_MOMENTUM

New `TestMomentumStrategy` (`trading_engine/strategy_execution/
strategies/test_momentum.py`) — explicitly marked NON_PRODUCTION in its
own docstring and `display_name`, **never added to
`build_default_registry()`** (verified by
`test_test_momentum_is_never_registered_in_the_production_registry`).
Proven, via `tests/unit/trading_engine/test_strategy_extensibility.py`
(4 tests, all passing), to move through:

```
local StrategyRegistry.register()
    -> StrategyConfigurationValues
    -> StrategyExecutionCoordinator.run() (the SAME class backtesting reuses)
    -> StrategySignal (with real evidence)
    -> build_signal_evidence() (generic dispatch)
    -> PaperTradingService (risk) -> PaperBroker (paper execution)
    -> SignalCommunicationService (Telegram/Discord — real messages,
       including "Key Evidence:", faked network boundary only)
    -> DjangoSignalRepository.list_signals() (the same query the Signal
       Operations Center / reports read)
```

with **zero** `if strategy_id == "test_momentum"` branches anywhere in
any of those engines — the test file itself is the mechanical proof.

## 6. Change-Surface Audit (§9)

Files touched to add `TEST_MOMENTUM`, categorized honestly:

| Category | Files | Count |
|---|---|---|
| Strategy-specific (expected, always required for any new strategy) | `strategies/test_momentum.py` (new module) | 1 |
| Strategy-specific tests | `test_strategy_extensibility.py` (new) | 1 |
| Registration (expected, one dict/list entry per new strategy — the SAME pattern any real strategy addition requires) | `evidence.py` (`_DESCRIBERS` dict, +1 entry, +1 small formatter function) | 1 |
| Generic infrastructure changes | none | 0 |
| Unwanted core-engine changes | none | 0 |

`scanner`/`signal_pipeline_runtime.py`, `backtester`/`research.
backtesting.*`, `risk`/`PaperTradingService`, `PaperBroker`,
`communications`/`templates.py`/`signal_communication.py`,
`reports`/`application/reporting/*` — **all confirmed unchanged** by
`git diff --stat` for this checkpoint (only `evidence.py` gained a
dict entry; no other production file outside the new strategy module
and its own test file was touched). This matches §9's own "good result"
shape almost exactly, with the one expected registration line counted
honestly rather than hidden.

## 7. Backtesting Architecture Audit (§10)

Mapped against the target pipeline in the directive:

| Stage | Status | Evidence |
|---|---|---|
| Historical Market Data | EXISTS | `HistoricalBar` (Checkpoint 63.x) |
| Data Quality Validation | EXISTS | `BarAggregationResult.missing_intervals`/`anomalous_observations`, `BarQualityGrade` (Checkpoint 24A) |
| Database-First Retrieval | EXISTS, PROVEN | `test_scanner_reads_only_from_database_never_the_provider_once_complete` (Checkpoint 63.x, re-confirmed 64.16) |
| Session Construction | EXISTS | `session_for_instant()` (real NSE calendar) |
| Timeframe / Bars | EXISTS | `BarAggregationService` |
| Strategy | EXISTS, SHARED | `StrategyExecutionCoordinator` — the SAME class the live path uses (Checkpoint 64.16's confirmed audit: no divergent implementation) |
| Signal + Evidence | EXISTS | `StrategySignal.evidence`, now flows to backtesting the same way (§5 above) |
| TradePlan | EXISTS in the PAPER path (Checkpoint 64.7); **NOT YET simulated in the backtest engine** — see §9 below, a genuine gap |
| Risk | EXISTS in the PAPER path; backtest engine does not currently run signals through `PaperTradingService`'s risk gate — a genuine, disclosed gap (the backtest engine has its OWN, simpler entry/exit/cost simulation, not the shared risk engine) |
| Execution Simulator | EXISTS | `engine.py`/`portfolio.py`, direction-flip based |
| Costs / Slippage | EXISTS | `IndianCashEquityIntradayCostModel` (`cost_model.py`) |
| Positions | EXISTS | `SimulatedTrade`, `OpenPosition` |
| P&L | EXISTS | `compute_metrics()` |
| Performance Analysis | EXISTS (subset — see §14 below) | `BacktestMetrics` |
| Validation / Robustness | PARTIAL — see §16-18 below | `BacktestTrustLevel` exists as a labeling contract; the actual promotion mechanics (walk-forward, robustness perturbation) do not yet exist |

**No parallel/duplicate implementation was found or created.** The one
real architectural gap this audit surfaces — the backtest engine does
not run signals through the shared `PaperTradingService` risk gate or
simulate `TradePlan` stop/target exits — is disclosed honestly below
(§9/§10), not silently worked around or hidden.

## 8. Database-First Backtesting — Re-confirmed, Unmodified

The `check DB → sufficient? → read DB : fetch API → validate → persist
→ read DB → scan` rule (§11) remains proven by the same test cited
above — not re-audited from scratch this checkpoint (64.16 already did
that full audit); this section exists to confirm the rule was not
weakened or bypassed by the strategy-extensibility work, and it was
not (zero files in `research.backtesting`'s data-retrieval path were
touched).

## 9. Data Quality — Confirmed Existing Coverage (§12)

`BarAggregationResult` already distinguishes missing bars
(`missing_intervals`), and anomalous/invalid observations
(`anomalous_observations`) from genuinely clean, `TRADING_GRADE_BAR`
data (`BarQualityGrade`, Checkpoint 24A). Duplicate/out-of-order
handling happens during aggregation (`aggregate_quotes_into_bars`).
Timezone/session-boundary/holiday handling is centralized in
`session_for_instant()` (a single real NSE calendar implementation,
not duplicated per caller). Warm-up periods are handled per-strategy —
`evaluate()` returns `None` until `required_features()` are all
present, never a fabricated early signal (`compute_signals()`'s own
`warmup_bars` counter, `execution.py`). No missing market data is ever
fabricated to fill a gap anywhere in this path.

## 10. Look-Ahead Bias — Confirmed Existing, Mandatory Test (§13)

**Already exists, already mandatory, already passing** —
`tests/unit/research/test_backtesting_engine.py`'s own "No-look-ahead
protection (Part 25, mandatory)" section, specifically
`test_future_bars_do_not_affect_earlier_signals`: truncates the bar
series at an arbitrary point and proves every signal/trade decision up
to that point is IDENTICAL whether or not later bars exist — the
defining test of no-look-ahead bias, already in the suite before this
checkpoint. `test_entry_never_fills_at_the_signal_bars_own_price`
additionally proves entries fill at the NEXT bar's open, never the
signal bar's own price. No new test was needed; this checkpoint's
audit is a confirmation, not a new build.

## 11. Execution Simulation & Intrabar Ambiguity — Confirmed + One Honest Gap (§14/§15)

The execution simulator does NOT assume "signal price = perfect fill":
entries and direction-flip exits fill at the NEXT bar's OPEN (confirmed
by the same look-ahead tests above), and the existing, ALREADY
established `IndianCashEquityIntradayCostModel`
(`verified_nse_cash_equity_intraday_cost_model()`, cost_model.py) is
reused — **no new Indian cost model was invented**, per §14's explicit
instruction.

**Honest, disclosed gap for §15**: the current backtest engine trades
on strategy DIRECTION FLIPS (Checkpoint 27/28's original design), not
on `TradePlan` stop-loss/target simulation — confirmed by reading
`engine.py` in full: there is no stop/target exit code path in the
backtester at all. This means the intrabar "both stop and target
touched in the same candle" scenario §15 asks about **cannot currently
occur** in this engine, because stops/targets are not simulated as exit
triggers during backtesting today (they ARE used in the live PAPER path
via `PaperBroker`, a structurally separate execution engine,
Checkpoint 64.7). This is disclosed here as a real, meaningful gap for
future backtesting fidelity — simulating TradePlan-based exits would
require adding exactly this ambiguity policy at that time — not
something this checkpoint fabricates a policy for today when the
underlying mechanism does not exist yet.

## 12. Performance Metrics — Confirmed Coverage + Honest Gaps (§16)

`compute_metrics()` (`metrics.py`) already produces: Gross Profit/Loss,
Net P&L, Return %, Total/Winning/Losing Trades, Win Rate, Average
Trade/Winner/Loser, Profit Factor, Max Drawdown (+ percent + duration in
bars), and (beyond the directive's own list) trade-level Sharpe/Sortino.
The Mark-to-Market curve (`MarkToMarketPoint`, one point per bar) IS the
Equity Curve and Drawdown Curve the directive asks for — already
computed, already exposed.

**Honest gaps**: `Expectancy`, `Maximum Consecutive Losses`, and
`Risk/Reward` are NOT currently computed fields. Signals/Risk
Approvals/Risk Rejections/Orders/Fills counts exist for the LIVE PAPER
path (Daily Session Report, Checkpoint 64.10/64.17) but are not part of
`BacktestMetrics` specifically (the backtest engine does not run through
the shared risk gate at all — see §7 above). Not built this checkpoint
— disclosed as real, scoped future additions to `compute_metrics()`
rather than fabricated or silently ignored.

## 13. Validation Splits, Walk-Forward, Robustness, Regime Analysis (§17-20)

Audited (`docs/architecture/BACKTESTING_ARCHITECTURE.md`, the existing
`BacktestTrustLevel` contract) — **none of these four capabilities exist
today**, and none were built this checkpoint (per §18's explicit "do
not implement a huge optimizer merely because walk-forward is
desirable," and §20's explicit "do not build a speculative regime
classifier"). Documented honestly as the next research capabilities:

- **Validation splits** (Dev/Validation/Out-of-Sample): `BacktestTrustLevel`
  (POC/RESEARCH_READY/VALIDATION_READY/PRODUCTION_RESEARCH_READY)
  already exists as a LABEL a result can carry, but nothing in this
  codebase currently enforces or computes which level a given result
  earns — every result today is `POC` by construction (per that enum's
  own docstring). A real dev/validation/out-of-sample split would need
  a date-range partitioning convention layered on top of the existing
  `run_backtest(bars, ...)` entry point — a real, buildable, NOT YET
  built extension.
- **Walk-forward validation**: does not exist. Would need a rolling
  re-optimization/re-evaluation harness calling `run_backtest()`
  repeatedly across shifting windows — a genuinely new orchestration
  layer, correctly deferred per the directive's own explicit
  instruction not to build it this checkpoint.
- **Robustness** (slippage perturbation, delayed entry, different date
  windows/stocks/regimes, parameter perturbation, missing/poor data):
  does not exist as an automated suite. `run_backtest()` already accepts
  different bars/config/cost-model per call, so ad-hoc robustness
  checks are POSSIBLE today by calling it repeatedly with varied inputs
  — but no dedicated robustness-test harness or report exists.
- **Regime analysis** (Bull/Bear/Sideways/High-Vol/Low-Vol): no regime
  classifier or regime-segmented reporting exists. Building one
  speculatively was explicitly avoided per §20's own instruction.

## 14. Research Profiles (§21)

Unchanged from Checkpoint 64.17's `docs/research/STRATEGY_DEFAULT_
PROFILES.md`, which already documents exactly the Aggressive/Balanced/
Conservative EMA/SMA/ATR profiles this checkpoint's §21 repeats
verbatim, plus the experiment matrix. Not duplicated here — referenced.
These remain research parameter sets, never trading recommendations,
and this checkpoint did not change any system default (re-confirmed by
the unmodified-defaults test cited in §3 above).

## 15. Strategy Approval Lifecycle (§22) — Documented, Not Implemented

No lifecycle STATE MACHINE or persisted status field exists for this
today (`StrategyRegistry.activate()`/`deactivate()` is a binary
"currently evaluated or not" toggle, not a multi-stage approval
pipeline). Documented here as the intended future model, per the
directive's own "design/document" instruction (not "implement"):

```
DRAFT -> BACKTESTED -> VALIDATED -> PAPER_APPROVED
      -> LIVE_PAPER_VERIFIED -> LIVE_ELIGIBLE
```

`LIVE_ELIGIBLE != LIVE_ENABLED` — critically, no stage in this lifecycle
ever implies real order placement becomes possible. Real trading remains
a SEPARATE, structural, code-level constant (`real_trading_state ==
"DISABLED"`, re-verified every checkpoint since 64.11) that this
lifecycle does not and must not gate — enabling it would require a
distinct, separately-approved capability, not a strategy reaching
`LIVE_ELIGIBLE`.

## 16. Future Strategy Thought Experiment (§23)

For each named future strategy, whether the CURRENT platform supports it
without core-engine changes:

| Strategy | Parameters | Required indicator | Evaluation | Evidence | TradePlan | Risk/Paper/Comms/Report |
|---|---|---|---|---|---|---|
| VWAP Reversal | `ParameterDefinition[]` ✓ | VWAP is NOT in the current `sma`/`ema`/`atr` feature family — a NEW `signal_intelligence.feature_engine` function would be needed (a real, scoped, feature-layer addition, not a core-engine change) | `evaluate(bar, feature_values, config)` ✓ once VWAP is a feature | ✓ generic, via one new describer registration | Optional, strategy's choice | ✓ all unchanged |
| RSI Momentum | ✓ | Same as VWAP — RSI is a new feature family, not yet implemented | ✓ | ✓ | Optional | ✓ |
| Supertrend | ✓ | Composite of ATR + trend logic — buildable from the EXISTING `atr` feature plus new strategy-side logic (no new feature needed) | ✓ | ✓ | ✓ (same TradePlan mechanism ATR strategy already uses) | ✓ |
| Bollinger Mean Reversion | ✓ | New feature (rolling std-dev band around SMA) - `sma` exists, the band itself would be new | ✓ | ✓ | Optional | ✓ |
| Opening Range Breakout | ✓ | Needs a session-open-relative price window — buildable from raw `Bar` data the strategy already receives, no new feature required | ✓ | ✓ | ✓ | ✓ |
| Volume Breakout | ✓ | `Bar.volume` already exists on every bar - a volume-ratio strategy needs no new feature at all | ✓ | ✓ | Optional | ✓ |

**Conclusion**: for 4 of 6 (Supertrend, Opening Range Breakout, Volume
Breakout, and any purely price/volume-derived strategy), the platform
supports the ENTIRE pipeline today with zero core changes — only a new
strategy module + evidence registration, exactly like `TEST_MOMENTUM`
proved. For 2 of 6 (VWAP Reversal, RSI Momentum — and similarly
Bollinger), the one missing generic abstraction is a NEW feature
function in `signal_intelligence.feature_engine` (VWAP/RSI/rolling
std-dev) — a real, identified, narrowly-scoped gap, not a platform
redesign. `compute_feature_series()`'s own prefix-dispatch design
(`sma_N`/`ema_N`/`atr_N`) already anticipates this: adding `vwap`/`rsi`
as a new prefix is the same shape of change as adding a strategy, never
a second engine.

## 17. Over-Engineering Guard (§24)

No ML/AI trade-decision-making, automatic optimizer, portfolio
optimizer, or reinforcement learning was added or proposed as a
near-term build — explicitly out of scope per the directive. The core
trading decision remains deterministic, versioned (`specification_
version`/`code_version`/`configuration_version`), explainable (Signal
Evidence, Checkpoint 64.18), and auditable (signal_id → evidence →
TradePlan → risk → execution → communication → report, proven
end-to-end since Checkpoint 64.16/64.19).
