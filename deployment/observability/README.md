# deployment/observability

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Observability stack wiring (metrics/logs/traces export). Tools locked at Checkpoint 3: structlog (logs), Prometheus (metrics), OpenTelemetry SDK wired in with backend deferred, Sentry (errors) — see [TECHNOLOGY_MAPPING.md](../../docs/architecture/TECHNOLOGY_MAPPING.md) §11.

## Depends On

control_plane/monitoring, control_plane/structured_logging

## Must Not Depend On

Business logic

