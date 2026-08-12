# CONFIGURATION_MANAGEMENT.md

Authoritative documentation for the configuration-management layer
implemented at **Checkpoint 6**. Companion to
[DOMAIN_CONTRACTS.md](DOMAIN_CONTRACTS.md) (the contracts configuration
validates against) and
[TECHNOLOGY_MAPPING.md](TECHNOLOGY_MAPPING.md) §13 (the four-way
configuration taxonomy this checkpoint implements one quadrant of).

## 1. The Five Things This Checkpoint Keeps Separate

| Concept | Answers | Where it lives | Implemented this checkpoint? |
|---|---|---|---|
| **Domain Contracts** | What the system *is* | `src/intraday/domain/*/contracts.py` (Checkpoint 5) | No — consumed, not changed |
| **Configuration** | What the system is configured *to do* | `config/*.yaml` (data) | ✅ Yes (3 example instances) |
| **Application Schema** | How configuration is *validated* | `src/intraday/application/config_schema/*.py` | ✅ Yes |
| **Runtime Settings** | Environment/runtime operational settings | `src/intraday/settings/*.py` (Checkpoint 4) | No — untouched |
| **Secrets** | Credentials and sensitive values | Environment variables / `.env` (Checkpoint 3 §12) | No — untouched |

These five were never collapsed. In particular: `application/config_schema`
validates *trading parameter* configuration only — it has no opinion on
Django settings modules, and it never reads an environment variable
directly (no secret ever flows through this layer).

## 2. The Pipeline (implemented)

```
config/{risk,universe,strategies}/*.yaml   (configuration DATA)
        ↓  loader.py: load_yaml_config()   (generic YAML → dict, no domain knowledge)
        ↓  {risk,universe,strategy}.py: load_*()   (dict → validated domain contract)
        ↓
domain.risk.RiskLimits / domain.universe.Universe / domain.strategy.StrategyVersion
```

`schema.py`'s `build_schema_for()` is the mechanism that guarantees Rule
13 ("never redefine a parameter independently of its domain contract"):
every `ConfigSchema` is derived by **introspecting the domain dataclass's
own fields** via `dataclasses.fields()` — no schema module hand-lists a
field name or type. If `domain.risk.RiskLimits` gains or loses a field,
`RISK_LIMITS_SCHEMA` changes automatically on the next import; nothing in
`risk.py` needs editing to stay in sync (only the loader's explicit
keyword-argument construction would need a matching update, which a
`mypy --strict` run makes structurally hard to forget).

**Validation is never duplicated.** `load_risk_limits()` etc. coerce raw
YAML values into the right Python types (string → `Decimal`, string →
`Exchange`/`Enum`) and then construct the real domain dataclass — every
invariant (positivity, required-reason-on-rejection, etc.) is enforced
exactly once, inside the domain contract's own `__post_init__`
(Checkpoint 5). The config layer only adds *source* context
(`ConfigValidationError` wraps the domain exception with a file/field
label) — it never re-implements *what* is invalid.

## 3. What Was Implemented

| Domain contract | Schema module | Loader function | Example instance |
|---|---|---|---|
| `domain.risk.RiskLimits` | `application/config_schema/risk.py` | `load_risk_limits()` | `config/risk/default.yaml` |
| `domain.universe.Universe` | `application/config_schema/universe.py` | `load_universe()` | `config/universe/example.yaml` |
| `domain.strategy.StrategyVersion` | `application/config_schema/strategy.py` | `load_strategy_version()` | `config/strategies/example.yaml` |

All three example YAML instances are loaded and validated end-to-end by
`tests/unit/application/config_schema/test_loader_end_to_end.py` — proving
the full `config/*.yaml → domain contract` pipeline works against real
committed files, not only synthetic test dicts.

## 4. What Was Deliberately NOT Implemented

- **Strategy parameters** (e.g. indicator periods, entry/exit thresholds).
  No domain contract models them yet — Checkpoint 5 implemented only
  `StrategyIdentity`/`StrategyVersion`/`StrategyMaturityState`, not a
  parameter set. `config/strategies/example.yaml` therefore configures
  only the version/lineage/maturity shape. Inventing a generic
  "parameters" schema now would violate the "don't invent fields not
  justified by current requirements" rule carried forward from
  Checkpoint 5.
- **`config/broker`, `config/environments`** — untouched. Broker
  configuration needs `domain.broker` consumers that don't exist yet
  (no broker adapter); environment configuration is already handled by
  the Django settings modules (Checkpoint 4).
- **Persistence of configuration instances** — example instances are
  static YAML files, not database rows. `infrastructure/persistence`
  (not yet implemented) will eventually store *runtime-editable* config
  instances (Checkpoint 3 §13's "runtime configuration" category); the
  YAML files here are closer to that quadrant's file-based bootstrap
  equivalent, not a long-term storage decision.
- **Frontend config forms** — no `application/contracts` (API) exposure
  and no generated TypeScript types exist for these schemas yet. The
  `ConfigSchema`/`ConfigFieldSchema` types are structured precisely so a
  future OpenAPI/form-generation step can consume them, but that
  generation step itself is not built.
- **Runtime config reload / hot-swap** — loaders are called once,
  synchronously; no file-watching or cache-invalidation exists.

## 5. Architecture Compliance

- `application/config_schema` depends only on `domain.*` and the stdlib
  `yaml` library — no Django, Celery, Redis, or broker import.
  `.importlinter`'s layering contract (`application` → bounded contexts →
  `domain`) already permits and expects this direction; no contract was
  modified.
- `import-linter`: still **5/5 kept, 0 broken** after this checkpoint's
  code was added (81 files analyzed, up from 72).
