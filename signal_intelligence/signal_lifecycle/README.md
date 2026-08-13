# signal_intelligence/signal_lifecycle

> Checkpoint 20: first real implementation. See
> [docs/architecture/SIGNAL_LIFECYCLE_ARCHITECTURE.md](../../docs/architecture/SIGNAL_LIFECYCLE_ARCHITECTURE.md)
> for the full contract.

## Responsibility

Manages the temporal-validity state of a `DirectionalIndication`
(`signal_intelligence/signal_generation`, Checkpoint 18) as time
progresses — a two-state model (`ACTIVE`/`EXPIRED`), an explicit expiry
policy, and deterministic, immutable transitions.

**Not yet implemented** (this checkpoint's real code, `src/intraday/
signal_intelligence/signal_lifecycle/`, does not do this): the original
placeholder responsibility — "manages signal state transitions and
expiry" against `domain/signal` — remains this bounded context's
eventual full responsibility once `domain.signal.Signal` itself can be
honestly produced. Checkpoint 20 explains this gap explicitly, following
the same resolution pattern Checkpoints 18 and 19 already established.

## Depends On

`signal_intelligence/signal_generation` (`DirectionalIndication`) —
documented, deliberate intra-bounded-context reuse, not a `domain/`
dependency. `domain/market_data` (`timeframe_to_timedelta`),
`domain/shared_kernel`.

**Deliberately does NOT depend on** `signal_intelligence/signal_verification`
— lifecycle (temporal validity) and verification (outcome correctness)
are orthogonal questions, evaluated independently (see the architecture
doc's "VerificationResult Relationship" section).

## Must Not Depend On

`domain/signal`, `domain/strategy`, `signal_intelligence/signal_verification`,
`signal_intelligence/feature_engine`, execution concerns,
`trading_engine`, infrastructure, Django, any broker, order/broker
concerns.
