# signal_intelligence/theoretical_outcome

> Checkpoint 21: first real implementation. See
> [docs/architecture/SIGNAL_THEORETICAL_OUTCOME_ARCHITECTURE.md](../../docs/architecture/SIGNAL_THEORETICAL_OUTCOME_ARCHITECTURE.md)
> for the full contract.

## Responsibility

Measures maximum favorable/adverse price excursion (MFE/MAE) — what
price objectively did after a `DirectionalIndication`
(`signal_intelligence/signal_generation`, Checkpoint 18) — over an
explicit future observation window. An objective price-path
measurement, never a profitability/trading-policy claim.

**Not yet implemented** (this checkpoint's real code, `src/intraday/
signal_intelligence/theoretical_outcome/`, does not do this): the
original placeholder responsibility — "computes theoretical signal
outcome metrics: MFE, MAE, **conditional expectancy**" against
`domain/signal` — remains partially deferred. MFE/MAE are implemented
this checkpoint; **conditional expectancy is explicitly NOT
implemented** — it requires a defined trading policy (entry/exit/
position-size/costs) this bounded context has no authority to invent.
See the architecture doc's own section on why, and which future bounded
context should own it.

## Depends On

`signal_intelligence/signal_generation` (`DirectionalIndication`) —
documented, deliberate intra-bounded-context reuse, not a `domain/`
dependency. `domain/market_data` (`Bar`, `ensure_chronological`,
`timeframe_to_timedelta`), `domain/shared_kernel`.

**Deliberately does NOT depend on** `signal_intelligence/signal_verification`
or `signal_intelligence/signal_lifecycle` — evaluated explicitly and
kept independent (see the architecture doc's relationship sections).

## Must Not Depend On

`domain/signal`, `domain/strategy`, `signal_intelligence/signal_verification`,
`signal_intelligence/signal_lifecycle`, `signal_intelligence/feature_engine`,
execution concerns, `trading_engine`, infrastructure, Django, any
broker.
