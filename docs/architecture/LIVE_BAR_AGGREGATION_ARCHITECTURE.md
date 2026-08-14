# Live Bar Aggregation Foundation

Checkpoint 24A. Bridges Checkpoint 23's live `Quote` observations to the
canonical `Bar` shape the existing feature/signal architecture already
expects — read-only, deliberately unwired from
`SignalGenerationService`. Exists specifically to avoid the invalid
architectural shortcut of connecting live `Quote`s directly to a
pipeline that requires `Bar`s.

```
Dhan Quote → Quote normalization → Bar aggregation → Canonical Bar
    → Persistence → Read-only API → Frontend
```

## Scope boundary

What this checkpoint IS: a pure, deterministic Quote→Bar aggregation
function, an application-layer orchestration service, upsert
persistence, a read-only API, and a "Recent Bars" table on the
existing Live Market Data Monitor.

What this checkpoint is NOT: `SignalGenerationService`,
`FeatureEngineService`, and every `trading_engine/*` module remain
completely untouched — mechanically proven by a dedicated architecture
test (`test_bar_aggregation_boundaries.py`), not just documented.

## Why a pure, stateless, replay-safe design

Checkpoint 23's `LiveQuoteObservation` table is already append-only and
already the single source of truth for every observed quote. Rather
than building a second, independently-mutable, stateful bar
accumulator (which would need its own revision/locking logic to stay
consistent with the observation log), `aggregate_quotes_into_bars()` is
a **pure function** recomputed from scratch on every call, over the
full recent observation history. This has one deliberate, explicitly
documented consequence: a late-arriving observation for a
already-CLOSED interval correctly **revises** that bar's OHLC the next
time aggregation runs, because the underlying data genuinely changed —
this is intended behavior, not a bug, and is proven by a dedicated test
(`test_delayed_quote_for_a_past_interval_revises_that_bars_ohlc`).

## The canonical Bar contract — reused, not duplicated

`domain/market_data/contracts.py`'s `Bar` (Checkpoint 5/14) is reused
verbatim and unmodified as the CLOSED-bar representation —
`AggregatedBar.to_bar()` converts a CLOSED `AggregatedBar` into a real
`Bar`, with `Bar.timestamp` (bar close time, per its own pre-existing
convention) set to `interval_end`. A **new** wrapper type,
`AggregatedBar`, was introduced specifically because a FORMING bar
cannot be validly represented by `Bar` — `Bar`'s own invariants assume
a genuinely completed interval, and a forming bar's "close" is
provisional by definition. Calling `to_bar()` on a FORMING bar raises
`IncompleteBarError` — the existing signal engine (once wired, in a
future checkpoint) can never receive an incomplete bar disguised as a
closed one.

## Aggregation rule (Checkpoint 24A §4)

Per instrument, per 1-minute interval (this checkpoint's canonical base
timeframe — no other base timeframe exists yet in this codebase):

```
OPEN  = price of the earliest-by-(source_timestamp, arrival order) observation
HIGH  = max observed price in the interval
LOW   = min observed price in the interval
CLOSE = price of the latest-by-(source_timestamp, arrival order) observation
VOLUME = not computed
```

Ties at the exact same `source_timestamp` are broken by arrival order
(the observation's position in the input sequence) — a deterministic,
tested rule, not undefined behavior.

## Volume — an explicit, documented limitation

Dhan's Market Quote response includes a `volume` field, but it is a
**cumulative day-volume figure**, not a per-tick trade size — safely
deriving a per-bar traded-volume delta from it would require either (a)
correctly handling session-start resets and any provider-side
corrections/backfills, or (b) capturing per-tick trade sizes directly
(which the Market Quote endpoint does not provide — only Dhan's tick-
by-tick feed would). Neither is attempted this checkpoint. Every
`Bar`/`AggregatedBar` produced here has `volume = Decimal("0")` (a
placeholder required only because `Bar` itself requires a non-negative
volume field) — never a fabricated or misleading number. The frontend
renders volume as an explicit "—", not a fake zero that could be
mistaken for "zero volume traded."

## Forming vs. Closed — never conflated

`BarStatus.FORMING` / `BarStatus.CLOSED` are distinct enum values on
`AggregatedBar`. At most one bar per instrument is FORMING (the
interval containing `as_of`); every earlier interval with at least one
observation is CLOSED. The API (`BarResponseSerializer.status`) and
frontend (a distinct badge — "◐ Forming" vs. "● Closed") both surface
this explicitly; no code path can silently drop the distinction.

## Gap detection — reported, never fabricated

Every interval within an instrument's own observed span (from its
earliest observation to the last fully-CLOSED interval before `as_of`)
that has **zero** observations is reported in `missing_intervals` — no
bar is ever fabricated for it. The currently-FORMING interval is never
reported as missing (it hasn't ended yet, so "missing" doesn't apply).

