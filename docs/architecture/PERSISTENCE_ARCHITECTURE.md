# PERSISTENCE_ARCHITECTURE.md

Authoritative documentation for the persistence foundation implemented at
**Checkpoint 7**. Companion to [DOMAIN_CONTRACTS.md](DOMAIN_CONTRACTS.md)
(what is persisted) and
[CONFIGURATION_MANAGEMENT.md](CONFIGURATION_MANAGEMENT.md) (where the
persisted values originate).

## 1. Persistence Boundaries

```
domain contracts (Checkpoint 5, technology-neutral)
      ↓ consumed by
application/config_schema (Checkpoint 6, validates raw config -> domain object)
      ↓ consumed by
application/repositories (Checkpoint 7, Protocol interfaces — WHAT persistence must do)
      ↓ implemented by
infrastructure/persistence (Checkpoint 7, Django ORM — HOW it's done)
      ↓ uses
PostgreSQL
```

The domain layer does not know PostgreSQL exists. `application/repositories`
does not know Django exists (its Protocols reference only domain/
application dataclasses). Only `infrastructure/persistence` knows both —
that is its entire purpose. This is mechanically enforced by
`.importlinter` contract #6 (new this checkpoint): **application must not
depend on infrastructure** — verified by an adversarial test during this
checkpoint's validation (an injected `application → infrastructure` import
was confirmed to break the contract, then removed).

## 2. Persisted Domain Concepts — and Why Only These

| Concept | Persisted? | Justification |
|---|---|---|
| `RiskLimits` (via `RiskConfigurationRecord`) | ✅ | Explicitly named in Checkpoint 7 §4; must survive restart to be usable |
| `Universe` | ✅ | Explicitly named; backtest/live parity requires a durable, versioned universe |
| `StrategyVersion` | ✅ | Explicitly named; lineage/reproducibility requires durability |
| `Instrument` | ❌ not yet | No consumer needs a durable instrument master yet — no market-data adapter exists to populate or query it (Checkpoint 5/6 scope). Revisit at the market-data checkpoint. |
| `Bar` / `Quote` (market data) | ❌ | No market-data ingestion exists (explicitly out of scope, §18) |
| `Signal`, `Order`, `Position`, `Trade` | ❌ | No signal/risk/execution engine exists yet to produce them (§18) |
| `FeatureValue` | ❌ | No feature engine exists yet |
| `TradingSession` | ❌ | No session-management service exists yet |

Every other domain dataclass, every `ConfigSchema`/`ConfigFieldSchema`
introspection object, and every transient value object was deliberately
**not** given a table — there is no consumer yet that needs it to survive
a restart (Checkpoint 7 §4).

## 3. Django Models

Six models in `infrastructure/persistence/models.py`, one immutable
"version" table + one mutable "active pointer" table per persisted
concept:

| Version table (immutable) | Active-pointer table (mutable) |
|---|---|
| `RiskConfigurationVersion` | `ActiveRiskConfiguration` |
| `UniverseVersion` | `ActiveUniverse` |
| `StrategyVersionRecord` | `ActiveStrategyVersion` |

**Why split:** activating a different version must never mutate historical
data (Checkpoint 7 §6). The active-pointer tables are the *only* mutable
state in this persistence model — `update_or_create` on a single row keyed
by the configuration's identity. Version tables only ever receive `INSERT`;
no code path calls `.update()` or `.save()` on an existing version row.

**Numeric precision:** `RiskConfigurationVersion`'s three money fields use
`DecimalField(max_digits=14, decimal_places=2)` — `NUMERIC(14,2)` in
PostgreSQL, i.e. INR values up to 999,999,999,999.99 (paise precision).
Chosen as a deliberately reasoned, not copy-pasted, precision: comfortably
covers intraday position-scale money for a single account without
inventing headroom nothing yet justifies.

