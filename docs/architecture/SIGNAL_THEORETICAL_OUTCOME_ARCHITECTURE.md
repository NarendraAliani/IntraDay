# Theoretical Outcome

Checkpoint 21. Establishes the first technology-neutral measurement of
what price objectively did after a `DirectionalIndication` (Checkpoint
18) — maximum favorable excursion (MFE) and maximum adverse excursion
(MAE) over an explicit future observation window. This is a
**measurement primitive**, not a trading strategy or research engine.

```
    THEORETICAL OUTCOME = what price objectively did
    STRATEGY             = what a trader decides to do about it
```

No entry rule, stop-loss rule, target rule, position sizing, order
execution, broker integration, or profitability claim exists anywhere in
this bounded context.

```
Market Data → Feature Engine → SMA/EMA/ATR → DirectionalIndication
                                                      ↓
                       ┌──────────────────┬───────────┴───────────┐
                       ↓                  ↓                       ↓
             Signal Verification  Signal Lifecycle      Theoretical Outcome
             (outcome correctness) (temporal validity)   (price-path measurement:
             SUPPORTED/NOT_SUPPORTED/ ACTIVE/EXPIRED      MFE/MAE)
             INCONCLUSIVE
```

All three are independent siblings consuming `DirectionalIndication` —
not a chain.

## Reference price

`indication.price` — the **same** reference price `VerificationResult`
(Checkpoint 19) already uses. Reusing it keeps every signal-intelligence
measurement anchored to the one canonical "what price was known at
signal time" value; introducing a second reference-price convention
(e.g. "first future bar close") would let two measurements silently
disagree about what "the signal price" even means.

## MFE / MAE definition — clamped, not the raw brief formula

```
BULLISH:
    MFE = max(0, max_i(high_i - reference_price))
    MAE = min(0, min_i(low_i  - reference_price))

BEARISH:
    MFE = max(0, max_i(reference_price - low_i))
    MAE = min(0, min_i(reference_price - high_i))
```

where `i` ranges over every future bar in the observation window.

