# Market Intelligence — Implementation Decision Matrix & Roadmap

Checkpoint 65.15-R. RESEARCH/DESIGN ONLY — no production code, migrations,
database, live Dhan, or strategy changes were made while producing this
document. Builds directly on the accepted 65.14-R research
(`docs/research/MARKET_INTELLIGENCE_ENHANCEMENT_RESEARCH.md`), which is
treated here as ground truth and not re-derived. NSE is closed (verified:
2026-08-30 is a Sunday; see task report for the exact IST check).

This document converts 65.14-R's findings into: a final concept
classification, an observable-vs-inferred taxonomy, an implementation
decision matrix, a refined correlation model, a Gainz evidence
methodology, backtest-integration rules, a Fire Sale proxy state design,
an Unwinding inference taxonomy, a sector/index data-foundation spec, a
sentiment comparison, a redundancy rule, eight implementation gates, a
re-evaluated priority order, an explanation of the real-data dependency,
and the final phased roadmap. Zero code, zero database, zero live
connection.

---

## Part 1 — Final Concept Classification

| Concept | Classification | Reason |
|---|---|---|
| Short-Term Rebound | **EXISTING** (as `rebound_candidate`, a setup detector) | Implemented, tested, no look-ahead. A `confirmed_rebound` label is a separate FUTURE concept that belongs to backtest/outcome code, not the feature engine (65.14-R §3.1). |
| MA Divergence | **EXISTING** | `ma_divergence_sma`/`_ema` implemented, tested, no look-ahead. Slope-divergence and momentum-divergence are FUTURE FEATURE candidates, explicitly out of scope until a real consumer needs them. |
| Sector Deviation | **RESEARCH-ONLY** → **FUTURE FEATURE/FILTER** | Formula candidates compared, none chosen. Fully blocked on sector mapping + sector index data, neither of which exists. |
| Sector-wise DMA | **RESEARCH-ONLY** → **FUTURE FEATURE** | Same blocker as Sector Deviation; should be built from the same sector-index pipeline, not independently. |
| Fire Sale | **RESEARCH-ONLY** → **FUTURE CONTEXT (proxy only)** | Cannot be implemented as a true Fire Sale detector from OHLCV data under any circumstance — forced-vs-voluntary selling is not observable here. Only a dislocation *proxy* is a legitimate future target (Part 7). |
| Unwinding | **RESEARCH-ONLY** → **DEFER** | Genuinely non-ambiguous unwinding requires OI (rising/falling OI × price cross table). Cash-only proxies are indistinguishable from ordinary directional price action and must not be built (65.14-R §3.6). Hard-gated on NSE_FNO, out of scope platform-wide. |
| Bull Regime | **EXISTING** (branch of `market_regime`) | Implemented, tested. A richer composite (`market_regime_v2`) is DEFER — no evidence current rule is insufficient. |
| Bear Regime | **EXISTING** (branch of `market_regime`) | Same as Bull Regime. |
| Market Sentiment | **RESEARCH-ONLY** → **DEFER** | Every real source (breadth, options, news, vendor) is blocked by missing infrastructure; the only currently-buildable proxy (volatility) is REJECT as redundant with `market_regime`/ATR. Do not implement any "sentiment" feature now. |
| Index vs Stock Correlation | **RESEARCH-ONLY** → **FUTURE RISK MODIFIER / FUTURE CONTEXT** | Fully blocked on index price series (none ingested). Highest information-value-per-complexity of the blocked concepts once index data exists. |

No concept in this checkpoint is classified REJECT outright — the closest
candidates for outright rejection are the *redundant variants* identified
in 65.14-R's redundancy matrix (volatility-as-sentiment, MA-distance-as-
4th-rebound-condition, cash-only unwinding proxy), which are addressed
per-variant in Parts 7, 8, 11 below rather than as top-level concepts.

---

## Part 2 — Observable vs Inferred: A Formal Taxonomy

To stop the platform from ever claiming certainty the data does not
support, every future market-intelligence output must be tagged with
exactly one of the following six levels. This taxonomy is new to 65.15-R
(65.14-R distinguished the concepts qualitatively; this makes the
distinction a checkable label).

1. **DIRECTLY OBSERVABLE** — read straight off a raw bar with no
   transformation: open, high, low, close, volume, timestamp.
2. **DERIVED** — a deterministic, fully-specified function of directly
   observable values with no ambiguity in what it measures: SMA/EMA, ATR,
   RSI, `price_delta`, `price_vs_ma_pct`, `ma_divergence`, relative
   volume. What it measures is exactly its formula — no interpretive
   leap.
3. **PROXY** — a derived value *asserted to stand in for* a concept it
   cannot directly measure, where the gap between the proxy and the real
   concept is real and must be disclosed. Example: an RVOL+ATR+gap
   dislocation score standing in for "Fire Sale" — it measures
   dislocation, not forced selling.
4. **INFERRED** — a conclusion drawn by combining multiple
   observable/derived signals under an explicit, falsifiable model, where
   the model's assumptions are stated and the conclusion remains
   probabilistic, not asserted as fact. Example: "falling OI + falling
   price → long liquidation" is an inference under the standard F&O
   interpretation model, not a direct read of "liquidation."
5. **EXTERNALLY SOURCED** — obtained from a third party (news feed,
   vendor sentiment score, India VIX) whose own construction methodology,
   timestamp integrity, and revision history this platform does not
   control and must independently verify before trusting for backtesting.
6. **NOT RELIABLY OBSERVABLE** — the underlying fact cannot be determined
   from any data source currently in scope for this platform, cash or
   F&O. Must not be claimed, proxied, or inferred — only stated as
   unknown.

### Applied to the six contested concepts

