# Market Intelligence — Index/Sector Data Foundation (Architectural Design)

Checkpoint 65.16-R. RESEARCH/DESIGN ONLY — zero production code, zero
migrations, zero database writes, zero live Dhan connection, zero
scanner/backtest execution. NSE is closed (verified 2026-08-30 is a
Sunday; IST ≈ 14:23). Builds directly on the accepted 65.14-R
(`MARKET_INTELLIGENCE_ENHANCEMENT_RESEARCH.md`) and 65.15-R
(`MARKET_INTELLIGENCE_IMPLEMENTATION_ROADMAP.md`), both treated as
ground truth and not re-derived. This document does not repeat their
conclusions in full — it designs the shared data foundation those two
prior checkpoints identified as needed for Index↔Stock Correlation,
Sector Deviation and Sector-wise DMA, but did not specify.

---

## Executive Summary

65.15-R classified Sector Deviation, Sector-wise DMA and Index↔Stock
Correlation as blocked on the same two missing pieces: (1) index/sector
*price series* and (2) a stock→sector *mapping*. Nothing in the current
codebase supplies either — confirmed by direct inspection in Part 1
below, not assumed from prior reports. This document designs, without
implementing, the minimum data model, alignment rule, provenance
contract and quality-state vocabulary those three features would need,
and shows precisely how it would plug into the existing
`HistoricalBar` / feature-registry / backtest / Market Context
architecture rather than becoming a fourth, parallel pipeline.

