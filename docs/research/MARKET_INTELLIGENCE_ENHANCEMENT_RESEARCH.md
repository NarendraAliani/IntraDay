# Market Intelligence & Strategy Enhancement — Research

Checkpoint 65.14-R. RESEARCH/DESIGN ONLY — no production code, migrations,
database, live Dhan, or strategy changes were made while producing this
document. Every claim below about current code was verified by reading the
actual module, not recalled from prior checkpoint summaries.

## 1. Executive Summary

This checkpoint researches ten proposed market-intelligence concepts
requested for the FO Scanner platform: Short-Term Rebound, MA Divergence,
Sector Deviation, Sector-wise DMA, Fire Sale, Unwinding, Bull Regime, Bear
Regime, Market Sentiment, Index vs Stock Correlation.

Headline finding: **three of the ten already have real, tested production
implementations** (Short-Term Rebound → `rebound_candidate`; MA Divergence →
`ma_divergence_sma`/`ma_divergence_ema`; Bull/Bear Regime → `market_regime`,
which folds both bull and bear into one categorical feature). Re-implementing
these under new names would be pure duplication and is explicitly rejected.
The remaining seven require data this platform does not yet have (sector
mapping/index series/OI) or are external dependencies (sentiment feeds) that
should not be added speculatively. None of the ten should be implemented in
this checkpoint; two (Sector Deviation, Index↔Stock Correlation) are the
highest-value additions once index/sector data exists.

## 2. Current Capability Inventory (Part 1)

Verified against `src/intraday/signal_intelligence/feature_engine/` and
`field_registry.py` (`_FIELDS` tuple) directly.

| # | Concept | Status | Evidence |
|---|---|---|---|
| 1 | Short-Term Rebound | **ALREADY IMPLEMENTED** (as *candidate* detector only) | `rebound_candidate.py`: `price_delta_N<0 AND rsi_M<threshold AND bullish_engulfing==1` |
| 2 | MA Divergence | **ALREADY IMPLEMENTED** | `ma_divergence.py`: `ma_divergence_sma`/`ma_divergence_ema` = `(fast_ma-slow_ma)/slow_ma` |
| 3 | Sector Deviation | **NOT IMPLEMENTED** — blocked | no sector table/mapping exists anywhere in `models.py` (confirmed 65.02, re-confirmed here) |
| 4 | Sector-wise DMA | **NOT IMPLEMENTED** — blocked | requires a sector index price series; none exists |
| 5 | Fire Sale | **RESEARCHED ONLY** (term corrected from "Firecell" at 65.08) | zero implementation; `market_regime.py` explicitly disclaims being a Fire Sale detector |
| 6 | Unwinding | **RESEARCHED ONLY** | depends on OI; `OpenInterestObservation` table exists but is 0 rows (NSE_FNO empty) |
| 7 | Bull Regime | **ALREADY IMPLEMENTED** (as one branch of `market_regime`) | `market_regime.py` BULL branch: `adx_14>=ADX_MIN AND plus_di>minus_di AND ema_fast>ema_slow` |
| 8 | Bear Regime | **ALREADY IMPLEMENTED** (as one branch of `market_regime`) | same module, BEAR branch (mirror condition) |
| 9 | Market Sentiment | **NOT IMPLEMENTED** | no sentiment source of any kind wired into the platform |
| 10 | Index vs Stock Correlation | **NOT IMPLEMENTED** — blocked | no index price series exists; `market_regime` is single-instrument only, never index-derived |

Also inventoried: the feature registry (`field_registry._FIELDS`, 20 entries
as of 65.08 — raw OHLCV, SMA/EMA/ATR, RSI/ADX/±DI/RVOL/MACD-hist/candle-body,
engulfing patterns, price_delta, price_vs_ma_pct×2, ma_divergence×2,
rebound_candidate, market_regime); the categorical type seam
(`FieldDataType.CATEGORICAL`/`CategoricalFeatureValue`, 65.07); the
correlation read-model (`correlation_repository.py`, 64.82 — bulk,
read-only, four fixed queries, EXACT-ID joins only, no inference); evidence
persistence (`SignalEvidenceRecord`, 64.81); `HistoricalBar.provenance`
(65.12, 0 REAL_DHAN rows currently); `gainz_compatible_research` (64.99,
profile "alpha", NOT in `build_default_registry()`, unreachable from the
live scanner, with two explicitly documented BLOCKER omissions — breakout
and RSI-momentum — neither of which this checkpoint touches).

## 3. Concept Research

For each concept: A–O per the checkpoint's Research Standard.

### 3.1 Short-Term Rebound (Part 2)

**A.** A short, sharp recovery in price following a decline, distinct from a
trend reversal — inherently a shorter time horizon than a regime change.

**B/C.** Current `rebound_candidate(t) ∈ {0,1}`:
`price_delta_N(t)<0 AND rsi_M(t)<oversold AND bullish_engulfing(t)==1`.
This is a **setup detector**, not a confirmed rebound. A rigorous design
separates two concepts:
- `rebound_candidate` (existing): the setup fired at bar t.
- `confirmed_rebound` (NOT implemented): would require forward-looking
  confirmation — e.g. `close[t+k] > close[t] * (1+min_recovery_pct)` for some
  k bars later, and *only* has meaning as a **labeling function for
  backtesting/outcome analysis**, never as a real-time feature (using
  `t+k` at decision time is definitionally look-ahead). These must remain
  architecturally separate: `rebound_candidate` is a feature; a
  `confirmed_rebound` label belongs to backtest/outcome evaluation code,
  never to the feature engine.

