# Gainz Signal Engine — Research Audit (Checkpoint 64.96)

## Status
AUDIT-ONLY. Gainz remains DISABLED. No production code exists or was created from this reference. This document is research/architecture documentation, not a specification for an active strategy.

## Reference Source
`docs/research/gainz_signal_engine_reference.py`, supplied by the user at Checkpoint 64.96. The file's own header states it is a "research & rebuild" implementation "inspired by the PUBLICLY VISIBLE GainzAlgo V2 Alpha logic" and explicitly NOT the proprietary GainzAlgo implementation. This document treats that statement as controlling and never claims authenticity or mathematical equivalence to any real GainzAlgo product.

A separate, unrelated, project-authored file (`src/intraday/trading_engine/strategy_execution/strategies/gainz_compatible_research.py`, Checkpoint 64.50) predates this reference file and remains unregistered/inert; it is not derived from this reference and was not touched this checkpoint.

## Verified Public Concepts
- Bullish/bearish engulfing candlestick pattern — a well-known, textbook technical-analysis pattern, not proprietary to any vendor.
- ATR-multiple stop-loss / risk:reward target ladder — a widespread, non-proprietary risk-management technique used across many independent trading systems.

## Inferred Concepts
- "Stable candle" body-ratio filter (threshold 0.70) — plausible as a public "Alpha"-style filter per the reference file's own comment, not independently verified against any external specification.
- RSI 80/20 asymmetric "not exhausted" gate — inferred from the reference file's own comment attribution; not independently confirmed.