| Concept | Level | Justification |
|---|---|---|
| Fire Sale (forced selling) | **NOT RELIABLY OBSERVABLE** | "Forced" requires participant-level/margin data this platform will never have access to. |
| Fire Sale dislocation score | **PROXY** | RVOL+ATR+gap dislocation is derived and real, but is not Fire Sale — must be named/labeled `fire_sale_proxy`, never `fire_sale`. |
| Capitulation | **NOT RELIABLY OBSERVABLE** as a labeled fact; **PROXY** as "volume/volatility extreme co-occurring with a local price extreme" | The terminal-phase claim requires knowing it *was* terminal, which is only knowable in hindsight — any real-time flag is a proxy, not a confirmed capitulation. |
| Panic Selling | **NOT RELIABLY OBSERVABLE** | Requires knowing selling was fear-driven and voluntary, not mechanical (margin) or algorithmic — no data source distinguishes participant motive. |
| Liquidation Cascade | **INFERRED at best** (never NOT RELIABLY OBSERVABLE-only, because the *mechanical self-reinforcing pattern* — accelerating price decline with expanding volume across consecutive bars — is a derivable shape) but the *causal* claim ("margin calls triggered this") is **NOT RELIABLY OBSERVABLE**. Any implementation must separate the observable shape from the unobservable cause. |
| Unwinding (cash-only) | **NOT RELIABLY OBSERVABLE** | Indistinguishable from ordinary directional price action without OI (65.14-R §3.6). |
| Unwinding (OI-vs-price cross table, once F&O exists) | **INFERRED** | Standard, well-established interpretation model, but still an inference from OI+price co-movement, not a direct read of a party's book. |
| Market Sentiment (any OHLCV-derived form) | **PROXY at best** (volatility-regime), explicitly REJECTED per 65.14-R §3.9 as redundant with existing ATR/`market_regime` — do not build even as a labeled proxy. | |
| Market Sentiment (breadth-derived) | **DERIVED**, once full-universe ingestion exists (does not today) | A/D ratios and new-highs/lows are computable facts, not inferences, given the raw universe data. |
| Market Sentiment (news/vendor) | **EXTERNALLY SOURCED** | Must never be presented with the same confidence as a DERIVED feature; carries HIGH look-ahead risk from re-timestamped archives. |
| Market Sentiment (options-derived, e.g. PCR/IV skew) | **DERIVED**, once NSE_FNO/OptionQuote exists (does not today) | A well-established professional metric, directly computable from OI/IV data once ingested — not an inference once the source data exists. |

**Enforcement rule:** any future feature/context module's docstring and
its `FieldDataType`/naming must declare its observability level. A
PROXY or INFERRED output must never be named as though it were DERIVED
(e.g. `fire_sale_proxy`, never `fire_sale`; `long_liquidation_inferred`,
never `long_liquidation`). A NOT RELIABLY OBSERVABLE concept must never
appear as a feature output at all — only as documentation of what is
out of reach.

---

## Part 3 — Implementation Decision Matrix

| Concept | Current Status | Architectural Layer | Required Data | Data Available Now | Historical Avail. | Live Avail. | Backtestable | Look-Ahead Risk | False-Positive Risk | Redundancy Risk | Complexity | Info Value | Priority | Dependency | Validation Requirement |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Short-Term Rebound | EXISTING | Feature | OHLCV | Yes | Yes | Yes | Yes | None (verified) | Falling-knife | Low (deliberately excludes MA-distance) | Low | Medium | Done | None | Already gated by existing tests; no new action |
| `confirmed_rebound` label | Not built | Backtest/outcome labeling utility only | OHLCV forward bars | Yes (but by definition future-relative) | Yes | N/A (label, not RT feature) | Yes (as a label) | HIGH if ever exposed as a real-time feature | N/A | Low | Low | Medium (for outcome analytics) | Priority 3 (Phase D) | rebound_candidate | Must never enter `field_registry`; lives only in outcome-analysis code |
| MA Divergence | EXISTING | Feature | OHLCV | Yes | Yes | Yes | Yes | None (verified) | Sideways whipsaw | High overlap w/ `price_vs_ma_pct` but KEEP (different reference series) | Low | Medium | Done | None | None |
| Sector Deviation | RESEARCH-ONLY | Feature/Context/Signal-filter | Sector index OHLCV + stock→sector mapping | No | No | No | No (until data exists) | HIGH if beta-adjusted variant estimated using data beyond t | Mis-mapped sector membership | None (distinct axis from market_regime/index correlation) | Medium-high | High | 1 (post-data) | Sector data foundation (Part 9) | REAL_DHAN-provenance sector data; out-of-sample backtest before any strategy use |
| Sector-wise DMA | RESEARCH-ONLY | Feature/Context | Sector index OHLCV | No | No | No | No | Low once built correctly | Low | None in principle; shares data pipeline w/ Sector Deviation — bundle, don't duplicate effort | Medium (reuses existing SMA/EMA compute) | Medium | 2 (post-data) | Same sector data foundation | Same as Sector Deviation |
| Fire Sale Proxy | RESEARCH-ONLY | Context / Risk Layer modifier | OHLCV (RVOL/ATR/gap) — proxy version buildable today | Yes (proxy inputs only) | Yes | Yes | Yes | Low | Ordinary high-volatility bars (e.g. results day) misflagged | None (kept conceptually separate from `market_regime`=BEAR) | Low-medium | Medium (capped by no breadth/OI to disambiguate) | 2 | None for proxy version; breadth version needs full-universe ingestion | Must be validated on REAL_DHAN data; must never be renamed `fire_sale` without breadth/OI confirmation upgrade |
| Unwinding (cash-only) | REJECTED as a buildable proxy | N/A | Price+volume only | Yes but insufficient | Yes but insufficient | Yes but insufficient | N/A — would be indistinguishable from ordinary price action | N/A | HIGH — cannot separate long-liq from fresh shorting | N/A | N/A | None (rejected) | DEFER (entire concept) | NSE_FNO/OI | Must not be built even as a labeled proxy — 65.14-R's own conclusion |
| Unwinding (OI-gated) | RESEARCH-ONLY | Feature/Context | OI history (`OpenInterestObservation`) | No (0 rows) | No | No | No | Low once OI exists, if computed strictly ≤t | Low (well-established interpretation) | None | Low once OI exists (standard cross-table) | High | Research Later | NSE_FNO/OI ingestion (explicitly out of scope) | Full OI backfill/live feed validated before any use |
| Bull/Bear Regime | EXISTING | Feature (categorical) | OHLCV | Yes | Yes | Yes | Yes | None (verified) | Regime-dependent w/ other features, not itself | Structural overlap w/ `ma_divergence_ema` sign — KEEP both, documented | Low | Medium | Done | None | None |
| Regime v2 composite | Not built | Context | Breadth + drawdown + sector participation (partially blocked) | Partial | Partial | Partial | Partial | Depends on components | Unproven | Would need to prove existing `market_regime` insufficient first | Medium-high | Unproven | DEFER | Breadth infra, sector data | Evidence current rule is insufficient for a real consumer |
| Market Sentiment (volatility proxy) | REJECTED | N/A | OHLCV | Yes | Yes | Yes | Yes | Low | N/A | HIGH — redundant with ATR/market_regime | N/A | None (rejected) | Rejected | None | N/A |
| Market Sentiment (breadth) | RESEARCH-ONLY | Context | Full-universe per-bar ingestion | No | No | No | No | Low | Universe-coverage gaps | Low | High (new heavy ingestion) | Medium-high | Research Later | Full-universe ingestion pipeline | Universe coverage validated bar-by-bar |
| Market Sentiment (options) | RESEARCH-ONLY | Context | NSE_FNO/OptionQuote | No | No | No | No | Moderate | Low once data exists | Low | High | Medium-high | Research Later (F&O-gated) | NSE_FNO/OI ingestion | Same OI validation as Unwinding |
| Market Sentiment (news/vendor) | RESEARCH-ONLY | Context | External feed + NLP | No | No | No | No (archives rarely clean) | HIGH | HIGH (noisy) | Low | High + ongoing cost/dependency | Uncertain | Research Later, lowest sub-priority | External vendor contract | Timestamp-integrity audit of any vendor archive before backtest use |
| Index vs Stock Correlation | RESEARCH-ONLY | Context / Risk modifier / anomaly detector | Index OHLCV | No | No | No | No | Low if computed strictly ≤t | Illiquid-stock noise mistaken for decoupling | None (distinct from market_regime and Sector Deviation) | Low-medium once index data exists | High | 1 (post-data) | Index data foundation (Part 9) | REAL_DHAN-provenance index data; liquidity gate before use as anomaly detector |

