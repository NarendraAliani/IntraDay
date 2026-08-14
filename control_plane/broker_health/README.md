# control_plane/broker_health

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Tracks broker connectivity/API health independent of any single broker (Rule 5.3).

## Depends On

domain/broker

## Must Not Depend On

Concrete broker SDKs directly

## Checkpoint 22 update

A narrower predecessor now exists:
`ProviderConnectionStatus` (`infrastructure/persistence/models.py`) and
`infrastructure/api/settings_views.py`'s "Test Connection"/status
endpoints track Dhan/Telegram/Discord connectivity status per-provider,
driven by explicit user action (not continuous health monitoring). This
is not yet the domain/broker-abstracted, continuously-monitored health
tracking this README describes — that remains deferred. See
[SETTINGS_ARCHITECTURE.md](../../docs/architecture/SETTINGS_ARCHITECTURE.md)'s
"Connection status model" section.

