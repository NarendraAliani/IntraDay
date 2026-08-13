# Signal Generation

Checkpoint 18. Establishes the first technology-neutral interpretation
of feature state — a deterministic `DirectionalIndication`
(`BULLISH`/`BEARISH`/`NEUTRAL`) derived from SMA, EMA, and ATR. This is
**not** a trading strategy, an order-generation system, broker
integration, or live trading. It establishes a clean boundary:

```
Feature Calculation (signal_intelligence/feature_engine)
        ↓
Signal Generation (signal_intelligence/signal_generation)
        ↓
Future Strategy / Trading Engine (not built yet)
```

## Why the output is NOT `domain.signal.Signal`

`domain/signal/contracts.py`'s `Signal` (Checkpoint 5) is a
**strategy-level** candidate decision: it requires `strategy_id`,
`strategy_version`, `theoretical_entry`, `theoretical_stop_loss`,
`theoretical_targets`. This checkpoint's brief explicitly forbids
inventing stop-loss/target/position-sizing values, and there is no
strategy yet for a `strategy_id` to reference —
`trading_engine/strategy_execution` does not exist as executable code
until a later checkpoint, confirmed by this bounded context's own
Checkpoint-1 README, which already named the future responsibility as
"converts **strategy output** into canonical Signal objects."
Constructing a `domain.signal.Signal` today would require fabricating a
`strategy_id` and price levels this checkpoint has no authority to
invent — exactly the class of dishonest placeholder this project has
refused at every prior checkpoint (e.g. Checkpoint 17's refusal to
invent a previous-close for ATR's first bar).

`DirectionalIndication` (`signal_intelligence/signal_generation/contracts.py`,
new) is deliberately smaller and earlier-stage: "does the current
feature state look bullish, bearish, or neutral?" — answerable purely
from features, with no strategy attached. A future strategy/signal-
verification layer will consume `DirectionalIndication`s (among other
inputs) to eventually produce a real `domain.signal.Signal`.
`domain/signal/contracts.py` itself is **unchanged** this checkpoint.

## Why `DirectionalIndication` lives in the bounded context, not `domain/`

The project's own minimum-viable-shared-kernel rule (Checkpoint 2 §3.1):
a concept enters `domain/` only when at least two bounded contexts need
the *identical* contract — never speculatively. Today only
`signal_intelligence/signal_generation` produces or consumes
`DirectionalIndication`; no second bounded context has a confirmed need
yet. This exactly mirrors why `SimpleMovingAverageDefinition`/
`ExponentialMovingAverageDefinition`/`AverageTrueRangeDefinition`
(Checkpoints 15–17) live in `signal_intelligence/feature_engine`, not
`domain/feature` — only `FeatureValue` itself (the genuinely
cross-context *output*, pre-approved at Checkpoint 5 for Rule 5.5
parity) lives in `domain/`. Promoting `DirectionalIndication` to
`domain/signal` is a natural, deliberate future step once a second real
consumer exists (e.g. `signal_intelligence/signal_verification` or
`research/backtesting` replay) — not a decision to make now.

## Signal semantics

```
BULLISH  iff  EMA > SMA  AND  price > EMA  AND  ATR is valid
BEARISH  iff  EMA < SMA  AND  price < EMA  AND  ATR is valid
NEUTRAL  otherwise
```

Equality cases (`EMA == SMA`, `price == EMA`) fall through to NEUTRAL by
construction — `>`/`<` are both false for equal Decimals, no special
casing needed. `price` is the source bar's own `close` (the same price
concept SMA/EMA already compare against internally). This is explicitly
**not** a trading strategy: no stop-loss, target, position size, or
execution instruction is produced or implied.

## ATR's role — deliberately structural, not directional (yet)

ATR does **not** participate in the bullish/bearish comparison itself
this checkpoint — no threshold (e.g. "ATR > 2%") was invented, since no
existing architecture decision establishes one and inventing an
arbitrary magic number is explicitly forbidden. ATR's role is narrower:
it must **exist**, be **valid** (non-negative — a real True-Range
average can never be negative; `InvalidAtrValueError` otherwise), and be
**aligned** (same instrument/timeframe/timestamp as the other inputs)
for an indication to be produced at all. This proves Signal Generation
can consume a feature that is not close-only and not part of the
directional test, without embedding its computation — the same
architectural point Checkpoint 17 proved for the Feature Engine itself,
one layer up.

## Feature alignment rule

All four inputs (the price bar, SMA, EMA, ATR) must share the **exact
same** `instrument_id`, `timeframe`, **and** `timestamp` — not "the
latest value we happen to have for each." A caller with genuinely
misaligned inputs (e.g. SMA as of 10:15 but EMA as of 10:16) gets a
raised, specific error (`MisalignedFeatureTimestampError` etc.) — never a
silently-blended read across different market states. This mirrors
`domain.market_data.quality.ensure_chronological()`'s own "reject, never
silently paper over" policy (Checkpoint 14 §16), and is tested directly
against the checkpoint brief's own illustrative misaligned example
(SMA@10:15, EMA@10:16, ATR@10:14, Price@10:16).

