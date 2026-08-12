# config/strategies

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Strategy parameter configuration instances validated against application/config_schema; never duplicated ad hoc in frontend (Rule 13). **Implemented at Checkpoint 6:** `example.yaml` validates only the version/lineage/maturity shape (`domain.strategy.StrategyVersion`) via `application/config_schema/strategy.py` — strategy *parameters* (indicator periods etc.) have no domain contract yet and are intentionally absent. See [CONFIGURATION_MANAGEMENT.md](../../docs/architecture/CONFIGURATION_MANAGEMENT.md).

## Depends On

application/config_schema

## Must Not Depend On

Strategy implementation code

