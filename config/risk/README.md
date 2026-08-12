# config/risk

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Risk limit configuration instances validated against domain/risk contracts. **Implemented at Checkpoint 6:** `default.yaml` is an example instance loaded/validated via `application/config_schema/risk.py` — see [CONFIGURATION_MANAGEMENT.md](../../docs/architecture/CONFIGURATION_MANAGEMENT.md). Values are illustrative placeholders, not an approved production risk policy.

## Depends On

domain/risk

## Must Not Depend On

Strategy-specific overrides bypassing risk engine