The checkpoint brief's own illustrative formula (`MFE = max(future_high
- reference)`, `MAE = min(future_low - reference)`) is used as the
basis but **explicitly clamped at zero** — a deliberate refinement:
MFE ("favorable excursion") can never legitimately be negative (a
"negative favorable movement" isn't favorable, it's the absence of one);
MAE ("adverse excursion") can never legitimately be positive. Without
clamping, a BULLISH indication whose price only ever rose would report
a spuriously *positive* MAE (low never dropped below reference, so
`min(low - reference) > 0`) — misleadingly suggesting a favorable
minimum instead of correctly reporting "no adverse movement occurred"
(MAE = 0). This clamping makes `MFE >= 0` and `MAE <= 0` universal
invariants, tested directly as Hypothesis properties.

## Observation horizon and future-bar boundary

`horizon_bars: int` — explicit, required, reusing the exact convention
Checkpoint 19's `VerificationResult` already established (no second
horizon abstraction introduced). A bar's timestamp must be strictly
after `indication.timestamp` to count as a future observation — a bar
at the same instant, or before it, is rejected
(`NonFutureObservationError`), never silently included. Only the first
`horizon_bars` future bars are used; extras are accepted but ignored
(mirrors Checkpoint 19's own over-supply policy).

## NEUTRAL semantics

A NEUTRAL indication has no favorable/adverse direction to measure —
`mfe`/`mae` are `None`, never `0` (which would be a real, different,
dishonest measurement implying "no movement occurred" when movement may
well have occurred; it simply isn't classifiable as favorable/adverse
without a direction).

## Partial / missing horizon semantics

`ObservationCompleteness` — `COMPLETE` (≥ `horizon_bars` bars
available), `PARTIAL` (1..horizon_bars-1 available — MFE/MAE **are**
computed from what exists, a real measurement over a shorter-than-
requested window, explicitly flagged so a consumer never mistakes it
for a complete one), `NO_DATA` (zero bars — `mfe`/`mae` are `None`,
never `0`; missing data must remain distinguishable from a genuine zero
excursion). This mirrors, but does not import,
`VerificationResult.outcome`'s own `INCONCLUSIVE` distinction — a
deliberately independent, differently-shaped enum for a differently-
shaped question (see "Relationship with VerificationResult" below).

## Same-bar high/low ambiguity

A single future bar can legitimately contribute to **both** the MFE and
MAE calculation — no claim is made about which occurred first within
that bar. OHLC data alone cannot answer that (it would require intrabar
tick data, out of scope); no target-hit-before-stop/stop-before-target
inference is made anywhere in this module.

## Decimal / financial precision

Full `Decimal` arithmetic throughout — reference price, every bar's
high/low, MFE, MAE. No `float` conversion anywhere. Tested against the
classic binary-float traps (`0.10`, `1.01`, `99.99`, `10000.00`).

## MFE/MAE representation — absolute only, no percentage

Reported as absolute `Decimal` price movement, matching
`VerificationResult`'s own precedent (`reference_price`/`observed_price`
are absolute prices, never percentages). A percentage is trivially
derivable by any consumer (`mfe / reference_price`) — adding both would
duplicate the same information in two representations for no benefit
this checkpoint's scope requires.

## Relationship with VerificationResult — independent

`theoretical_outcome` does **not** import `signal_verification` at all
(mechanically enforced). `VerificationResult` asks a narrower question —
a single-point "was the call supported at exactly N bars out?"
`TheoreticalOutcome` measures richer path behavior — the full excursion
across the whole window. Genuine reuse was considered and rejected:
coupling them would force a consumer of one to pull in the other's
shape even when it has no reason to, and the two calculations solve
different problems (single-point comparison vs. windowed extremes) that
don't share meaningful code, only a superficially similar signature.

## Relationship with SignalLifecycle — independent

`theoretical_outcome` does **not** import `signal_lifecycle` either. An
indication's `SignalLifecycle` can be `EXPIRED` while its historical
theoretical outcome remains perfectly measurable — e.g. an indication
generated at T, lifecycle-expired at T+15m, but a 30-minute observation
horizon still has real historical bars to measure against from T to
T+30m. Signal *validity* (is this still fresh right now?) and
historical *measurability* (what did price actually do?) are unrelated
questions — conflating them would incorrectly gate a legitimate
historical measurement behind an unrelated freshness check.

## Conditional expectancy — explicitly deferred

**Not implemented this checkpoint.** Expectancy requires a defined
trading policy — entry, exit, position size, transaction costs, and an
outcome classification (win/loss) — none of which this bounded context
has authority to invent (the checkpoint brief's own explicit
prohibition). MFE/MAE are objective measurements available *before* any
policy exists; expectancy is a statistic *about* a policy's results and
therefore belongs to a future strategy/research layer (most likely
`research/deep_analysis` or a future strategy-evaluation bounded
context) once `trading_engine/strategy_execution` and a real trading
policy exist to compute it from.

## Identity & versioning

Structural — `(outcome_definition_name, outcome_definition_version,
instrument_id, timeframe, signal_timestamp, horizon_bars)` — the same
convention every prior signal-intelligence contract in this codebase
already established. `outcome_definition_name =
"mfe_mae_price_excursion"`, `outcome_definition_version =
Version(value="v1")`, reusing the existing `Version` primitive, kept
distinct from every sibling contract's own definition fields.

## Immutability & determinism

Frozen dataclass; `compute_theoretical_outcome()`/
`compute_theoretical_outcomes()` never mutate `indication` or any bar.
Identical inputs always produce an identical `TheoreticalOutcome`.

## Architecture enforcement

`signal_intelligence/theoretical_outcome` imports only
`domain/market_data`, `domain/shared_kernel`, and
`signal_intelligence/signal_generation` (for `DirectionalIndication`) —
never `signal_verification`, `signal_lifecycle`, `trading_engine`,
`feature_engine`'s own compute internals, or infrastructure. Verified
two ways: `lint-imports` (6/6 kept) and a dedicated static-scan
architecture test
(`tests/unit/architecture/test_theoretical_outcome_boundaries.py`) that
positively asserts the package's only imports are the documented,
approved set — including the explicit absence of both sibling signal
modules.

## Application layer

`TheoreticalOutcomeService` (`application/services/theoretical_outcome.py`):
composes `HistoricalMarketDataService` (Checkpoint 14, future-bar
retrieval) with `signal_intelligence.theoretical_outcome`'s pure
measurement function — mirrors `SignalVerificationService`'s (Checkpoint
19) exact shape, since real orchestration (bar retrieval) is genuinely
needed here, unlike Checkpoint 20's `signal_lifecycle`. No MFE/MAE
mathematics of its own.

## No persistence, no API, no frontend, no research engine

**None was introduced.** No database model, no DRF endpoint, no
OpenAPI schema change (confirmed: regenerated schema byte-identical in
substance). No backtest engine, walk-forward analysis, Monte Carlo,
strategy optimization, win rate, or profit factor — `TheoreticalOutcome`
is a measurement primitive later research systems may consume, not the
research engine itself.

## Domain promotion assessment

**Not promoted to `domain/` this checkpoint.** `theoretical_outcome` is
now a *fourth* intra-context consumer of `DirectionalIndication` (after
`signal_generation`, `signal_verification`, `signal_lifecycle`) — this
further strengthens the intra-context reuse pattern but does not change
the underlying conclusion: the project's minimum-viable-shared-kernel
rule requires a second **bounded context** (one of the five major
divisions), not a fourth submodule within `signal_intelligence`. No
consumer outside `signal_intelligence` exists yet. This is the same
open architectural question flagged at Checkpoints 19 and 20, now with
a fourth data point and still no resolution — recommend continued
tracking, not treated as closed.