Defense in depth: each `FeatureValue`'s `feature_name` is checked against
its expected prefix (`sma_`/`ema_`/`atr_`) — `WrongFeatureTypeError` if a
caller passes values in the wrong parameter slot.

## Signal identity & versioning

Structural identity, not a random UUID — `(definition_name,
definition_version, instrument_id, timeframe, timestamp)`, mirroring
`FeatureValue`'s own identity convention exactly, for the same
reproducibility reason: two calls with identical inputs produce an
identical `DirectionalIndication`. `definition_name` =
`"sma_ema_atr_directional"`, `definition_version` = `Version(value="v1")`
— the rule's own version, distinct from (and not duplicating) which
SMA/EMA/ATR periods were used, since that is already fully carried by
each embedded `FeatureValue`'s own `feature_name` (e.g. `"sma_20"`).
Reuses the project's existing `Version` primitive — no second versioning
system was introduced.

## Signal provenance

Full provenance is carried directly, not just referenced by name: the
exact `FeatureValue` instances (`sma`, `ema`, `atr`) that produced an
indication are embedded fields on `DirectionalIndication` itself, so it
is independently reproducible and auditable without a second lookup. No
database persistence was introduced this checkpoint — the contract
itself carries enough provenance to support later persistence.

## No-look-ahead guarantee

`generate_directional_indication` is a pure function of its four
arguments only — no look-ahead is possible by construction. At the
series level, `generate_directional_indications` iterates aligned
timestamps in chronological order, and each indication depends only on
that timestamp's own bar/feature values, never a later one — tested
explicitly (future-observation-appended/modified tests, plus a
Hypothesis property test), exactly mirroring the SMA/EMA/ATR precedent
from Checkpoints 15–17.

## Missing-feature policy (Checkpoint 18 §17, explicit decision)

Two layers, two different, deliberate policies:

- **`generate_directional_indication`** (single observation): SMA/EMA/ATR
  are all **required, non-optional** parameters. If a caller does not
  have a value for one, it simply cannot call this function for that
  timestamp — there is no "missing but let's produce NEUTRAL anyway"
  path, because silently downgrading to NEUTRAL when a required input is
  literally absent would conflate "the market is balanced" with "we
  couldn't even compute the indicator," a category error a reproducible,
  auditable system must not make.
- **`generate_directional_indications`** (series alignment): when
  composing three independent feature series with different warm-up
  lengths (e.g. SMA(20) warms up later than EMA(10)), a timestamp missing
  one of the three is **skipped** — no indication is produced for it,
  exactly as `compute_simple_moving_average` et al. produce no output
  during their own warm-up. This is the natural, expected shape of
  legitimate partial-warm-up data, not an error condition.

## Architecture enforcement

`signal_intelligence/signal_generation` imports only `domain/feature`,
`domain/market_data`, `domain/shared_kernel` — never
`signal_intelligence/feature_engine`'s compute functions, never
infrastructure, never Django. Verified two ways: `lint-imports` (6/6
kept — the existing generic infrastructure-isolation contracts already
cover this, no new contract needed) and a dedicated static-scan
architecture test
(`tests/unit/architecture/test_signal_generation_boundaries.py`,
mirroring the Checkpoint 4 `test_narrow_dependency_exception.py`
pattern) that positively asserts the package's only `domain.*` imports
are `feature`/`market_data`/`shared_kernel`, and that it never imports
`feature_engine` or any infrastructure/framework module. Only
`application/services/signal_generation.py` (a different layer) composes
`FeatureEngineService` with the pure interpretation function — "the
feature engine owns computation, signal generation owns interpretation"
is a checked boundary, not just an assertion.

## Application layer

`SignalGenerationService` (`application/services/signal_generation.py`):
composes `HistoricalMarketDataService` (Checkpoint 14, bar retrieval),
`FeatureEngineService` (Checkpoints 15–17, SMA/EMA/ATR computation), and
`signal_intelligence.signal_generation`'s pure alignment/interpretation
function. Contains no directional-rule mathematics of its own — exactly
`application/`'s documented orchestration role. Tested with an in-memory
fake market-data repository (mirrors every other application-service
test in this codebase); never imports Django, PostgreSQL, Redis, Celery,
HTTP, or Dhan (verified by a static AST-based test, same pattern as
`FeatureEngineService`'s own).

## No persistence, no API, no frontend

**None was introduced.** No database model, no DRF endpoint, no OpenAPI
schema change (confirmed: regenerated schema byte-identical in
substance), no dashboard. `DirectionalIndication` is designed to support
future persistence (full provenance already embedded) but nothing
persists it yet — consistent with every feature-engine checkpoint's own
deferral.
