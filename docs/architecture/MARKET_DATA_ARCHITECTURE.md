# Market Data & Instrument Foundation

Checkpoint 14. Establishes the provider-neutral historical market-data
foundation future `feature_engine`/`signal_generation`/
`research.backtesting`/`trading_engine` checkpoints will consume — no
indicator, signal, strategy, order, or broker-integration code exists
anywhere in this checkpoint. The output of this checkpoint is **data**,
not signals.

## What already existed (Checkpoint 5) vs. what's new (Checkpoint 14)

Checkpoint 5 already established the canonical shared-kernel/domain
contracts this checkpoint builds on — re-reading them was the first step
here, not re-inventing them:

| Concept | Status |
|---|---|
| `Instrument`, `InstrumentType`, `TradingStatus`, `make_instrument_id` | Already complete (Checkpoint 5) — unchanged |
| `Exchange` (NSE/BSE), `Timeframe`, `InstrumentId`, `ensure_utc` | Already complete (Checkpoint 5, shared kernel) — unchanged |
| `Bar`, `Quote`, `MarketDataQuality` | Already complete (Checkpoint 5) — `Bar` extended this checkpoint (see below) |
| `TradingSession`, `SessionStatus` | Already complete (Checkpoint 5) — extended with `.contains()` this checkpoint |
| Provider-neutral historical-data **access** (repository Protocol + service) | **New this checkpoint** |
| A deterministic fixture provider | **New this checkpoint** |
| Ordering/duplicate/completeness validation | **New this checkpoint** |
| Raw vs. adjusted price semantics | **New this checkpoint** |

## Instrument identity

No change was needed — `Instrument.instrument_id` (derived
deterministically from `(Exchange, symbol)` via `make_instrument_id`,
Checkpoint 5) already correctly distinguishes an NSE listing from a BSE
listing of the same symbol, and already keeps `symbol` (the exchange-
traded ticker) distinct from `instrument_id` (the domain-owned,
broker-neutral identity). No provider token, ISIN, or segment field was
added — none is required by anything this checkpoint builds, and adding
one speculatively would be exactly the premature abstraction the
checkpoint brief warns against. Provider-token mapping remains an
infrastructure-adapter concern (Checkpoint 3 §6), not represented in the
canonical identity — confirmed by inspection, not just by decision.

## Market-data contract

`application/repositories.HistoricalMarketDataRepository` (new): a
read-only Protocol —

```python
def get_bars(
    self, instrument_id: InstrumentId, timeframe: Timeframe,
    start: datetime, end: datetime,
) -> tuple[Bar, ...]: ...
```

No `DhanRequest`/`DhanResponse`/HTTP/SDK type appears in this signature
or anywhere in `application/` or `domain/` — verified by `lint-imports`
(6/6 kept) and by the pre-existing domain-purity architecture test, which
now also covers every new file in this checkpoint (it globs the whole
`domain/` package). A Dhan-backed adapter and the deterministic fixture
adapter built this checkpoint satisfy this Protocol identically; neither
`application/services/market_data.py` nor any domain module has ever
imported a provider name.

## Bar / candle model

`Bar` (Checkpoint 5, unchanged structurally except for one new field —
see below): `instrument_id`, `timeframe`, `timestamp`, `open`, `high`,
`low`, `close`, `volume`, `quality`, `adjustment`.

**Timestamp semantics, explicitly re-confirmed, not left ambiguous**:
`Bar.timestamp` is the bar's **close** time. A five-minute bar covering
`[09:15, 09:20)` IST is stamped `09:20` IST (`03:50` UTC internally).
This was already Checkpoint 5's decision (its own docstring already said
so); Checkpoint 14 pins it with an explicit test
(`test_bar_timestamp_is_documented_as_close_time`) and derives
`expected_bar_timestamps()`'s arithmetic from it (the first expected bar
in a session closes `market_open + timeframe duration` after open, not
at open itself).

**Numeric precision**: `Decimal` throughout (Checkpoint 3 §18, unchanged
— `Bar` already used `Decimal`, never `float`).

