# Signal Verification

Checkpoint 19. Establishes the first technology-neutral evaluation of
whether a `DirectionalIndication` (Checkpoint 18) was subsequently
supported by actual market-price movement. This is observation and
outcome evaluation only — not a trading strategy, order system, broker
integration, or live trading.

```
Market Data → Feature Engine → SMA/EMA/ATR → DirectionalIndication
                                                      ↓
                                             Signal Verification
                                                      ↓
                                     SUPPORTED / NOT_SUPPORTED / INCONCLUSIVE
```

## Relationship to the bounded context's own Checkpoint-1 README

`signal_intelligence/signal_verification/README.md` (Checkpoint 1) named
the FUTURE, full responsibility: "verifies realized signal outcomes
against theoretical expectation... compares `domain/signal`'s original
prediction against `signal_intelligence/theoretical_outcome`'s idealized
MFE/MAE/conditional expectancy." That depends on `domain/signal`'s
strategy-level `Signal` (still unbuilt — Checkpoint 18 explained why)
and on `theoretical_outcome` (MFE/MAE/path analysis — explicitly out of
this checkpoint's scope per the brief §14). Checkpoint 19 is therefore,
like Checkpoint 18, an intentionally smaller, earlier-stage building
block: a single, deterministic price comparison — no MFE, no MAE, no
path analysis, no strategy.

## Outcome semantics

```
BULLISH + observed_price >  reference_price  -> SUPPORTED
BULLISH + observed_price <= reference_price  -> NOT_SUPPORTED

BEARISH + observed_price <  reference_price  -> SUPPORTED
BEARISH + observed_price >= reference_price  -> NOT_SUPPORTED

NEUTRAL (any observed_price)                 -> INCONCLUSIVE
```

`reference_price` is `indication.price` — the signal-time close, already
carried on `DirectionalIndication` from Checkpoint 18; never a future
bar's close. Equal prices are treated as **NOT_SUPPORTED** for BULLISH/
BEARISH, not SUPPORTED and not INCONCLUSIVE — "no net movement" cannot
honestly support a directional call that specifically predicted movement,
mirroring `generate_directional_indication`'s own treatment of equality.

`VerificationOutcome` is deliberately `SUPPORTED`/`NOT_SUPPORTED`/
`INCONCLUSIVE` — never `BUY`/`SELL`/`PROFIT`/`LOSS`, which belong to
future strategy/execution semantics this checkpoint does not touch.

## Evaluation horizon

`horizon_bars: int` is an explicit, required parameter — no magic
default (e.g. "next 5 bars" hard-coded). The verifier evaluates exactly
**one** future observation: the bar `horizon_bars` bars after the
signal — the smallest deterministic implementation, explicitly not a
path/MFE/MAE analysis across the whole horizon (deferred to
`signal_intelligence/theoretical_outcome`). Bars beyond `horizon_bars` in
a supplied series are accepted but ignored — a caller may over-supply
without changing the result (tested via a Hypothesis property).

## Reference price

`indication.price` — the `DirectionalIndication`'s own signal-time close
(Checkpoint 18). Never a future bar's close, and never re-derived.

## Future observation boundary

A bar's `timestamp` must be **strictly after** `indication.timestamp` to
be a legitimate verification observation — a bar at the same instant, or
before it, is rejected (`NonFutureObservationError`), never silently
dropped or reordered. `ensure_chronological()` (Checkpoint 14) is reused
verbatim for ordering/duplicate validation across the future-bar series
— not reimplemented.

## Neutral signal semantics

A `NEUTRAL` `DirectionalIndication` made no directional prediction to
support or refute — its only honest verification outcome is
`INCONCLUSIVE`, regardless of what price does afterward. Never silently
treated as `NOT_SUPPORTED`.

## Incomplete-horizon semantics

If fewer than `horizon_bars` future bars are available (end-of-day
signal, holiday, missing data, interrupted feed), the outcome is
`INCONCLUSIVE` — never silently treated as `NOT_SUPPORTED`. "We don't
yet know" is a distinct, honest state from "the market moved against the
call."

## Identity & versioning

Structural identity — `(verification_definition_name,
verification_definition_version, instrument_id, timeframe,
signal_timestamp, horizon_bars)` — mirroring `FeatureValue`/
`DirectionalIndication`'s own convention, no random UUID.
`verification_definition_name = "single_point_price_movement"`,
`verification_definition_version = Version(value="v1")` — reuses the
existing `Version` primitive, distinct from (and never confused with)
`DirectionalIndication`'s own `definition_name`/`definition_version`
(which identifies the rule that *produced* the indication, not the rule
that evaluates it afterward).

## Provenance

The entire source `indication` is embedded directly on
`VerificationResult` (which itself embeds its own SMA/EMA/ATR
`FeatureValue`s) — independently reproducible and auditable without a
second lookup. No persistence introduced; the contract carries enough
information to support it later.

## DirectionalIndication promotion assessment

**Not promoted to `domain/` this checkpoint — and the evidence is more
nuanced than a simple yes/no.**

`signal_intelligence/signal_verification` is now a second real consumer
of `DirectionalIndication`, importing it directly from
`signal_intelligence.signal_generation.contracts` (unavoidable: no
`domain/` equivalent exists, per Checkpoint 18's own decision). This
**is** genuine evidence — a real cross-submodule dependency now exists
where none did before.

However, the project's minimum-viable-shared-kernel rule (Checkpoint 2
§3.1) sets the bar at **two bounded contexts** — the five major
divisions (`research`, `signal_intelligence`, `trading_engine`,
`control_plane`, `communication`). `signal_generation` and
`signal_verification` are both submodules of the *same* bounded context
(`signal_intelligence`) — this is intra-context reuse, exactly like
`feature_engine`'s SMA/EMA/ATR definitions being shared internally
within `signal_intelligence` without ever needing `domain/` promotion.
No bounded context *outside* `signal_intelligence` (e.g.
`research/backtesting` replaying verification, or `control_plane/audit`
logging results) has a confirmed need for `DirectionalIndication` yet.

**Conclusion**: promotion is not yet justified by the project's own
rule, but this checkpoint's finding — a second real consumer within the
same context — is the closest this contract has come. Recommend
revisiting the moment a bounded context *outside* `signal_intelligence`
needs the identical shape.

## Architecture enforcement

`signal_intelligence/signal_verification` imports only `domain/market_data`,
`domain/shared_kernel`, and `signal_intelligence/signal_generation`
(for `DirectionalIndication`) — never `trading_engine`, infrastructure,
Django, or `feature_engine`'s own compute internals. Verified two ways:
`lint-imports` (6/6 kept — the existing generic infrastructure-isolation
contracts already cover this) and a dedicated static-scan architecture
test (`tests/unit/architecture/test_signal_verification_boundaries.py`,
mirroring Checkpoint 18's own `test_signal_generation_boundaries.py`
pattern) that positively asserts the package's only imports are the
documented, approved set.

## Application layer

`SignalVerificationService` (`application/services/signal_verification.py`):
composes `HistoricalMarketDataService` (Checkpoint 14, future-bar
retrieval) with `signal_intelligence.signal_verification`'s pure
evaluation function. Contains no outcome-determination logic of its own.
Tested with an in-memory fake market-data repository; never imports
Django, PostgreSQL, Redis, Celery, HTTP, or Dhan (verified by a static
AST-based test, same pattern as `SignalGenerationService`'s own).

## No persistence, no API, no frontend

**None was introduced.** No database model, no DRF endpoint, no OpenAPI
schema change (confirmed: regenerated schema byte-identical in
substance). `VerificationResult` is designed to support future
persistence (full provenance already embedded) but nothing persists it
yet.

## Multiple-signal / series verification

`verify_directional_indications()` verifies several `DirectionalIndication`s
against one shared bar series, preserving input order, never
cross-contaminating instruments/timeframes, and never letting one
indication's future data affect another's result (tested explicitly —
two structurally-identical indications given different futures produce
independently correct, different outcomes).
