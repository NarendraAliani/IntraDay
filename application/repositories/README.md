# application/repositories

> New directory added at Checkpoint 7 — see
> [docs/architecture/ARCHITECTURE_DECISIONS.md](../../docs/architecture/ARCHITECTURE_DECISIONS.md)
> for the decision record justifying this addition to the approved
> `application/` layer.

## Responsibility

Repository/application interfaces (`typing.Protocol`) mediating between
the application layer and `infrastructure/persistence`. Three interfaces
exist — `RiskConfigurationRepository`, `UniverseRepository`,
`StrategyVersionRepository` — one per persisted configuration concept
(Checkpoint 7). No repository was created for a concept without a real,
current consumer. Implementations live in
`infrastructure/persistence/repositories.py` and are never imported here
— this directory defines the interface, infrastructure implements it
(dependency inversion). See
[PERSISTENCE_ARCHITECTURE.md](../../docs/architecture/PERSISTENCE_ARCHITECTURE.md).

## Depends On

domain/strategy, domain/universe, application/config_schema (RiskConfigurationRecord)

## Must Not Depend On

infrastructure (mechanically enforced by `.importlinter` contract #6 — adversarially verified during Checkpoint 7's validation), Django, any ORM, any concrete persistence technology