**D.** OHLCV bars only (already satisfied).
**E.** Intraday bar timeframe the strategy runs on (existing behavior).
**F.** Stock-level.
**G.** Leading (a setup precedes any confirmed reversal) but with the
"falling knife" risk described in J.
**H.** Correlates with `price_vs_ma_pct` (a rebound candidate is almost
always simultaneously below its short MA — this is why `rebound_candidate`
deliberately excluded MA-distance as a fourth redundant condition, per its
own module docstring) and with `price_delta` (one of its own dependencies).
**I.** False positives: a stock in a genuine downtrend can print an
oversold RSI + bullish engulfing candle and continue falling (the falling
knife). Without volume confirmation or index/sector confirmation the
existing feature cannot distinguish a real reversal from a dead-cat bounce.
**J.** Regime-dependent: a rebound candidate inside a `market_regime=BEAR`
context has a structurally different prior probability of continuing than
one inside `SIDEWAYS` or `BULL` — this is exactly the kind of
context-conditioning Part 11's evidence model is for, and is NOT wired
today.
**K.** Backtestable — deterministic, bar-indexed.
**L.** No look-ahead in the existing feature (verified: reads price_delta,
rsi, bullish_engulfing only at t). A `confirmed_rebound` *label* would by
definition use future bars and must never be exposed as a real-time
feature.
**M.** Low complexity to extend (e.g. add relative_volume confirmation) —
but see redundancy analysis (§5) before doing so.
**N.** Fully available today (cash OHLCV only).
**O.** Feature (context), as it already is. A future `confirmed_rebound`
would be an **outcome-labeling utility for backtest/correlation analysis**,
not a feature.

### 3.2 Moving Average Divergence (Part 3)

**A.** How far apart two moving averages are, as a normalized measure of
trend strength/momentum shift.

**B/C.** Existing: `ma_divergence_sma`/`ma_divergence_ema` =
`(fast_ma - slow_ma)/slow_ma`, a **distance divergence** between a fast and
slow MA of the *same type*. This is distinct from several other things the
term "MA divergence" can mean, none of which exist today:
- *Price vs MA divergence*: already separately covered by
  `price_vs_ma_pct_sma`/`_ema` (`(close-ma)/ma`) — a different pair.
