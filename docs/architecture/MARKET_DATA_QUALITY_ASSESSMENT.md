# Market Data Quality Assessment

Produced during Checkpoint 24A finalization, before any decision to
begin Checkpoint 24 (Live Signal Observation). Answers one question
directly: **is the current Quote→Bar pipeline (Checkpoints 23-24A)
good enough to build trading signals on?**

## The sampling mechanism, precisely

Every bar this platform currently produces is built from **explicit-
trigger REST point samples**, not continuous tick data:

- Each "Refresh" action performs exactly one `POST /v2/marketfeed/quote`
  call, returning one `last_price` snapshot per instrument at that
  instant.
- There is **no guaranteed minimum sampling frequency**. The interval
  between two samples is however long elapses between two Refresh
  actions — seconds if an operator clicks repeatedly (bounded below by
  Dhan's own 1 request/second rate limit and this platform's 5-second
  debounce), or minutes/hours if nobody does.
- A 1-minute bar is built from whatever samples happened to land in
  that 60-second window — zero, one, or several.

This is a deliberate, correct design for Level 1 observation
(Checkpoint 23's own stated goal) and was never claimed to be more than
that. This document exists to make the consequence of that design
explicit before it is asked to bear more weight.

## Quantitative answer, per OHLCV field

**OPEN — cannot be guaranteed.** `AggregatedBar.open` is the price of
whatever sample happened to be first in the interval, not necessarily
the true first traded price. If the first sample lands 40 seconds into
the minute, the first 40 seconds of real price action are invisible to
this bar.

**HIGH — cannot be guaranteed; is a lower bound only.** The true
intra-minute high can only ever be *at least* the observed high. A
price spike between two samples is invisible — `AggregatedBar.high` can
under-report the real high, never over-report it.

**LOW — cannot be guaranteed; is an upper bound only.** Symmetric to
HIGH: the true intra-minute low can only ever be *at most* the observed
low. `AggregatedBar.low` can under-report a real dip, never fabricate
one that didn't happen.

**CLOSE — approximated, not authoritative.** `AggregatedBar.close` is
the price of the last sample in the interval, which may be seconds
before the interval's true boundary. Better-anchored than OPEN/HIGH/LOW
(it is at least a real, recent observed price), but still not
guaranteed to equal the exchange's own official close tick for that
minute.

**VOLUME — not computed, by design (unchanged from Checkpoint 24A's
own documented limitation).** Dhan's Market Quote response includes a
day-cumulative `volume` figure (and a same-day `ohlc` block) - this
platform's client parses the `ohlc` block but **never uses it**
in aggregation (verified by direct inspection of
`infrastructure/market_data_providers/dhan/client.py` - only
`last_price` feeds `aggregate_quotes_into_bars()`). Deriving a
per-bar volume delta from the cumulative figure was correctly assessed
as unsafe at Checkpoint 24A and remains so. `AggregatedBar`/`Bar.volume`
is always `Decimal("0")`, rendered in the UI as an explicit "—" - never
fabricated.

## Classification: SAMPLE_BAR

Of the four candidate classifications:

| Classification | Verdict | Why |
|---|---|---|
| `TRADING_GRADE_BAR` | **Rejected** | Would claim the OHLC values are reliable enough to feed a strategy's entry/exit logic. The analysis above shows HIGH/LOW are structurally one-sided (can only under-report), OPEN/CLOSE are approximate - a strategy computing ATR or a breakout level on this data could be silently wrong in a way that costs money. |
| `CANONICAL_MARKET_BAR` | **Rejected** | Would claim this is the authoritative, exchange-grade OHLC record for the interval - it manifestly is not; it is derived from whatever an operator happened to sample. |
| `OBSERVATION_BAR` | Too weak | Undersells what actually exists - this is a real, structurally-validated, non-fabricated aggregation with genuine (if bounded) OHLC semantics, gap detection, and FORMING/CLOSED discipline - not a bare price ticker. |
| **`SAMPLE_BAR`** | **Selected** | Accurately names what this is: a real, honest, statistically-bounded aggregation built from discrete point samples rather than continuous/tick data. Every value it reports is genuinely observed (never fabricated), but its fidelity is fundamentally bounded by sampling gaps that are architecturally intrinsic to the current data source, not a bug to be fixed within the current design. |

**These bars are suitable for:** Level 1 live market-data observation,
architecture/pipeline validation, UI/UX testing, diagnostics, and
proving the Quote→Bar→API→frontend path works end-to-end (which
Checkpoint 24A's own test suite does thoroughly).

**These bars are NOT yet suitable for:** live signal generation,
strategy backtesting parity claims, or any decision informing real or
simulated trading. Checkpoint 24A's own decision to keep
`SignalGenerationService` unwired was therefore not merely cautious
scope discipline - the data itself does not yet support that use
honestly.

## What would be required for trading-grade bars (OPEN decision - not implemented)

Two documented Dhan capabilities were identified as the plausible paths
to trading-grade fidelity - **neither has been verified against
Dhan's official documentation in this checkpoint, and neither is
implemented here**:

1. **Dhan's WebSocket live market feed** - a persistent, continuously-
   pushed tick stream would eliminate the sampling-gap problem
   entirely (every trade/quote update is seen, not just whichever
   instant an operator happened to poll). This is the path Checkpoint
   23's own architecture doc already named as deferred, for the
   documented reason that this application has no persistent process
   to host a long-lived WebSocket client yet (no Celery worker, an
   unused ASGI stub).
2. **A Dhan historical/intraday-OHLC REST endpoint**, if one exists
   with exchange-computed (not client-aggregated) minute candles -
   would provide authoritative OHLC directly, sidestepping
   client-side aggregation fidelity entirely. Referenced in general
   terms in prior research but **not verified**: the exact endpoint
   path, request shape, and whether it provides true intraday (not
   just prior-day) data were not confirmed against Dhan's official
   documentation during this checkpoint.

**Update (Checkpoint 25.1):** this decision is no longer fully open.
Both capabilities (1) and (2) were confirmed to exist against Dhan's
own official documentation, and a **hybrid** of the two was identified
as the correct target architecture - see
[DHAN_MARKET_DATA_CAPABILITY_RESEARCH.md](DHAN_MARKET_DATA_CAPABILITY_RESEARCH.md)
for the full evidence. Three specific facts about Dhan's actual
behavior (same-day intraday candle availability, candle authority,
timestamp timezone) remain unconfirmed by documentation alone and
require direct API verification before implementation - that research
document's own six-condition promotion checklist is now the
authoritative gate for this decision, superseding the general
"marked OPEN" language originally written here.

## Conclusion feeding the CP24A acceptance classification

The architecture built in Checkpoints 23-24A (adapter, aggregation,
persistence, API, frontend) is sound and does exactly what it claims
to do, with comprehensive test coverage proving it. The open question
is entirely about the **data source's fidelity for a purpose it was
never claimed to serve yet (signal generation)** - not about a defect
in what was built. This is why Checkpoint 24A is classified **AMBER**
(observation-quality foundation, trading-grade data explicitly still
open) rather than GREEN or RED - see `taskReport.md`'s Checkpoint 24A
finalization section for the full acceptance reasoning.

## Checkpoint 31 update

`docs/research/TRADING_GRADE_BAR_VALIDATION.md` closed two of
Checkpoint 25.1's three unconfirmed facts with a real, live, read-only
API call: same-day intraday availability (VERIFIED) and timestamp/
timezone convention (VERIFIED, genuine UTC epoch). Candle authority
remains unconfirmed beyond one data point of independent corroboration
against Google Finance. `AGGREGATED_BAR`'s new `BarQualityGrade`/
`BarProvenance` types (`domain/market_data/aggregation.py`) now make
`SAMPLE_BAR` an explicit, typed, structurally-proven property of every
bar this pipeline produces, not merely a documentation claim. Still
**AMBER** - `TRADING_GRADE_BAR` remains unreachable (4 of 6 conditions
still unmet, primarily the unchanged persistent-process/WebSocket
infrastructure gap).
