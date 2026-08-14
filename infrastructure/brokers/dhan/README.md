# infrastructure/brokers/dhan

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Initial broker integration (implementation deferred to Checkpoint 8 per the roadmap). Must implement domain/broker contract only — see [TECHNOLOGY_MAPPING.md](../../../docs/architecture/TECHNOLOGY_MAPPING.md) §7 for the broker-abstraction layering and auth/order/reconciliation mapping this adapter must satisfy.

## Depends On

domain/broker

## Must Not Depend On

Other bounded contexts' internals

## Checkpoint 22 update

`src/intraday/infrastructure/brokers/dhan/client.py` now implements a
minimal, **read-only** connectivity client (`check_dhan_connectivity()`)
— NOT the full `domain.broker.BrokerGateway` contract this README
describes above, which remains deferred until order-placement is
authorized. See
[PROVIDER_CONNECTIVITY_ARCHITECTURE.md](../../../docs/architecture/PROVIDER_CONNECTIVITY_ARCHITECTURE.md)
for the client's scope, the exact endpoint used
(`GET /v2/profile`), and status-mapping details.