- *Slope divergence*: comparing the fast MA's slope to the slow MA's slope
  (e.g. `Δfast_ma - Δslow_ma`) — NOT implemented; would need first-difference
  of two MA series across two bars, which the current feature-engine
  architecture (single-bar-at-a-time strategy evaluation, no
  previous-bar-feature-value channel — the exact same limitation
  `gainz_compatible_research`'s BLOCKER B documents for RSI momentum) cannot
  express as a feature without a "previous feature value" seam.
- *Momentum vs MA divergence* (e.g. RSI diverging from price trend, a
  classic technical "bearish/bullish divergence" pattern): NOT implemented,
  requires comparing extrema across multiple bars — architecturally a
  different, heavier class of feature (needs a rolling-window pivot/extrema
  detector), not a trivial extension.

**Conclusion:** the existing `price_vs_ma_pct` + `ma_divergence` pair is
**sufficient and correctly scoped** for what this checkpoint's ten concepts
actually need; slope-divergence and momentum-divergence are genuinely
different, unimplemented concepts, not gaps in the existing two — they
should stay explicitly out of scope until a real consumer needs them (same
discipline the existing modules' own docstrings apply to mixed SMA/EMA
pairs).

**H.** High overlap with `price_vs_ma_pct` by construction — see redundancy
matrix (§5).
**I.** Choppy/sideways markets produce frequent near-zero crossings with no
real trend — false "divergence" signals in `SIDEWAYS`/`TRANSITION` regime.
**J.** Regime-dependent in the same way.
**K/L.** Backtestable, no look-ahead (verified in module docstring and
code: reads only MA values at t).
**M.** None needed — already implemented.
**O.** Feature (context) — matches current classification.

### 3.3 Sector Deviation (Part 4)

**A.** How a stock's return differs from its sector's return — isolates
stock-specific (idiosyncratic) behavior from sector-wide moves.

**B/C.** Candidate formulations, compared (not chosen — no sector data
exists to validate any of them):
- **Simple return spread**: `stock_return_N - sector_return_N`. Simplest,
  but sensitive to volatility differences between the stock and its sector.
- **Normalized return spread**: `(stock_return_N - sector_return_N) /
  sector_volatility_N`. Removes some scale sensitivity.
- **Beta-adjusted residual**: `stock_return_N - β·sector_return_N` where β
  is a rolling regression coefficient. Most statistically correct
  (isolates true alpha vs the sector), but requires a rolling regression —
  materially higher implementation complexity, and β estimates are noisy
  over short intraday windows.
- **Z-score deviation**: standardize the spread against its own rolling
  distribution — good for cross-sectional ranking (e.g. "top decile sector
  outperformers"), less good as a single-stock real-time signal.
- **Relative strength**: `stock_price / sector_index_price`, tracked as a
  ratio series and its own trend — the simplest to implement but loses the
  return-based interpretability of the spread formulations.

No formulation is recommended for implementation now; the beta-adjusted
residual is the most defensible *if and when* sector index history exists
long enough to estimate rolling β reliably (needs materially more history
than a same-day intraday window can supply — likely a daily-bar β estimated
over weeks, applied to intraday deviation).

**D.** Sector index price series (does not exist) + a stock→sector mapping
table (does not exist — `models.py` confirmed to have zero sector table).
**E.** Sector deviation is meaningful at both intraday (short lookback) and
daily (rolling β) timeframes; the two need different data.
**F.** Stock-level output, but sector-level input.
**G.** Coincident-to-lagging (reacts to sector moves after they occur).
**H.** Overlaps partially with `market_regime` (index/market-wide trend)
and with the stock's own momentum features — but sector deviation isolates
a genuinely different axis (stock vs its peer group, not stock vs the whole
market), so it is NOT redundant with existing features once sector data
exists.
**I.** Missing/incorrect sector mapping (e.g. a conglomerate spanning
multiple sectors) produces a meaningless deviation number; must fail
honestly (no output) rather than default to a wrong sector.
**J.** Highly regime-dependent — a "sector outperformer" reading means
something different in a broad bull tape vs a broad selloff.
**K.** Backtestable only once historical sector index bars exist.
**L.** No look-ahead risk in the formula itself, provided the sector return
at t only uses bars ≤t (same discipline as every existing feature).
**M.** Medium-high (new data pipeline: sector mapping + sector index
series + corporate-action handling for reconstitutions).
**N.** BLOCKED — sector mapping and sector index data do not exist in this
platform today.
**O.** Context or signal filter (e.g. "only take a bullish stock signal if
sector deviation is also positive") — never a standalone strategy.

### 3.4 Sector-wise DMA (Part 5)

**A.** Distance/trend of a sector's own index price relative to its
Daily Moving Average(s), analogous to `price_vs_ma_pct` but applied to the
sector index rather than a stock.

**B/C.** `sector_price_vs_dma_pct = (sector_index_close - DMA(sector_index,
N)) / DMA(sector_index, N)` — mathematically identical formula to the
existing `price_vs_ma_pct`, just applied to a different underlying series
(a sector index instead of a stock).

**Redundancy check (the directive's explicit ask):** Sector-wise DMA
answers "is the sector itself trending up/down and by how much" — this is
*not* the same question Sector Deviation answers ("is this stock
outperforming its sector"), and it is *not* the same question
`market_regime`/index trend answers ("is the whole market trending"). All
three are legitimately different axes (stock-vs-sector, sector-vs-its-own-
history, market-vs-its-own-history), so Sector-wise DMA is **not
redundant** in principle — but it is entirely blocked by the same missing
sector-index-data dependency as Sector Deviation, and the two would very
likely be built from the same sector-index ingestion pipeline, so they
should be scoped together, not independently.

**D–O:** identical data blockers to §3.3 (sector index series required);
same stock/sector/market-level distinction; coincident/lagging; feature or
context (never strategy); backtestable only once sector index history
exists; medium implementation complexity (reuses the existing SMA/EMA
compute functions verbatim once a sector index bar series exists — no new
math, only a new instrument-class source).

### 3.5 Fire Sale (Part 6)

Per the corrected terminology (65.08): **Fire Sale**, never "Firecell."

**Definitions, deliberately distinguished** (the directive explicitly warns
against treating these as identical):

- **Fire Sale**: rapid, forced selling driven by an urgent liquidity need
  (not necessarily fear-driven — e.g. a fund meeting redemptions), producing
  a severe, possibly temporary discount to normal value. The defining
  feature is *forced*, not necessarily *panicked*.
- **Panic Selling**: fear-driven selling by many independent participants
  reacting to news/sentiment, not necessarily forced by margin or liquidity
  constraints. Can occur without any single large forced seller.
- **Capitulation**: the terminal phase of panic selling — the point where
  even the most resistant holders give up and sell, typically marked by a
  volume/volatility spike and often (not always) a local price extreme.
  Capitulation is a *specific moment*, panic selling is the *broader
  process* leading to it.
- **Liquidation Cascade**: a mechanical, self-reinforcing sequence where
  falling prices trigger margin calls/stop-losses/forced closes, which push
  price further down, triggering more forced closes. Distinguished from
  Fire Sale by the *cascading, self-reinforcing* mechanism specifically
  (Fire Sale can be a single forced seller with no cascade).
- **Unwinding**: closing out previously-held positions (long liquidation or
  short covering) — a broader, regime-neutral term that is not inherently
  panicked or forced; see §3.6. Fire Sale/Capitulation/Cascade are all
  *specific, usually-bearish* subtypes of position unwinding under stress;
  Unwinding itself is directionally neutral and can be orderly.

**What is realistically observable from OHLCV-only cash market data
(no OI, no order book, no news feed):**
- Abnormal volume-price dislocation: large `relative_volume` spike
  co-occurring with a large negative `price_delta`/return over a short
  window — an *observable proxy*, not proof of forced selling.
- Volatility shock: a spike in `atr` or true range relative to its own
  recent history.
- Gap-down liquidation: an opening-bar gap materially below the prior
  close, especially combined with continued selling into the open.
- Breadth collapse: requires market-wide/multi-stock breadth data (percent
  of stocks declining, new lows), which this platform does not have (no
  breadth infrastructure exists — confirmed absent at 65.02).

**Explicitly NOT knowable from this data:** whether selling is *forced*
(margin call, redemption, risk-limit breach) vs *voluntary panic* — that
distinction requires order-level/participant-level data (broker
category data, margin data) this platform has no access to. **This document
does not claim intrinsic/fundamental value can be known from market data at
all** — any "discount to fundamental value" framing is inherently
unmeasurable here; only the *price/volume/volatility dislocation itself* is
observable, never the "true value" it is allegedly discounted from.

A future `fire_sale_proxy` context feature (NOT implemented here) would
necessarily be a **dislocation detector**, not a true Fire Sale detector,
and must be named/documented honestly as such if ever built.

### 3.6 Unwinding (Part 7)

**A.** The closing of previously-open positions — long liquidation (selling
existing longs) or short covering (buying back existing shorts) — as
distinct from fresh directional entries.

**What can actually be inferred from price+volume alone (no OI):**
very little, and only ambiguously. A volume spike with a price decline is
consistent with *either* long liquidation *or* fresh short-selling — cash
OHLCV data cannot distinguish these. This is a hard limit, not an
implementation gap.

**What becomes possible only with F&O/OI data (explicitly NOT implemented,
NSE_FNO deferred, `OpenInterestObservation` confirmed 0 rows):**
- Falling OI + falling price → long liquidation (longs exiting).
- Falling OI + rising price → short covering (shorts exiting).
- Rising OI + rising price → fresh long buildup.
- Rising OI + falling price → fresh short buildup.
This OI-vs-price cross table is the standard, well-established way
"unwinding" is actually measured in F&O markets — and it is **entirely
gated on data this checkpoint explicitly must not implement.**

**Conclusion:** Unwinding as a genuinely observable, non-ambiguous concept
is **F&O/OI-dependent** and cannot be honestly approximated from cash data.
Any cash-only "unwinding proxy" would be indistinguishable from ordinary
directional price action and should not be built — it would create a
feature whose name overstates what it actually measures.

### 3.7 / 3.8 Bull Regime / Bear Regime (Part 8)

Both are **already implemented** as two branches of the single
`market_regime` categorical feature (65.08) — verified in
`market_regime.py`: `BULL` requires `adx_14>=ADX_MIN AND plus_di>minus_di
AND ema_fast>ema_slow`; `BEAR` requires the mirror condition. This is
**already more robust than a naive `price>SMA=bull`** rule — it combines
trend *strength* (ADX threshold) with trend *direction agreement* across
two independent signals (DI dominance AND EMA ordering), and explicitly
falls back to `SIDEWAYS`/`TRANSITION` rather than forcing every bar into a
binary bull/bear label.

**Should it become a richer composite context?** Per the directive, this is
a documented *should-eventually* question, not an instruction to act. A
more complete regime composite would ideally also weigh: breadth
(percent of stocks/sectors trending with the market — blocked, no breadth
data), volatility regime (e.g. ATR percentile — computable today but not
wired in), drawdown from a rolling high (computable today, not wired in),
and sector participation (blocked, no sector data). **Recommendation:**
`market_regime` should NOT be modified in this checkpoint (explicitly
prohibited); a future checkpoint could research a `market_regime_v2`
composite, but only with clear evidence the current rule is insufficient
for a real strategy consumer — not speculatively.

**H.** `market_regime`'s BULL/BEAR branches structurally overlap with
`ma_divergence` (`ema_fast>ema_slow` in market_regime is one directional
sign of what `ma_divergence_ema` measures numerically) — see redundancy
matrix (§5) for the KEEP/MERGE call.

### 3.9 Market Sentiment (Part 9)

Sources compared, none recommended for implementation:

| Source | Data needed | Latency | Reliability | Cost/dependency | Backtestable? | Look-ahead risk |
|---|---|---|---|---|---|---|
| Price-derived (e.g. put/call-free proxies like breadth momentum, VIX-India level) | India VIX / breadth series | real-time if subscribed | proxy only, not "true" sentiment | requires a new market-data feed (India VIX is a separate instrument this platform does not ingest) | yes, if historical VIX archived | low if timestamp-aligned correctly |
| Breadth-derived (advance/decline, new highs/lows) | market-wide per-stock data across full universe, every bar | real-time if computed in-house | reasonable, well-established | requires ingesting the FULL NSE universe every bar (heavy) — not currently done | yes | low |
| Volatility-derived (ATR percentile, realized-vol regime) | already-available OHLCV | none (already have the inputs) | reasonable proxy for "stress," not sentiment per se | none — computable today with existing features | yes | low |
| News sentiment (NLP on headlines) | external news feed + NLP pipeline | seconds-to-minutes | noisy, vendor-dependent | new paid data dependency + inference pipeline | very hard — news archives rarely timestamp-clean enough to avoid look-ahead | HIGH (headline timing/reprocessing artifacts are a classic backtest look-ahead trap) |
| Options-derived (put/call ratio, IV skew) | NSE_FNO/OptionQuote | real-time if subscribed | well-established professional metric | requires exactly the F&O data this checkpoint must not implement | yes once OI/IV history exists | moderate |
| External sentiment feeds (social/vendor scores) | 3rd-party API | varies | unverified, vendor black-box | ongoing external dependency, cost, and reliability risk | poor — vendor scores rarely have clean historical replay | HIGH |

**Conclusion:** the only sentiment-adjacent signal buildable today without
a new external dependency is a **volatility-regime proxy** (ATR
percentile) — which is not really "sentiment," it is a relabeling of data
already in `market_regime`'s ambit. Genuine sentiment (breadth, options,
news) is blocked by missing universe-wide/F&O/vendor data. **Recommendation:
do not add a "sentiment" feature that is secretly just volatility under a
more exciting name** — that would be exactly the kind of feature the
directive warns against creating "because it sounds financially
meaningful."

### 3.10 Index vs Stock Correlation (Part 10)

**A.** A rolling statistical correlation between a stock's returns and its
benchmark index's returns — distinct from relative strength (a ratio/trend
comparison, not a correlation coefficient), beta (a regression slope
capturing *magnitude* of co-movement, correlation captures *strength* of
co-movement independent of magnitude), sector correlation (peer-group
co-movement, a different reference series), and "index sensitivity" (an
umbrella term that could mean either beta or correlation depending on
usage — this ambiguity is exactly why the three should be kept as distinct,
precisely-named metrics rather than folded into one loosely-defined
"sensitivity" feature).

**B/C.** `index_correlation_N(t) = Pearson(stock_return[t-N:t],
index_return[t-N:t])`, a value in `[-1, 1]`.

**Pearson vs Spearman:** Pearson measures linear co-movement and is the
standard choice for return series that are approximately continuous and
not dominated by outliers; Spearman (rank correlation) is more robust to
outlier bars (e.g. one halted/circuit-filter bar) and to non-linear
relationships, at the cost of discarding magnitude information. For
intraday return series with occasional extreme bars (circuit filters, gap
opens), **Spearman is likely the more robust default** if this were ever
implemented, with Pearson available as a secondary diagnostic.

**D.** Requires an index price series (e.g. NIFTY 50/NIFTY 500 bars) at the
same timeframe as the stock — **does not currently exist**; this platform
ingests individual stock instruments only (no index instrument confirmed
absent per 65.02 audit).
**E.** Rolling lookback window is a real design choice: too short (e.g.
<20 bars) is noisy; too long dilutes responsiveness to genuine regime
shifts. No value should be hard-coded without backtested justification —
none is proposed here.
**F.** Stock-level output, requires index-level input.
**G.** Coincident (a rolling window trails the present by construction).
**H.** Distinct from `market_regime` (which is single-instrument, not
index-referenced) and from Sector Deviation (peer-group, not
whole-market). Genuinely new information once index data exists.
**I.** A correlation breakdown (stock decoupling from the index) can mean
either genuine idiosyncratic news (real signal) or simply illiquidity/thin
trading in that stock producing noisy returns (false signal) — the feature
cannot distinguish these without a liquidity/volume-based gate.
**J.** Correlations are known to rise sharply in market-wide stress
(everything sells off together) and fall in calm/idiosyncratic-driven
markets — so this feature is itself regime-dependent in a well-documented
way (a fact that could make it useful as a stress/regime *confirmation*
input, not just a per-stock filter).
**K.** Backtestable once index history exists.
**L.** No look-ahead risk in the formula itself provided both series are
computed only from bars ≤t.
**M.** Low-to-medium once index data exists (rolling correlation is a
standard, cheap computation) — the real cost is the new index-data
ingestion, not the math.
**N.** BLOCKED — no index price series ingested today.
**O.** Context / anomaly detector / risk modifier (e.g. down-weight
conviction on a signal whose stock has decoupled from its index) — never a
standalone strategy trigger by itself.

## 4. Correlation Framework — Feature → Context → Strategy → Signal → Outcome (Part 11)

The platform already has half of this chain built and unused for real
signals: `scan_run_id`/`strategy_version_identifier` link a signal to its
producing scanner run and strategy version; `SignalEvidenceRecord` links a
signal to the named feature values that fed it; `correlation_repository.py`
(64.82) provides a **read-only, bulk, EXACT-ID-only** traversal from signal
→ evidence → orders → trades — it performs zero inference (verified in its
own module docstring: "no relationship is ever derived from a timestamp
proximity, a price match, an instrument match, or a string similarity").
This is real infrastructure, not aspirational — but it has **never
processed a real Gainz/context-aware signal**, because `gainz_compatible_
research` is not registered in `build_default_registry()` and no NSE
session has run live yet (65.12: 0 REAL_DHAN rows).

**Future evidence model** (research only, nothing built):
`Feature → Context → Strategy → Signal → Outcome`, e.g. `MA Divergence +
Market Regime + Index/Stock Correlation → Strategy Signal → Trade Outcome`.
To eventually measure this without conflating correlation with causation:

- **Feature→Signal correlation**: for signals a strategy actually emitted,
  what was the distribution of a given feature's value at evaluation time
  (already recoverable via `SignalEvidenceRecord` today, in principle, for
  any strategy that populates evidence — this is descriptive statistics on
  stored evidence, not a new capability).
- **Context→Signal correlation**: same, but conditioned on `market_regime`
  category at signal time — requires `market_regime` to actually be
  recorded as evidence for a live-running strategy (not true today; Gainz
  does not consume `market_regime`, and no strategy's evidence has been
  observed with real market data).
- **Feature→Outcome / Context→Outcome / Strategy→Outcome correlation**:
  joins evidence to `PaperTradeRecord.realized_pnl` via the existing
  `signal_id` links — architecturally possible today, but with 0 real
  trades from real market data, there is currently nothing to compute this
  over (correlation on synthetic/fixture data is not market evidence, per
  65.11's own explicit finding).
- **Feature interactions / regime-conditioned performance**: would require
  grouping stored outcomes by *combinations* of evidence values (e.g.
  win-rate of `rebound_candidate=1` signals specifically inside
  `market_regime=BEAR`) — a reporting/analytics layer on top of the
  existing read model, not a new storage concept.

**Correlation ≠ causation — how the framework must make this explicit:**
any future correlation/analytics surface must (1) report sample sizes
alongside every correlation figure (a correlation from 5 trades is not
evidence of anything), (2) never auto-promote a discovered correlation into
a strategy parameter without an out-of-sample validation step, and (3)
always report correlations *conditioned on regime* rather than as a single
pooled number, since a spurious correlation is far more likely to appear
when regimes are pooled together than when analyzed within-regime. None of
this is built; it is a design constraint for whoever eventually builds the
analytics layer described above.

## 5. Feature Redundancy Matrix (Part 12)

| Pair | Relationship | Recommendation | Reason |
|---|---|---|---|
| `price_vs_ma_pct` vs `ma_divergence` | Both are "distance from a moving average" — one against price, one between two MAs | **KEEP both** | Genuinely different reference series (price vs MA, MA vs MA); already implemented; not duplicative in practice |
| `rebound_candidate` vs (proposed) volume-confirmed rebound | proposed variant adds `relative_volume` | **REJECT as a new feature; recommend STRATEGY-layer composition** | `rebound_candidate`'s own docstring already made this call — combine at strategy layer, don't fork the feature |
| `rebound_candidate` vs `price_vs_ma_pct` | a rebound candidate is almost always already below its MA | **REJECT adding MA-distance as a 4th rebound condition** | Redundant per the existing module's own documented exclusion rationale — confirmed correct on inspection |
| `market_regime`(BULL/BEAR branches) vs `ma_divergence_ema` | `market_regime`'s direction test uses `ema_fast>ema_slow`, which is the *sign* of what `ma_divergence_ema` measures *numerically* | **KEEP both, DERIVE relationship documented** | `market_regime` needs a categorical trend-strength-gated label; `ma_divergence` needs a continuous magnitude. Not the same output shape — but any future composite regime should reuse `ma_divergence`'s existing computation rather than recomputing EMA comparison a third way |
| Sector Deviation vs Index/Stock Correlation | both compare a stock to an external reference series | **KEEP both if ever built — DIFFERENT reference (sector vs index) and DIFFERENT statistic (spread/residual vs correlation coefficient)** | Not redundant: one measures directional over/under-performance, the other measures co-movement strength, independent of direction |
| Index trend vs Bull/Bear Regime | both describe "is the market trending up or down" | **MERGE conceptually, if ever built** | An index-level bull/bear read would be the *same rule* (`market_regime`'s formula) applied to an index instrument instead of a stock instrument — reuse the existing `market_regime` computation on an index bar series rather than inventing a second regime rule |
| Sector-wise DMA vs Sector Deviation | both sector-derived | **KEEP both, DERIVE from the same sector-index pipeline** | Different questions (is the sector trending vs is the stock beating the sector) — but share the same blocked data dependency, so should be built together, not independently |
| Fire Sale proxy vs `market_regime`=BEAR | both describe adverse conditions | **KEEP conceptually separate, do NOT merge** | `market_regime`=BEAR is a *sustained trend* classification; Fire Sale is a *dislocation event* classification (can occur inside any regime, including a brief panic within an otherwise BULL tape) — conflating them would lose the event-vs-trend distinction the directive explicitly asked to preserve |
| "Sentiment via volatility" vs ATR/`market_regime` | proposed sentiment proxy is just ATR percentile | **REJECT as a distinct "sentiment" feature** | Would be volatility relabeled — no new information; see §3.9 conclusion |

## 6. Feature / Context / Strategy Boundary Rules (Part 13)

1. If a concept is a **pure numeric/categorical function of bars up to
   t**, with no BUY/SELL decision attached, it belongs in the **Feature
   Registry** (`field_registry.py` + a `feature_engine` module) — this is
   where `rebound_candidate`, `ma_divergence`, `market_regime` all
   correctly live today.
2. If a concept **combines multiple canonical features into a single
   higher-level market condition** that many strategies could reasonably
   share (e.g. a future composite regime, a Fire Sale dislocation flag),
   it belongs in **Market Context**, built by composing existing canonical
   feature computations — never by having each strategy recompute its own
   private version. `market_regime`'s own module docstring already
   establishes this discipline (it composes five *already-existing*
   canonical computations, never reimplements their math).
3. A **Strategy** may combine Context + Features into a scoring/decision
   rule, but must never re-derive a canonical Context computation
   privately (e.g. a strategy must never hand-roll its own bull/bear
   classification when `market_regime` already exists — this is exactly
   the anti-pattern Part 13 warns against).
4. **Signal Scoring** (e.g. Gainz's weighted conditions) belongs to the
   strategy layer, not the feature engine — weights are strategy-specific
   judgment, not universal market facts.
5. **Risk Layer** modifiers (e.g. down-weighting size on a Fire Sale
   dislocation, or on a broken index correlation) consume Context/Features
   but must never themselves compute a new indicator from raw bars — they
   read already-published feature/context values only.
6. **Reporting** (redundancy analysis, correlation dashboards) is a
   read-only consumer of stored evidence — must never write back into
   Feature/Context/Strategy layers.

## 7. Gainz Alpha Relationship (Part 14, research only — Gainz untouched)

Possible future relationships, none implemented, none assumed beneficial:

- **Gainz signal + market_regime**: e.g. only trust a Gainz `alpha` BUY
  signal when `market_regime` is BULL or TRANSITION, suppress in BEAR.
  Plausible, but Gainz's own adapter does not currently consume
  `market_regime` at all (confirmed in `gainz_compatible_research.py` —
  its condition list is the eight items from the 64.98 audit; `market_
  regime` is not among them), so this is a genuinely new integration, not
  an existing behavior.
- **Gainz signal + rebound_candidate**: e.g. treat a Gainz BUY signal that
  coincides with `rebound_candidate=1` as higher-conviction. Plausible but
  unverified — could equally be redundant, since Gainz's own condition set
  already includes an RSI-exhaustion gate and a bullish-engulfing
  condition, which substantially overlap `rebound_candidate`'s own inputs.
- **Gainz signal + sector_deviation** / **+ index_correlation**: blocked by
  the same missing sector/index data as §3.3/§3.10.

**What evidence would be required to prove any of these "improve" Gainz:**
a real out-of-sample backtest (or, eventually, live paper-trading period)
comparing signal outcomes *with* vs *without* the added context gate, on
REAL_DHAN-provenance data (not synthetic/fixture data — 65.11 already
established that synthetic-data backtest results are engine validation
only, never market evidence), with a large enough trade sample to make the
comparison statistically meaningful, and ideally tested across more than
one market regime period so the result isn't an artifact of one particular
tape. None of this evidence exists yet — 0 REAL_DHAN rows, `gainz_
compatible_research` not registered in the live scanner registry, 0 real
trades.

## 8. Backtest Requirements (Part 15)

| Feature | Historical data required | Min lookback / warm-up | Leakage risk if built correctly |
|---|---|---|---|
| `rebound_candidate` (existing) | OHLCV only | `max(delta_lookback, rsi_lookback)+1` bars | none (verified no-lookahead in code) |
| `ma_divergence` (existing) | OHLCV only | `slow_lookback` bars | none (verified) |
| `market_regime` (existing) | OHLCV only | `max(28, ema_slow_lookback)` bars | none (verified) |
| Sector Deviation (future) | sector index OHLCV + mapping | sector-return lookback + (if beta-adjusted) a longer daily-bar estimation window | HIGH if beta is estimated using data beyond t — must roll strictly on ≤t history |
| Sector-wise DMA (future) | sector index OHLCV | DMA lookback (same as stock-level DMA) | low, same discipline as existing MA features |
| Fire Sale proxy (future) | OHLCV only (proxy version) or breadth (full version) | ATR/RVOL lookback for the proxy; full universe for breadth | low for the proxy; breadth version requires strict same-timestamp alignment across the whole universe |
| Unwinding (future, F&O-gated) | OI history | OI lookback | N/A until NSE_FNO exists — explicitly deferred |
| Sentiment (future, mostly blocked) | varies by source | varies | HIGH for news/vendor sentiment — historical news/vendor archives are notoriously prone to look-ahead via republished/corrected timestamps |
| Index↔Stock Correlation (future) | index OHLCV | rolling correlation window N | low if computed strictly on ≤t returns |

The canonical backtest engine can, in principle, test any of the future
features **without changing execution semantics**, provided each is
delivered as a `FeatureValue`/`CategoricalFeatureValue` series through the
existing dispatcher — exactly the same seam `market_regime` already proved
out. No backtest engine change is proposed or required by this research.

## 9. Data Dependency Matrix (Part 16)

| Concept | Required data | Currently available? | Historical avail.? | Live avail.? | NSE_FNO dependency? | Index dependency? | Sector dependency? | Implementation difficulty |
|---|---|---|---|---|---|---|---|---|
| Short-Term Rebound | OHLCV | Yes | Yes | Yes | No | No | No | Done (existing) |
| MA Divergence | OHLCV | Yes | Yes | Yes | No | No | No | Done (existing) |
| Sector Deviation | sector index + mapping | No | No | No | No | No | **Yes** | Medium-high once data exists |
| Sector-wise DMA | sector index | No | No | No | No | No | **Yes** | Medium once data exists |
| Fire Sale (proxy) | OHLCV (RVOL/ATR/gap) | Yes (proxy only) | Yes | Yes | No | No | No | Low-medium (proxy); breadth version needs full universe ingestion |
| Unwinding | OI | No | No | No | **Yes** | No | No | Blocked entirely |
| Bull Regime | OHLCV | Yes | Yes | Yes | No | No | No | Done (existing, via `market_regime`) |
| Bear Regime | OHLCV | Yes | Yes | Yes | No | No | No | Done (existing, via `market_regime`) |
| Market Sentiment | varies (VIX/breadth/news/options/vendor) | No (any real source) | No | No | Partial (options-derived) | Partial (VIX/breadth) | No | Blocked / speculative |
| Index↔Stock Correlation | index OHLCV | No | No | No | No | **Yes** | No | Low-medium once index data exists |

**Explicit blockers:** sector mapping/index (Sector Deviation, Sector-wise
DMA), index price series (Index↔Stock Correlation, richer Bull/Bear
composites), F&O/OI (Unwinding, options-derived sentiment), full-universe
breadth ingestion (breadth-based Fire Sale/sentiment), external vendor
feeds (news/social sentiment).

## 10. Implementation Priority Ranking (Part 17)

| Priority | Concept | Reasoning |
|---|---|---|
| **Already done — no action** | Short-Term Rebound, MA Divergence, Bull/Bear Regime | Real, tested, in the registry. Do not re-implement. |
| **PRIORITY 1** (once index data exists) | Index↔Stock Correlation | Genuinely new information axis, low implementation complexity once index bars exist, clean backtestability, low look-ahead risk, useful as a risk modifier/anomaly detector for any strategy including Gainz |
| **PRIORITY 1** (once sector data exists) | Sector Deviation | Genuinely new information (isolates idiosyncratic vs peer-group moves), moderate complexity, high strategy-integration value as a signal filter |
| **PRIORITY 2** | Sector-wise DMA | Same data dependency as Sector Deviation (bundle together), lower standalone value than Sector Deviation itself since it largely restates sector-index trend information a strategy could derive from Sector Deviation's own inputs |
| **PRIORITY 2** | Fire Sale (proxy version, OHLCV-only) | Buildable today with existing data, but real-world value is capped without breadth/OI to disambiguate genuine forced-selling from ordinary volatility — useful mainly as a risk modifier ("reduce size/pause entries during extreme dislocation"), not a signal generator |
| **RESEARCH LATER** | Unwinding | Entirely gated on NSE_FNO/OI, which is explicitly out of scope platform-wide right now; revisit only after F&O data exists |
| **RESEARCH LATER** | Market Sentiment | High false-positive/look-ahead risk (news/vendor sources), most sub-forms blocked by missing data (breadth/OI/VIX ingestion), and the only currently-buildable proxy (volatility) is redundant with existing features — low priority until a specific, validated source is chosen |
| **DEFER** | Composite Bull/Bear regime v2 (breadth+drawdown+sector participation) | `market_regime` already exists and works; a richer composite should only be pursued with evidence the current rule is insufficient for a real consumer, not speculatively |

## 11. Recommended Future Roadmap (Part 18)

Reordered from the directive's suggested structure based on this
research's findings (index/sector data blockers dominate sequencing more
than the original phase letters implied):

- **Phase A — Data Foundation (prerequisite for everything else).**
  Ingest an index price series (e.g. NIFTY 50/500) and a stock→sector
  mapping table with sector index series. Nothing in Phase B/C below can
  be *validated* against real data without this, though the math for each
  can be designed/reviewed in parallel.
- **Phase B — Index/Sector Context.** Implement Index↔Stock Correlation and
  Sector Deviation as canonical Market Context features (reusing existing
  SMA/EMA/return-computation patterns), once Phase A data exists. Bundle
  Sector-wise DMA into the same effort (shared data dependency).
  Backtest-validate on REAL_DHAN data only — never on synthetic/fixture
  data as evidence.
- **Phase C — Dislocation/Fire Sale proxy.** Build the OHLCV-only Fire Sale
  proxy (RVOL+ATR+gap dislocation detector) as a Risk Layer modifier —
  does not require Phase A data, can proceed independently, but should stay
  low priority relative to Phase B's higher information value.
  **NOTE:** if a future checkpoint's breadth infrastructure changes this
  calculus (i.e. full-universe breadth becomes available), a stronger
  breadth-confirmed Fire Sale version should be revisited then.
- **Phase D — Correlation/Evidence Engine.** Build the descriptive
  Feature→Context→Strategy→Signal→Outcome analytics layer described in §4,
  reading the existing `correlation_repository.py`/`SignalEvidenceRecord`
  data — but only once real (REAL_DHAN-provenance) signals and trades
  actually exist to analyze; building this against synthetic data would
  produce numbers that look like evidence but are not.
- **Phase E — Gainz Contextual Validation.** Only after Phase B/D exist:
  research (not assume) whether gating Gainz signals on `market_regime`/
  Sector Deviation/Index Correlation actually improves outcomes, using the
  evidence standard defined in §7. Gainz itself remains unmodified until
  this evidence exists.
- **Phase F — Sentiment / Unwinding.** Explicitly deferred until F&O/OI
  data (Unwinding) or a specifically chosen, vetted sentiment data source
  (Sentiment) is available — no speculative implementation before then.

## 12. Explicitly Deferred Items

Sector Deviation, Sector-wise DMA, Index↔Stock Correlation (all — no index/
sector data exists); Unwinding and any OI-dependent logic (NSE_FNO/
OptionQuote explicitly out of scope); Market Sentiment in every form except
possibly a volatility-regime proxy, and even that is judged redundant
(§3.9); any modification to `market_regime`, Gainz, EMA/SMA/ATR strategies,
the backtest engine, or the correlation repository; any new database table,
migration, or live data ingestion.

## 13. Risks

- Treating a "sounds financially meaningful" concept as automatically
  worth building (the directive's own named risk) — mitigated here by
  rejecting the volatility-as-sentiment proxy and the MA-distance-as-a-
  4th-rebound-condition additions.
- Building sector/index features against synthetic placeholder data and
  mistaking backtest results for market evidence (65.11's precedent risk,
  applies equally to any future concept here).
- Conflating Fire Sale/Capitulation/Panic Selling/Liquidation Cascade
  (addressed explicitly in §3.5) — a future implementer collapsing these
  into one flag would misrepresent what the platform can actually detect.
- Assuming Gainz improves with added context without an actual controlled
  comparison (addressed in §7).

## 14. False Positives (per concept, consolidated)

Rebound: falling-knife continuation. MA Divergence: sideways-market whipsaw
crossings. Sector Deviation (future): mis-mapped sector membership.
Fire Sale proxy: ordinary high-volatility bars (e.g. results day) that are
not actually forced selling. Index Correlation (future): illiquid-stock
noise mistaken for decoupling. Market Sentiment (any external source):
vendor/news noise, stale or re-timestamped headlines.

## 15. Look-Ahead Risks

Confirmed LOW/none in the three already-implemented features (verified in
code). Confirmed HIGH-RISK-IF-DONE-CARELESSLY for: beta estimation in
Sector Deviation (must roll strictly on ≤t history), any news/vendor
sentiment source (historical archives are routinely re-timestamped/
corrected after the fact — a classic backtest trap), and any
`confirmed_rebound` label (inherently forward-looking by definition — must
never be exposed as a real-time feature, only as a backtest/outcome label).

## 16. Deferred Items

See §12 — repeated here per Part 21's content list: everything requiring
sector, index, F&O/OI, breadth, or external vendor data; any richer
`market_regime` composite; any Gainz modification.