## Anomalous observations — excluded, never silently dropped

A `Quote` with `source_timestamp > as_of` (a provider clock-skew or
bad-data case) is excluded from aggregation and recorded in
`anomalous_observations` with a reason — never silently discarded
without a trace, matching `domain/market_data/quality.py`'s own
"reject explicitly" policy from Checkpoint 14.

## Persistence — upsert, not append-only (a deliberate departure from `LiveQuoteObservation`)

`AggregatedBarObservation` is keyed uniquely by `(instrument_symbol,
timeframe, interval_start)` and **upserted** (`update_or_create`) on
every aggregation run — unlike `LiveQuoteObservation`'s append-only
design. This is intentional: a bar is a derived, recomputable
projection of the observation log, not an independent observation
itself, so revising a stored bar (FORMING→CLOSED, or a late-data
revision) is correct, not corruption.

## API — read/write separation, matching Checkpoint 23's pattern exactly

`GET .../bars/` reads only already-persisted `AggregatedBarObservation`
rows — it never triggers aggregation or a broker call itself
(mechanically proven:
`test_reading_bars_never_calls_dhan`/`test_bars_endpoint...`). Bar
aggregation itself is chained into Checkpoint 23's existing
`POST .../refresh/` endpoint, immediately after a successful quote
save — this adds **zero** additional broker calls (aggregation only
reads already-persisted quotes), and keeps bars in sync with quotes
without introducing a second manual trigger. A bug in aggregation can
never mask a successful refresh result — the aggregation call is
wrapped in its own `try`/`except`, logged, and swallowed
(`test_bar_aggregation_failure_never_masks_a_successful_refresh_result`).

## Frontend

The existing Live Market Data Monitor (Checkpoint 23) gains a "Recent
Bars (1-Minute)" table — Symbol/Timeframe/Interval/Open/High/Low/
Close/Volume/Status/Source Timestamp — read-only, auto-refreshed
alongside the existing session/health/quotes on the same 5-second
client-side timer. No Buy/Sell/Entry/Stop Loss/Target/Execute/Position/
P&L control exists anywhere, verified by the same dedicated
"never renders any trading control" test extended to cover the new
section.

## Data-quality classification: SAMPLE_BAR, not TRADING_GRADE_BAR

A dedicated quantitative review
([MARKET_DATA_QUALITY_ASSESSMENT.md](MARKET_DATA_QUALITY_ASSESSMENT.md),
produced at Checkpoint 24A finalization) concluded these bars are
`SAMPLE_BAR` grade: real, honest, non-fabricated aggregations of
discrete point samples, but structurally unable to guarantee a true
OPEN/HIGH/LOW/CLOSE the way continuous tick data or exchange-computed
candles could. This is the primary reason
`SignalGenerationService`/`FeatureEngineService` remain unwired beyond
this checkpoint - not merely scope discipline, but because the data
itself does not yet honestly support that use. See that document for
the full field-by-field analysis and the open (unverified,
not-implemented) decision on whether Dhan's WebSocket feed or a
historical-OHLC endpoint is the right path to trading-grade fidelity.

## Deferred / explicitly out of scope

Wiring bars to `FeatureEngineService`/`SignalGenerationService`
(Checkpoint 24 - explicitly gated on the data-quality classification
above being resolved first), any other timeframe besides 1-minute,
real traded volume, WebSocket-driven incremental aggregation,
per-instrument retention/rotation policy for `AggregatedBarObservation`
(inherits Checkpoint 23's "revisit before scaling" limitation), a full
exchange holiday calendar (still deferred from Checkpoint 23).
