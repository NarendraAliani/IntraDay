# deployment/environments

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Environment topology definitions (development/testing/staging-paper/production, each with its own `TRADING_MODE` and credential set — see [TECHNOLOGY_MAPPING.md](../../docs/architecture/TECHNOLOGY_MAPPING.md) §14). Docker/docker-compose locked as the mechanism; a dedicated IaC tool (Terraform etc.) remains an explicitly deferred, non-blocking choice.

## Depends On

config/environments

## Must Not Depend On

Business logic

