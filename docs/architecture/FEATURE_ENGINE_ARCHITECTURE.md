# Feature Engine

Checkpoint 15. Establishes the first technology-neutral feature
computation — Simple Moving Average (SMA) — and the architecture future
EMA/RSI/ATR/VWAP/Supertrend/Bollinger Bands/momentum/volatility features
will follow. Output is **features**, not signals: nothing here scores,
ranks, or interprets a feature value as a trading decision.

## Feature vs. raw data vs. signal

Three distinct concepts, kept structurally distinct, never blurred:

- **`Bar`** (`domain/market_data`, Checkpoint 5/14) — raw/market-derived
  data. A fact about what happened.
- **`FeatureValue`** (`domain/feature`, Checkpoint 5, unchanged this
  checkpoint) — a deterministic *derivation* from one or more bars. A
  computed number, not an opinion.
- **Signal** (`domain/signal`, not implemented) — a trading decision
  *candidate*. Not built yet, not touched this checkpoint.

## What already existed (Checkpoint 5) vs. what's new (Checkpoint 15)

`domain/feature/contracts.py`'s `FeatureValue` — `feature_name: str`,
`feature_version: Version`, `instrument_id`, `timeframe`, `timestamp`,
`value: Decimal` — was **already exactly right** and needed **zero
changes**. Its own docstring, written at Checkpoint 5, already gave the
worked example `"ema_20"` for how a feature name should bake its
parameter in — this checkpoint's `SimpleMovingAverageDefinition.feature_name`
(`"sma_5"`, `"sma_10"`, ...) follows that exact convention rather than
inventing a new one.

