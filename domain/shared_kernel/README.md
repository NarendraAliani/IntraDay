# domain/shared_kernel

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Common value objects used across every domain: money, price, quantity, timeframe, timestamps, enumerations, identifiers. Prevents duplicate primitive definitions.

**Added at Checkpoint 2:** generic version/lineage identifiers (e.g. a
`Version` value object usable for code_version, strategy_version,
config_version, dataset_version, universe_version, backtest_engine_version)
and a generic `parent_reference` id shape. These exist here — instead of as
part of a full `domain/experiment` contract — because `research/experiments`,
`trading_engine/strategy_registry`, and `control_plane/audit` all need to
stamp/compare version identifiers without needing the full Experiment
aggregate. The full Experiment record (hypothesis, dataset/universe/backtest
lineage, decision) is owned exclusively by `research/experiments`.

## Depends On

Nothing

## Must Not Depend On

Any bounded context