**Ordering / duplicate behavior**: a `Bar` *series* is expected to be
strictly increasing by `timestamp` with no duplicates.
`domain.market_data.quality.ensure_chronological()` (new) validates
this and **rejects** (raises `OutOfOrderBarError`/
`DuplicateBarTimestampError`) rather than silently reordering or
dropping — see [Validation Rules](#validation-rules).

## Timeframe model

Reused Checkpoint 5's `Timeframe` enum unchanged (`TICK`, `1m`, `3m`,
`5m`, `15m`, `30m`, `1h`, `1d`) — no new timeframe was added, and none of
the unrelated existing code that already used `Timeframe` was touched.
New this checkpoint: `domain.market_data.quality.timeframe_to_timedelta()`,
mapping each fixed-duration timeframe to its `timedelta` — `TICK`
deliberately has no entry and raises `ValueError`, since a tick is a
single event, not a time bucket, and returning an arbitrary placeholder
duration for it would be worse than refusing.

## Timezone semantics

Unchanged from Checkpoint 3/5 (re-confirmed, not re-decided): UTC is the
sole internal representation, enforced by `ensure_utc()` on every
timestamp-bearing field (`Bar.timestamp`, `TradingSession.market_open`/
`market_close`/`square_off_deadline`) — a naive or non-UTC-offset
datetime is rejected outright, never silently converted. `Asia/Kolkata`
(IST) wall-clock conversion is a presentation-boundary concern that does
not exist anywhere in `domain/` or `application/` — this checkpoint adds
no new IST-handling code, since none of its new logic renders anything
for a human. The same instant never has two meanings: every UTC value
this checkpoint produces (`expected_bar_timestamps()`,
`missing_bar_timestamps()`) is derived arithmetically from an already-
UTC `TradingSession`, never from a second, independently-computed IST
source.

## Trading session model

`TradingSession` (Checkpoint 5, unchanged) remains "the shape of one
already-determined session" — no exchange-calendar service, no holiday
list, no market-hours computation exists anywhere in this codebase, by
design (Checkpoint 5 Section 19, re-confirmed here). New this checkpoint:
`TradingSession.contains(timestamp) -> bool`, a deterministic range
check against the session's own already-known bounds — the minimal
building block `expected_bar_timestamps()`/`missing_bar_timestamps()`
need to reason about "does this instant belong to this session," without
this contract gaining any calendar knowledge.

## Raw vs. adjusted price semantics

`Bar` gained a new field: `adjustment: PriceAdjustment = PriceAdjustment.RAW`
(`PriceAdjustment` is a new two-value enum, `RAW`/`ADJUSTED`). This is a
genuine, justified extension of a locked Checkpoint 5 contract — the
same precedent as Checkpoint 7 extending `RiskLimits` — because whether a
bar's prices are raw or corporate-action-adjusted is a property of the
bar itself, not something a wrapper type layered on top should carry.

**No adjustment computation exists anywhere in this codebase.** Every
bar produced by this checkpoint (the fixture adapter) is `RAW`.
`ADJUSTED` is not reachable from any code path yet — it exists as the
explicit label a future corporate-action processor MUST set correctly
when it exists, rather than a future checkpoint discovering there is no
way to distinguish raw from adjusted data at all. Prices are never
silently adjusted anywhere in this checkpoint (Checkpoint 14 §10).

## Data quality model

Two independent mechanisms, kept deliberately separate rather than
merged into one "data quality framework":

1. **Per-bar quality flag** (`Bar.quality: MarketDataQuality` —
   `OK`/`STALE`/`SUSPECT`, unchanged from Checkpoint 5): a provider
   adapter's own assessment of one bar's trustworthiness. Untouched this
   checkpoint.
2. **Series-level integrity** (`domain/market_data/quality.py`, new):
   `ensure_chronological()` (ordering/duplicates) and
   `missing_bar_timestamps()` (completeness against an expected,
   session-bounded schedule). These are properties of a *collection* of
   bars, not of any one bar, so they are functions over a `tuple[Bar,
   ...]`, not new `Bar` fields.

No `received_at`/`generated_at`/provenance metadata was added — nothing
in this checkpoint's scope needs it yet (no live ingestion exists), and
adding it speculatively would be exactly the "huge data-quality
framework" the checkpoint brief warns against building.

## Validation rules

| Rule | Enforcement | Policy on violation |
|---|---|---|
| `high >= max(open, close)`, `low <= min(open, close)` | `Bar.__post_init__` (Checkpoint 5, unchanged) | Raises `ValueError` at construction — a `Bar` violating this can never exist |
| `volume >= 0` | `Bar.__post_init__` (unchanged) | Raises `ValueError` |
| `timestamp` timezone-aware, UTC | `ensure_utc()` (unchanged) | Raises `ValueError` |
| Series strictly ordered, no duplicate timestamps | `ensure_chronological()` (new) | Raises `OutOfOrderBarError`/`DuplicateBarTimestampError` — **rejected, never silently reordered or dropped** |
| Series completeness against an expected schedule | `missing_bar_timestamps()` (new) | Returns the gap list — an observability function, not a validator; a caller decides what "incomplete" means for its use case |

