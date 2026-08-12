# infrastructure/messaging

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Concrete internal messaging/queue technology connecting bounded contexts. Locked at Checkpoint 3: Celery with Redis as broker + result backend for async/background jobs, Celery Beat for scheduled tasks, Redis Pub/Sub for live tick fan-out — see [TECHNOLOGY_MAPPING.md](../../docs/architecture/TECHNOLOGY_MAPPING.md) §5. RabbitMQ/Kafka evaluated and explicitly rejected as unjustified at this platform's scale.

## Depends On

domain/shared_kernel

## Must Not Depend On

Strategy logic

