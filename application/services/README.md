# application/services

> New directory added at Checkpoint 8 — see
> [docs/architecture/ARCHITECTURE_DECISIONS.md](../../docs/architecture/ARCHITECTURE_DECISIONS.md)
> for the decision record justifying this addition to the approved
> `application/` layer.

## Responsibility

Use-case services (`RiskConfigurationService`, `UniverseService`,
`StrategyVersionService`) orchestrating calls to the repository Protocol
interfaces in `application/repositories`. Depend only on the Protocol —
never on a concrete (Django-backed) implementation — so each service is
fully testable with an in-memory fake repository (see
`tests/unit/application/services/`). Contains no persistence logic and no
domain business rules of its own; only "not found"/"invalid" translation
between repository results and the application-level exceptions in
`application/services/errors.py`. See
[docs/api/CONFIGURATION_API.md](../../docs/api/CONFIGURATION_API.md).

## Depends On

application/repositories, application/config_schema (records)

## Must Not Depend On

infrastructure (mechanically enforced by `.importlinter` contract #6, adversarially verified at Checkpoint 7 and re-checked at Checkpoint 8), Django, any ORM
