# Checkpoint 53 — Dhan v2 Live Market Feed WebSocket Protocol Research

Fresh research pass against DhanHQ's own official v2 API documentation
(`https://dhanhq.co/docs/v2/live-market-feed/`), fetched during this
checkpoint. This is protocol-level documentation research only - it does
NOT constitute a live connection test, since this environment's Dhan
credential remains unusable for real verification (Checkpoint 41's own
documented finding, unchanged). Every fact below is labelled per this
project's own established classification discipline.

## Connection

| Fact | Value | Classification |
|---|---|---|
| WebSocket URL | `wss://api-feed.dhan.co?version=2&token=...&clientId=...&authType=2` | VERIFIED_PRIMARY (official docs) |
| Required query params | `version=2`, `token`, `clientId`, `authType=2` | VERIFIED_PRIMARY |
| Max connections per user | 5 | VERIFIED_PRIMARY |
| Max instruments per connection | 5000 | VERIFIED_PRIMARY |
| Max instruments per subscription message | 100 | VERIFIED_PRIMARY |
| Server ping interval | every 10 seconds | VERIFIED_PRIMARY |
| Client unresponsive timeout | connection closed if no response for >40 seconds | VERIFIED_PRIMARY |
| Byte order | Little Endian, for every packet | VERIFIED_PRIMARY |
| Disconnect reason 805 | "if more than 5 websockets are established, the first socket will be disconnected" | VERIFIED_PRIMARY |

## Subscription request (client → server)

```json
{
    "RequestCode": 15,
    "InstrumentCount": 2,
    "InstrumentList": [
        {"ExchangeSegment": "NSE_EQ", "SecurityId": "1333"}
    ]
}
```

Disconnect request: `{"RequestCode": 12}`. VERIFIED_PRIMARY.

## Response header (every packet, 8 bytes total per the documented byte ranges)

| Bytes | Type | Size | Field |
|---|---|---|---|
| 0 | byte | 1 | Feed Response Code |
| 1-2 | int16 | 2 | Message Length (payload) |
| 3 | byte | 1 | Exchange Segment |
| 4-7 | int32 | 4 | Security ID |

VERIFIED_PRIMARY. (Documentation's own byte numbering is 1-indexed
inclusive-inclusive; the table above is re-expressed 0-indexed to match
Python `struct` slicing conventions used in this checkpoint's decoder -
this re-indexing is a PROJECT_DECISION for implementation convenience,
not a re-verified fact.)

## Packet types implemented THIS checkpoint

| Code | Packet | Implemented | Fields (beyond header) |
|---|---|---|---|
| 2 | Ticker | YES | float32 LTP, int32 LTT (epoch) |
| 50 | Disconnect | YES | int16 disconnect reason code |

VERIFIED_PRIMARY for both layouts.

## Packet types documented but NOT implemented this checkpoint (named, not silently skipped)

| Code | Packet | Status |
|---|---|---|
| 4 | Quote | Documented above, decoder NOT written this checkpoint |
| 5 | OI | Documented above, decoder NOT written this checkpoint |
| 6 | Prev Close | Documented above, decoder NOT written this checkpoint |
| 8 | Full (incl. 5-level market depth) | Documented above, decoder NOT written this checkpoint |

Reason: this checkpoint's scope was deliberately bounded to proving the
decoder architecture is correct and safe (never crashes on malformed
input) against ONE simple and ONE control packet type, rather than
spreading effort thin across all seven documented packet shapes without
depth on any of them. Extending to Quote/OI/PrevClose/Full is
mechanical, not architecturally novel, once Ticker/Disconnect are
proven - a named next action, not a blocker.

## Explicitly UNKNOWN / not verified this checkpoint

- Authentication error behavior (what the server sends back on an
  invalid token/clientId over the WebSocket itself, as opposed to REST).
- Real subscription acknowledgment packet shape (if any exists distinct
  from the first data packet).
- Actual token validity duration for a live-generated (not manually
  generated) access token used specifically for this WebSocket.
- Real-world reconnect/backoff behavior recommended by Dhan (the
  documentation excerpt fetched this checkpoint did not cover this).

These remain UNKNOWN, not assumed, and are not implemented against this
checkpoint.

## What this research enables this checkpoint

A binary packet decoder (`infrastructure/market_data_providers/dhan/
packet_decoder.py`) built against the VERIFIED_PRIMARY header + Ticker +
Disconnect layouts above, with deterministic byte-level test fixtures
constructed directly from this documented structure (no live connection
needed to test a decoder against known-correct bytes). This is real,
verifiable progress distinct from a live connection test - the decoder's
correctness is checkable today; only its use against Dhan's ACTUAL
production stream remains LIVE_VERIFICATION_BLOCKED.
