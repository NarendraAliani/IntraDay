# Market Context Intelligence — Audit & Architecture Design

Checkpoint 65.02. OFFLINE, AUDIT + ARCHITECTURE-DESIGN ONLY. No strategy was
implemented, no live data was fetched, no synthetic data was created. This
document is the Part S deliverable the checkpoint directive calls for; see
`taskReport.md` for the same material in checkpoint-report form, plus the
Final Product Gate Q&A.

## Method

This audit was produced by (1) reading the entire canonical feature engine
(`src/intraday/signal_intelligence/feature_engine/`: `field_registry.py`,
`definitions.py`, `sma.py`, `ema.py`, `atr.py`, `rsi.py`,
`directional_movement.py`, `relative_volume.py`, `macd_histogram.py`,
`candle_body_ratio.py`, `bullish_engulfing.py`, `bearish_engulfing.py`,
`price_delta.py`), (2) a case-insensitive repository-wide search for
`firecell`, `unwind`, `sector`, `regime`, `sentiment`, `correlation`, and
(3) an OFFLINE, read-only query of the local Postgres database (via
`manage.py shell`, no Dhan connection, no worker, no scanner) to check
empirically whether sector, index, breadth or OI data actually exist, rather
than assuming from code alone.

Empirical DB findings (read-only, offline):
- `HistoricalBar`: 5,100 rows, symbols observed are all NSE cash equities
  (e.g. ADANIPORTS, ADANIENT, ADANIENSOL, ADANIGREEN, ADANIPOWER, ATGL,
  SAMPANN) — **no index symbol (NIFTY/SENSEX/sector index) rows exist**.
- `AggregatedBarObservation`: 851 rows (genuine Dhan-sourced, per 65.01) —
  same "no index rows" situation applies; not verified further here since
  65.01 already fully characterized this table's provenance status.
- `OpenInterestObservation`: **0 rows** — empirically confirms NSE_FNO/OI is
  not just architecturally frozen but has zero data present.
- No `Instrument` model/table with a `sector` column, and no sector/breadth/
  sentiment table of any kind exists anywhere in `models.py`.
- `InstrumentType.INDEX` exists only as a domain **enum value**
  (`src/intraday/domain/instrument/contracts.py`) explicitly reserved for
  "market-context/regime-detection... never as tradable instruments" — this
  is architectural intent from an earlier checkpoint, not an implementation;
  no index data has ever been ingested against it.

## Per-Concept Findings

### 1. Short-Term Rebound — `rebound_candidate` IMPLEMENTED (65.04)

**NOT A TRADING SIGNAL. NOT GAINZ-SPECIFIC. NOT PERFORMANCE-VALIDATED.**
`rebound_candidate` is a generic MARKET CONTEXT feature that answers only
"does current price action exhibit a deterministic short-term rebound
setup?" — it is never a BUY/SELL/HOLD recommendation, never a target/
stop-loss/entry, and its default parameters were never tuned against any
outcome data. Whether/how a future strategy acts on this context is
entirely out of scope for the feature layer.

**Module:** `signal_intelligence/feature_engine/rebound_candidate.py`
(`compute_rebound_candidate`). **Definition:** `ReboundCandidateDefinition`
in `definitions.py`. **Registered field ID:** `rebound_candidate`
(`field_registry.py`) — parameterized name shape
`rebound_candidate_{delta_lookback}_{rsi_lookback}_{rsi_oversold_threshold}`
(e.g. `rebound_candidate_10_14_30`), dispatched by
`application.services.strategy_execution.compute_feature_series`.

**Definition (formula/logic):**
```
rebound_candidate(t) = 1  if  price_delta_N(t) < 0
                        AND  rsi_M(t) < rsi_oversold_threshold
                        AND  bullish_engulfing(t) == 1
                    = 0  if all three dependencies are available at t but
                        the combined condition is false
                    = UNAVAILABLE (no output at t) if ANY dependency has
                        no value at t
```

**Dependencies (composed, never recalculated):** `compute_price_delta`
(`price_delta.py`), `compute_relative_strength_index` (`rsi.py`),
`compute_bullish_engulfing` (`bullish_engulfing.py`) — the exact same
public functions the dispatcher already calls for those fields
individually, joined by timestamp. No private indicator math is
reimplemented anywhere in this module.

**Ingredient selection — included vs. deliberately excluded:**
- INCLUDED — `price_delta_N(t) < 0`: establishes the antecedent decline a
  rebound is relative to.
- INCLUDED — `rsi_M(t) < rsi_oversold_threshold`: establishes the decline
  reached a momentum extreme, not just any negative delta.
- INCLUDED — `bullish_engulfing(t) == 1`: establishes a concrete, already-
  canonical reversal candle actually printed at `t`.
- EXCLUDED — `relative_volume`: would add a fourth parameter, and this
  platform's SAMPLE_BAR-sourced fixtures carry `volume == 0` (per
  `field_registry.py`'s own `volume` field docs), so requiring it here
  would make the feature spuriously unavailable across most current
  fixture/historical data for no corresponding conceptual gain. A future
  strategy can already compose `rebound_candidate` with `relative_volume`
  itself at the strategy layer.
- EXCLUDED — `price_vs_ma_pct`/SMA/EMA distance: redundant with the two
  included momentum/decline conditions in virtually every real case;
  adding it would fragment the parameter set without sharpening the
  concept. Left for a future strategy to layer on if a real consumer needs
  it.

**Parameters (minimum set, no arbitrary score/weight):**
`delta_lookback` (→ `PriceDeltaDefinition.lookback`), `rsi_lookback` (→
`RelativeStrengthIndexDefinition.lookback`), `rsi_oversold_threshold`
(integer in `[0, 100]`, compared with strict `<` against the raw RSI
value). None are defaulted inside `ReboundCandidateDefinition` — every
caller supplies all three explicitly, exactly like `PriceDeltaDefinition`.
**RESEARCH DEFAULTS only** (never auto-applied, not used by any production
call site this checkpoint — see `rebound_candidate.py` module docstring):
`RESEARCH_DEFAULT_DELTA_LOOKBACK = 10` (mirrors `price_delta.py`'s own
REFERENCE-ARTIFACT default), `RESEARCH_DEFAULT_RSI_LOOKBACK = 14` (the
standard Wilder RSI period convention `rsi.py` already documents),
`RESEARCH_DEFAULT_RSI_OVERSOLD_THRESHOLD = 30` (the classic textbook RSI
oversold line — a well-known TA convention, **not** threshold-optimized
against any performance data). None of these is a VALIDATED MARKET
PARAMETER; reclassification requires a future checkpoint that actually
validates against real outcome data.

**Warm-up:** purely derived from the three dependencies' own warm-ups —
`price_delta_N` needs `N + 1` bars, `rsi_M` needs `M + 1` bars,
`bullish_engulfing` needs 2 bars. First valid `rebound_candidate` output
is therefore at `max(delta_lookback, rsi_lookback) + 1` bars — no second
warm-up convention was invented. Fewer bars than that → empty tuple.

**No-lookahead:** `rebound_candidate(t)` reads only each dependency's
already-computed value AT timestamp `t`; each dependency independently
already depends only on bars at or before `t`. Verified by a mutation-
style test (`test_f1_no_lookahead_mutating_last_bar_does_not_change_earlier_outputs`
in `tests/unit/signal_intelligence/feature_engine/test_checkpoint_65_04_rebound_candidate.py`)
and a future-bar-extension test.