---

## Part 4 — Correlation Intelligence: Refined Analytical Model

Extending 65.14-R §4's `Feature → Context → Strategy → Signal → Outcome`
chain into the explicit pairwise/combined analyses the directive
requests. All of the below are **descriptive analytics on top of the
existing read-only `correlation_repository.py`/`SignalEvidenceRecord`
infrastructure** — no new storage concept, no new inference engine, and
none of them are runnable today because 0 real trades exist.

| Analysis | What it measures | Data source | Status |
|---|---|---|---|
| Feature→Signal | Distribution of a feature's value among bars where a strategy actually fired | `SignalEvidenceRecord` | Architecturally possible today for any strategy that populates evidence; no real data yet |
| Feature→Outcome | Correlation between a feature's value at signal time and `realized_pnl` | Evidence + `PaperTradeRecord` via `signal_id` | Same |
| Context→Signal | Signal rate conditioned on `market_regime` (or future context) category | Evidence, if the strategy records context | Requires the consuming strategy to actually record context as evidence — not true for Gainz today |
| Context→Outcome | `realized_pnl` conditioned on context category at signal time | Evidence + trades | Same prerequisite |
| Strategy→Outcome | `realized_pnl` distribution per `strategy_version_identifier` | Existing linkage | Possible today, no real data |
| Feature+Context→Outcome | `realized_pnl` conditioned on a feature value AND a context category jointly | Evidence + trades, grouped | New reporting logic only, no new storage |
| Feature+Strategy→Outcome | Same feature, split by strategy version — tests whether a feature's value is predictive independent of which strategy consumed it | Evidence + trades | New reporting logic only |
| Context+Strategy→Outcome | Regime-conditioned performance per strategy version | Evidence + trades | New reporting logic only |
| Regime-conditioned performance | Win-rate/PnL split by `market_regime` category | Evidence + trades | New reporting layer |
| Feature-threshold performance | Outcome split by feature value bucket (e.g. RSI<20 vs 20-30 vs 30+) | Evidence + trades | New reporting layer |
| Feature interaction effects | Outcome for combinations, e.g. `rebound_candidate=1 AND market_regime=BEAR` | Evidence + trades, grouped | New reporting layer; requires enough joint sample size to be meaningful |
| Sector-conditioned performance | Outcome split by stock's sector at signal time | Evidence + trades + sector mapping | Blocked until sector data exists |
| Index-conditioned performance | Outcome split by index-correlation regime (e.g. high/low decoupling) | Evidence + trades + index data | Blocked until index data exists |
| Gainz-conditioned performance | Outcome split specifically for `gainz_compatible_research` signals, further sliced by context | Evidence + trades | Blocked — not in `build_default_registry()`, no real signals yet |

**Non-negotiable reporting discipline for every row above, once built:**
1. Report sample size (N trades) alongside every figure — a correlation
   from <30 trades should be labeled "insufficient sample," never
   presented as a finding.
2. Report the time period and market regime(s) covered — a correlation
   measured across one bull-only tape is not a general finding.
3. Report `strategy_version_identifier` — a correlation for v1 of a
   strategy does not necessarily hold for v2.
4. Never auto-promote a discovered correlation into a strategy parameter
   change without an out-of-sample validation step on a held-out period.
5. Report correlations regime-conditioned wherever possible, never as a
   single pooled number across regimes, since pooled correlations are far
   more prone to being spurious/confounded than within-regime ones.
6. **Correlation ≠ causation, explicitly, on every output.** A discovered
   Feature→Outcome correlation is evidence *worth investigating*, not
   proof the feature *causes* the outcome — confounds (e.g. both the
   feature and the outcome being driven by the same underlying regime)
   must be actively considered, not assumed away, before any correlation
   is treated as actionable.

---

## Part 5 — Gainz Alpha Experimental Methodology

Gainz remains untouched. This defines how future evidence must be
collected — not a promise the enhanced version will win.

**Controlled, single-variable comparison, one context factor at a time:**