**JSONB usage:** `UniverseVersion.members` is one `JSONField` (maps to
PostgreSQL `jsonb`) holding `[{"instrument_id": ..., "status": ...}, ...]`,
rather than a related table — a universe is read/written as one atomic
unit already (Checkpoint 5's `Universe.members` is one immutable tuple),
and no consumer needs to query individual members at the SQL level yet.

**Database-level constraints** (Checkpoint 7 §11 — persistence invariants,
distinct from domain invariants):

| Model | Constraint | Enforces |
|---|---|---|
| `RiskConfigurationVersion` | `UniqueConstraint(risk_configuration_id, version)` | No silent duplicate version |
| `RiskConfigurationVersion` | 3× `CheckConstraint(...__gt=0)` | Backstop against a bypassed domain validation, not a replacement for it |
| `ActiveRiskConfiguration` | `unique=True` on `risk_configuration_id` | Exactly one active pointer per config id |
| `UniverseVersion` | `UniqueConstraint(universe_id, version)` | No silent duplicate version |
| `StrategyVersionRecord` | `UniqueConstraint(strategy_id, specification_version, code_version, configuration_version)` | Matches `StrategyVersion`'s own identity shape |

**Domain invariant vs. persistence invariant, explicitly distinguished**:
positivity of `max_intraday_loss` etc. is enforced first and authoritatively
by `RiskLimits.__post_init__` (domain layer) before a repository ever sees
a value; the database `CheckConstraint` is a second-line-of-defense
backstop, not a re-implementation — it exists only to catch a value that
somehow bypassed the domain layer (e.g. a future raw SQL script), not to
duplicate business logic in SQL. No attempt was made to move *every*
domain invariant into SQL (Checkpoint 7 §11 explicitly warns against this).

## 4. Repository Interfaces

Three `typing.Protocol` interfaces in `application/repositories/__init__.py`
— `RiskConfigurationRepository`, `UniverseRepository`,
`StrategyVersionRepository` — created because the application layer
genuinely needs configuration state to survive a restart, and because the
persistence technology must remain swappable without touching application
or domain code. No repository was created for a concept without a real,
current consumer (Checkpoint 7 §7). No Django `Model`, `QuerySet`, or
ORM-specific exception crosses any Protocol method's signature — Django's
`IntegrityError` is caught inside `infrastructure/persistence/repositories.py`
and re-raised as the technology-neutral `DuplicateVersionError`.

## 5. Configuration Persistence — the RiskConfigurationRecord Wrapper

`domain.risk.RiskLimits` (Checkpoint 5) is a pure value object with no
identity or version — the shared kernel is locked to 14 contracts and
identity/versioning was not part of that approved shape. Persistence needs
identity + version + a creation timestamp, so
`application/config_schema/records.py` adds exactly those three fields in
a small **application-layer** wrapper, `RiskConfigurationRecord`, without
modifying the locked domain contract. `Universe` and `StrategyVersion`
already carry their own identity/version fields (Checkpoint 5), so no
equivalent wrapper was needed for them.

## 6. Versioning & Immutability

Every persisted configuration version is treated as an immutable historical
record: `save()` is the only write path on a version table, and it always
`INSERT`s. Changing configuration never overwrites a historical row —
`activate()` only ever writes to the separate, mutable active-pointer
table. A historical configuration therefore remains exactly reconstructable
by `(configuration_id, version)` for as long as its row exists.

## 7. Transaction Boundaries

The domain layer never manages a transaction — it has no persistence
awareness at all. `infrastructure/persistence/repositories.py`'s
`activate()` methods wrap a read-then-write (verify the version exists,
then upsert the active pointer) in `django.db.transaction.atomic()`,
preventing a torn state where the pointer is updated to a version that
turns out not to exist. `save()` is a single `INSERT` and does not need an
explicit atomic block (already atomic at the statement level). No
distributed transaction exists or is needed (Checkpoint 7 §14).

## 8. Concurrency

`activate()`'s read-then-write is wrapped in `transaction.atomic()` but
does **not** use `select_for_update()` row locking — activation is a rare,
operator-driven action (not a hot path), so speculative row-locking would
be over-engineering for a concurrency scenario with no realistic contention
yet (Checkpoint 7 §15). Duplicate-version creation is prevented by the
database `UniqueConstraint` itself (translated to `DuplicateVersionError`),
which is a simpler and sufficient mechanism for the "two operators save the
same version simultaneously" race than application-level locking would be.

## 9. PostgreSQL Testing Strategy

**Resolved at this checkpoint** (Checkpoint 4's SQLite exception is now
retired): `settings/testing.py` uses the same PostgreSQL configuration as
`settings/base.py` — no SQLite anywhere in that file anymore. Consequence:
any test using Django's `db`/`django_db` fixture requires a real, reachable
PostgreSQL instance.

Tests that need it are decorated with **both** `@pytest.mark.django_db`
**and** `@requires_postgres` (`tests/postgres_utils.py`) — a `skipif`
evaluated at **collection time**, before pytest-django would attempt
session-level test-database creation. This means an unreachable PostgreSQL
server produces a clean, individually-reported "skipped" result for the
affected tests, not a hard session-wide failure that would also break
unrelated pure-Python tests (domain contracts, config schema — none of
which ever touch a database connection).

**A real, generalizable fix was made during this checkpoint**: psycopg has
no default connection timeout, so an unreachable PostgreSQL host caused
`manage.py makemigrations`'s own migration-history consistency check (and
any other DB-touching command) to hang indefinitely rather than fail fast.
Fixed by adding `OPTIONS: {"connect_timeout": 5}` (configurable via
`POSTGRES_CONNECT_TIMEOUT`) to `settings/base.py`'s `DATABASES` — a
permanent production-safety improvement (fail fast on an unreachable DB),
not merely a workaround for this checkpoint's validation environment.

## 10. Migration Strategy

- `manage.py makemigrations persistence` generates
  `infrastructure/persistence/migrations/0001_initial.py` — validated to
  match the current models (`makemigrations --check --dry-run` reports "No
  changes detected").
- `manage.py migrate --plan` and an actual `migrate` **require a live
  PostgreSQL connection** and were **not run successfully** in this
  environment — no PostgreSQL server is available (confirmed absent since
  Checkpoint 4). This is reported honestly, not faked; see taskReport.md's
  Checkpoint 7 section for the exact commands attempted and their results.
- In CI (GitHub Actions, real Postgres service container), both
  `makemigrations --check` and the full persistence test suite (including
  `migrate`-dependent `django_db` tests) run for real, not skipped.

## 11. Future API Mapping (identified, not built)

Per Checkpoint 7 §20, the following are flagged as future work, not
implemented now:

- **Resources needing API exposure eventually**: active risk configuration
  (read), active universe (read), active strategy version (read), version
  history for each (read), an "activate version" write endpoint per
  concept (write, requires the AI/operator governance gate from Checkpoint
  2 §11 to decide who may call it).
- **Read models**: a combined "current configuration snapshot" read model
  (active risk + active universe + active strategy versions in one
  response) is a plausible first API resource — cheaper to build once
  `application/contracts` exists than three separate calls.
- **Safe-for-frontend operations**: reading active/historical configuration
  is safe to expose broadly; *activating* a version should be gated behind
  the same operator-role authorization Checkpoint 3 §12 already specified
  for AI-proposal approval — not exposed to an unauthenticated or
  read-only frontend role.

No `application/contracts` entry, DRF serializer, or view was created this
checkpoint — this section is documentation of future work only.