## Unverified Concepts
- "Price delta" N-bar close comparison.
- Specific ATR SL/TP multiples (1.0 / 1.0 / 2.0 / 3.0) as authentically GainzAlgo-derived values (vs. the file author's own choice).
- Repeat-signal suppression semantics as a GainzAlgo-specific behavior (vs. generic alerting hygiene).

## Proprietary / Unknown
- The additive point-scoring system across all conditions (weights such as 25, 15, 12, 10, 8, 7...) and the resulting "confidence" blend formula (`dominant*0.85 + separation*0.35 + independent*3.0`).
- The six-profile (alpha/trend/breakout/mean_reversion/hybrid/scalp) consensus-voting architecture.
No external evidence was available to confirm or deny these against a real GainzAlgo specification; they are classified PROPRIETARY-UNKNOWN and must never be presented as verified.

## Architectural Conflicts With This Project
1. **Execution semantics.** The reference engine's entry price is the SAME candle's close (`row["close"]`, evaluated on close). The project's canonical backtest engine (`src/intraday/research/backtesting/historical_execution.py`) fills MARKET orders at the NEXT bar's open — an explicitly documented no-look-ahead convention. These are incompatible as-is; any adapter must translate the reference file's `entry` into an entry CANDIDATE consumed by the existing next-bar-open fill logic, never a same-bar fill price.
2. **Position sizing inside the signal path.** The reference file computes share quantity directly inside `generate_gainz_signals()` (`risk_per_trade`, `max_position_value_pct`). The project's canonical architecture requires all sizing/approval to flow through `RiskDecision`/`OrderIntent` (`domain/risk/contracts.py`, `domain/order/contracts.py`), strictly downstream of any strategy signal. This must never be bypassed.
3. **Confirmed consensus bug.** `consensus_signal()` always attaches the `hybrid` profile's own entry/SL/TP1/TP2/TP3/position_size to every row, regardless of whether `hybrid`'s own per-row signal agrees with, or is even directional alongside, the separately-computed vote-based `consensus_signal`. This can produce a labeled BUY/SELL consensus row carrying `NaN` or even opposite-direction SL/TP values. See `taskReport.md` (Checkpoint 64.96) "Consensus Audit" for the full trace.
4. **Feature duplication risk.** The reference file recomputes RSI/ATR/ADX/EMA/Relative-Volume/MACD-Histogram/Candle-Body-Ratio itself. All seven already exist as canonical features in `src/intraday/signal_intelligence/feature_engine/`. Any adaptation MUST call the canonical functions and must never reintroduce a second indicator implementation.
5. **Terminology.** The six "profiles" share ~90% of their scoring logic and nearly all input features — they are not independent strategies. Any future adapter design must use the term PROFILE (a parameter/weight overlay), never STRATEGY, for these six variants, and must not treat multi-profile agreement as independent confirmation without further design work.

## Known Defects (see taskReport.md Checkpoint 64.96 for full trace)
- Consensus/hybrid risk-level attachment mismatch (CONFIRMED).
- `min_rr` and `require_confirmed_bar` declared in `SignalConfig` but never read/enforced anywhere in the file (CONFIRMED, via full-file search).
- `min_relative_volume` inconsistently applied (scoring bonus respects the config value; the confidence "independent dimensions" count hardcodes 1.0 instead).
- Internal warm-up inconsistency: `_adx()`'s `plus_dm`/`minus_dm` EWMs omit `min_periods=period` while `atr`/`adx` in the same function enforce it.
- EMA-derived conditions (`trend_bull`/`trend_bear`, MACD) have no `min_periods` gating, unlike RSI/ATR/ADX, so they can fire earlier during warm-up than the file's own `valid_data` check accounts for.
- First-bar ATR/True-Range seed effectively uses only `high-low` (both other TR legs are `NaN` on row 0), understating true range on gap-prone opens.

## Stock vs. Stock-Option Limitation
The reference engine is generic OHLCV/underlying-equity logic — it requires only `open, high, low, close, volume` and has zero awareness of strike, expiry, CE/PE, option premium, OI, IV, or Greeks. It cannot be used for option-premium trading without substantial new inputs and design work. `NSE_FNO`, `OptionQuote`, `OI`, `IV`, `Greeks`, `OptionChain`, `OptionBar` remain FROZEN and were not touched by this audit.

## Future Adapter Design (not implemented)
A future, separately-approved checkpoint would need to build:
1. A feature-translation layer calling ONLY canonical `feature_engine` functions.
2. New canonical or strategy-local derived conditions for engulfing / price-delta / breakout (each its own design decision, compared against `atr_volatility_breakout.py` first to avoid duplicating existing breakout logic).
3. A `Strategy`-protocol-conforming class (`parameter_schema()` / `required_features()` / `evaluate()` / `build_trade_plan()`), mirroring the existing `gainz_compatible_research.py` precedent.
4. An explicit, adapter-owned fix (never a patch to the reference file) for the consensus/hybrid mismatch — or omission of multi-profile consensus entirely in a first version.
5. Entry-price handling routed through the existing next-bar-open `HistoricalExecutionSimulator`, never same-candle-close.
6. Complete removal of position-sizing logic from the signal path; sizing/approval delegated entirely to the existing risk engine.
7. A renamed, documented "setup_quality_score" concept if confidence-like output is ever surfaced on a project contract — never named "confidence" or "probability."

## Future Validation Plan (not implemented)
Indicator parity vs. canonical features; warm-up/NaN-handling tests (especially the two warm-up inconsistencies found); closed-candle-only evaluation tests; no-lookahead tests against next-bar-open fills; profile determinism tests; a pinned regression test reproducing the confirmed consensus/hybrid mismatch; repeat-suppression-vs-position-state non-conflation tests; signal reproducibility tests; risk-level direction-consistency tests; position-sizing exclusion-from-signal-path tests; historical reproducibility on a frozen fixture; and correlation-provenance tests that never assert predictive causality.

## Authority
This document supersedes no prior "no authentic Gainz reference exists" statement retroactively — it records that, as of Checkpoint 64.96, a user-supplied RESEARCH/REBUILD reference now exists and has been read and audited, while reaffirming that it is NOT proprietary GainzAlgo source and NOT verified equivalent to it.