What's new: the actual SMA *computation* (`signal_intelligence/
feature_engine/sma.py`) and its identity type
(`SimpleMovingAverageDefinition`) — Checkpoint 5's own comment on
`FeatureValue` said this belonged in `signal_intelligence/feature_engine`
"in a later checkpoint." This is that checkpoint.

## A genuine architectural reconciliation

The checkpoint brief's instruction ("Feature Engine → HistoricalMarketDataService
→ Repository → Infrastructure", §15) and this project's own pre-existing,
locked architecture (`signal_intelligence/feature_engine/README.md`,
written at Checkpoint 1: "Depends On: domain/feature, domain/market_data"
— explicitly NOT `application`) appear to conflict at first read.
`.importlinter` contract #3 (`layers`: `application` above
`signal_intelligence` above `domain`) settles it structurally: a bounded
context may never import `application` (only the reverse). Resolved by
splitting "Feature Engine" into its two real halves, both of which the
brief's instruction is satisfied by together:

- **The calculation** (`signal_intelligence/feature_engine/sma.py`) —
  pure, technology-neutral, depends only on `domain/feature` and
  `domain/market_data`, exactly as the bounded context's own README
  already specified. No `application` import, no infrastructure import.
- **The orchestration** (`application/services/feature_engine.py`'s
  `FeatureEngineService`) — depends on `application/services/market_data.
  HistoricalMarketDataService` (Checkpoint 14) *and* on
  `signal_intelligence.feature_engine`'s pure function — exactly
  `application/`'s documented role ("orchestrates the bounded contexts,"
  `.importlinter` contract #3's own name). This is the piece that
  satisfies "Feature Engine → HistoricalMarketDataService → Repository →
  Infrastructure": `FeatureEngineService` never bypasses
  `HistoricalMarketDataService` to reach `FixtureHistoricalMarketDataRepository`
  or a future Dhan adapter directly.

Verified, not merely asserted: `lint-imports` (6/6 kept) is the first
real exercise of contract #3's `signal_intelligence` layer in this
codebase — no prior checkpoint had put any code there. This checkpoint
both populates it and proves the boundary holds.

## Feature identity

`SimpleMovingAverageDefinition(lookback: int)` — the smallest useful
identity: one field, because SMA has exactly one parameter. `lookback=5`
and `lookback=10` are distinct definitions (`feature_name` "sma_5" vs.
"sma_10"); two definitions with the same `lookback` are equal
(`@dataclass(frozen=True)` gives structural equality for free) and
produce the identical `feature_name`/`feature_version`.

**No generic `FeatureDefinition` registry/framework was built.** A
future `EMADefinition`/`RSIDefinition`/`ATRDefinition` follows this exact
same small, one-off pattern — its own tiny frozen dataclass with a
`feature_name`/`feature_version` property — rather than this checkpoint
building a parameterization framework speculatively ahead of a second
concrete feature actually needing one (the checkpoint brief's own
"do not automatically create all of them" instruction, applied).

`lookback` validation (`InvalidLookbackError`): must be a real `int`
(not `float`, and not `bool` — `bool` is a Python subclass of `int`, so
`SimpleMovingAverageDefinition(lookback=True)` is explicitly rejected
rather than silently meaning `lookback=1`), and strictly positive. Zero
and negative lookbacks are rejected at construction, not at computation
time.

## FeatureValue semantics for SMA

`FeatureValue.timestamp` equals its **source bar's own timestamp** —
which is itself the bar's CLOSE time (`Bar`'s own Checkpoint 5/14
convention). No second timestamp convention was introduced. A feature
value computed from the bar closing at 09:20 IST is itself timestamped
09:20 IST — "the SMA as of the moment this bar closed."

`FeatureValue.instrument_id`/`timeframe` are derived from the input bars
themselves (`bars[0].instrument_id`/`bars[0].timeframe`), never passed
as separate, independently-suppliable parameters that could disagree
with what the bars actually contain.

## SMA specification

`SMA(t) = mean(close[t-N+1 .. t])` — `Bar.close` only, never
open/high/low/volume, exactly as specified.

**Warm-up (Checkpoint 15 §8, explicit decision)**: the first `lookback -
1` bars produce **no output at all** — not `None`, not a shorter-period
average. Exactly `lookback` real observations are required before the
first `FeatureValue` is ever emitted. After warm-up, one output exists
per input bar (`N` bars in → `N - lookback + 1` values out),
chronologically ordered, never reordered.

**Complexity**: O(n) in the number of input bars — a fixed-size rolling
window (`collections.deque(maxlen=lookback)`) with a running sum, never
an O(n·lookback) re-summation per output. Verified correct against the
checkpoint brief's own hand-worked example (closes 100/102/104/106/108,
`SMA(3)` = 102/104/106) as a literal unit test.

**Precision**: full `Decimal` division (`window_sum / lookback`), no
`float` conversion anywhere, no explicit rounding applied. A future
consumer needing a specific display precision rounds explicitly at its
own boundary — this function does not invent a rounding policy nothing
in this checkpoint's scope requires.

## No-look-ahead guarantee

Not merely a structural claim — tested explicitly (Checkpoint 15 §7):
`test_future_bar_does_not_influence_earlier_output` and
`test_modifying_a_future_bar_does_not_change_earlier_sma_values` compute
the same prefix of bars twice, once alone and once with an extra/altered
bar appended, and assert the earlier outputs are byte-identical either
way. A Hypothesis property test
(`test_no_output_uses_future_observations`) generalizes this across
arbitrary generated bar series and lookback values. This holds by
construction — the rolling window only ever accumulates bars already
iterated in chronological order — but the checkpoint brief explicitly
required testing the invariant, not just relying on the implementation
shape, so it is tested directly.

## Instrument / timeframe consistency

A feature series must come from exactly one instrument and one
timeframe. `compute_simple_moving_average` validates this defensively
(even though `HistoricalMarketDataService.get_bars()` already filters to
one instrument/timeframe by its own query parameters) — raising
`MixedInstrumentSeriesError`/`MixedTimeframeSeriesError` if the input
bars disagree. Defense in depth: a future caller constructing a bar
tuple by hand (e.g. in a test, or a not-yet-existing consumer) gets the
same protection the service's own callers get for free.

## Market-data integrity reuse

`compute_simple_moving_average` calls `domain.market_data.quality.
ensure_chronological()` (Checkpoint 14) as its first step — duplicate or
out-of-order input bars are rejected (`DuplicateBarTimestampError`/
`OutOfOrderBarError`) before any SMA arithmetic runs. This rule was
**not reimplemented** — Checkpoint 14's canonical series validation is
reused verbatim, exactly per instruction.

## Application layer

`FeatureEngineService` (`application/services/feature_engine.py`):
depends on `HistoricalMarketDataService` (Checkpoint 14) and
`signal_intelligence.feature_engine`'s pure functions — never Django,
PostgreSQL, Redis, Celery, HTTP, or Dhan. Tested with an in-memory fake
market-data repository (deliberately not `FixtureHistoricalMarketDataRepository`,
to prove the service depends on the Protocol boundary, not any one
concrete adapter), plus a static AST-based test confirming the module
itself imports no `django`/`intraday.infrastructure`/Dhan-named module.

## No persistence, no API, no frontend

**None of the three were added, per explicit instruction.** No
TimescaleDB table for feature values (persistence remains deferred to
whenever real ingestion+storage is authorized — unchanged from
Checkpoint 14's own deferral). No DRF endpoint, URL, or OpenAPI schema
change (confirmed: the regenerated schema contains zero feature/SMA
references). No dashboard, chart, or indicator viewer. There is no real
consumer yet (`signal_intelligence/signal_generation` doesn't exist) to
justify any of the three.

## Research/backtest parity

`compute_simple_moving_average` is a pure function: identical `bars` +
identical `definition` always produces an identical `tuple[FeatureValue,
...]`, regardless of which future consumer (live, paper, backtest,
research) calls it — verified by
`test_same_input_produces_identical_output` and
`test_repeated_calculation_produces_identical_decimal_values`. No
consumer exists yet; the guarantee is proven now so it doesn't need to
be re-verified once one does.

---

## Checkpoint 16 — Exponential Moving Average (recursive/stateful computation)

Checkpoint 15 proved the Feature Engine architecture for a **fixed-window**
calculation (SMA). Checkpoint 16 exists specifically to prove it for a
**recursive/stateful** one — EMA, where each output depends on the
previous output, not on re-summing a fixed window of raw inputs.

### EMA definition

`EMA_t = alpha * close_t + (1 - alpha) * EMA_(t-1)`, where
`alpha = 2 / (N + 1)` for period `N` — the canonical formula. Uses
`Bar.close` only, exactly like SMA.

### Seed / initialization decision — the central design question

**Chosen: seed with `SMA(N)` of the first `N` closes** (`EMA_N =
mean(close_1..close_N)`), then apply the recursive relationship for every
bar after the seed.

The two standard alternatives and why the seed choice was made,
recorded here in full (also in `ARCHITECTURE_DECISIONS.md` #72):

- **Rejected — seed with the first close (`EMA_1 = close_1`)**: makes
  the entire infinite recursive series permanently sensitive to one
  comparatively noisy observation; the bias decays but never
  structurally vanishes. It also produces a "first EMA value" at bar 1
  that isn't meaningfully a period-`N` value at all — just the raw
  close under a misleading label.
- **Chosen — seed with `SMA(N)`**: the convention used by the
  overwhelming majority of charting platforms and quant libraries,
  giving stable, cross-checkable, widely reproducible results (the
  checkpoint brief's own instruction to prefer this). It also aligns
  naturally with this project's existing SMA foundation (Checkpoint 15)
  and gives EMA the *identical* warm-up length as SMA of the same
  period — a caller who already understands SMA's warm-up rule needs no
  second, different rule for EMA.

**First valid timestamp**: the `N`th bar's own timestamp (the same bar
whose close completes the seed window) — not the first bar's timestamp.
**Warm-up behavior**: identical shape to SMA — the first `N - 1` bars
produce no output at all (not `None`, not a partial average); the `N`th
bar produces the seed value; every bar after that produces one
recursively-computed value. `N` bars in → exactly `N - lookback + 1`
values out, same as SMA.

**Relationship with SMA — deliberately NOT a call dependency.** The seed
*value* (mean of the first `N` closes) is conceptually identical to what
`compute_simple_moving_average` would produce for that window, but
`ema.py` computes it **locally** (`sum(...) / lookback` over the seed
window) rather than calling `sma.compute_simple_moving_average`. Calling
it would couple EMA's seed to SMA's own public output type/versioning —
a future rounding-policy change to SMA would then silently change EMA's
seed too, an action-at-a-distance bug this checkpoint refuses to
introduce. `sma.py` and `ema.py` have no dependency edge on each other;
both depend only on `domain/feature` + `domain/market_data`.

### Stateful computation model

No new abstraction was introduced (no `FeatureStateMachine`, no
`IndicatorFramework`, no `GenericRecursiveEngine`) — the existing
`compute_*(definition, bars) -> tuple[FeatureValue, ...]` functional
shape from Checkpoint 15 was sufficient. The "state" is a single local
`Decimal | None` accumulator (`previous_ema`) carried across one `for`
loop inside a single pure function call — O(1) additional state, O(n)
time, never a global, never persisted between calls. Checkpoint 16
confirms the Checkpoint 15 functional style generalizes to recursive
calculations without needing a stateful class or engine.

### Numeric precision

`alpha` is computed as `Decimal(2) / Decimal(N + 1)` — full `Decimal`
arithmetic throughout (alpha, the seed mean, and every recursive step),
no `float` conversion anywhere, no explicit rounding.

### No-look-ahead guarantee

Holds by construction (the accumulator only ever carries forward
already-computed history) and is tested explicitly, exactly like SMA:
`test_future_bar_does_not_influence_earlier_output`,
`test_modifying_a_future_bar_does_not_change_earlier_ema_values`, and a
Hypothesis property (`test_no_output_uses_future_observations`)
generalizing across arbitrary series/lookbacks.

### Timestamp alignment

Unchanged convention: `FeatureValue.timestamp` equals its source bar's
own timestamp (the bar's CLOSE time). No second timestamp rule was
introduced for EMA.

### Complexity

O(n) in the number of input bars, O(1) additional calculation state —
never a repeated full-window recalculation, never an unnecessary data
structure (a single scalar accumulator, unlike SMA's fixed-size
`deque`).

### Feature identity

`ExponentialMovingAverageDefinition(lookback: int)` — the identical
one-off, single-field pattern as `SimpleMovingAverageDefinition`
(Checkpoint 15 §4), confirming that pattern scales to a second feature
without needing a registry. `feature_name` is `ema_{lookback}` (`"ema_5"`,
`"ema_10"`, ...) — the exact worked example `FeatureValue`'s own
Checkpoint 5 docstring already gave.

### Feature version

Reuses the existing `FEATURE_ENGINE_VERSION` ("v1") — no second
versioning system was introduced. It is still the feature-engine
implementation's own version, unrelated to `pyproject.toml`'s package
version or the OpenAPI schema version (no API surface exists in this
bounded context).

### No persistence, no API, no frontend, no Dhan

Unchanged from Checkpoint 15's own deferral — none of the three was
added; no live provider was introduced.
