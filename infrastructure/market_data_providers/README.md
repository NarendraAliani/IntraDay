# infrastructure/market_data_providers

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Concrete market-data feed adapters implementing domain/market_data contracts. Dhan's feed is the confirmed live source at launch (`infrastructure/market_data_providers/dhan`, not yet implemented); the architecture requires Dhan never be the canonical owner of market-data semantics — see [TECHNOLOGY_MAPPING.md](../../docs/architecture/TECHNOLOGY_MAPPING.md) §6. Additional/historical vendors remain an open, non-blocking choice.

## Depends On

domain/market_data

## Must Not Depend On

Strategy logic

