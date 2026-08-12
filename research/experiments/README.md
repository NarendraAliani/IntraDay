# research/experiments

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Sole owner of the full canonical Experiment contract (Section 9) — moved here
from `domain/experiment` at Checkpoint 2 because it is a research-lifecycle
concept, not something signal_intelligence or trading_engine ever construct
(see [ARCHITECTURE_DECISIONS.md](../../docs/architecture/ARCHITECTURE_DECISIONS.md) #11).
An Experiment record holds: experiment_id, parent_experiment_id (self-referential,
forms the lineage DAG), hypothesis reference, one-change-per-iteration
description, configuration/dataset/universe/strategy/code/backtest-engine
version identifiers (using `domain/shared_kernel`'s generic version
primitive), results reference, analysis/observations, and decision
(promote/reject/iterate). Other bounded contexts that need to reference an
experiment (e.g. `trading_engine/strategy_registry` recording which
experiment justified a promotion, or `control_plane/audit` tracing production
strategy provenance) store only the `experiment_id` — never a copy of the
full record.

## Depends On

domain/shared_kernel (version/lineage primitives), domain/strategy, research/hypotheses, research/strategy_specifications

## Must Not Depend On

Live systems

