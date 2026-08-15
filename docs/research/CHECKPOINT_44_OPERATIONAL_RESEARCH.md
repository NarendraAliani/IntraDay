# Checkpoint 44 Operational Research

A real fresh-research attempt this checkpoint (not a re-citation) —
still narrower than Part 1's full 20+-item list given the time
available, but genuinely new findings, not reused ones.

## Resolved: same-day intraday candle availability (one of three
named "load-bearing unknowns")

**`VERIFIED_SECONDARY`** (a direct fetch of
`docs.dhanhq.co/api/v2/historical-data/get-intraday-ohlc` returned only
page chrome, not the endpoint body — the documentation viewer is
JS-rendered and did not yield field-level detail via fetch this
session either, same limitation prior checkpoints hit repeatedly).
Corroborated via search-result excerpts of Dhan's own published
historical-data documentation:

- Dhan's `POST /v2/charts/intraday` endpoint **does provide same-day
  (current trading day) 1-minute OHLC+Volume candles**, for all
  segments including F&O.
- Separately, a 5-trading-day intraday history is available across
  1/5/15/25/60-minute timeframes.
- A single request is capped at 90 days of range for any of the above
  intervals.
- Required parameters: `securityId`, `exchangeSegment`, `instrument`,
  `interval`, `oi`, `fromDate`, `toDate`.

**This resolves the "does same-day intraday OHLC exist at all"
question affirmatively** — it does. It does NOT resolve the other two
named unknowns (candle authority relative to the WebSocket feed;
exact timestamp timezone of returned candles) — a direct fetch could
not retrieve the field-level response schema this session either, so
those two remain `UNKNOWN`, not converted to an assumption.

## Still `UNKNOWN` (not converted to an assumption)

- **Candle authority**: whether `/v2/charts/intraday`'s same-day
  candles are computed from the SAME tick stream the WebSocket feed
  delivers (making them a legitimate reconciliation/backfill source
  for gaps in the live feed) or from a separately-computed pipeline
  that could disagree with it. Not determinable from what was
  fetchable this session.
- **Timestamp timezone**: whether returned candle timestamps are IST
  or UTC, and whether they represent interval OPEN or interval CLOSE
  (this project's own `Bar.timestamp` convention is CLOSE — a mismatch
  here would silently misalign every bar this pipeline ever backfills).
- Every other item in Part 1's Dhan/NSE/SEBI list (WebSocket
  authentication specifics, heartbeat cadence, reconnect requirements,
  subscription limits, order-update WebSocket, Super Order stop-loss/
  trailing semantics, SEBI's exact technical provisions) remains
  exactly where Checkpoints 37-41 left it — re-cited, not re-verified,
  a real and repeated research gap this checkpoint again did not fully
  close given the time spent on the operational-loop implementation
  instead. Named explicitly rather than silently repeated without
  acknowledgment.

## Consequence for this checkpoint's implementation

Given "candle authority" and "timestamp timezone" remain unresolved,
`/v2/charts/intraday` was **not** wired into the market-data ingestion
pipeline this checkpoint — using it for gap recovery/backfill without
knowing whether its candles agree with the live feed's own aggregation
would risk silently corrupting exactly the trading-grade-bar honesty
this project has protected since Checkpoint 24A/31. The existing
REST-quote-polling ingestion path (Checkpoint 23, unchanged) remains
the only market-data source this checkpoint's code touches.
