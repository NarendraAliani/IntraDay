# Signal Lifecycle

Checkpoint 20. Establishes the first technology-neutral state model for
a `DirectionalIndication`'s (Checkpoint 18) temporal validity as time
progresses. This checkpoint is intentionally small — state, transition,
expiry, temporal validity only. Not a trading strategy, order execution,
broker integration, position/risk/portfolio management, MFE/MAE, or
persistence.

```
Market Data → Feature Engine → SMA/EMA/ATR → DirectionalIndication
                                                      ↓
                                    ┌─────────────────┴─────────────────┐
                                    ↓                                   ↓
                          Signal Verification                 Signal Lifecycle
                          (outcome correctness)                (temporal validity)
                          SUPPORTED/NOT_SUPPORTED/               ACTIVE/EXPIRED
                          INCONCLUSIVE
```

Verification and lifecycle are siblings, not a chain — see
"VerificationResult Relationship" below.

## Lifecycle responsibility

`signal_intelligence/signal_lifecycle/README.md` (Checkpoint 1) named
the future, full responsibility: "manages signal state transitions and
expiry" against `domain/signal`. That depends on the strategy-level
`Signal` (still unbuilt — Checkpoints 18/19 explained why). Checkpoint 20
is, like both prior checkpoints, an intentionally smaller, earlier-stage
building block: the temporal validity of a `DirectionalIndication`, not
a strategy-level signal's full lifecycle.

## State model — why ACTIVE/EXPIRED, not CREATED/ACTIVE/EXPIRED

**`CREATED` was considered and rejected.** A `DirectionalIndication`
already carries its own creation instant (`timestamp`, Checkpoint 18).
Introducing a separate lifecycle `CREATED` state would either duplicate
that instant under a second name, or imply a distinct real-world
condition ("created but not yet active") that nothing in this system's
current scope produces — unlike a future `Order` (which genuinely has a
PENDING-then-risk-approved gate), no approval or staging step exists
between an indication being generated and its lifecycle beginning. A
lifecycle begins directly in `ACTIVE`, computed purely from the
indication's own `timestamp`, an explicit `expires_at`, and the instant
being evaluated (`as_of`). This is the smallest honest model for what
this system actually does today, not an arbitrary simplification.

**`VERIFIED` was considered and rejected** — see "VerificationResult
Relationship" below.

`SignalLifecycleState` is exactly two values: `ACTIVE`, `EXPIRED`.

## State transition rules

State is a **pure function** of `(expires_at, as_of)`:

```
as_of <  expires_at  -> ACTIVE
as_of >= expires_at  -> EXPIRED
```

A half-open validity interval `[signal_timestamp, expires_at)` — the
exact instant `expires_at` itself already counts as `EXPIRED`, not the
last active instant. Tested at the exact boundary (one microsecond
before/at/after).

`create_lifecycle(indication, expires_at, as_of)` begins a lifecycle.
`advance_lifecycle(lifecycle, as_of)` re-evaluates an existing lifecycle
at a later instant, returning a **new**, immutable `SignalLifecycle` —
never mutating the original.

## Illegal transitions

Because state is a pure function of `(expires_at, as_of)`, once
`as_of >= expires_at`, every later (larger) `as_of` remains
`>= expires_at` too — `EXPIRED -> ACTIVE` is **structurally impossible**
through forward-moving time, without needing an explicit transition
table to forbid it. The one thing that CAN illegitimately produce it is
a caller passing an earlier `as_of` than a lifecycle's own last-evaluated
`as_of` (rewinding time) — `advance_lifecycle()` rejects this with
`NonMonotonicTimeError`. This unifies "illegal transition" with "no
time-travel," which is a stronger, more general guarantee than a
hand-written state-transition table would give.

## Idempotency

`as_of == lifecycle.as_of` (no time has passed) is explicitly **allowed**
and idempotent — re-evaluating "now" again always returns an equal
`SignalLifecycle`. `ACTIVE -> ACTIVE` and `EXPIRED -> EXPIRED` (advancing
forward without crossing the boundary) are both ordinary, allowed
no-ops — not special-cased, since they fall out naturally from the pure
state function.

## Expiry semantics — no magic default

