# signal_intelligence/signal_verification

> Checkpoint 19: first real implementation. See
> [docs/architecture/SIGNAL_VERIFICATION_ARCHITECTURE.md](../../docs/architecture/SIGNAL_VERIFICATION_ARCHITECTURE.md)
> for the full contract.

## Responsibility

Evaluates whether an already-generated `DirectionalIndication`
(`signal_intelligence/signal_generation`, Checkpoint 18) was
subsequently supported by actual market-price movement — a
deterministic, single-point price comparison at an explicit horizon.

**Not yet implemented** (this checkpoint's real code, `src/intraday/
signal_intelligence/signal_verification/`, does not yet do this): the
original placeholder responsibility — "verifies realized signal outcomes
against theoretical expectation... compares `domain/signal`'s original
prediction against `signal_intelligence/theoretical_outcome`'s idealized
MFE/MAE/conditional expectancy" — remains this bounded context's
eventual full responsibility, once `domain.signal.Signal` itself can be
honestly produced (needs `trading_engine/strategy_execution`) and
`signal_intelligence/theoretical_outcome` (MFE/MAE/path analysis) exists.
Checkpoint 19 explains this gap explicitly — see the architecture doc
above.

## Depends On

`signal_intelligence/signal_generation` (`DirectionalIndication`) —
documented, deliberate intra-bounded-context reuse, not a `domain/`
dependency (see the architecture doc's promotion assessment).
`domain/market_data` (`Bar`), `domain/shared_kernel`.

## Must Not Depend On

`domain/signal`, `domain/strategy`, `signal_intelligence/theoretical_outcome`,
`signal_intelligence/feature_engine`, execution concerns, `trading_engine`,
infrastructure, Django, any broker.
