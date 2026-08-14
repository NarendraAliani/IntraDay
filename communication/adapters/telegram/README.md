# communication/adapters/telegram

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Telegram Bot API adapter (implementation deferred to a future checkpoint; interface only so far). Runs within the locked Django/Celery stack (dispatched as a Celery task against `communication/contracts`) — see [TECHNOLOGY_MAPPING.md](../../../docs/architecture/TECHNOLOGY_MAPPING.md) §2, §5.

## Depends On

communication/contracts

## Must Not Depend On

Trading logic

## Checkpoint 22 update

`src/intraday/communication/adapters/telegram/client.py` now implements
a minimal client: `check_telegram_connectivity()` (Bot API `getMe`) and
`send_telegram_test_message()` (`sendMessage`) — connectivity checking
and an explicit test message only, not a general notification-routing
adapter. See
[PROVIDER_CONNECTIVITY_ARCHITECTURE.md](../../../../docs/architecture/PROVIDER_CONNECTIVITY_ARCHITECTURE.md).