**Output semantics:** Decimal `1`/`0` — the same boolean-as-Decimal
convention `bullish_engulfing`/`bearish_engulfing` already use.
`FeatureValue.value` has no boolean variant; this is a CONTEXT condition,
never a signal string.

**Edge cases / honest unavailability:** insufficient history, or any one
dependency missing a value at a bar's timestamp, produces NO
`rebound_candidate` output at that bar — never a fabricated 0/1.

**Limitations:** only price-action/momentum-based; carries no volume or
moving-average-distance corroboration by design (see exclusions above);
not validated against any real trading outcome; not connected to any
strategy, Gainz, or the backtest engine this checkpoint.

**Future strategy usage:** a future Strategy-layer checkpoint may read
`rebound_candidate` as one input among others (optionally combined with
`relative_volume`/`price_vs_ma_pct` at that layer) to decide entries — that
decision, and any performance validation, is explicitly out of scope here.

### 2. Moving Average Diversions — `price_vs_ma_pct` IMPLEMENTED (65.03); `ma_divergence` IMPLEMENTED (65.05)
SMA and EMA exist and are fully productionized (`sma.py`, `ema.py`,
`definitions.py`, registered in `field_registry.py`). No dedicated "DMA"
(Daily Moving Average, the NSE-market usage of the term — e.g. "50
DMA"/"200 DMA") field exists distinct from SMA; in this codebase SMA
already fills that role, so a future DMA feature would be a semantic
label/parameterization on the same `SimpleMovingAverageDefinition`
pattern, not a new calculation engine.

**`price_vs_ma_pct` — IMPLEMENTED at Checkpoint 65.03.** Module:
`signal_intelligence/feature_engine/price_vs_ma_pct.py`. Definitions:
`PriceVsMaPctSmaDefinition`/`PriceVsMaPctEmaDefinition` in
`definitions.py`. Registered field IDs: `price_vs_ma_pct_sma`,
`price_vs_ma_pct_ema` in `field_registry.py`. Dispatched by
`application.services.strategy_execution.compute_feature_series()`
(feature names `"price_vs_ma_pct_sma_<N>"` / `"price_vs_ma_pct_ema_<N>"`).

- **Formula:** `price_vs_ma_pct(t) = (close[t] - moving_average(t)) /
  moving_average(t)`, where `moving_average(t)` is the canonical SMA or
  EMA value at `t` (never a new MA calculation). Output is a bare signed
  Decimal fraction (e.g. `0.02` = 2% above the MA), never pre-multiplied
  by 100 and never a boolean: `>0` = price above the MA, `<0` = price
  below the MA, `=0` = price exactly equals the MA.
- **Parameters:** `lookback: int` (the MA period), identical
  parameterization convention to `SimpleMovingAverageDefinition`/
  `ExponentialMovingAverageDefinition` — no hardcoded 20/50/200, every
  caller supplies `lookback` explicitly (no default is baked into either
  `Definition`).
- **SMA/EMA compatibility — design decision:** the existing
  `field_registry.parse_feature_name()` convention (shared by the
  registry resolver and the `compute_feature_series` dispatcher) only
  strips a TRAILING RUN OF INTEGER segments off a feature name to
  recover numeric parameters. MA type ("sma"/"ema") is categorical, not
  numeric, so it cannot be carried as a parameter of one shared feature
  name without breaking that convention for every other feature or
  inventing a second, incompatible parser. The smallest correct fix that
  reuses the EXISTING convention exactly (multi-word kinds followed by
  purely-numeric params are already supported, e.g. `plus_di`,
  `macd_hist`) is TWO field identities — `price_vs_ma_pct_sma` and
  `price_vs_ma_pct_ema` — that both delegate to ONE shared core formula
  function (`price_vs_ma_pct._price_vs_ma_pct_from_ma_series`) and to
  the SAME canonical `sma.compute_simple_moving_average`/
  `ema.compute_exponential_moving_average` functions already used
  everywhere else. No second moving-average engine, no new registry.
- **Warm-up:** identical to the underlying SMA/EMA's own warm-up
  (Checkpoints 15/16) — no new warm-up policy invented. SMA-backed: the
  first `lookback - 1` bars produce no output; the first value appears
  at the bar where the SMA itself first has `lookback` observations.
  EMA-backed: the first value appears at the EMA's own SMA-seeded index,
  identical bar count to the SMA case. "Unavailable" always means NO
  output row exists for that timestamp — never `None`, never a partial
  or fabricated value.
- **No-lookahead:** `price_vs_ma_pct(t)` depends only on `close[t]` and
  `moving_average(t)`, and the underlying SMA/EMA are already proven
  no-lookahead — no future bar can ever influence any output at `t`.
  Verified with mutate-the-last-bar and shorter-vs-longer-series tests
  (Checkpoint 65.03 test suite, section F).
- **Zero/invalid MA handling:** `Bar.__post_init__` already forbids a
  non-positive `close`, but an MA value could still reach exactly zero
  in principle; that output is SKIPPED entirely (never a raw
  `ZeroDivisionError`, never a silently wrong value) — the same
  "skip, never fabricate" discipline `candle_body_ratio.py` and
  `relative_volume.py` already use for their own zero-denominator cases.
- **Applicability:** generic, reusable by any strategy or future context
  layer (EMA crossover, SMA trend filter, ATR breakout, Gainz, or a
  future Market Context consumer) — NOT Gainz-specific, and NOT
  connected to Gainz in Checkpoint 65.03 (Gainz remains completely
  unmodified this checkpoint).
- **Future strategy usage:** none of this checkpoint's existing
  strategies were modified to consume it and the backtest engine does
  not integrate it — it exists purely as a reusable capability a future
  checkpoint (or a future Gainz-consuming layer) may opt into.

**`ma_divergence` — IMPLEMENTED at Checkpoint 65.05.** Module:
`signal_intelligence/feature_engine/ma_divergence.py`. Definitions:
`MaDivergenceSmaDefinition`/`MaDivergenceEmaDefinition` in
`definitions.py`. Registered field IDs: `ma_divergence_sma`,
`ma_divergence_ema` in `field_registry.py`. Dispatched by
`application.services.strategy_execution.compute_feature_series()`
(feature names `"ma_divergence_sma_<fast>_<slow>"` /
`"ma_divergence_ema_<fast>_<slow>"`).

- **NOT A TRADING SIGNAL. NOT A CROSSOVER EVENT. NOT GAINZ-SPECIFIC. NOT
  PERFORMANCE-VALIDATED.** `ma_divergence` outputs a single signed
  numeric ratio and nothing else — no BUY/SELL/HOLD, no `bullish_cross`/
  `bearish_cross`/`crossover_state`, no Gainz weighting or scoring, and
  its exact formula/parameterization has NOT been validated against any
  real trading outcome data. It is a raw, generic, reusable measurement —
  a future strategy or context layer decides what, if anything, to do
  with it.
- **Formula:** `ma_divergence(t) = (fast_ma(t) - slow_ma(t)) /
  slow_ma(t)`, where `fast_ma`/`slow_ma` are the canonical SMA or EMA
  values at `t` (never a new MA calculation). Output is a bare signed
  Decimal fraction (NOT pre-multiplied by 100 — identical convention to
  `price_vs_ma_pct`): `>0` = fast MA above slow MA, `<0` = fast MA below
  slow MA, `=0` = fast MA exactly equals slow MA.
- **Relationship to `price_vs_ma_pct`:** `price_vs_ma_pct` measures
  `close` vs ONE moving average; `ma_divergence` measures ONE moving
  average vs ANOTHER moving average (fast vs slow) — a distinct, generic
  concept, not a duplicate or a rename. Both share the same signed-
  fraction numeric convention, the same "delegate to canonical SMA/EMA,
  never reimplement" discipline, and the same "skip on zero denominator"
  safety rule; `ma_divergence`'s module and this section were written
  directly against `price_vs_ma_pct`'s own precedent.
- **MA-type combinations supported — design decision:** exactly like
  `price_vs_ma_pct`, `field_registry.parse_feature_name()` only strips a
  TRAILING RUN OF INTEGER segments off a feature name, so MA type
  (categorical) cannot be a numeric parameter. `ma_divergence` needs TWO
  MA-type slots (fast, slow), which naively is 2×2 = 4 combinations; this
  checkpoint implements only the two SAME-TYPE identities —
  `ma_divergence_sma` (SMA fast + SMA slow) and `ma_divergence_ema` (EMA
  fast + EMA slow) — deliberately NOT `ma_divergence_sma_ema`/
  `ma_divergence_ema_sma` mixed-type identities, because no canonical,
  non-arbitrary definition of a mixed SMA/EMA divergence exists anywhere
  in this codebase or its research docs, and the directive's own
  "only if justified" gate is not met absent that precedent (unlike the
  same-type identities, which mirror `price_vs_ma_pct_sma`/`_ema`'s
  already-accepted precedent exactly). Both identities delegate to the
  SAME canonical `sma.compute_simple_moving_average`/
  `ema.compute_exponential_moving_average` functions — no second moving-
  average engine, no new registry.
- **Parameters:** `fast_lookback: int`, `slow_lookback: int` — both
  positive integers, and `fast_lookback` must be strictly less than
  `slow_lookback` (validated in `__post_init__`, `InvalidLookbackError`
  otherwise) — fast and slow are NEVER silently swapped. No defaults are
  baked into either `Definition`; every caller supplies both explicitly.
  The classic 9/20, 20/50, 50/200 period pairs sometimes associated with
  "moving average divergence" are NOT hard-coded or defaulted anywhere in
  this module — unlike `rebound_candidate.py`, this checkpoint does not
  even publish RESEARCH DEFAULT constants for them, since no concrete
  consumer has asked for one yet.
- **Warm-up:** purely derived from the two MA dependencies' own warm-ups
  — no second warm-up convention. Because `fast_lookback <
  slow_lookback` is enforced, the slow MA's own warm-up is always the
  later, binding one; the first valid `ma_divergence` output is exactly
  the first timestamp where both the fast and slow MA already have a
  value (SMA-backed: `slow_lookback` bars; EMA-backed: the slow EMA's own
  seed index).
- **No-lookahead:** `ma_divergence(t)` depends only on `fast_ma(t)` and
  `slow_ma(t)`, and both underlying SMA/EMA are already proven
  no-lookahead — no future bar can ever influence any output at `t`.
  Verified with mutate-the-last-bar and shorter-vs-longer-series tests
  (Checkpoint 65.05 test suite, section F).
- **Zero/invalid slow-MA handling:** if `slow_ma(t) == 0`, that output is
  SKIPPED entirely (never a raw `ZeroDivisionError`, never a fabricated
  `inf`/`0`/`None` stand-in) — the same "skip, never fabricate"
  discipline `price_vs_ma_pct.py` already established.
- **Distinction from the `ema_crossover` strategy:** `ma_divergence` is a
  feature-engine MARKET CONTEXT computation, not a strategy — it has no
  BUY/SELL/HOLD decision attached and is completely independent of, and
  was not used to modify, the existing `ema_crossover`/`sma_trend_filter`/
  `atr_volatility_breakout` strategies. A future strategy/context layer
  can derive a crossing EVENT by comparing `ma_divergence[t]` against
  `ma_divergence[t-1]`'s sign — that derivation layer is explicitly OUT
  OF SCOPE for this checkpoint; no `bullish_cross`/`bearish_cross`/
  `crossover_state` logic exists anywhere in `ma_divergence.py`.
- **Applicability:** generic, reusable by any strategy or future context
  layer (EMA crossover, SMA trend filter, ATR breakout, Gainz, or a
  future Market Context consumer) — NOT Gainz-specific, and NOT
  connected to Gainz, any existing strategy, or the backtest engine in
  Checkpoint 65.05 (all remain completely unmodified this checkpoint).

### 3. Sector Deviations — DATA-BLOCKED / MISSING
No sector classification, sector index data, or sector-constituent mapping
exists anywhere in the codebase or database (confirmed empirically: no
`sector` column on any model, `Instrument` model does not even exist in
persistence). Required data: (a) a stock→sector mapping (constituent list),
(b) sector-level return data (either a real sector index feed, or a
derived-from-constituents aggregate), (c) stock return, (d) relative
performance = stock return − sector return. None of (a)–(b) exist. Per the
HARD RULES this checkpoint explicitly does NOT fabricate a sector mapping or
dataset. **Classification: DATA REQUIREMENT / MISSING — hard blocker.**

### 4. Sectorwise DMA — DATA-BLOCKED (depends on Concept 3)
Stock-level DMA (via existing SMA) is available once Concept 2 is built.
Sector DMA requires a sector return/price series, which requires Concept 3's
data first. Potential future outputs (design only): `stock_above_sector_dma`
(boolean), `stock_sector_dma_divergence` (stock DMA-relative-position minus
sector DMA-relative-position), `sector_trend_state` (derived from sector DMA
slope, feeding into the Market Regime layer, Concept 7/8). **Cannot be
implemented until Concept 3's sector data source exists.**

### 5. Fire Sale (formerly referenced as "Firecell") — UNDEFINED, NOT IMPLEMENTED

**Terminology correction (Checkpoint 65.08):** the term "Firecell" used in
earlier checkpoints (e.g. 65.02) was a placeholder. The correct future
research concept is **Fire Sale** — a separate, NOT-yet-defined Market
Stress/Dislocation concept. Fire Sale is NOT implemented in 65.08 (or any
prior checkpoint), has no defined trigger conditions, and is NOT part of
the `market_regime` state vocabulary (BULL/BEAR/SIDEWAYS/TRANSITION only —
see section 7&8 below). Any future "Firecell" reference in older
checkpoint text should be read as this same undefined, not-yet-implemented
Fire Sale concept.


Repository-wide case-insensitive search for `firecell` returns **zero
matches** anywhere: no code, no docs, no tests, no comments, no prior
checkpoint report. This is a genuinely undefined term in this codebase —
not a term this audit is choosing not to look for, but one confirmed absent.
Per the checkpoint's explicit instruction, **no definition was guessed and
none is proposed here.**

**Exact clarification required before any implementation work can begin:**
1. What market phenomenon does "Firecell" describe (e.g., a specific
   price/volume pattern, a specific screener/scanner concept, a term from
   an external tool or vendor, or a proprietary trading-desk term)?
2. What are its precise trigger conditions (which fields, what
   thresholds, what timeframe)?
3. Is it a per-stock signal, a sector-level signal, or a market-wide
   signal?
4. Is there a reference implementation, external document, or named source
   analogous to how Gainz had (and still lacks) a verifiable reference?
Without answers to the above, any implementation would be a guess, which the
checkpoint directive explicitly forbids.

### 6. Unwinding — DATA-BLOCKED / MISSING (partial groundwork for cash-only inference)
No `unwind`-related trading concept exists in the codebase; the only two
repository hits for "unwind" are unrelated (a worker-process shutdown
comment, and a risk-engine architecture-decision record explicitly
*forbidding* the Control Plane from ever originating "emergency unwind
trades" — a governance boundary, not a market-context feature). Two
distinct sub-concepts must be separated per Part I:
- **Cash-equity inference** (long unwinding / position reduction inferred
  from price+volume behavior alone): theoretically buildable from existing
  primitives (`price_delta`, `relative_volume`, EMA/SMA trend state) once a
  precise definition of the pattern is agreed — but no such definition
  exists yet in this repository, so this remains MISSING, not merely
  data-blocked.
- **Derivatives/OI-based inference** (short covering / OI unwinding):
  requires `OpenInterestObservation` data. Empirically confirmed **0 rows**
  in that table, and NSE_FNO is architecturally FROZEN per prior
  checkpoints. **DATA-BLOCKED**, confirmed by direct DB inspection, not
  assumption.

### 7 & 8. Bull / Bear Market Context / `market_regime` — CHECKPOINT 65.08: IMPLEMENTED — RESEARCH DEFAULT

**Status: IMPLEMENTED (Checkpoint 65.08) — RESEARCH DEFAULT. NOT A TRADING
SIGNAL. NOT GAINZ-SPECIFIC. NOT PERFORMANCE-VALIDATED. NOT BREADTH-BASED.
NOT SENTIMENT-BASED. NOT INDEX-CONFIRMED. NOT A FIRE SALE DETECTOR.**

`market_regime` is now a registered, production, PARAMETERIZED categorical
Market Context feature — `signal_intelligence.feature_engine.market_regime`
(`compute_market_regime`), registered in `field_registry.py` as
`FieldDataType.CATEGORICAL`, dispatched by
`application.services.strategy_execution.compute_feature_series`, and
tested in `tests/unit/signal_intelligence/feature_engine/
test_checkpoint_65_08_market_regime.py`. It is upstream MARKET CONTEXT
only — not a strategy, not a BUY/SELL/HOLD signal, not wired into Gainz,
not wired into any existing strategy, not wired into the backtest engine,
not exposed as a scanner strategy.

**State vocabulary (closed, enforced by `market_regime` itself, not by the
generic `CategoricalFeatureValue` contract):** exactly four states —
`BULL`, `BEAR`, `SIDEWAYS`, `TRANSITION`. No `HIGH_VOLATILITY`, `CRASH`,
`RECOVERY`, `PANIC`, `RISK_ON`/`RISK_OFF`. No Fire Sale, no "Firecell"
(see section 5's terminology correction).

**Exact rule (verbatim from the 65.06 design, implemented — not
re-derived — in 65.08):**

```
trend_strength_ok = adx_14[t] >= ADX_MIN
bull_direction     = plus_di_14[t] > minus_di_14[t] AND ema_fast[t] > ema_slow[t]
bear_direction     = minus_di_14[t] > plus_di_14[t] AND ema_fast[t] < ema_slow[t]

BULL       if trend_strength_ok AND bull_direction
BEAR       if trend_strength_ok AND bear_direction
SIDEWAYS   if NOT trend_strength_ok
TRANSITION otherwise
```

**Inputs — canonical only:** `adx_14`, `plus_di_14`, `minus_di_14` (the
canonical Wilder directional-movement family, FIXED at the standard
14-period smoothing — not one of `market_regime`'s own parameters), plus a
canonical `ema_fast`/`ema_slow` pair at caller-supplied lookbacks. No
sector, index, breadth, sentiment, or OI data. No Gainz output. No
EMA-crossover/SMA-trend-filter/ATR-breakout STRATEGY signal.

**Parameters:** `MarketRegimeDefinition(adx_min, ema_fast_lookback,
ema_slow_lookback)` — `feature_name` e.g. `"market_regime_20_9_20"`. All
three are required, explicit, and validated: `adx_min` must be a positive
int, `ema_fast_lookback` must be a positive int, `ema_slow_lookback` must
be a positive int strictly greater than `ema_fast_lookback`. Invalid
inputs raise `InvalidLookbackError` — never silently repaired, clamped, or
swapped.

**`ADX_MIN` is a RESEARCH DEFAULT, not a validated market parameter.** No
value (e.g. 20) is defaulted, auto-applied, or claimed objectively
correct anywhere in this codebase; every `MarketRegimeDefinition`
construction supplies it explicitly, and it has NOT been tuned or
optimized against any backtest/performance data.

**Warm-up:** derived purely from the five dependencies' own warm-ups — the
binding constraint is `max(28, ema_slow_lookback)` bars (28 = ADX's own
`2 * 14` warm-up floor). No separately invented warm-up number.

**Unavailable data:** if ANY of the five dependencies (adx_14, plus_di_14,
minus_di_14, ema_fast, ema_slow) has no value at a timestamp, `market_regime`
produces NO output there — never a fabricated `SIDEWAYS` or `TRANSITION`
fallback. Missing data is not a business state.

**No-lookahead:** `market_regime(t)` reads only each dependency's value AT
timestamp t; every dependency is independently already proven to depend
only on bars at or before t. Verified by a mutation-style future-bar test
and a future-bar-extension test in the dedicated test file.

**Determinism:** pure functions over immutable inputs — no mutable or
persisted state; identical input + configuration always produce identical
categories, timestamps, and ordering. Verified directly by a dedicated
test.

**Boundary/edge cases documented and tested:** `adx_14[t] == ADX_MIN`
(counts as trend-strength-OK, via `>=`); `plus_di_14[t] == minus_di_14[t]`
or `ema_fast[t] == ema_slow[t]` (neither direction condition can hold →
`TRANSITION` if trend-strength-OK, else `SIDEWAYS`); insufficient history
/ missing any dependency (no output); invalid parameters (rejected at
construction).

**Relationship to other Market Context features (none modified):**
- `price_vs_ma_pct` — price relative to a single MA. `market_regime` does
  not use this.
- `ma_divergence` — fast MA relative to slow MA, a signed numeric ratio,
  no state/enum. `market_regime` independently derives EMA fast/slow
  ordering as ONE ingredient of its own rule, but is a categorical STATE,
  never a numeric divergence value.
- `rebound_candidate` — a local, short-term reversal-setup condition (0/1
  Decimal). `market_regime` is a broader trend-strength/direction STATE
  derived from canonical ADX/DI/EMA features, unrelated in scope and
  output type.

**What was explicitly NOT done in 65.08:** no Gainz wiring, no strategy
consumption, no backtest integration, no scanner exposure, no
sector/index/breadth/sentiment/OI data added, no Unwinding, no Fire Sale/
Firecell, no threshold optimization, no new states beyond BULL/BEAR/
SIDEWAYS/TRANSITION.

---

**Superseded prior status (Checkpoint 65.06, kept for history):**

Checkpoint 65.06 set out to implement `market_regime` as a generic,
deterministic Market Context feature classifying current market state
(candidate states: BULL/BEAR/SIDEWAYS/TRANSITION) built only from existing
canonical features (`ema`/`sma`, `adx`, `plus_di`/`minus_di`, `atr`/ATR%,
`price_vs_ma_pct`, `ma_divergence`) — genuinely upstream of any strategy,
never derived from EMA-crossover/SMA-strategy/ATR-breakout/Gainz output.

**Purpose (if/when implemented):** describe current market state as
context available to any future strategy/adapter (including a future Gainz
adapter) — never itself a BUY/SELL decision.

**Finding — Part I output-type gap.** Before writing the rule, the
existing feature-engine architecture was inspected for a categorical/enum
output convention:
- `FeatureValue.value` (`domain/feature/contracts.py`) is declared and
  runtime-enforced as `Decimal` only — `__post_init__` raises `TypeError`
  if the value is not a `Decimal` instance. There is no string/enum
  variant of `FeatureValue`.
- `FieldDataType` (`signal_intelligence/feature_engine/field_registry.py`)
  defines exactly one member: `DECIMAL`. No `CATEGORICAL`/`ENUM`/`STRING`
  member exists anywhere in the registry.
- `compute_feature_series` (`application/services/strategy_execution.py`),
  the sole dispatcher every strategy/backtest/scanner call path goes
  through, returns `tuple[FeatureValue, ...]` — i.e. it inherits the same
  Decimal-only constraint.
- Every feature implemented through 65.05R (`price_vs_ma_pct`,
  `ma_divergence`, `rebound_candidate`) is numeric Decimal, including the
  0/1 boolean-as-Decimal convention `rebound_candidate` uses — there is no
  precedent anywhere in the codebase for encoding a small fixed enum as a
  documented Decimal code.
- This is the *exact same gap* the Checkpoint 64.96 Gainz audit already
  flagged as BLOCKER C: `docs/research/gainz_signal_engine_reference.py`
  computes a plain Python `str` `regime` label (`RANGE`/`BULL_TREND`/
  `BEAR_TREND`/`TRENDING`/`LOW_TREND`) purely as informational metadata —
  never fed through `FeatureValue`, never a scoring input — and
  `gainz_compatible_research.py` classifies that field "REQUIRED BUT
  UNAVAILABLE" and omits it from the production adapter for exactly this
  reason.

**Decision.** Per the 65.06 directive's Part I, forcing a categorical
label into the numeric `FeatureValue.value` field (e.g. abusing sentinel
Decimal codes without any typed contract) would be exactly the "ad-hoc
encoding" the directive prohibits. No genuinely clean, already-existing
representation was found, so implementation was correctly **not**
attempted this checkpoint. The state design work (Parts A/D) was still
completed as research (see `taskReport.md` for the full BULL/BEAR/
SIDEWAYS/TRANSITION rule, the no-lookahead/warm-up/parameterization
design, and the unavailable-data handling) so a future checkpoint can
implement it directly once the type-system extension exists.

**Smallest architectural extension that would be required** (not built
this checkpoint): a categorical `FeatureValue` variant — e.g. either (a) a
sibling dataclass such as `CategoricalFeatureValue` carrying a `str`
member restricted to a documented closed vocabulary plus an `UNAVAILABLE`
sentinel, with `compute_feature_series` widened to a `Union` return type
the dispatcher and downstream consumers explicitly branch on, or (b) a new
`FieldDataType.CATEGORICAL` member paired with a documented
`Mapping[str, Decimal]` code table baked into the field definition itself
(closest in spirit to the "small fixed enum as a documented Decimal code"
precedent the checkpoint asked to verify — but no such precedent currently
exists, so this would be new). Either path touches shared contracts
(`domain/feature/contracts.py`, `field_registry.py`, the dispatcher) used
by every existing feature and strategy, so it is deliberately scoped as
its own future checkpoint's Part I decision, not something to bolt on
inside a single-feature checkpoint.

**Checkpoint 65.07 update — type-system extension now exists,
`market_regime` STILL NOT IMPLEMENTED.** 65.07 built the "smallest
architectural extension" option (a) described immediately above:
`domain/feature/contracts.py` now defines `CategoricalFeatureValue`, a
sibling dataclass to `FeatureValue` sharing the same provenance fields
(`feature_name`/`feature_version`/`instrument_id`/`timeframe`/`timestamp`)
plus a validated non-empty `category: str`, and an `AnyFeatureValue =
FeatureValue | CategoricalFeatureValue` union type.
`field_registry.FieldDataType` gained a `CATEGORICAL` member alongside
`DECIMAL`. `coordinator.FeatureSeriesComputer`'s return type was widened
from `tuple[FeatureValue, ...]` to `tuple[AnyFeatureValue, ...]`. No
closed-vocabulary enum and no `UNAVAILABLE` sentinel were built — 65.07
deliberately did not go further than proving the contract shape (see
`taskReport.md`'s Checkpoint 65.07 section for the full rationale,
including why vocabulary enforcement belongs to each concrete
categorical feature's own definition module rather than this generic
contract). **`market_regime` remains NOT IMPLEMENTED and NOT
REGISTERED** — this status line is unchanged by 65.07; only the
prerequisite type-system gap this section originally identified is now
closed.

**Superseded prior note (pre-65.06, kept for history):**
`STRATEGY_EXTENSIBILITY_AND_RESEARCH_ARCHITECTURE.md` (§13) already
identifies "Regime analysis (Bull/Bear/Sideways/High-Vol/Low-Vol): no regime
classifier or regime-segmented reporting exists" and explicitly instructs
"do not build a speculative regime classifier" ahead of real data — this
audit independently confirms and defers to that finding rather than
duplicating or overriding it. Separately, `docs/research/
gainz_signal_engine_reference.py` (a read-only research reference, not
production code) computes a `regime` label (`RANGE`/`BULL_TREND`/
`BEAR_TREND`/`TRENDING`/`LOW_TREND`) from ADX/DI values purely as
*diagnostic metadata* — `gainz_compatible_research.py` explicitly notes this
`regime` field is classified "REQUIRED BUT UNAVAILABLE" and is **not** used
as a scoring input, and is **omitted** from the production adapter. This is
the closest existing prior art for a regime concept, and it is explicitly
non-authoritative research scaffolding, not a reusable production
component.

Per the directive, Bull/Bear must NOT become two separate strategy engines.
**Design (research only, NOT built):** a single generic `market_regime`
context concept with a small state enum evaluated only after real
ADX/trend/volatility data is available at scale — states to evaluate (not
finalize) are BULL / BEAR / SIDEWAYS / HIGH_VOLATILITY / TRANSITION, derived
from already-existing canonical fields (`adx`, `plus_di`/`minus_di`,
`ema`/`sma` slope, `atr`) plus, eventually, sector/index breadth (Concepts
3/9/10). Any strategy (existing or future, including Gainz) would read
`market_regime` as a context input — never embed its own private regime
classifier, avoiding exactly the duplication the checkpoint forbids.

### 9. Market Sentiment — MISSING, split PRICE/VOLUME vs NLP
Zero repository hits for "sentiment." Per Part H, this must be split:
- **NLP/news sentiment**: explicitly out of scope this checkpoint and not
  designed further here (the directive says "Do NOT implement NLP").
- **Price/volume-derived market sentiment** (deterministic, no NLP):
  theoretically composable from breadth (advancers/decliners), index trend,
  volatility (ATR-based), volume expansion (`relative_volume`), sector
  breadth (Concept 3), dispersion, and highs/lows — **but breadth, index,
  and sector data do not currently exist in this repository** (confirmed
  empirically above). **DATA-BLOCKED** for the price/volume variant; NLP
  variant is out-of-scope/not designed.

### 10. Index vs Stock Correlation — DATA-BLOCKED, and a naming collision to flag
The repository's existing `correlation` code (`correlation_repository.py`,
`correlation_views.py`, `CORRELATION_QUERY_API.md`,
`CORRELATION_TRACEABILITY.md`, `test_checkpoint_64_81_correlation_traceability.py`,
etc.) is **Feature→Strategy→Signal audit-trail traceability** — a
provenance/lineage concept ("which feature computation led to which
signal") — **not** statistical correlation between two price time series.
This audit explicitly does not confuse the two, per the directive's own
warning. No rolling-return correlation, beta, relative-strength, or
index-divergence calculation exists anywhere. Building it requires genuine
index historical bar data, which is empirically absent (no index symbols in
`HistoricalBar` or `AggregatedBarObservation`). **DATA-BLOCKED.**

**Future feature contract (design only, once index data exists):**
- Required interval: same bar interval as the stock series being compared
  (no cross-interval resampling ambiguity).
- Rolling window: a fixed N-bar window over aligned returns (N to be chosen
  by research once real data exists — not fixed here).
- Return definition: simple close-to-close return, `close[t]/close[t-1] - 1`
  (consistent with `price_delta`'s existing close-to-close convention).
- Warm-up: N bars for both series before the first value can be computed.
- Missing index bars: must be treated as an honest gap (skip pairing,
  never forward-fill/interpolate a fabricated index value) — matching the
  platform's existing "no fabricated data" discipline (`FieldAvailability`).
- Session alignment: only bars from the same trading session/timestamp on
  both series pair; unmatched timestamps on either side are dropped rather
  than approximately aligned.

## Existing Feature Reuse Summary

*(Table below is the original 65.02 audit snapshot, kept for history. As of
65.08: "Bull/Bear Regime" is IMPLEMENTED as `market_regime` — see section
7&8 above. "Firecell" is a corrected terminology reference to the
still-undefined, still-NOT-implemented "Fire Sale" concept — see section 5.)*

| Concept | Existing fields it can reuse |
|---|---|
| Rebound | rsi, price_delta, bullish_engulfing, relative_volume, sma/ema |
| MA Diversion | sma, ema (new percent/divergence math needed, no new MA engine) |
| Sector Deviation | none (blocked on sector data) |
| Sectorwise DMA | sma (stock side only; sector side blocked) |
| Firecell | none — undefined |
| Unwinding | price_delta, relative_volume (cash-only, pending definition); OI blocked |
| Bull/Bear Regime | adx, plus_di, minus_di, ema/sma (trend slope), atr |
| Sentiment | relative_volume, atr (price/volume side only; breadth/index blocked) |
| Index Correlation | price_delta's return convention (index data itself blocked) |

## Feature Registry Design (Part N)

No second registry is proposed. `field_registry.py`'s existing
`FieldDefinition`/`_FIELDS`/`_FIELDS_BY_ID` shape, and its
`parse_feature_name`/`resolve_feature_name` parameterized-name convention,
already generalize to any new field. Namespace prefixes such as `context.*`,
`market.*`, `sector.*`, `index.*` are worth evaluating for future context
features to distinguish them from `core.*` per-bar features, but the exact
prefix syntax should be decided against real registry conventions at
implementation time, not finalized speculatively here (per Part N's own
instruction). No change was made to `field_registry.py` in this checkpoint.

## Performance / Scaling (Part O)

Context features (sector, regime, sentiment, index-correlation) will
eventually be computed once per sector/index/timeframe and shared/cached
across every stock that consumes them, rather than recomputed per-stock —
avoiding the N+1 pattern of e.g. recomputing "is NIFTY trending up" once per
scanned symbol. No implementation of caching is done this checkpoint; this
is a forward design note only, per the directive's "do not prematurely
optimize" instruction.

## Narrow Exception (Part C's carve-out)

The checkpoint directive permits one narrow, unambiguous generic feature
addition if "clearly consistent with the existing feature-engine
architecture." This audit evaluated `price_vs_ma_pct` as the candidate and
**deliberately did not implement it**: while the formula itself is
unambiguous, `ma_divergence`'s exact shape (raw vs. percentage vs.
cross-state) is not, and implementing one half of a two-part concept mid-
audit risks exactly the "if in doubt, don't implement" case the directive
warns against. Zero code was added under this exception. See `taskReport.md`
Part C / Final Product Gate B for the explicit STATUS.

## Blockers Summary

| Blocker | Status |
|---|---|
| Sector classification/constituents | MISSING — no code, no data |
| Sector index data | MISSING |
| Index historical data (NIFTY/SENSEX/sector indices) | MISSING — 0 index rows in HistoricalBar or AggregatedBarObservation |
| Market breadth data (advancers/decliners, highs/lows) | MISSING |
| OI data | 0 rows empirically confirmed; NSE_FNO architecturally FROZEN |
| Firecell definition | UNDEFINED — clarification required, see Concept 5 |
| Real, COMPLETE historical session data (carried from 65.01) | Still NO — unrelated to but compounds every above blocker for backtesting purposes |

## Market Context Consumption Contract (Checkpoint 65.09)

OFFLINE, INTEGRATION-CONTRACT checkpoint. Follows 65.08 (accepted, implemented
`market_regime`). No feature's behavior changed here, no strategy was
modified, no code implements any new consumption path. This section documents
how a FUTURE strategy checkpoint could consume the four existing Market
Context features safely — it is a contract description, not new
infrastructure.

### Current features (inventory)

| Feature (field_id) | Output type | Category | Dependencies | Warm-up | Missing-data semantics | No-lookahead | Research status |
|---|---|---|---|---|---|---|---|
| `price_vs_ma_pct_sma` / `price_vs_ma_pct_ema` | `FeatureValue.value: Decimal` (signed ratio) | Price Context | SMA or EMA(lookback) | MA's own warm-up (`lookback`/`lookback-1`) | Skips output when MA==0 (never fabricates) | Yes — depends only on close[t] and MA(t) | Not performance-validated |
| `rebound_candidate` | `FeatureValue.value: Decimal` (1/0) | Rebound Context | `price_delta`, `rsi`, `bullish_engulfing` | `max(delta_lookback, rsi_lookback) + 1` | No output if ANY dependency missing | Yes | Not performance-validated |
| `ma_divergence_sma` / `ma_divergence_ema` | `FeatureValue.value: Decimal` (signed ratio) | Trend Context | two SMAs or two EMAs (fast/slow) | `slow_lookback` | Skips output when slow MA==0 | Yes | Not performance-validated |
| `market_regime` | `CategoricalFeatureValue.category: str` (BULL/BEAR/SIDEWAYS/TRANSITION) | Trend Context | `adx_14`, `plus_di_14`, `minus_di_14`, `ema_fast`, `ema_slow` | `max(28, ema_slow_lookback)` | No output if ANY of the five dependencies missing | Yes | Not performance-validated |

All four are single-instrument, single-timeframe, single-timestamp
computations (Part H) — none reads across instruments or timeframes.

### Does the existing architecture already support consumption?

Yes, for numeric context, with zero new abstraction. `price_vs_ma_pct_*` and
`ma_divergence_*` are already registered `field_registry` entries with
`FieldDataType.DECIMAL`; a strategy that lists one in `required_features()`
would already receive its `FeatureValue` through the existing
`feature_series_cache` → `latest_features` → `strategy_features` path in
`StrategyExecutionCoordinator.run()` — no `ContextRegistry`,
`MarketContextEngine2`, or per-strategy adapter is needed. No strategy does
this today, and none is being wired to do so in this checkpoint.

For categorical context (`market_regime`), the existing architecture has a
real gap, not a missing engine. `field_registry._derived_categorical()`
already tags `market_regime` as `FieldDataType.CATEGORICAL`, and
`compute_feature_series()`/`feature_series_cache` are already typed
`AnyFeatureValue` (`FeatureValue | CategoricalFeatureValue`, 65.07). But
`StrategyExecutionCoordinator.run()` narrows the per-bar snapshot to
`latest_features: dict[str, FeatureValue]` before calling
`Strategy.evaluate()`, and `Strategy.evaluate()`'s own signature is
`feature_values: dict[str, FeatureValue]`. If a future strategy declared
`market_regime` in `required_features()` today, the coordinator would put the
`CategoricalFeatureValue` object into that `dict[str, FeatureValue]` anyway
(Python does not enforce the annotation at runtime) — an untyped, silently
wrong value would reach `evaluate()`. No current strategy does this, so this
latent mismatch has no live effect this checkpoint, but it means: **a
categorical-aware strategy cannot be added safely without a small, explicit
type change** — see "Categorical Consumption Boundary" below. That change is
NOT made in 65.09.

### Numeric context

A future strategy consumes `price_vs_ma_pct_*` / `ma_divergence_*` /
`rebound_candidate` exactly as it consumes `sma`/`ema`/`rsi` today: list the
parameterized field_id in `required_features()`, read the matching
`FeatureValue` from the `feature_values` dict `evaluate()` already receives,
and check `value` against its own thresholds. No contract change required.

### Categorical context

A future strategy that wants `market_regime` needs `Strategy.evaluate()`'s
`feature_values` parameter type widened from `dict[str, FeatureValue]` to
`dict[str, AnyFeatureValue]` (or an equivalent explicit union), and
`StrategyExecutionCoordinator.run()`'s `latest_features`/`strategy_features`
dicts widened to match — otherwise `FeatureValue.value: Decimal`'s type
safety is not weakened, but the categorical value passed through it is
untyped. This is the smallest correct change: it does not require a new
protocol method, a second dispatch path, or a strategy-specific adapter —
only a type widening at the one seam where numeric and categorical series
already merge. **Not made in 65.09** — no current strategy requires it.

### Time alignment

All context consumption must be for the SAME `instrument_id`, the SAME
`timeframe`, and the SAME `timestamp` as the strategy's own bar/feature
evaluation — exactly what `StrategyExecutionCoordinator.run()` already
enforces by keying `latest_features` off `latest_bar.timestamp` alone. No
multi-timeframe or cross-instrument context contract exists or is
implemented here; a future strategy must not attempt to align a context
feature computed on a different timeframe or a different instrument without
an explicitly designed (not yet built) multi-timeframe contract.

### Missing context

Every one of the four features already follows "no output at t" rather than
a fabricated value (never `False`/`0`/`SIDEWAYS` as a stand-in). A future
consumer must preserve this: `field_id not in feature_values` (or
`feature_values.get(field_id) is None`) means UNAVAILABLE, and must be
branched on explicitly — never treated as "condition is false" or defaulted
to any specific category/value. This is exactly `StrategyExecutionCoordinator
.run()`'s existing `strategy_features = {fid: latest_features[fid] for fid in
required if fid in latest_features}` behavior (a missing field_id is simply
absent from the dict, not present with a placeholder) — no new semantics
required, only documented as a contract a future strategy's `evaluate()` must
honor.

### Provenance and correlation

`FeatureValue` and `CategoricalFeatureValue` already carry identical
provenance fields — `feature_name`, `feature_version`, `instrument_id`,
`timeframe`, `timestamp` — so a future context-aware strategy loses no
traceability by consuming either. No second correlation system is proposed;
the existing `field_registry.resolve_feature_name()` / `ResolvedFeatureName`
mechanism (64.81) already resolves a parameterized context feature name
(e.g. `market_regime_20_9_20`) back to its registry `field_id` exactly as it
does for `ema_20` today — the same Feature → Strategy → Signal → Trade →
Outcome correlation path future checkpoints would use for context features
is the one that already exists for numeric ones.

### Strategy consumption boundary

Context Feature ≠ Strategy ≠ Signal, frozen explicitly: a context feature
(e.g. `market_regime`) describes market state only; a strategy interprets
context plus its own strategy-specific conditions; a signal is the strategy's
resulting actionable BUY/SELL/HOLD decision. No context feature module
computes or embeds a BUY/SELL/HOLD decision, and none may become a hidden
signal generator — decision logic belongs exclusively in the strategy layer.

### Feature namespacing

No new namespace is introduced. `field_registry`'s existing
`FieldCategory.DERIVED_FEATURE` / `FieldDataType` pair already distinguishes
"what kind of data" (numeric vs. categorical) from "what family" via the
field_id itself (e.g. `price_vs_ma_pct_*`, `ma_divergence_*`,
`rebound_candidate`, `market_regime` are already self-describing names); no
core-vs-context field naming rule was found missing. No mass rename is
proposed.

### Grouping

The four features fall into three informal, documentation-only groups (not a
second registry): **Price Context** (`price_vs_ma_pct_sma`,
`price_vs_ma_pct_ema`), **Rebound Context** (`rebound_candidate`), **Trend
Context** (`ma_divergence_sma`, `ma_divergence_ema`, `market_regime`).

### Gainz relationship

Gainz (`gainz_compatible_research`) MAY consume any of these four features in
a future checkpoint via the same `required_features()` / `evaluate()`
contract described above. Gainz is NOT modified and NOT connected to any
context feature in 65.09.

### Deferred concepts (unchanged)

Sector Deviation, Sectorwise DMA, Index-vs-Stock Correlation, Market
Sentiment, Unwinding remain deferred — blocked on missing sector/index/
breadth/OI data (see Blockers Summary above), unchanged by this checkpoint.
Fire Sale remains a deferred FUTURE Market Stress/Dislocation concept, not
implemented and not added to `market_regime`'s vocabulary. "Firecell" remains
a retired/invalid term.

## First Strategy Integration (Checkpoint 65.10)

OFFLINE checkpoint. Implements the 65.09-recommended first integration:
`sma_trend_filter` now consumes `price_vs_ma_pct_sma` through the existing
`required_features()` / `evaluate()` contract described above — the FIRST
live-eligible strategy (one of the three in `build_default_registry()`) to
consume a reusable Market Context feature. `ema_crossover` and
`atr_volatility_breakout` are unchanged. Gainz is unchanged and not
connected to any context feature. `market_regime`, `rebound_candidate`, and
`ma_divergence` remain unconsumed by any strategy.

**Exact change**: before 65.10, `sma_trend_filter` declared a raw `sma_N`
dependency and computed `(price - sma) / sma` INLINE via a
`band = sma * band_percent / 100` comparison. That inline computation is
exactly the `price_vs_ma_pct_sma` formula. 65.10 replaces the raw `sma_N`
dependency with `price_vs_ma_pct_sma_N` and reads the ratio directly from
the canonical `FeatureValue` — the strategy no longer computes MA distance
itself. This is a substitution of the existing computation's source, not an
added computation.

**Role of the context feature**: REQUIRED CONDITION. `price_vs_ma_pct_sma`
does not sit alongside the strategy's existing threshold decision as
additional confirmation or a separate filter — it IS that decision. This is
the only role consistent with the strategy's own pre-existing documented
intent ("how far is price from its SMA, in percent, BULLISH/BEARISH beyond
a configured band"), which is precisely what `price_vs_ma_pct_sma` computes.
No new trading semantics were invented; the BULLISH/BEARISH/NEUTRAL
threshold logic and the `band_percent` parameter are unchanged bit-for-bit —
only the source of the ratio moved from local arithmetic to the canonical
feature.

**Configuration**: no new parameter was introduced. `band_percent` (existing,
`default=0.75`, already documented as a RESEARCH DEFAULT / conservative
starting point — see `docs/research/STRATEGY_DEFAULT_PROFILES.md`) is
divided by 100 to convert it from a configured percent into the same signed-
fraction units `price_vs_ma_pct_sma` already outputs — a unit conversion
only, not a new threshold.

**Missing context**: unchanged contract. `sma_trend_filter.evaluate()`
returns `None` when `price_vs_ma_pct_sma_N` is absent from `feature_values`
(warm-up incomplete, feature not computed, etc.) — exactly as it returned
`None` for a missing `sma_N` before 65.10. No 0/neutral/FALSE default was
introduced.

**Evidence**: `StrategySignal.evidence` now carries the `price_vs_ma_pct_sma`
`FeatureValue` (feature_name, feature_version, instrument_id, timeframe,
timestamp, value) verbatim, in place of the previous raw `sma` `FeatureValue`
— never reconstructed after signal generation.

**Does NOT establish performance improvement.** No threshold was optimized,
no backtest comparison was run, and no historical return was measured. This
checkpoint is a correctness-of-integration change only — see
`taskReport.md` (Checkpoint 65.10) for the full Final Product Gate.

## First Backtest-Level Correctness Validation (Checkpoint 65.11)

OFFLINE, CORRECTNESS-ONLY checkpoint. Follows 65.10 (accepted). Proves, for
the first time at the BACKTEST level (not just the strategy-unit level),
that the wiring `Historical bars → canonical price_vs_ma_pct_sma →
sma_trend_filter → StrategySignal → existing backtest execution path`
mechanically works — using the EXISTING, UNMODIFIED canonical backtest
engine. **No production code was changed in this checkpoint** — only a new,
additive test file
(`tests/unit/research/test_checkpoint_65_11_sma_backtest_integration.py`)
was added.

### Exact execution path

`intraday.application.services.backtesting.BacktestingService.run()` →
`intraday.research.backtesting.engine.run_backtest()` — confirmed by direct
inspection of both modules before writing any test code (not assumed from a
prior checkpoint's summary). Feature computation inside the engine goes
through `research.backtesting.execution.compute_signals()`, which calls the
SAME `compute_feature_series` dispatcher
(`application.services.strategy_execution.compute_feature_series`) the live
`StrategyExecutionCoordinator` uses — the identical dispatcher, not a
test-local reimplementation.

### Data used and why this is ENGINE VALIDATION ONLY, not research evidence

Verified directly against the live database before writing any test (not
assumed unchanged from 65.00/65.01): `HistoricalBar` currently holds 5,100
rows, **all** labeled `source='API_FETCH'`, spanning only NSE cash-equity
symbols (no index rows), with no genuinely-complete real historical session
ever confirmed — the same unresolved data situation established in
65.00/65.01/65.02 is still present, unchanged. Given that, this checkpoint
does **not** read from `HistoricalBar`/`AggregatedBarObservation` and does
**not** touch the real database at all. Instead it constructs a small,
explicit, obviously-synthetic, deterministic fixture (12 one-minute bars,
flat warm-up then a clean step up then a clean step down, a pure function of
bar index) purely to exercise the mechanical wiring. Both repositories
`BacktestingService` depends on (`HistoricalMarketDataRepository`,
`BacktestResultRepository`) are satisfied by small in-memory test-local
fakes conforming to their real `Protocol` definitions — never a Django/
Postgres-backed implementation, so nothing in the test file can write to, or
read fixture data from, the production database. **Classification: ENGINE
VALIDATION ONLY.** No P&L, win-rate, or any other metric produced by this
test is interpreted as research evidence of strategy performance.

### What was verified

- **Feature availability / warm-up**: `price_vs_ma_pct_sma_5` becomes
  available at exactly the bars the underlying SMA(5)'s own warm-up permits;
  asserted as "feature missing at t ⇒ signal absent at t" via
  `compute_signals()`'s own `warmup_bars`/`None`-signal behavior, not a
  hard-coded bar count.
- **Equivalence**: the legacy pre-65.10 formula `(close - SMA) / SMA`,
  computed independently in the test, is numerically identical
  (`==` on `Decimal`) to the canonical `price_vs_ma_pct_sma` value at every
  timestamp in the fixture, and the resulting BULLISH/BEARISH/NEUTRAL
  classification computed from each is identical for every bar — a
  correctness check, not a performance claim.
- **Missing context**: `sma_trend_filter.evaluate()` with an empty
  `feature_values` dict returns `None` — never a fabricated NEUTRAL/0
  signal.
- **Execution semantics**: every simulated trade's `entry_price` equals the
  `open` of the bar immediately after the triggering signal bar — the
  existing next-bar-open fill rule (confirmed by reading `engine.py` lines
  ~371-373 before writing the test), unchanged and unaltered by this
  checkpoint.
- **Evidence**: every non-`None` `StrategySignal.evidence` tuple contains
  exactly one `FeatureValue` with `feature_name` starting with
  `price_vs_ma_pct_sma`, and populated `feature_version`, `instrument_id`,
  `timeframe`, `timestamp` (matching the signal's own timestamp), and
  `value` — read directly off the value the strategy consumed, never
  reconstructed after the backtest.
- **Determinism**: the exact same deterministic configuration run twice
  through `BacktestingService.run()` produces the same `backtest_id`, the
  same trade sequence (entry/exit timestamps, prices, direction, net P&L),
  and — via a second independent `compute_signals()` call — the same
  signal directions, timestamps, and evidence values, bar for bar.

### What this does NOT prove

Not proven, and not claimed: strategy profitability, predictive value, or
any historical performance improvement; correctness of `price_vs_ma_pct_sma`
or `sma_trend_filter` against REAL market behavior (both remain
research-status "not performance-validated" — unchanged by this
checkpoint); anything about `market_regime`, `rebound_candidate`, or
`ma_divergence` (still unconsumed by any strategy); anything about Gainz
(unmodified, untouched). See `taskReport.md` (Checkpoint 65.11) for the
full Final Product Gate Q&A.
