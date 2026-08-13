# signal_intelligence/signal_generation

> Checkpoint 18: first real implementation. See
> [docs/architecture/SIGNAL_GENERATION_ARCHITECTURE.md](../../docs/architecture/SIGNAL_GENERATION_ARCHITECTURE.md)
> for the full contract.

## Responsibility

Interprets already-computed feature state (SMA/EMA/ATR `FeatureValue`s,
from `signal_intelligence/feature_engine`) into a deterministic
`DirectionalIndication` (`BULLISH`/`BEARISH`/`NEUTRAL`) — the smallest
correct building block between feature computation and a future trading
decision.

**Not yet implemented** (this checkpoint's real code, `src/intraday/
signal_intelligence/signal_generation/`, does not produce
`domain.signal.Signal`): "converts strategy output into canonical
Signal objects" remains this bounded context's eventual full
responsibility, once `trading_engine/strategy_execution` exists to
supply a real `strategy_id`. Checkpoint 18 explains this gap explicitly
— see the architecture doc above.

## Depends On

`domain/feature` (`FeatureValue`), `domain/market_data` (`Bar`),
`domain/shared_kernel`. Deliberately does **not** depend on
`signal_intelligence/feature_engine` — feature computation and signal
interpretation are kept architecturally separate (only
`application/services/signal_generation.py` composes both, at the
orchestration layer).

## Must Not Depend On

`domain/strategy`, `domain/signal` (not yet — see above), Risk engine,
order management, `signal_intelligence/feature_engine`, infrastructure,
Django, any broker.