Checkpoint 14 §16's explicit question — "does invalid data raise an
error or get returned with a quality flag?" — is answered per rule
above: single-bar OHLC/volume/timezone violations were already
construction-time errors (Checkpoint 5); the new series-level ordering
rule is also a hard rejection, not a flag, because a caller silently
consuming an out-of-order or duplicated series has no way to know it
happened otherwise. Completeness, by contrast, is inherently a
*report* (a session can legitimately have fewer bars than expected for
reasons the domain layer cannot judge, e.g. mid-session data not yet
ingested) — so it returns a value, not a rejection.

## Application layer

`application/services/market_data.py`: `HistoricalMarketDataService`,
depending only on `HistoricalMarketDataRepository` (the Protocol) — never
a concrete implementation. `get_bars()` retrieves and validates
(`ensure_chronological`); `completeness()` retrieves and reports gaps
against a session. Tested with an in-memory fake repository
(`tests/unit/application/services/test_market_data_service.py`), proving
the service works without Django, PostgreSQL, or any provider — mirrors
`RiskConfigurationService`'s own test pattern (Checkpoint 8).

## Infrastructure adapter

`infrastructure/market_data_providers/fixtures.py`:
`FixtureHistoricalMarketDataRepository` — a deterministic, in-memory
`HistoricalMarketDataRepository` implementation. **No Dhan code, no
network call, no credentials, no live provider of any kind was
introduced this checkpoint** — explicitly required by Checkpoint 14 §14:
"a fixture adapter is acceptable and preferable to coupling the
checkpoint to external availability." The eight bars it serves for the
synthetic `NSE:FIXTURE01` instrument are hand-authored (not
randomly generated, even with a fixed seed) and cover only the first 40
minutes of a synthetic session, deliberately incomplete against a
full-day `TradingSession` — so `HistoricalMarketDataService.
completeness()` has a real, non-empty, deterministic result to report in
tests.

Dhan itself remains untouched: `infrastructure/brokers/dhan/` (a
Checkpoint 1-era placeholder directory) was not modified, no Dhan SDK
dependency was added to `pyproject.toml`, and no code anywhere imports a
Dhan-specific type. When a real Dhan market-data adapter is built in a
future checkpoint, it will implement `HistoricalMarketDataRepository`
exactly as the fixture adapter does — the Protocol boundary this
checkpoint establishes is what makes that possible without touching
`application/`.

## Persistence

**Deliberately deferred — no new Django model, no migration, this
checkpoint.** The Technology Mapping's existing decision (PostgreSQL/
TimescaleDB hypertables for durable historical data, Parquet for bulk
research storage) is unchanged and was not redesigned. Building a
TimescaleDB-backed table now, before any real ingestion pipeline exists
to populate it, would mean creating schema for zero real data — exactly
the "do NOT ingest large historical datasets... do NOT create
production-scale partitioning unless required" the checkpoint brief
warns against. The in-memory fixture adapter already makes the full
domain → application → infrastructure path testable end-to-end without
a database at all (relevant given PostgreSQL remains unreachable in this
sandbox regardless). **This must be revisited** at the checkpoint that
introduces real historical-data ingestion — that checkpoint will need
the actual hypertable schema this one deliberately does not build yet.

## API / frontend boundary

**None was introduced.** No `infrastructure/api` view, no URL, no
OpenAPI schema change, no frontend contract regeneration — confirmed by
inspection: `manage.py spectacular --fail-on-warn` produces a
byte-identical schema to before this checkpoint (verified by diffing the
regenerated output). Checkpoint 14 §19 is explicit that a market-data
dashboard, candlestick chart, or data explorer belongs to a later
checkpoint, and that an API boundary should only be added when a real
consumer needs one — no consumer (feature engine, backtester, etc.)
exists yet, so no boundary was added speculatively.

## Provider boundary (Dhan)

`import-linter`'s existing contracts #1/#2 already mechanically forbid
`domain`/`application` from ever importing `infrastructure` (including a
future `infrastructure/market_data_providers/dhan/`) — no new contract
was needed to express this, since the existing generic infrastructure-
isolation rule already covers it. No Dhan adapter exists yet to write a
"Dhan depends on the canonical contract, not vice versa" test against;
that test becomes meaningful (and should be added) once a real Dhan
adapter exists.
