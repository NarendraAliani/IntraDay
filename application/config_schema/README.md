# application/config_schema

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Schema definitions strategies/config/risk parameters are declared against, enabling dynamic frontend form generation instead of hard-coded duplicate definitions (Rule 13).

**API contract vs. config schema, clarified at Checkpoint 2 (Section 8):**
this is a specialized subset of `application/contracts` — specifically the
schemas for *user-configurable* parameter surfaces (strategy parameters, risk
limits), not general request/response shapes. A config schema entry must
derive its field definitions from the corresponding `domain/strategy` or
`domain/risk` contract (never redefine a parameter's type/range independently)
so a single edit to the domain contract propagates to both the config
instances in `config/` and the generated frontend form.

**Implemented at Checkpoint 6:** `src/intraday/application/config_schema/`
— schema derivation (`schema.py`, introspects domain dataclasses, never
hand-lists fields), and loaders for `RiskLimits`, `Universe`, and
`StrategyVersion`. See
[docs/architecture/CONFIGURATION_MANAGEMENT.md](../../docs/architecture/CONFIGURATION_MANAGEMENT.md).

**Extended at Checkpoint 7:** `records.py` adds `RiskConfigurationRecord`
— a small application-layer versioning envelope (identity + `Version` +
`RiskLimits` + timestamp) needed to persist `RiskLimits`, which itself has
no identity/version (the locked domain contract was not modified). See
[docs/architecture/PERSISTENCE_ARCHITECTURE.md](../../docs/architecture/PERSISTENCE_ARCHITECTURE.md).

## Depends On

domain/strategy, domain/risk, domain/universe

## Must Not Depend On

Hard-coded frontend forms