The central finding: `HistoricalBar` can represent index and sector
bars with **zero schema change**, provided index/sector identifiers are
minted into the *same* `instrument_id` namespace the table already
uses (Part 2/Final Output C). The genuinely new surface is not a bar
table — it is (a) an identity/classification layer (which
`instrument_id`s are indices, which stocks belong to which sector at
which point in time) and (b) an alignment + provenance + quality-state
discipline layered on top of reads from that table. This keeps the
foundation additive, consistent with every prior checkpoint in this
line (63.x's DB-first archive, 65.12's additive provenance field,
65.05/65.03's feature-registry conventions).

---

## Part 1 — Existing Architecture (Inspected, Not Assumed)

| Dependency | State | Evidence |
|---|---|---|
| Instruments/symbols | PARTIAL | No dedicated `Instrument` model exists. `HistoricalBar` carries `instrument_id` (opaque `CharField(max_length=100)`), `exchange`, `symbol` as plain denormalized fields — identity is convention, not a referenced table. |
| Exchanges | PARTIAL | `exchange = CharField(max_length=8)` on `HistoricalBar`/others — free-text, no `Exchange` model/enum. |
| Indices | MISSING | Grepped `models.py` (39 model classes enumerated) — no `Index`, `IndexBar`, `IndexConstituent`, or similarly named model exists anywhere. Confirms 65.02/65.14-R's finding still holds at 65.16-R. |
| Sectors | MISSING | Same sweep — no `Sector`, `SectorIndex`, `SectorMembership` model exists. |
| Historical bars | EXISTS | `HistoricalBar` (models.py:1188), uniqueness `(instrument_id, timeframe, bar_timestamp)`, OHLCV as `DecimalField`, `source` (pipeline-stage provenance) + `provenance` (65.12, REAL_DHAN/SYNTHETIC_TEST/UNKNOWN data-genuineness) as two orthogonal fields. This is the intended read surface for scanner/backtester per its own docstring ("the whole point of this checkpoint's architecture is that the scanner/backtester read ONLY from this table"). |
| Live market data | EXISTS | `LiveQuoteObservation`, `AggregatedBarObservation` — a separate live-ingestion pipeline, deliberately NOT reused for historical archive identity (per `HistoricalBar`'s own docstring, which explains why it is NOT built on `AggregatedBarObservation`). |
| Market-data archives | EXISTS | `MarketDataArchiveDay` (64.73) — per-(instrument, trading date) completeness/validation projection, consumed read-only by `correlation_repository.py`'s `bulk_archive_evidence`. |
| Feature registry | EXISTS | `signal_intelligence/feature_engine/field_registry.py` + per-feature modules (`price_vs_ma_pct.py`, `ma_divergence.py`, `rebound_candidate.py`). Convention: `parse_feature_name()` strips only a *trailing run of integer segments* (periods/windows) off a feature name; a categorical axis (e.g. SMA vs EMA) cannot be smuggled into that slot and must be folded into the feature's *kind* name instead (e.g. `ma_divergence_sma`, `ma_divergence_ema`) — established precedent this design must inherit for any `sector_deviation_*`/`index_correlation_*` naming. |
| Market Context | EXISTS | `docs/research/MARKET_CONTEXT_INTELLIGENCE.md` + `market_regime` feature branch (Bull/Bear regime) — consumes feature-registry outputs, does not itself own data ingestion. |
| Correlation repository | EXISTS, but a different "correlation" | `DjangoCorrelationRepository`/`correlation_repository.py` (64.82) is a **traceability read model** (signal → order → trade → evidence → archive-completeness lineage via stored foreign keys only, explicitly "not an inference engine"). It is unrelated to Pearson/Spearman price correlation and must not be confused with, or reused as, the future Index↔Stock Correlation feature's storage. |
| SignalEvidenceRecord | EXISTS | `models.py:1720` — `fields: JSONField` of `[label, value]` pairs, referenced by `signal_id` string (never a Django FK), immutable evidence snapshot. A future correlation/sector-deviation feature would surface here only as another `[label, value]` pair, unchanged shape. |
| Backtesting | EXISTS | `BacktestRun`, `BacktestResultRecord`, canonical DB-first backtest engine (63.x line) reading `HistoricalBar` exclusively. |
| Dhan integration | PARTIAL/UNSAFE-TO-TOUCH | `DhanCredential`, live quote polling exist; no real historical-candle REST adapter exists yet (`PROVENANCE_REAL_DHAN` constant defined in `domain/market_data/provenance.py` but "no provider that emits this label exists yet as of 65.12"). Out of scope to touch this checkpoint regardless.
| `provenance.py` module | EXISTS | `domain/market_data/provenance.py` — `PROVENANCE_REAL_DHAN` / `PROVENANCE_SYNTHETIC_TEST` / `PROVENANCE_UNKNOWN`, exhaustive/mutually exclusive, `is_research_eligible()` gate. This is the exact vocabulary the index/sector foundation must reuse, not reinvent. |
| Archive→HistoricalBar projection | DOCUMENTED, NOT IMPLEMENTED | 65.12 designed but did not build a real Dhan historical-candle adapter; `MarketDataArchiveDay` → `HistoricalBar` projection path exists structurally but has no REAL_DHAN-labeled rows flowing through it yet. |
| Database models file | EXISTS | `src/intraday/infrastructure/persistence/models.py`, 39 model classes as of this checkpoint, `app_label = "persistence"` throughout. |
| API contracts | NOT INSPECTED IN DEPTH (out of scope) | No index/sector-related API surface found in the files touched during this inspection; irrelevant until Gate 3+ (per 65.15-R gating). |

No file in this table was modified during this inspection.

---

## Part 2 — Index Data Model Design

**Scope**: NIFTY 50, BANKNIFTY, FINNIFTY, MIDCPNIFTY (NSE), SENSEX
(BSE) as the initial five. Additional indices (NIFTY NEXT 50, sectoral
indices — see Part 3, which subsumes these) should be added later
under the *same* identifier scheme, not a new one — there is no reason
to special-case the initial five structurally.

For each index, the model needs exactly the same axes `HistoricalBar`
already has for stocks:

- **Identifier**: a stable `instrument_id` string in a clearly
  namespaced form, e.g. `INDEX:NSE:NIFTY50`, `INDEX:NSE:BANKNIFTY`,
  `INDEX:BSE:SENSEX`. Namespacing by a literal `INDEX:` prefix (rather
  than a separate table+FK) keeps every consumer that already knows
  how to query `HistoricalBar` by `instrument_id` working unchanged —
  it never needs to know "is this an index" to read a bar; it only
  needs to know that when it does need to know (Part 13, Part 4), the
  prefix or a companion lookup table answers it.
- **Exchange**: `NSE` or `BSE`, same `exchange` field already present.
- **Symbol representation**: the human-readable index name
  (`"NIFTY 50"`, `"NIFTY BANK"`, `"SENSEX"`) — distinct from
  `instrument_id`, exactly as stock `symbol` (`"RELIANCE"`) is
  distinct from a stock's `instrument_id` today.
- **Timeframe**: identical vocabulary to `HistoricalBar.timeframe`
  (`"1m"`, `"5m"`, `"15m"`, `"1h"`, `"EOD"`) — an index bar is a bar,
  not a different kind of object.
- **OHLCV**: an index has genuine open/high/low/close; "volume" is
  either absent or a constituent-aggregate depending on provider — the
  field stays present (schema consistency) but its *quality state*
  (Part 13) should be flagged `INCOMPLETE`/`MISSING` when a provider
  does not supply it, rather than defaulting to `0`, which would read
  as a real zero-volume observation.
- **Timestamp convention**: bar-close timestamp, IST, identical to the
  existing stock convention (`bar_timestamp` is already documented as
  a close-time identity component) — this must NOT diverge per asset
  class, or Part 5's alignment rule becomes asset-class-conditional.
- **Trading-session convention**: NSE/BSE equity session
  (09:15–15:30 IST) for all five listed indices — no separate session
  calendar needed initially since none of the five trade extended
  hours on the cash side relevant here.
- **Historical source**: none exists yet (no historical-candle adapter
  for indices any more than for stocks — same Gate-1 blocker as
  65.15-R's Part 12/14 established for stock data).
- **Live source**: none exists yet; would ride the same future
  Dhan-quote-polling pipeline `LiveQuoteObservation`/
  `AggregatedBarObservation` already use for stocks, once an index
  instrument identity exists to poll.
- **Data provenance**: reuse `domain.market_data.provenance` verbatim
  (`PROVENANCE_REAL_DHAN` / `PROVENANCE_SYNTHETIC_TEST` /
  `PROVENANCE_UNKNOWN`) — an index bar is exactly as provenance-prone
  as a stock bar, and inventing a parallel vocabulary would recreate
  the ambiguity 65.12 fixed for stocks.
- **Corporate-action considerations**: index *composition* changes
  (constituent additions/removals, weight rebalances) do not restate
  historical index *levels* the way a stock split restates historical
  *prices* — index providers publish a continuous adjusted series.
  The foundation therefore does not need a stock-style split/bonus
  adjustment mechanism for index bars themselves; it only needs to
  record *when* a rebalance happened as metadata (Part 10), since a
  sector-deviation or correlation calculation spanning a rebalance
  date should be able to flag that its inputs changed underlying
  composition mid-window.
- **Missing-data behavior**: see Part 13 — never interpolated or
  carried-forward silently; a missing index bar for a given timestamp
  must surface as `MISSING`, not be papered over with the last known
  value, because a stock bar at that same timestamp would then be
  compared against stale index data without anyone knowing.

**Final Output C — Can `HistoricalBar` safely represent index/sector
data?** Yes, cleanly, with **zero schema change**. `HistoricalBar`'s
actual columns (`instrument_id`, `exchange`, `symbol`, `timeframe`,
`bar_timestamp`, OHLCV, `source`, `provenance`) describe "a bar for
some tradeable/quotable series," and nothing in the model or its
`UniqueConstraint`/indexes assumes the series is an individual stock.
The only thing that would make this unsafe is *conflating* an index's
`instrument_id` with a stock's — which the `INDEX:`-prefixed
identifier scheme above prevents by construction, at the identifier
layer, not the schema layer. The smallest required architectural
change is therefore **not** a `HistoricalBar` migration; it is a new,
separate, small lookup construct (Part 4) that answers "is this
`instrument_id` an index, a sector index, or a stock, and if a stock,
which sector did it belong to as of date X" — metadata the bar table
was never meant to carry and should not be made to carry (a bar row
must stay one immutable OHLCV observation, not also a classification
record subject to later correction).

---

## Part 3 — Sector Data Foundation

**Minimum sector universe**: driven by the F&O stock universe already
implied by `UniverseVersion`/`ActiveUniverse` (existing models) —
standard NSE sectoral indices covering it: NIFTY BANK, NIFTY IT, NIFTY
AUTO, NIFTY PHARMA, NIFTY FMCG, NIFTY METAL, NIFTY REALTY, NIFTY
ENERGY, NIFTY FIN SERVICE, NIFTY MEDIA — ten sector indices is a
defensible minimum that covers the large majority of F&O names without
requiring every NSE sectoral index NSE publishes. (NIFTY BANK doubles
as both a tradeable index, per Part 2, and a sector index here — one
row, two roles, no duplication needed.)

Per sector, the design needs:
- **Sector identifier**: same `INDEX:` namespace as Part 2
  (`INDEX:NSE:NIFTYIT`, etc.) — a sector index *is* an index; it does
  not need a separate table.
- **Sector name**: human-readable (`"IT"`, `"Banking"`), independent
  of the index's own display name, since "the IT sector" and "the
  NIFTY IT index" are conceptually distinct even though the latter is
  used as the former's proxy.
- **Exchange/index source**: NSE for all listed above.
- **Constituent mapping**: see Part 4.
- **Historical/live index data**: identical mechanism to Part 2 —
  sector indices are ordinary index bars in `HistoricalBar`.
- **Timestamp alignment**: identical rule, Part 5 — no sector-specific
  variant.
- **Constituent changes / historical mapping / versioning**: this is
  the one genuinely new piece of state sectors need beyond Part 2's
  index design, addressed fully in Part 4 — a stock's *current*
  sector must never be applied retroactively to a historical date
  where its actual sector membership differed.
- **Missing data**: same Part 13 vocabulary, no special case.

---

## Part 4 — Stock→Sector Mapping (Canonical Design)

**Minimum viable model**: a small, explicitly time-versioned mapping
table — conceptually:

```
StockSectorMembership:
    stock_instrument_id     (matches HistoricalBar.instrument_id)
    sector_instrument_id    (matches the INDEX: identifier, Part 3)
    effective_from          (date, inclusive)
    effective_to            (date, inclusive, nullable = "still current")
    source                  (e.g. "NSE_SECTOR_CLASSIFICATION_MANUAL_2026")
```

One row per (stock, sector, time range) — never a bare
`stock → current sector` dictionary. Looking up "what sector was
RELIANCE in on 2024-03-15" is `effective_from <= date <=
(effective_to OR infinity)`, which is the whole point: **a stock's
current sector classification must never be silently back-applied**.
Symbol changes, mergers, delistings and reclassification are all the
*same* operation on this model — close out the old row's
`effective_to` and open a new row — no separate mechanism needed for
each corporate-action type.

**Minimum viable for first implementation**: a single manually curated
snapshot (`effective_from` = platform inception date, `effective_to` =
NULL) covering the current F&O universe's current sector membership,
with the time-versioning *columns* present from day one even though
only one version per stock exists initially. Building the columns now
and back-filling history only when/if a reclassification is actually
discovered is the right amount of engineering — building a full
historical reclassification dataset up front, with no consumer yet and
no real correlation/deviation feature to validate it against, would be
over-engineering exactly what the directive warns against.

---

## Part 5 — Timestamp Alignment (No-Look-Ahead Rule)

This is the load-bearing rule for every downstream feature (Parts
6–8).

**Rule**: for a feature calculation attributed to stock bar closing at
timestamp `T` on timeframe `TF`, the index/sector bar used as its
co-input must be the bar on the **same timeframe `TF`, whose
`bar_timestamp` is `<= T`, and closest to `T` without exceeding it**.
Never a bar with `bar_timestamp > T` (that is look-ahead by
definition), and never a same-timestamp bar from a *different*
timeframe silently substituted (a 5m stock bar must not be aligned
against a 1m or EOD index bar without an explicit, named resampling
step — resampling is a future feature-engine concern, not something
the alignment layer does implicitly).

Concretely:
- **Timezone**: IST throughout, matching `HistoricalBar.bar_timestamp`
  today — no UTC/IST ambiguity is introduced.
- **Market session boundaries**: only bars within 09:15–15:30 IST are
  eligible; a request for alignment against a timestamp outside that
  window (e.g. a signal evaluated exactly at open before any bar has
  closed) yields `WARMING_UP` (Part 13), not the previous day's final
  bar treated as "current."
- **Missing candles**: if no index/sector bar exists at or before `T`
  within a bounded look-back window (e.g. the last N expected bars for
  that timeframe), the result is `MISSING`, not "use the nearest
  available bar regardless of age."
- **Delayed feeds / unequal timestamps**: because alignment always
  looks *backward* from `T` and never forward, a delayed index feed
  simply produces an older `bar_timestamp` than the stock bar's `T` —
  this is exactly what the **staleness threshold** (Part 13's `STALE`
  state) exists to catch: if the gap between the stock bar's `T` and
  the aligned index bar's `bar_timestamp` exceeds a configured
  tolerance (e.g. 2× the timeframe's bar width), the observation is
  `STALE`, not silently accepted as current.
- **Partial candles**: an in-progress (not-yet-closed) bar is never a
  valid alignment target, live or backtest — only bars with a
  completed `bar_timestamp` in the past relative to the evaluation
  clock are eligible, mirroring how the canonical backtest engine
  already must treat `HistoricalBar` rows (it cannot see a bar whose
  close time is after the simulated "now").

**Why this prevents look-ahead structurally, not just by convention**:
because the alignment function's only allowed input is "the largest
`bar_timestamp <= T` for this identifier/timeframe," the exact same
function is correct in both live and backtest contexts (Part 12) —
live, "now" is wall-clock time; backtest, "now" is the simulated replay
cursor. Neither caller can accidentally pass a future bar in, because
the underlying query itself is bounded by `<= T` and by an
externally-supplied `T`, not by "whatever the table currently
contains."

---

## Part 6 — Index↔Stock Correlation Contract (Design Only)

**Pearson vs Spearman**: Pearson measures linear co-movement of
*returns* and is the industry-standard choice for index/stock beta-
style relationships when returns are approximately well-behaved over
the sampled window; it is sensitive to outliers (a single large
gap-day return can dominate a short window). Spearman measures
monotonic rank co-movement and is more robust to those outliers/fat
tails but discards magnitude information a trader cares about
("moves twice as much" vs. "moves in the same direction"). Recommendation:
**Pearson on returns as the primary/initial contract**, since the
consuming use case (correlation as a risk/context modifier) cares
about magnitude of co-movement, not just direction; Spearman is worth
keeping available as an alternate output once real data exists to
compare the two empirically (per 65.15-R's Gate 1 — no such comparison
can happen on synthetic data).

Contract:
- **Return calculation**: simple period-over-period `%` return per
  bar, `(close[t] - close[t-1]) / close[t-1]`, on the *aligned* bar
  pair from Part 5 — never price levels directly (levels are
  non-stationary; correlating levels instead of returns is a
  well-known statistical error this design explicitly avoids).
- **Rolling window**: parameterized (e.g. 20/60/120 bars), following
  the same trailing-integer-segment naming convention `ma_divergence`
  established (`index_correlation_sma`-style period suffixes, not a
  new parsing mechanism).
- **Minimum observations**: a floor (e.g. 20) below which the output
  is `WARMING_UP`, not a computed-but-unreliable low-N number.
- **Timeframe**: whichever timeframe the calling feature/context needs
  (EOD for daily context, intraday timeframe for a scanner-time
  filter) — the contract itself is timeframe-agnostic, per Part 5's
  timeframe-consistent alignment rule.
- **Warm-up period**: `window` bars of aligned, non-`MISSING`,
  non-`STALE` history required before first output.
- **Missing/stale-data behavior**: any aligned pair in the window that
  is `MISSING` or `STALE` (Part 13) drops that pair from N rather than
  substituting a value — reported N shrinks, never gets a fabricated
  fill.
- **Output range**: `[-1, +1]` (Pearson) as a `Decimal`, following the
  same bare-fraction (not ×100) convention `price_vs_ma_pct`/
  `ma_divergence` use.
- **Confidence/sample-size reporting**: N (actual observations used
  this window) must be emitted alongside the coefficient — a
  correlation value alone, without N, is exactly the kind of
  unqualified figure 65.15-R's Part 4 already flagged as
  misleading.
- **Correlation vs beta vs relative strength — kept distinct**:
  correlation (this contract) measures co-movement *direction/strength*
  only; beta (slope of stock-return-vs-index-return regression) adds
  *magnitude of sensitivity* and is a separate future contract; relative
  strength (stock return minus index return, or their ratio) is a
  separate, simpler *spread* measure with no statistical window
  requirement at all. None of the three should be computed by, or
  aliased to, the same function — conflating them was an explicit
  anti-pattern flagged in 65.15-R.

---

## Part 7 — Sector Deviation Contract (Design Only)

Candidates compared:
- **Raw return spread** (`stock_return - sector_return`): simplest,
  but not scale-normalized — a 2% spread means something different for
  a low-vol vs high-vol stock.
- **Normalized spread** (`spread / stock's own ATR or realized vol`):
  scale-aware, still simple.
- **Z-score** (`(spread - rolling_mean(spread)) / rolling_std(spread)`):
  expresses "how unusual is today's deviation relative to this stock's
  own recent deviation history" — directly comparable across stocks.
- **Beta-adjusted residual** (`stock_return - beta * sector_return`):
  the most statistically correct ("this stock moved more/less than its
  historical sensitivity to the sector would predict"), but depends on
  a stable beta estimate — another moving part, another warm-up
  requirement, another failure mode if beta itself is unstable.
- **Relative strength**: same caveat as Part 6 — a distinct, simpler
  concept, not a Sector Deviation candidate itself.

**Recommended initial candidate: Z-score of the raw return spread.**
It is the smallest formula that is still scale-aware and cross-stock
comparable, needs no beta-estimation warm-up on top of the deviation
window itself, and — critically per 65.15-R Part 12's Gate-1 floor —
is simple enough to validate against real REAL_DHAN data as soon as it
exists, rather than requiring a second empirical validation step (beta
stability) before the first one (does the spread concept hold at all)
is even confirmed.

- **Lookback/timeframe/warm-up**: same structure as Part 6 (rolling
  window with a minimum-observations floor before output).
- **Timestamp**: Part 5's alignment rule, unchanged.
- **Minimum observations**: floor for the rolling mean/std, e.g. 20.
- **Missing-data behavior**: identical to Part 6 — drop, never
  substitute.
- **Sector-mapping dependency**: this feature is the first hard
  consumer of Part 4's mapping — its output is only as trustworthy as
  the mapping's `effective_from`/`effective_to` coverage on the
  evaluation date; a stock with no mapping row covering that date must
  produce `MISSING`, never silently fall back to "no sector."
- **Backtest behavior**: identical calculation contract at backtest
  time and live time (Part 12) — the mapping lookup and the alignment
  lookup both take an explicit `T`, so a backtest at simulated date D
  and a live evaluation at real date D would produce the same output
  given the same underlying data.

---

## Part 8 — Sector-Wise DMA (Design Only)

Three related values considered: sector DMA itself (e.g. 50-day/200-day
moving average of the *sector index*), distance from sector DMA
(`(sector_close - sector_dma) / sector_dma` — literally
`price_vs_ma_pct` applied to a sector-index instrument rather than a
stock instrument, reusing the existing feature unchanged once a
sector's `instrument_id` exists), and sector DMA slope (`sector_dma[t]
- sector_dma[t-n]`, a rate-of-change).

**Which should actually become features**: only **distance from sector
DMA** is a new feature identity worth adding
(`sector_price_vs_dma_pct`-shaped) — because the raw "sector DMA"
value by itself is not directly comparable across sectors (an absolute
index-point average) and the *slope* is redundant with 65.15-R's
existing redundancy rule (Part 11 of the roadmap already flags
MA-distance-as-4th-rebound-condition-style redundancy; a DMA slope
here would duplicate what `ma_divergence` already expresses generically
for any instrument, sector index included, once one exists). Avoid
minting three fields when one (distance-from-DMA) captures the
decision-relevant signal and the existing `ma_divergence` feature
already covers slope-like divergence generically for any instrument.

---

## Part 9 — Fire Sale Proxy Dependency

Per 65.15-R Part 7, Fire Sale Proxy is a **dislocation proxy**, never a
claim of confirmed forced liquidation — that rule is unchanged and
reaffirmed here. Potential inputs and their current state:

| Input | Already available? |
|---|---|
| Abnormal price movement | YES — derivable from existing `HistoricalBar` stock data alone (e.g. return z-score). |
| Abnormal volume | YES — existing `HistoricalBar.volume`, same instrument. |
| Volatility | YES — ATR-style, existing feature-engine primitives. |
| Index dislocation | NO — requires this checkpoint's index foundation (Part 2). |
| Sector dislocation | NO — requires this checkpoint's Sector Deviation contract (Part 7), which itself requires Part 3/4. |

So Fire Sale Proxy's *stock-only* inputs are implementable today
without this foundation; its *contextual* inputs (is the whole
sector/index also dislocated, which would suggest market-wide stress
rather than single-stock news) are exactly the two inputs this
foundation unlocks. This confirms 65.15-R's sequencing: Fire Sale
Proxy can ship an initial stock-only version before the index/sector
foundation exists, and can be *strengthened* (not redesigned) once
Parts 2–7 are real — a clean incremental dependency, not a hard block.
No implementation of any of this happens in this checkpoint.

---

## Part 10 — Data Provenance

Every future market-intelligence *observation* (a correlation value, a
sector-deviation value, a DMA-distance value) is a **derived value**,
distinct from the raw `HistoricalBar` rows it was computed from. It
needs its own provenance envelope, traceable to:

- **Source**: which calculation module/version produced it (mirrors
  `SignalEvidenceRecord`'s existing pattern of recording
  `strategy_id`/`schema_version`).
- **Symbol/index**: the stock `instrument_id` and the
  index/sector `instrument_id` both.
- **Timestamp**: the stock bar's `T` the observation is attributed to.
- **Timeframe**: unchanged from the calculation's own timeframe.
- **Calculation version**: an explicit version string on the formula
  (Part 7 already shows there are multiple candidate formulas — a
  version tag prevents silently comparing Z-score-era output against a
  later beta-residual-era output as if they were the same thing).
- **Source data timestamp**: the *aligned* index/sector
  `bar_timestamp` actually used (Part 5) — may lag `T` and that lag is
  itself provenance-relevant (feeds Part 13's `STALE` determination).
- **Data completeness state**: the Part 13 quality state the
  observation was computed under.

**Interaction with existing architecture**: this envelope is
*metadata about a derived value*, structurally the same shape
`HistoricalBar.provenance` already is metadata about a raw bar — reuse
that precedent (a parallel small set of explicit fields) rather than
inventing a JSON blob. Where a derived observation is surfaced as
signal evidence, it fits `SignalEvidenceRecord.fields`'s existing
`[label, value]` shape unchanged; provenance fields would appear as
additional labeled pairs, not a schema change to that model. No model
is modified in this checkpoint — this is the design such a future
model/field addition should follow.

---

## Part 11 — Backtest Compatibility

The canonical backtest engine already reads `HistoricalBar` exclusively
and evaluates a simulated "now" moving forward through
`bar_timestamp` order. Because Part 5's alignment function takes an
explicit `T` as input and only ever looks at `bar_timestamp <= T`, the
backtest engine can call the exact same alignment/feature functions
live code calls, passing its simulated `T` — no backtest-specific
calculation branch is needed. Explicitly:
- **Warm-up period**: identical to live (Parts 6–8) — a backtest must
  not compute a feature before its warm-up window of *history prior
  to the backtest's own start date* is satisfied; a backtest starting
  on day 1 of available data cannot silently treat the first bar as
  already-warmed.
- **Historical/timestamp availability**: bounded by whatever
  `HistoricalBar` rows actually exist for the index/sector identifiers
  — if index history does not go back as far as stock history, the
  feature is `WARMING_UP`/`MISSING` for the uncovered range, not
  computed on a shorter, silently-mismatched window.
- **No future information**: guaranteed structurally by Part 5, not by
  discipline alone.
- **Corporate-action handling**: Part 2 already establishes index
  levels don't need split-style restatement; a stock corporate action
  during a backtest window is already handled (or not) by whatever the
  existing backtest engine does for stock `HistoricalBar` rows today —
  this foundation does not change that behavior.
- **Missing index/sector data**: `MISSING` state (Part 13) propagates
  into the feature output for that bar; the backtest engine's existing
  handling of an absent/None feature value (however it already handles
  a feature that cannot be computed) applies unchanged — no new
  backtest-engine branch is designed or implied.
- **Feature calculation at signal time**: identical function call,
  identical inputs-shape, as live (Part 12) — this is the one-
  calculation-contract requirement made concrete.

No change to `BacktestService`/backtest execution semantics is
designed or proposed here.

---

## Part 12 — Live Scanner Compatibility

Same principle stated from the live side: the live scanner, Market
Context, strategy filters, `SignalEvidenceRecord` and any future
correlation-analytics surface should all call **one** canonical
alignment function (Part 5) and **one** canonical calculation function
per feature (Parts 6–8), parameterized only by `T` (wall-clock "now"
live, simulated cursor in backtest) and by which `instrument_id`s to
compare. This is exactly the shape `field_registry.py`'s existing
dispatch (`compute_feature_series()`) already uses for
`ma_divergence`/`price_vs_ma_pct` today — the index/sector features
are designed to be additional entries in that same registry, not a
parallel mechanism, so "one calculation for live, another for
backtest" cannot arise by construction rather than by convention.
Nothing is implemented here.

---

## Part 13 — Data Quality States

Six explicit, mutually exclusive states, applied per observation (a
single aligned index/sector bar, or a single computed feature value):

| State | Meaning | Consumer behavior |
|---|---|---|
| `VALID` | Aligned bar found within tolerance; enough warmed-up history exists. | Calculated value emitted normally. |
| `WARMING_UP` | Not enough historical observations yet (below the minimum-observations floor, Parts 6–8) — a normal, expected early-window state, not an error. | No output value; feature reports `WARMING_UP`, not zero/None-as-zero. |
| `MISSING` | No aligned bar exists at all within the bounded lookback (Part 5). | No output value; if the feature is a hard filter input, suppress the signal rather than passing a fabricated neutral value. |
| `STALE` | An aligned bar exists but its `bar_timestamp` lags `T` beyond the configured tolerance (Part 5). | Value may still be calculated but must be flagged `STALE` in provenance (Part 10); a strategy consuming it should treat it as lower-confidence, never as equivalent to `VALID`. |
| `INCOMPLETE` | The bar/series exists but a required field is absent (e.g. index volume, Part 2) or a sector-mapping row does not cover the evaluation date (Part 4/7). | Value may be partially calculable; must be labeled `INCOMPLETE`, never silently treated as `VALID`. |
| `INVALID` | The underlying data fails a sanity check (e.g. negative price, OHLC ordering violated) — mirrors validation classes the existing archive/backtest pipeline already applies to stock bars. | No output value; warning surfaced, never passed downstream as a number. |

**Hard rule, restated from the directive and enforced by this table**:
missing data is never silently substituted with a prior value, a
default, or an interpolation — every non-`VALID` state is either "no
output" or an explicitly labeled, lower-trust output. This is a direct
extension of `domain.market_data.provenance`'s own existing philosophy
("no migration or provider... is allowed to assign [a label] without
positive evidence") to the derived-observation layer.

---

## Part 14 — Implementation Boundary (Recommended Sequence)

Six layers, deliberately not touched together by the first real
implementation checkpoint:

1. **Data foundation** — index/sector identity minting into
   `HistoricalBar`'s `instrument_id` namespace, the
   `StockSectorMembership` model (Part 4), the alignment function
   (Part 5), the quality-state vocabulary (Part 13) as a shared
   library. No feature yet.
2. **Feature calculation** — `index_correlation_*` /
   `sector_deviation_*` / `sector_price_vs_dma_pct` added to the
   feature registry, consuming layer 1's alignment function, following
   `ma_divergence`'s exact registration precedent.
3. **Market Context integration** — Market Context begins reading the
   new feature-registry entries.
4. **Strategy consumption** — a strategy filter begins reading the new
   Market Context signal.
5. **Backtest integration** — the canonical backtest engine's existing
   feature-computation path is exercised against the new features
   (Part 11) — no new engine code, but this is the point where
   correctness is actually proven against history.
6. **Reporting** — correlation-repository-style read models or
   dashboards surface the new observations.

**Recommended smallest safe sequence**: 1 → 2 → 5 (prove correctness
against real REAL_DHAN history in the backtest engine, since that is
the cheapest place to validate a formula against ground truth) → 3 → 4
→ 6. Layers 3/4 (live/production consumption) should not be attempted
before layer 5 has validated the formula on real data, consistent with
65.15-R's Gate 1/Gate 4 ordering. No implementation of any layer
happens in this checkpoint.

---

## Part 15 — Real-Data Dependency

Reconfirmed chain: REAL_DHAN capture → archive validation
(`MarketDataArchiveDay`) → `HistoricalBar` validation (provenance-
labeled) → backtest validation (canonical engine against REAL_DHAN
rows) → **index/sector foundation** (this document) → feature
calculation (Parts 6–8) → correlation analysis → Gainz contextual
experiment (65.15-R Part 5).

**Can be designed today** (and is, in this document): the entire data
model, alignment rule, quality-state vocabulary, provenance envelope,
and calculation *contracts* (formulas, parameters, warm-up rules) —
none of this requires a single real data point to specify correctly.

**Must wait for REAL_DHAN data**: any *empirical* decision — is
Pearson actually better than Spearman for this platform's real index
behavior, is Z-score-of-spread actually predictive, is the 20-bar
minimum-observations floor actually enough — none of that can be
validated on synthetic data (65.15-R's Gate 1 floor applies identically
here) and none of it is claimed as validated by this document.

---

## Part 16 — Checkpoint 65.14 Status

**65.14 (real NSE session capture) remains DEFERRED.** Reason: NSE
closed — 2026-08-30 is a Sunday (verified via system clock this
session, IST ≈ 14:23, well outside any trading session even on a
weekday). Not marked completed. The next real trading session should
begin with the live-capture checkpoint before any of the designs in
this document are implemented.

---

## Part 17 — Documentation

This document (`docs/research/MARKET_INTELLIGENCE_DATA_FOUNDATION.md`)
is the artifact this Part requires. `D:\IntraDay\taskReport.md` is
overwritten (not appended) with the full 65.16-R report per the
checkpoint's own instruction.

---

## Dependency Graph (textual)

```
REAL_DHAN capture (65.14, DEFERRED)
   -> Archive validation (MarketDataArchiveDay)
      -> HistoricalBar (provenance-labeled)
         -> Index/Sector identity minted into instrument_id (Part 2/3)
         -> StockSectorMembership mapping (Part 4)
            -> Alignment function (Part 5)
               -> Correlation contract (Part 6)
               -> Sector Deviation contract (Part 7)
               -> Sector DMA distance (Part 8)
                  -> Fire Sale Proxy (contextual strengthening, Part 9)
               -> Backtest validation (Part 11)
                  -> Market Context integration (Part 12/14)
                     -> Strategy consumption
                        -> Reporting / correlation analytics
```

## Risks

- **Identifier collision risk**: if the `INDEX:` prefix convention is
  not enforced consistently, an index `instrument_id` could collide
  with or be mistaken for a stock's — mitigated by making the prefix
  the single source of truth for classification rather than relying on
  a separate lookup that could drift out of sync.
- **Sector mapping drift**: a real reclassification event that is not
  recorded promptly would silently degrade Sector Deviation output
  quality (stocks mapped to a stale sector) without tripping any
  `INVALID`/`MISSING` state, since the row would still technically
  cover the date — this is a process risk, not something the schema
  alone prevents.
- **Formula premature commitment**: locking in Z-score-of-spread or
  Pearson before any real data exists to test them risks having to
  redo Gate 3/4 validation work if the empirical answer differs —
  mitigated by treating every formula choice in this document as a
  *recommended starting candidate*, not a final decision (consistent
  with 65.15-R's own framing).
- **Volume ambiguity for indices**: if a future provider silently
  supplies a fabricated/zero index volume rather than omitting the
  field, the `INCOMPLETE` state (Part 13) would not trigger unless
  providers are contractually/structurally required to signal absence
  explicitly — a genuine open question (see below).

## Open Questions

1. Should sector membership (Part 4) eventually be sourced from an
   authoritative NSE feed rather than manual curation, and if so, on
   what cadence?
2. Should the index identifier namespace (`INDEX:EXCHANGE:NAME`) be
   formalized as an actual enum/constant module before layer 1
   implementation, to prevent ad-hoc string drift the way
   `domain.market_data.provenance` formalized provenance constants?
3. What staleness tolerance (Part 5) is appropriate per timeframe —
   this document proposes "2× bar width" as a starting default but it
   is not empirically validated.
4. Should Beta (explicitly separated from Correlation in Part 6) be
   scoped as a near-term follow-on contract once Correlation itself is
   validated, or deferred indefinitely absent a concrete consumer?
5. How should a provider that supplies zero index volume as `0`
   (rather than omitting it) be distinguished from a genuine
   zero-volume observation — a provider-contract question, not
   resolvable from this codebase alone.

## Recommended Implementation Sequence

See Part 14. Restated as a single line: **foundation → feature →
backtest-validate → Market-Context/live → reporting**, never
implementing more than one layer's worth of new surface in a single
future checkpoint, and never attempting live/production consumption
(layers 3–4) before backtest validation against REAL_DHAN data
(layer 5) has run.