`create_lifecycle()` requires `expires_at: datetime` as an **explicit**
argument — no `DEFAULT_EXPIRY`/`DEFAULT_EXPIRY_MINUTES` constant exists
anywhere in this module. Nothing in this project's existing architecture
establishes a universal expiry policy (no strategy has been built yet to
define "how long should a directional read stay meaningful" — that is a
strategy-level/research decision, not this checkpoint's to invent).

`compute_expiry_from_bars(indication, lifetime_bars)` is an **optional**
convenience helper for the common "N bars from signal time" case, built
on the already-existing `timeframe_to_timedelta()` (Checkpoint 14) — bar-
count-relative expiry stays meaningful across every `Timeframe` this
project supports without a second, timeframe-specific magic number, the
same reasoning `horizon_bars` (Checkpoint 19) already established. It is
never called implicitly — a caller must explicitly choose to use it, or
compute `expires_at` any other way (e.g. a session close time, once
session-aware expiry is built).

`expires_at` must be strictly after `indication.timestamp`
(`InvalidExpiryError` otherwise) — a validity window that ends before it
begins is not legitimate. Creating a lifecycle where `as_of` is already
past `expires_at` (e.g. replaying historical data) is explicitly
**legitimate** — it simply begins life already `EXPIRED`, not an error.

## Market-time vs. wall-clock time — explicitly deferred

This checkpoint's expiry model uses wall-clock/bar-duration time only
(`timeframe_to_timedelta()` × N, or any caller-supplied `datetime`). No
trading-session-aware expiry (e.g. "expires at session close, whichever
comes first") is implemented — `domain.session.TradingSession` exists
but this checkpoint does not reach for it, since doing so correctly
would require deciding how session boundaries interact with expiry, a
decision with no existing architectural precedent to build from
honestly. Deferred, not faked.

## Temporal / timezone semantics

Every lifecycle timestamp (`signal_timestamp`, `expires_at`, `as_of`) is
validated by `ensure_utc()` (Checkpoint 3/5's own established
convention) — a naive or non-UTC-offset datetime is rejected outright,
never silently converted. No second time-normalization mechanism was
introduced.

## DirectionalIndication relationship

`SignalLifecycle` embeds the full source `indication` directly (full
provenance, same convention as `VerificationResult`), and additionally
carries flat `instrument_id`/`timeframe`/`signal_timestamp` fields for
direct accessibility — validated at construction to always match the
embedded indication's own values (a lifecycle can never be detached from
or inconsistent with its source indication).

## VerificationResult relationship — explicitly orthogonal

**`VERIFIED` is NOT a lifecycle state, and `signal_lifecycle` does not
import `signal_verification` at all** (mechanically enforced — see
Architecture Enforcement below).

`VerificationResult` (Checkpoint 19) answers "was the directional call
subsequently supported by price movement?" — a fact about **outcome**.
`SignalLifecycle` answers "is this indication still temporally valid
right now?" — a fact about **validity/staleness**. These are genuinely
orthogonal questions with independent answers:

- An indication can be `EXPIRED` and never verified at all (nobody
  asked, or the verification horizon hasn't completed).
- An indication can be `ACTIVE` and already `SUPPORTED` (verification's
  own horizon and lifecycle's own expiry are two independently-chosen
  parameters — verification can complete before expiry).
- Any other combination is equally valid.

Collapsing them into one enum would force every consumer of lifecycle
state to also depend on verification even when it has no reason to (a
caller that only needs "is this still fresh?" would be forced to also
retrieve/compute a `VerificationResult` it doesn't need) — and vice
versa. Keeping them independent means each can be tested, reasoned
about, and consumed without the other.

## Identity & versioning

Structural identity — `(lifecycle_definition_name,
lifecycle_definition_version, instrument_id, timeframe, signal_timestamp,
expires_at)` — reusing the source indication's own identity components
plus the chosen expiry instant, mirroring `FeatureValue`/
`DirectionalIndication`/`VerificationResult`'s identical convention. No
random UUID. `lifecycle_definition_name = "time_bounded_validity"`,
`lifecycle_definition_version = Version(value="v1")` — reuses the
existing `Version` primitive, kept explicitly distinct from
`DirectionalIndication`'s and `VerificationResult`'s own definition
fields.

## Immutability

`SignalLifecycle` is a frozen dataclass. `create_lifecycle()`/
`advance_lifecycle()` always return a new instance — the source
`indication` and any prior `SignalLifecycle` are never mutated. No
mutable state machine was introduced.

## Transition reason — deliberately not modeled

Expiry has exactly one cause in this checkpoint (time passing
`expires_at`) — a `reason`/taxonomy field would carry zero information
today. Deferred until a second expiry mechanism (e.g. explicit
cancellation) exists to actually distinguish.

## Domain promotion assessment

**Not promoted to `domain/` this checkpoint.** `signal_lifecycle` is now
a *third* submodule of `signal_intelligence` consuming
`DirectionalIndication` (after `signal_generation`, which produces it,
and `signal_verification`, Checkpoint 19). This strengthens the
intra-context reuse pattern but does not change the underlying
assessment: the project's minimum-viable-shared-kernel rule requires a
second **bounded context** (one of the five major divisions), not a
third submodule within the same one. No consumer outside
`signal_intelligence` exists yet. Recommend revisiting the moment a
bounded context outside `signal_intelligence` needs the identical shape.

## Architecture enforcement

`signal_intelligence/signal_lifecycle` imports only `domain/market_data`
(`timeframe_to_timedelta`), `domain/shared_kernel`, and
`signal_intelligence/signal_generation` (for `DirectionalIndication`) —
never `signal_verification`, `trading_engine`, `feature_engine`'s own
compute internals, or infrastructure. Verified two ways: `lint-imports`
(6/6 kept) and a dedicated static-scan architecture test
(`tests/unit/architecture/test_signal_lifecycle_boundaries.py`) that
positively asserts the package's only imports are the documented,
approved set — including the explicit absence of `signal_verification`.

## Application layer — deliberately not built

No `application/services/signal_lifecycle.py` was created this
checkpoint. Every prior signal-intelligence application service existed
to compose a bounded-context's pure function with
`HistoricalMarketDataService` (retrieving bars/features from a
repository). Lifecycle evaluation needs no such retrieval — its only
external input is "the current instant" (`as_of`), which a caller
already has and can pass directly to the pure `create_lifecycle()`/
`advance_lifecycle()` functions. Building an application service with
nothing genuine to orchestrate would be exactly the "application service
merely because previous checkpoints have one" the brief warned against.

## No persistence, no API, no frontend

**None was introduced.** No database model, no DRF endpoint, no OpenAPI
schema change (confirmed: regenerated schema byte-identical in
substance).

## Multi-lifecycle collection operation

`advance_lifecycles()` advances multiple `SignalLifecycle`s to the same
`as_of` in one call — preserves input order, evaluates each
independently (one lifecycle's state can never influence another's,
tested explicitly with a short-lived and a long-lived lifecycle side by
side), never aggregates across instruments/timeframes implicitly.
