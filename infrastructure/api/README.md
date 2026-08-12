# infrastructure/api

> New directory added at Checkpoint 8 — see
> [docs/architecture/ARCHITECTURE_DECISIONS.md](../../docs/architecture/ARCHITECTURE_DECISIONS.md)
> for the decision record justifying this addition to the approved
> `infrastructure/` layer.

## Responsibility

The HTTP delivery adapter: DRF views and URL routing exposing
`application/services` over HTTP at `/api/v1/config/`. Placed under
`infrastructure/`, not `application/`, because composing a concrete
(Django-backed) repository with an application service requires importing
`infrastructure.persistence` — something `application` itself must never
do (`.importlinter` contract #6). An HTTP API is a delivery mechanism (a
"driving adapter"), the same category as `infrastructure/persistence`
(a "driven adapter") or a future `infrastructure/brokers` adapter — all
allowed to depend on `application`, never the reverse. Views here never
query Django models directly, never contain persistence logic, and never
contain domain business rules — only request/response translation and
error mapping. See
[docs/api/CONFIGURATION_API.md](../../docs/api/CONFIGURATION_API.md).

## Depends On

application/services, application/contracts, application/repositories (exception types only), infrastructure/persistence (composition — the only place in this codebase infra composes itself with application services for HTTP delivery)

## Must Not Depend On

Domain directly (always goes through application/services); must never leak a Django exception, SQL error, stack trace, or table name into an HTTP response (see infrastructure/api/errors.py)