1. **Baseline**: Gainz `alpha` profile exactly as it exists today, run
   over a REAL_DHAN-provenance backtest period, producing a baseline
   win-rate/PnL/sample-size distribution.
2. **Gainz + Market Regime**: identical Gainz logic, with exactly one
   change — signals are additionally gated/filtered by `market_regime`
   category (e.g. suppress BEAR-regime signals) — measured over the
   *same* backtest period, same strategy version otherwise.
3. **Gainz + Index Correlation** (once index data exists): identical
   baseline, with only an index-correlation gate/risk-modifier added.
4. **Gainz + Sector Deviation** (once sector data exists): identical
   baseline, with only a sector-deviation gate added.
5. **Gainz + multiple context features combined**: only attempted *after*
   each single-factor experiment (2-4) has independently been measured —
   never skip straight to the combined version, because a combined result
   cannot be attributed to any one factor without the single-factor
   baselines already in hand.

**Rules:**
- Change exactly one variable per experiment. Never test "Gainz +
  regime + index correlation" as the *first* comparison against baseline.
- Use the same backtest period, same instrument universe, and the same
  `strategy_version_identifier` scheme across all variants in a given
  comparison set, so differences in the outcome are attributable to the
  added context, not to a different test setup.
- Report sample size, time period, and regime coverage for every variant
  (per Part 4's reporting discipline).
- Require the comparison period to span more than one `market_regime`
  category where feasible, so a result isn't an artifact of one
  particular tape (65.14-R §7).
- Do not assume the enhanced version is better — a null or negative
  result (context gating reduces trade frequency without improving
  win-rate/PnL) is a valid and useful outcome, and must be reported as
  such, not discarded.
- None of this is runnable until real trades exist (0 today). This
  methodology is prepared, not executed, in this checkpoint.

---

## Part 6 — Backtest Integration Design

The canonical backtest engine is not modified. Every future
feature/context enters through the same seam `market_regime` already
proved: delivered as a `FeatureValue`/`CategoricalFeatureValue` series
through the existing dispatcher, at a bar-indexed cadence, computed
strictly on bars ≤t.

| Future feature | Timestamp availability | Warm-up period | Calc window | Signal-time value | Execution-time value | Leakage risk |
|---|---|---|---|---|---|---|
| Sector Deviation | Requires sector index bar aligned to the same timestamp as the stock bar | Return lookback + (if beta-adjusted) a longer daily estimation window | N bars for spread; weeks for beta | Value at bar t only | Not re-evaluated after signal — same discipline as existing features (no changing feature value between signal and execution) | HIGH if beta ever estimated using data beyond t; must roll strictly on ≤t history |
| Sector-wise DMA | Same as Sector Deviation (shared pipeline) | DMA lookback | N bars | At t | Same | Low, identical discipline to existing MA features |
| Fire Sale Proxy | OHLCV only, already timestamp-aligned | RVOL/ATR lookback | N bars | At t | Same | Low |
| Index↔Stock Correlation | Requires index bar aligned to stock bar timestamp | Rolling correlation window N | N bars | At t | Same | Low if computed strictly on ≤t returns |
| Unwinding (OI-gated) | Requires OI observation aligned to bar timestamp | OI lookback | N bars | At t | Same | Low once OI exists and alignment is validated; HIGH if OI timestamps are looser than bar timestamps (must be explicitly checked, not assumed) |
| Sentiment (breadth) | Requires full-universe per-bar coverage at the same timestamp | Depends on metric | N bars | At t | Same | Low if universe coverage is complete; HIGH if any instrument's bar is missing/stale at that timestamp (silent gaps inflate/deflate breadth) |
| Sentiment (news/vendor) | External, frequently re-timestamped after publication | N/A | N/A | Ambiguous — "value at signal time" requires knowing what was known *at that literal moment*, which vendor archives routinely misrepresent | N/A | HIGH — classic look-ahead trap; must not be integrated without an audited, immutable historical archive |
| `confirmed_rebound` label | By definition forward-looking (`t+k`) | N/A (label, not RT feature) | k bars forward | **Must never have a signal-time value** — it does not exist at signal time | N/A — outcome-analysis only | Inherent, and precisely why it must never enter the feature/backtest dispatcher as an RT feature |

No entry/exit/SL/Target/first-hit/accounting semantics are proposed to
change for any of these — every future feature is additive context/risk
input to the existing decision surface, never a replacement for it.

---

## Part 7 — Fire Sale Proxy Design

A future `fire_sale_proxy` context feature (NOT implemented here) is
explicitly a **dislocation detector**, never a true Fire Sale detector.
Its observability level (Part 2) is **PROXY**.

**Observable components** (all DERIVED, all buildable from OHLCV alone
today, none implemented):
- Abnormal price displacement: an unusually large negative return over a
  short window relative to the stock's own recent distribution.
- Abnormal volume: `relative_volume` materially above its own baseline,
  co-occurring with the price displacement (not independently — a volume
  spike alone, or a price drop alone, is not dislocation).
- Gap behavior: an opening-bar gap materially below the prior close,
  especially with continued selling into the open.
- Volatility shock: ATR/true-range spike relative to its own recent
  history.
- Market breadth/context: **not available today** (no full-universe
  ingestion) — would strengthen the proxy materially if it existed, by
  distinguishing an idiosyncratic single-stock event (e.g. results day)
  from a market-wide dislocation, but its absence does not block the
  narrower single-stock proxy.
- Index/sector dislocation: **not available today** — same strengthening
  role as breadth, blocked on Part 9's data foundation.

**Proposed future states** (design only, not implemented):

| State | Meaning | Approx. trigger shape |
|---|---|---|
| `NORMAL` | No dislocation signature present | Price/volume/ATR within normal recent ranges |
| `ELEVATED_DISLOCATION` | One or two of the observable components elevated but not jointly extreme | e.g. RVOL elevated but price displacement modest, or vice versa |
| `FIRE_SALE_PROXY` | Multiple observable components jointly extreme (large negative price displacement + high RVOL + volatility shock, optionally gap-down) | Co-occurrence, not any single component alone — this is the core design discipline that keeps it honest as a *dislocation* read rather than a single-metric relabeling |
| `RECOVERY` | Price/volume normalizing after a prior `FIRE_SALE_PROXY` state within a bounded lookback | Requires state-transition logic, not just a point-in-time threshold |

**Explicit constraints carried forward from 65.14-R:**
- Must be kept conceptually separate from `market_regime`=BEAR — BEAR is
  a sustained trend classification, this is an event/dislocation
  classification that can occur inside any regime, including a brief
  panic within an otherwise BULL tape.
- Must never claim "forced" selling — only "abnormal dislocation."
- If/when breadth or sector/index data becomes available, a stronger
  breadth-confirmed variant should be revisited, but the OHLCV-only proxy
  should not wait for that.
- Belongs in the Market Context layer (composing existing RVOL/ATR/gap
  computations), consumed by the Risk Layer as a size-down/pause-entry
  modifier — never a standalone signal generator (per 65.14-R §6 Rule 2
  and Rule 5).

---

## Part 8 — Unwinding Design (Cash vs OI-Gated)

Explicitly NOT implementing OI-based unwinding — NSE_FNO/OI remains
out of scope. This section only classifies what is/isn't inferable.

| Evidence type | Cash-only (today) | With OI (future, gated) |
|---|---|---|
| Long liquidation evidence | **NOT RELIABLY OBSERVABLE** — a volume spike with falling price is equally consistent with fresh short-selling | **INFERRED** — falling OI + falling price, under the standard interpretation model |
| Short-covering evidence | **NOT RELIABLY OBSERVABLE** — a volume spike with rising price is equally consistent with fresh long buying | **INFERRED** — falling OI + rising price |
| Generic position unwinding | **NOT RELIABLY OBSERVABLE** from cash data alone | **INFERRED**, via the full OI-vs-price cross table (falling OI in either price direction) |
| Price-volume reversal | **DERIVED** — a real, nameable pattern (e.g. a sharp reversal candle on elevated volume) | Same, but should be reported alongside the OI inference, not confused with it |

**The critical distinction this section enforces:** "price-volume
reversal" is a real, honestly-nameable DERIVED pattern that can be built
from cash data today — but it must never be labeled or marketed as
"unwinding," "long liquidation," or "short covering," because those
specific claims require the OI-vs-price cross table this platform does
not have. A future cash-only feature may legitimately be named
`price_volume_reversal`; it may not be named `unwinding_proxy`, because
unlike Fire Sale (where a defensible dislocation proxy exists), 65.14-R's
own conclusion is that a cash-only unwinding proxy is indistinguishable
from ordinary directional price action and should not be built at all —
even as a labeled proxy.

---

## Part 9 — Sector/Index Data Foundation Roadmap

Design only, not implemented. Determines the minimum architecture Index
Correlation, Sector Deviation, and Sector-wise DMA all need.

**Minimum index series:** at least one broad market index (e.g. NIFTY 50)
ingested at the same bar timeframe the strategies run on, with the same
provenance discipline as `HistoricalBar` (REAL_DHAN vs synthetic must be
distinguishable, exactly as it is for stock bars today).

**Sector index series:** one index series per sector classification
scheme in use (e.g. NIFTY sectoral indices) — need not be exhaustive on
day one, but must cover the sectors of whatever stock universe the
platform trades.

**Stock→sector mapping:** a table (does not exist in `models.py` today,
confirmed at both 65.02 and 65.14-R) mapping each tradable instrument to
exactly one sector for deviation purposes, with an explicit "unmapped"
state rather than a default/guessed sector — per 65.14-R §3.3's honest-
failure requirement.

**Timestamp alignment:** index/sector bars must be aligned to the exact
same bar timestamps as stock bars; any misalignment (e.g. an index bar
missing at a timestamp a stock bar has) must produce an explicit
missing-data state for that computation at that bar, never a silently
stale or interpolated value — a repeat of the same discipline
`HistoricalBar.provenance` already enforces for stock data.

**Historical coverage:** must be backfilled far enough to support the
longest lookback any dependent feature needs (e.g. weeks, for a
beta-adjusted Sector Deviation variant) — not just from whatever date
live ingestion happens to start.

**Live coverage:** index/sector instruments must be added to whatever
live capture mechanism the (deferred) real 65.14 NSE session capture
uses — this is new live-data scope, not a byproduct of capturing stock
instruments alone.

**Corporate-action handling:** sector index composition changes
(reconstitutions) and stock-level corporate actions (that could shift
sector classification, e.g. a demerger) must be handled explicitly —
an unhandled reconstitution silently corrupts historical sector-relative
comparisons across the change date.

**Missing-data behavior:** for all three concepts, a missing
index/sector bar or mapping must produce "no output" (an explicit
missing/unavailable state), never a defaulted or last-known-value
guess — consistent with 65.14-R §3.3(I)'s explicit requirement.

**Shared foundation determination:** **Yes** — Index Correlation, Sector
Deviation, and Sector-wise DMA should share one data foundation (a
common "reference index/sector series" ingestion + alignment +
provenance layer), with the three features differing only in which
reference series they read and what statistic they compute over it.
Building three separate ingestion paths would triple the corporate-
action/alignment/provenance work for the same underlying data shape.

---

## Part 10 — Sentiment Comparison and Deferral Recommendation

| Source | Reliability | Availability | Backtestability | Latency | Cost | Look-ahead risk | Rank |
|---|---|---|---|---|---|---|---|
| Volatility-derived (ATR percentile) | Reasonable proxy for "stress," not sentiment | Available today | Yes | None | None | Low | Buildable but REJECTED — redundant with existing ATR/`market_regime` (65.14-R §3.9) |
| Breadth-derived (A/D, new highs/lows) | Well-established | Blocked — needs full-universe ingestion | Yes, once available | Real-time if computed in-house | Heavy (full universe every bar) | Low | 2nd most reliable, most work to unblock |
| Options-derived (PCR, IV skew) | Well-established professional metric | Blocked — needs NSE_FNO/OptionQuote | Yes, once OI/IV history exists | Real-time if subscribed | Requires exactly the F&O data out of scope | Moderate | 1st most reliable, but hard-gated by the platform-wide F&O prohibition |
| Price-derived (India VIX level) | Proxy, not "true" sentiment | Blocked — new instrument not ingested | Yes if historical VIX archived | Real-time if subscribed | New feed dependency | Low if timestamp-aligned | Middling |
| News sentiment (NLP) | Noisy, vendor-dependent | Blocked — new external dependency | Very hard — archives rarely timestamp-clean | Seconds-to-minutes | New paid dependency + inference pipeline | HIGH | Least reliable, worst risk profile |
| External vendor/social scores | Unverified, black-box | Blocked | Poor — rarely clean historical replay | Varies | Ongoing external cost/reliability risk | HIGH | Least reliable, worst risk profile |

**Recommendation, reaffirmed from 65.14-R and made explicit here:**
Market Sentiment as a whole should remain **deferred until the core
market context foundation (Part 9's index/sector data, and ideally
breadth) is proven** — not because sentiment is uninteresting, but
because every currently-buildable form is either redundant with
existing features (volatility) or gated on infrastructure this platform
does not have (breadth, options, external feeds). Sentiment should not
be the platform's next investment; it sits behind Sector/Index Context
in the priority order (Part 13).

---

## Part 11 — Feature Redundancy Rule (Permanent Design Rule)

**Rule, to be applied before any future feature is added to this
platform, without exception:**

> Before adding a feature, prove that no existing feature already
> provides materially the same information. This proof must explicitly
> answer: (1) Does an existing feature already compute this exact
> quantity? (2) Does an existing feature compute a materially equivalent
> quantity under a different name/formula? (3) What new information does
> this feature provide that no existing feature or combination provides?
> (4) What interaction value does it add when combined with existing
> features (not just its standalone value)? (5) What incremental
> backtest value has been measured (once real data exists) — not
> assumed? If the answer to (1) or (2) is yes and (3)/(4) do not
> establish a genuinely new axis, the proposal must be REJECTED or
> MERGED into the existing feature/strategy-layer composition, never
> built as a parallel feature.

This formalizes the discipline 65.14-R's redundancy matrix (§5) already
applied ad hoc (rejecting MA-distance-as-4th-rebound-condition,
volatility-as-sentiment) into a standing rule for every future proposal,
including ones not yet conceived. It also governs the six concepts in
this document that survive as FUTURE: each was checked against (1)-(4)
in 65.14-R §5 and 65.15-R Part 3 and found to measure a genuinely
distinct axis (stock-vs-sector, sector-vs-own-history, stock-vs-index-
co-movement, dislocation-vs-trend) before being carried forward — none
of them get a pass on this rule merely by having survived to this
checkpoint; the rule applies again at actual implementation time with
whatever the feature set looks like then.

---

## Part 12 — Implementation Gates

No feature may bypass these gates, in order. This is the checkpoint's
central new contribution.

- **GATE 1 — Real historical data exists.** At least one genuinely
  COMPLETE `MarketDataArchiveDay` with REAL_DHAN provenance exists for
  the instrument(s) the feature needs (stock, index, or sector, as
  applicable). Currently: 0 REAL_DHAN rows platform-wide — GATE 1 is not
  yet passed for anything.
- **GATE 2 — Data completeness/provenance validated.** The archived data
  has been checked for gaps, duplicate bars, and correct
  provenance-tagging (REAL_DHAN vs synthetic never conflated), and for
  any multi-series feature (sector, index, OI), correct timestamp
  alignment across the series has been verified, not assumed.
- **GATE 3 — Feature calculation validated.** The feature's formula has
  been computed against the validated data and manually/targeted-test
  spot-checked against a small number of known bars, confirming it
  matches the documented formula exactly (no off-by-one lookback, no
  accidental future-bar read).
- **GATE 4 — Backtest integration validated.** The feature is delivered
  through the existing `FeatureValue`/`CategoricalFeatureValue`
  dispatcher seam with zero changes to entry/exit/SL/Target/first-hit/
  accounting semantics, and a targeted check confirms the backtest run
  using it reproduces identical results to a run without it when the
  feature is not gated on (i.e. it is provably inert until a strategy
  actually consumes it).
- **GATE 5 — Baseline performance established.** For whatever strategy
  will eventually consume the feature (e.g. Gainz), a baseline
  performance distribution (win-rate/PnL/sample size) exists on
  REAL_DHAN-provenance data *without* the new feature, per Part 5's
  methodology.
- **GATE 6 — Incremental feature/context performance measured.** The
  same strategy is re-run with only the one new feature/context added
  (single-variable, per Part 5), and the incremental effect on the
  baseline is measured and reported with sample size, time period,
  strategy version, and regime coverage attached.
- **GATE 7 — No material leakage.** A specific, documented check
  confirms the feature's signal-time value could have been known at
  that literal moment in real trading — no forward bar reads, no
  re-timestamped external data, no beta/regression window extending
  past t. This is a distinct, explicit gate from Gate 3's formula
  check, because a formula can be locally correct yet still leak if its
  *inputs* (e.g. a sector index bar) were not actually available at t
  in a live setting.
- **GATE 8 — Production integration approved.** Only after Gates 1-7
  pass, with evidence (not assumption) that the feature provides
  incremental value, and with explicit reviewer sign-off, may the
  feature be wired into a live-reachable strategy/registry entry (e.g.
  registered in `build_default_registry()`).

No concept in this document has passed Gate 1 yet, because 0 REAL_DHAN
rows exist platform-wide. This is what makes every "FUTURE" item in Part
1 genuinely future, not merely unbuilt.

---

## Part 13 — Re-Evaluated Priority Ranking

Re-run using: data availability, implementation cost, incremental info
value, backtestability, live feasibility, missing-infrastructure
dependency, redundancy, risk.

| Order | Concept | Rationale for position |
|---|---|---|
| **0 (prerequisite to everything below)** | Real NSE session capture → REAL_DHAN archive validation (the deferred real 65.14) | Gate 1 blocks every other item; nothing below is backtestable-with-evidence until this exists. Not itself one of the 10 concepts, but sequences ahead of all of them. |
| **1** | Index↔Stock Correlation | Lowest implementation complexity once index data exists (rolling correlation is cheap, standard), lowest look-ahead risk if built correctly, and only needs ONE new series (a single index), not a mapping table — a materially smaller data-foundation lift than Sector Deviation. Highest info-value-per-complexity of the blocked concepts. |
| **1** | Sector Deviation | Ties with Index Correlation on info value (genuinely new axis, high strategy-integration value as a signal filter) but carries higher implementation cost (needs both a sector index series AND a stock→sector mapping table, with mapping-error risk Index Correlation doesn't have) — kept at priority tier 1 but sequenced to build on the shared foundation (Part 9) alongside Index Correlation, with Index Correlation likely landing first given the smaller data lift. |
| **2** | Sector-wise DMA | Same data dependency as Sector Deviation — bundle into the same effort — but lower standalone value since it restates information a strategy could largely already derive from Sector Deviation's own inputs. |
| **2** | Fire Sale Proxy (OHLCV-only) | Buildable today with zero new data dependency (highest live/backtest feasibility of any blocked concept), but real-world value is capped without breadth/OI to disambiguate genuine dislocation from ordinary volatility — useful mainly as a Risk Layer modifier, not a signal generator. |
| **Research Later** | Unwinding (OI-gated) | Entirely gated on NSE_FNO/OI, explicitly out of scope platform-wide; highest complexity of any item once unblocked. |
| **Research Later** | Market Sentiment | Every real source blocked (breadth/OI/VIX/news); the only currently-buildable form is redundant. Lowest priority of the researched concepts. |
| **Defer** | `market_regime` v2 composite | No evidence current rule is insufficient; speculative. |

**Did the order change from 65.14-R?** Not in substance — 65.14-R's §10
already placed Index↔Stock Correlation and Sector Deviation jointly at
"PRIORITY 1 (once data exists)," Sector-wise DMA and Fire Sale Proxy at
"PRIORITY 2," and Unwinding/Sentiment at "RESEARCH LATER." This
checkpoint's Part 13 re-derivation, run independently against the eight
stated criteria, **arrives at the same ordering** but makes one
refinement explicit that 65.14-R left implicit: **within the tied
"Priority 1" pair, Index↔Stock Correlation has a materially smaller data
foundation than Sector Deviation** (one series vs a series-plus-mapping-
table), so if the two cannot be built simultaneously, Index Correlation
should land first even though both remain co-equal in information value.
This is a sequencing refinement, not a re-ranking — the directive's
instruction not to assume Index Correlation must stay #1 was checked
explicitly and confirmed correct rather than assumed correct.

---

## Part 14 — Real-Data Dependency: Why It Gates Almost Everything

The real 65.14 (live NSE session capture) → REAL_DHAN archive →
`HistoricalBar` → canonical backtest → evidence chain must precede most
new intelligence work because:

1. **Gate 1 (Part 12) is a hard floor.** Every backtestability claim,
   every incremental-value measurement, every "does this actually help
   Gainz" question in Part 5 is meaningless without real trades on real
   data — 65.11's own established finding (synthetic/fixture backtest
   results are engine validation only, never market evidence) applies
   identically here.
2. **A correlation computed on synthetic data is not evidence of
   anything** about the real market, no matter how sophisticated the
   analytics layer in Part 4 becomes — the analytics layer's correctness
   and the data's realism are separate questions, and only the second one
   makes a result *evidence*.
3. **Look-ahead risk can only be conclusively ruled out against a real,
   fully-timestamped archive** — synthetic/fixture data can hide
   alignment bugs that a real multi-instrument archive (with real gaps,
   real halts, real corporate actions) would expose.

**What CAN proceed before real data exists (research/design work only):**
- Formula design and comparison for Sector Deviation variants (this
  document, done).
- Fire Sale Proxy state design and component selection (this document,
  done).
- The correlation/analytics-layer design (Part 4) and the Gainz
  experimental methodology (Part 5) — designing the *method* does not
  require real data, only *running* it does.
- The Part 9 data-foundation architecture (what tables, what alignment
  rules, what provenance discipline) — this is schema/pipeline design,
  reviewable without any data flowing through it yet.
- The Implementation Gates themselves (Part 12) — a process definition,
  not a data-dependent artifact.

**What MUST wait for real data:**
- Any actual sector/index ingestion running against live/historical
  Dhan feeds.
- Any Gate 3-8 activity for any concept.
- Any Gainz experiment from Part 5 (steps 1-5).
- Any correlation/outcome analysis from Part 4 producing an actual
  number (as opposed to the analysis being defined).
- Registering `gainz_compatible_research` into `build_default_registry()`
  for real evaluation — remains out of scope until there is real data to
  evaluate it against, independent of this checkpoint's other findings.

---

## Part 15 — Final Roadmap

```
CURRENT (65.15-R, research/design only)
   |
   v
65.14 Real NSE Capture (deferred; requires market open + explicit go-ahead)
   |
   v
Archive Validation (Gate 1 + Gate 2: REAL_DHAN completeness, provenance,
   gap-checking)
   |
   v
Archive -> HistoricalBar (existing pipeline, validated against real data)
   |
   v
REAL_DHAN Backtest Validation (Gate 4: canonical backtest run against
   real data, confirming existing entry/exit/SL/Target/accounting
   semantics behave identically to synthetic-data runs)
   |
   v
Baseline Strategy Evidence (Gate 5: baseline win-rate/PnL/sample-size for
   existing strategies, including Gainz, on real data — no context
   features added yet)
   |
   +--> Market Intelligence Features (Phase A/B/C, parallel tracks once
   |     baseline exists):
   |       - Phase A: Index + Sector data foundation (Part 9)
   |       - Phase B: Index<->Stock Correlation, Sector Deviation,
   |         Sector-wise DMA (Gates 3-4, once Phase A lands)
   |       - Phase C: Fire Sale Proxy (Gates 3-4; independent of Phase A,
   |         can proceed in parallel since it needs no new data)
   |
   v
Correlation/Outcome Analysis (Part 4's analytics layer, run against real
   evidence once Phase A-C features exist and have real signals to
   analyze)
   |
   v
Gainz Contextual Experiments (Part 5's single-variable methodology,
   Gates 5-6, run only after the relevant context feature has passed
   Gates 1-4 individually)
   |
   v
Production Integration (Gate 8: only for features with measured,
   reviewed, positive incremental evidence — registration into
   build_default_registry() or equivalent, with explicit sign-off)
```

Sequence changes from the directive's suggested structure: none of
substance — Sentiment and Unwinding are folded into the "Market
Intelligence Features" phase as explicitly lowest-priority/blocked
sub-tracks (per Part 13) rather than given their own top-level roadmap
stage, since both remain gated on infrastructure (breadth/F&O) that this
roadmap does not otherwise build.

---

## Final Output

**A. What is already implemented?**
Short-Term Rebound (`rebound_candidate`), MA Divergence
(`ma_divergence_sma`/`_ema`), Bull Regime and Bear Regime (both branches
of `market_regime`). All four are tested, verified no-look-ahead, and
require no further action.

**B. What is genuinely new?**
The Observable-vs-Inferred taxonomy (Part 2) and the eight Implementation
Gates (Part 12) are new analytical contributions of this checkpoint (not
present in 65.14-R). Substantively new *concepts* beyond what 65.14-R
already scoped: none — this checkpoint deliberately builds on 65.14-R's
concept research rather than introducing new market-intelligence ideas,
per the directive's research/design-only framing.

**C. What should be rejected as redundant?**
Volatility-as-sentiment (redundant with ATR/`market_regime`);
MA-distance as a 4th `rebound_candidate` condition (redundant with
`price_vs_ma_pct`); a cash-only "unwinding proxy" (would be
indistinguishable from ordinary directional price action, not merely
redundant but actively misleading if labeled "unwinding").

**D. What is a proxy rather than directly observable?**
Fire Sale/dislocation (proxy: RVOL+ATR+gap co-occurrence, never "forced
selling"); Capitulation (proxy: volume/volatility extreme near a local
price extreme, never confirmed-terminal in real time); the OHLCV-derived
"volatility sentiment" (proxy for stress, not sentiment, and rejected as
redundant regardless).

**E. What requires sector data?**
Sector Deviation, Sector-wise DMA (both fully blocked; share one data
foundation per Part 9).

**F. What requires index data?**
Index↔Stock Correlation (fully blocked); a hypothetical richer
market-wide regime composite would also benefit from index data but is
DEFERRED regardless of data availability.

**G. What requires F&O/OI?**
Unwinding in its only non-ambiguous form (OI-vs-price cross table);
options-derived Market Sentiment (PCR/IV skew). Both explicitly out of
scope platform-wide (NSE_FNO/OptionQuote, 0 rows).

**H. What should remain deferred?**
Unwinding (OI-gated) — until NSE_FNO exists. Market Sentiment in every
form — until the index/sector/breadth foundation is proven and a
specific source is vetted. `market_regime` v2 composite — no evidence of
need. Any Gainz modification — no evidence of benefit yet.

**I. What should be implemented first after real data is validated?**
Per Part 13: Index↔Stock Correlation and Sector Deviation, tied at
priority 1, with Index↔Stock Correlation likely sequenced first within
that tier due to its smaller data-foundation footprint (one index series
vs an index/sector series plus a stock→sector mapping table). Fire Sale
Proxy can proceed in parallel since it needs no new data foundation at
all.

**J. What is the minimum evidence required before implementation?**
Gates 1-7 (Part 12) passed for the specific feature: real REAL_DHAN
archive data covering the needed instrument(s), validated completeness/
provenance/alignment, a formula spot-check, provable backtest inertness
until consumed, a baseline strategy performance figure, a measured
single-variable incremental effect with sample size/period/regime/
strategy-version attached, and a documented no-leakage check. Gate 8
(production sign-off) additionally requires positive, reviewed
incremental evidence — not merely passing Gates 1-7.

**K. How will correlation between Feature→Context→Strategy→Signal→Trade→
Outcome be measured?**
Via the descriptive analytics layer in Part 4, built entirely on the
existing `correlation_repository.py` (bulk, read-only, exact-ID joins)
and `SignalEvidenceRecord`, grouping stored outcomes by feature values,
context categories, strategy versions, and their combinations — not a
new inference engine, and not runnable until real signals/trades exist.

**L. How will correlation be distinguished from causation?**
Every reported correlation must carry sample size, time period, regime
coverage, and strategy version; pooled-regime correlations are treated
as more confound-prone than within-regime ones and regime-conditioning is
required wherever feasible; no discovered correlation may be promoted
into a strategy parameter without an out-of-sample validation step; and
confounding explanations (e.g. a shared regime driving both the feature
and the outcome) must be actively considered before any correlation is
called actionable (Part 4's six-point discipline).

**M. How will Gainz incremental improvement be experimentally measured?**
Via the single-variable methodology in Part 5: an unmodified baseline
run on REAL_DHAN data, then successive single-context-factor variants
(regime, then index correlation, then sector deviation, each measured
independently before any combined variant), same backtest period/
universe/strategy-version scheme across variants, spanning more than one
regime where feasible, with null/negative results reported honestly, not
discarded. Gainz itself is not modified to run this — it is measured
this way once real data and the relevant context features both exist.

**N. What is the smallest next implementation checkpoint?**
Not a market-intelligence feature at all — it is the deferred real 65.14
(live NSE session capture → REAL_DHAN archive), which is Gate 1 for
every concept in this document. Absent that, the smallest *research-only*
next step would be detailed schema/pipeline design for the Part 9 index/
sector data foundation (still zero code/database), since it is the
shared prerequisite for the two priority-1 concepts (I).

---

## Explicitly Not Done In This Checkpoint

No production source code changed. No migrations. No database changes.
No synthetic market-data generation. No live Dhan calls. No scanner
start. No notifications. No NSE_FNO/OptionQuote/sector/index
infrastructure implementation. No Fire Sale, Unwinding, Sentiment, or
Index Correlation implementation. No Gainz, EMA/SMA/ATR strategy,
scanner execution, signal routing, BacktestingService, backtest
execution, TradePlan, OrderIntent, RiskDecision, accounting, live
ingestion, Dhan integration, HistoricalBar/MarketDataArchive schema, or
Market Context feature changes.
