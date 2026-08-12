# TECHNOLOGY_MAPPING.md

Authoritative technology-mapping document for the IntraDay platform,
produced at **Checkpoint 3**. It resolves the technology decisions
intentionally deferred at Checkpoints 1–2 and maps them onto the
already-LOCKED architecture in [ARCHITECTURE.md](ARCHITECTURE.md) and
[DOMAIN_BOUNDARIES.md](DOMAIN_BOUNDARIES.md). **No domain boundary changed
to accommodate a technology choice** — every choice below was tested against
the architecture, not the other way around (see §21 Architecture
Compatibility Tests).

No business logic, strategies, indicators, broker calls, order placement,
database business models, or frontend screens are implemented in this
checkpoint. Where a technology bootstrap file is unavoidable in a future
checkpoint, it must follow Rule 14 (filename/path/comment header) from
Checkpoint 1.

---

## 1. Selected Stack (at a glance)

| Layer | Choice |
|---|---|
| Language | Python 3.12 |
| Backend / API | Django + Django REST Framework + Django Channels (ASGI) |
| Dependency management | Poetry |
| Linting/formatting | Ruff |
| Static typing | mypy (strict mode) |
| System-of-record database | PostgreSQL (+ TimescaleDB extension for time-series) |
| Research/bulk data storage | Parquet files (local/object storage) |
| Cache | Redis |
| Async/background workers | Celery (Redis broker + result backend) |
| Scheduled tasks | Celery Beat |
| Market data | Provider-abstracted; Dhan live feed at launch |
| Broker | Dhan first, via `domain/broker` interface |
| Frontend | React + TypeScript + Vite |
| Contract generation | OpenAPI 3.x (drf-spectacular) → generated TypeScript types |
| Testing | pytest, pytest-django, Hypothesis, schemathesis, Playwright |
| Architecture enforcement | import-linter |
| Observability | structlog, Prometheus, OpenTelemetry (wired, not backed yet), Sentry |
| CI | GitHub Actions |
| Deployment | Docker / docker-compose, single Linux VM per environment |
| Time | UTC internally; IST at presentation/session boundary only |
| Financial values | Python `Decimal`, Postgres `NUMERIC` |

Every row is justified in the sections and decision matrix below.

---

## 2. Backend / API — Django + DRF + Channels

**Decision: Django + Django REST Framework, with Django Channels (ASGI) for
WebSocket/live-data.**

The platform needs two things that are architecturally in tension in a
"pick one framework" decision: (a) a control-plane/admin/governance-heavy
surface (config, audit, AI-proposal approval, strategy registry, risk limits
— CRUD-and-review heavy, exactly Django's strength via its built-in admin
and mature ORM/migrations/auth), and (b) live, low-latency data push to
dashboards (signals, positions, market data — WebSocket-native, historically
FastAPI/ASGI's strength).

Rather than run two frameworks/services (which the quality standard
explicitly warns against — "do not introduce distributed systems
infrastructure without a demonstrated requirement"), Django Channels lets a
single Django deployment serve both HTTP/REST (via DRF) and WebSocket (via
Channels, using Redis as the channel layer — the same Redis already required
for cache/Celery, no new infrastructure). This is the smallest reliable
solution that meets both needs.

Why not FastAPI as primary: FastAPI's native async and Pydantic-based typing
are genuinely stronger for a pure high-throughput async API, and its
automatic OpenAPI generation is excellent — but it has no equivalent to
Django's admin (a major, demonstrated need here: `control_plane`,
`config/*`, `ai_agent` governance approval, `research/experiments` review
all map naturally onto an admin-style CRUD/review UI that would otherwise
have to be hand-built), no built-in ORM/migrations of comparable maturity,
and a comparatively younger auth/permissions ecosystem. DRF +
drf-spectacular closes the OpenAPI-generation gap (see §10), so the
remaining advantage of FastAPI (raw async throughput) is not a demonstrated
requirement at Indian cash-equity intraday scale (moderate order/signal
volume, not HFT tick-by-tick).

**Escape hatch (not exercised now):** if a future checkpoint demonstrates a
concrete, measured latency requirement Django/Channels cannot meet (e.g. a
tick-ingestion hot path), that single hot path can be split into a small
dedicated FastAPI/asyncio service behind the same `domain/market_data`
contract — this does not require touching `domain/`, `signal_intelligence/`,
or `trading_engine/`, per the broker/market-data abstraction already locked
at Checkpoint 1–2. Not adopted now because no such requirement has been
demonstrated (Section 34 quality standard: don't over-engineer preemptively).

`application/gateways` = DRF viewsets/API views + Channels consumers.
`application/contracts` = DRF serializers + drf-spectacular schema (source of
truth for generated frontend types, §10). `application/config_schema` = DRF
serializers layered on top of `domain/strategy` / `domain/risk` field
definitions (never redefining a parameter independently, per Checkpoint 2).

## 3. Core Language — Python 3.12

- **Version:** Python 3.12, pinned as the minimum supported interpreter.
  Chosen over 3.13 for this checkpoint as the conservative, widely-verified
  choice for a financial system — the full numerical/data ecosystem
  (pandas, numpy, Django, Celery, broker SDKs) has the longest track record
  on 3.12 as of this checkpoint. Re-evaluate 3.13+ adoption at a later
  checkpoint once the dependency set is finalized and verified compatible;
  this is a PROPOSED future upgrade, not blocked by anything structural.
- **Typing strategy:** type hints are mandatory on all new code from
  Checkpoint 4 onward (`domain/*` contracts especially — they are the
  ubiquitous language and must be unambiguous). Enforced via mypy in strict
  mode in CI (§18).
- **Linting/formatting:** **Ruff** — a single fast tool replacing
  flake8+isort+black+pyupgrade. Chosen for the "smallest reliable solution"
  principle: one tool, one config file, one CI step, instead of four
  separately-versioned tools that can disagree.
- **Static analysis:** mypy (strict) for types; Ruff also covers a wide set
  of static lint rules (unused imports, complexity, security-adjacent
  patterns via `ruff` bandit-equivalent rules).
- **Dependency management:** **Poetry** — mature, lockfile-based,
  widely adopted, stable release history. `uv` was evaluated as a faster
  alternative but rejected for now as comparatively newer with a shorter
  production track record; Poetry is the more "boring, reliable" choice for
  a financial platform's dependency graph. This can be revisited without
  structural cost — Poetry lockfiles are exportable to formats `uv` can
  consume if the team later wants the speed.
- **Packaging approach:** a single installable package (`intraday`), `src/`
  layout, with sub-packages mirroring the already-approved top-level
  directories (`intraday.domain`, `intraday.research`,
  `intraday.signal_intelligence`, `intraday.trading_engine`,
  `intraday.control_plane`, `intraday.communication`, `intraday.application`,
  `intraday.infrastructure`). This is a monorepo — one package, one
  dependency graph, one CI pipeline — appropriate for a small team; a
  multi-package/microservices split is not justified at this scale.

## 4. Database Architecture

### Decision Matrix: System of Record

| Option | Advantages | Disadvantages | Decision |
|---|---|---|---|
| PostgreSQL | Strong ACID, rich types (JSONB, arrays, native UUID/NUMERIC), mature Django ORM support, huge fintech track record, TimescaleDB extension available in-engine | Slightly heavier ops than SQLite (irrelevant at production scale) | **SELECTED** |
| MySQL | Also mature, huge ecosystem | Weaker type system for financial invariants (no native array/JSONB parity, historically weaker CHECK constraint support), no first-party time-series extension equivalent to TimescaleDB | Rejected |

### Decision Matrix: Historical / Time-Series Market Data

| Option | Advantages | Disadvantages | Decision |
|---|---|---|---|
| TimescaleDB (Postgres extension) | Same engine as system-of-record — one database technology to run/back up/monitor; hypertables give time-series performance (partitioning, compression) without new infra | Not as fast as a dedicated columnar time-series engine at very large scale | **SELECTED** |
| ClickHouse / InfluxDB (dedicated TSDB) | Purpose-built time-series performance at very large scale | A second database technology to operate, back up, and monitor; not justified at intraday cash-equity (not HFT tick-by-tick) volumes | Rejected — no demonstrated need |
| Flat Parquet files only | Simple, cheap | Poor for point/range queries needed by live backtests without a query engine layer | Rejected as sole store; used as secondary bulk store (below) |

### Decision Matrix: Research Datasets / Experiment Artifacts

| Option | Advantages | Disadvantages | Decision |
|---|---|---|---|
| Parquet files on local/object storage, referenced by path/hash from a Postgres metadata row | Cheap, columnar, standard in the Python data-science ecosystem (pandas/Polars/DuckDB read it natively), keeps bulk data out of the transactional database | Requires an object-store or well-managed filesystem convention | **SELECTED** |
| Store bulk datasets directly in Postgres | One technology | Bloats the transactional database with data that's never transactionally updated, hurts backup/restore times for the actually-critical system-of-record tables | Rejected |

### System of Record vs. Analytical/Research Storage vs. Transient/Cache — Final Split

| Data category (`data/*`) | Storage | Why |
|---|---|---|
| `trading_state` (orders, positions, trades, strategy registry, risk limits) | PostgreSQL | Transactional, must be ACID-consistent, small-to-moderate volume |
| `audit_data` | PostgreSQL (dedicated schema, append-only table design) | Must be durable and queryable/joinable against trading_state for audit trails |
| `market_data` (live) | PostgreSQL/TimescaleDB (durable) + Redis (hot/transient snapshot) | Durable for reconciliation/replay; Redis only caches the latest tick/bar for fast reads |
| `historical_data` | PostgreSQL/TimescaleDB hypertables | Time-series performance without a second DB engine |
| `research_data` | Parquet files + Postgres metadata rows (`research/experiments`) | Bulk, rarely-updated, read-heavy analytical data |
| `analytics_reports` | PostgreSQL (small, queryable result tables) | Needs to be queried/joined for dashboards |
| `cache_transient` | Redis | By definition disposable/recomputable |

`domain/` never changes because of this split — it defines *meaning*;
`infrastructure/persistence` implements repository interfaces per category,
using the storage indicated above.

## 5. Cache and Async Architecture

**Redis is infrastructure for ephemeral/cache/messaging/coordination
workloads only — it is never a system of record.** (Terminology corrected
at Checkpoint 4 §3 to remove any ambiguity in how "cache" was previously
used as shorthand for several distinct roles.) One Redis instance serves
seven distinct, individually-scoped roles — distinct in *purpose*, not
necessarily in physical deployment:

| # | Role | Contents | Notes |
|---|---|---|---|
| 1 | **Cache** (Django cache framework) | Transient live market-data snapshots (latest tick/bar), short-lived computed values (e.g. current-bar feature cache), Django session state | Read-optimized copies only; source of truth is always PostgreSQL where one exists |
| 2 | **Django Channels layer** | In-flight WebSocket group-broadcast routing state | Ephemeral by nature of the channel-layer abstraction itself |
| 3 | **Celery broker** | Pending/in-flight task messages (reconciliation runs, notification dispatch, scheduled jobs) | A crashed/flushed broker loses only *queued, not-yet-executed* work, which is re-triggerable, not authoritative state |
| 4 | **Celery result backend** | Task result/status for a bounded retention window | Never the durable record of what a task *did* to trading state — that's written to PostgreSQL by the task itself |
| 5 | **Pub/Sub** | Live tick fan-out to feature engine / WebSocket clients / persistence writer | Fire-and-forget; the persistence writer's PostgreSQL write is what makes the tick durable |
| 6 | **Distributed locks** | e.g. preventing double order submission during a retry window | Coordination only — the lock's existence never substitutes for the authoritative order-state row in PostgreSQL |
| 7 | **Rate-limiting counters** | API/broker call throttling counters | Purely operational; resets safely to zero with no data-loss implication |

**PostgreSQL remains authoritative** for: orders, positions, trades, risk
limits, audit records, configuration, strategy registry, experiment
metadata, reconciliation state. All of these are durably persisted in
PostgreSQL; Redis may hold a read-optimized copy (role 1) but Postgres is
always the source of truth — **an empty or flushed Redis instance must never
cause loss of authoritative trading state**, only a cold cache, a
re-triggerable job queue, or a dropped live-data fan-out message (all
recoverable from PostgreSQL or the next incoming tick).

**Async / background processing: Celery, using Redis as both broker and
result backend** (reuses the Redis already required for cache — no new
infrastructure piece). Celery Beat handles scheduled tasks. Concrete job
categories: reconciliation runs, mandatory square-off enforcement checks,
notification dispatch (Telegram/Discord adapters), long-running backtest
jobs (kept off the request/response cycle), research/optimization batch
jobs, exchange-calendar and instrument-master refreshes, EOD reporting.

**Message broker decision matrix:**

| Option | Advantages | Disadvantages | Decision |
|---|---|---|---|
| Redis (as Celery broker) | Already required for cache; simplest possible operational footprint; sufficient throughput/durability for this platform's job volume | Weaker delivery guarantees than RabbitMQ under some failure modes | **SELECTED** |
| RabbitMQ | Stronger delivery guarantees, richer routing | A second piece of infrastructure to run/monitor; no demonstrated routing complexity that Redis+Celery can't handle | Rejected — no demonstrated need |
| Kafka | Very high-throughput durable event streaming, multiple consumer groups | Significant operational overhead; justified only for high-volume tick-by-tick multi-consumer streaming, explicitly out of scope for cash-equity intraday at this stage | Rejected — explicitly the "do not add Kafka just because it's a trading platform" case named in the brief |

Live-tick fan-out (feature engine, live dashboard WebSocket clients,
persistence writer all needing the same incoming tick) uses **Redis Pub/Sub**
(or Django Channels' Redis-backed group broadcast) — sufficient at
cash-equity intraday scale, no new infrastructure.

## 6. Market Data Architecture

- **Primary live source:** Dhan's market-data WebSocket feed at launch —
  but implemented as one interchangeable `infrastructure/market_data_providers/dhan`
  adapter behind `domain/market_data`, never the canonical owner of
  market-data semantics (explicit Checkpoint 3 requirement). A dedicated
  market-data vendor can be added later as
  `infrastructure/market_data_providers/<vendor>` with zero change to
  `signal_intelligence` or `research`.
- **Historical source:** a historical OHLCV/tick vendor or the broker's
  historical API, behind the same abstraction; stored durably in
  PostgreSQL/TimescaleDB (`data/historical_data`).
- **Normalization layer:** each provider adapter includes a normalizer that
  converts vendor-specific tick/symbol formats into the canonical
  `domain/market_data` + `domain/instrument` shapes *before* anything
  downstream sees them.
- **Instrument master:** canonical `domain/instrument` records in
  PostgreSQL (system-of-record — order placement/risk checks need fast,
  authoritative lookups), versioned so a backtest can resolve instrument
  identity as of a historical point in time (corporate actions can change
  symbols/lot sizes).
- **Exchange calendar:** NSE/BSE trading calendar (holidays, special/reduced
  sessions e.g. Muhurat trading) stored as versioned reference data in
  PostgreSQL, refreshed via a scheduled Celery Beat job; consumed by
  `domain/session`.
- **Trading-session model:** `domain/session` implemented against the
  exchange calendar plus entry-cutoff/square-off windows from
  `config/environments` / `config/risk`.
- **Corporate-action handling:** raw ingested historical data is
  immutable/append-only (never overwritten); split/bonus/dividend
  adjustments are computed into a separate derived "adjusted" series —
  required for research reproducibility (Rule 5.6) and validated by
  `research/data_validation`.
- **Symbol/token mapping:** provider-specific symbol/token ↔ canonical
  `instrument_id` mapping table in PostgreSQL, owned by the normalization
  layer.
- **Data-quality validation:** `control_plane/market_data_health` (live
  staleness/gap detection) and `research/data_validation` (offline
  survivorship-bias/corporate-action-consistency checks) both consume the
  same canonical contract but apply different checks, per their existing
  Checkpoint 1–2 responsibilities.

## 7. Broker Architecture

```
domain/broker  (interface: authenticate, place_order, modify_order,
                cancel_order, get_order_status, get_positions,
                get_holdings, stream_execution_reports)
      ↓ implemented by
trading_engine/broker_abstraction  (broker-agnostic orchestration: retry/
                                     backoff policy, normalizes broker-
                                     specific errors into domain/order
                                     status transitions)
      ↓ delegates to
infrastructure/brokers/<broker>  (Dhan first; each adapter owns that
                                   broker's specific REST/WebSocket API,
                                   auth/token lifecycle, error codes,
                                   rate limits)
```

- **Auth/token lifecycle:** broker-specific (e.g. Dhan's API-key + access-
  token refresh flow) — owned entirely inside that broker's adapter; token
  storage goes through the secret-management mechanism (§13), never
  `config/broker` as plaintext.
- **Order placement/modification/cancellation/status/positions/holdings/
  execution reports:** mapped 1:1 to `domain/broker` interface methods.
  Execution reports (streamed via WebSocket where the broker supports it)
  feed `trading_engine/execution_management` to produce `domain/trade`
  records, and `control_plane/reconciliation` to detect drift.
- **Broker failures/rate limits:** generic retry/backoff policy lives in
  `trading_engine/broker_abstraction`; broker-specific nuances live in each
  adapter; persistent failures surface to `control_plane/broker_health`,
  which can trigger `control_plane/kill_switch`.
- **Adding Zerodha/Angel One later:** implement
  `infrastructure/brokers/zerodha` (folder already reserved since
  Checkpoint 1) against the unchanged `domain/broker` interface — zero
  changes to strategy, signal, risk, or order-management code. Verified in
  §21.B.

No broker code is implemented at this checkpoint.

## 8. Frontend Architecture

**Decision: React + TypeScript + Vite.**

| Option | Advantages | Disadvantages | Decision |
|---|---|---|---|
| React + TypeScript | Largest ecosystem for real-time dashboard/charting components, strongest pairing with generated TS contract types for drift detection (§10), largest hiring/community pool | Larger bundle/tooling surface than a minimal framework | **SELECTED** |
| Vue + TypeScript | Lighter, gentle learning curve, good TS support | Smaller ecosystem specifically for financial charting/dashboard components | Rejected — not a strong enough differentiator to give up React's ecosystem depth here |
| Server-rendered (Django templates) | Simplest possible stack, one framework total | Fights directly against "highly intuitive," live-updating dashboards with WebSocket-driven charts/signals — a rich SPA is a demonstrated requirement (Section 12 of Checkpoint 1) | Rejected |

Build tooling: **Vite** (fast, mature by this checkpoint, avoids legacy
tooling debt). Data-fetching/cache layer: TanStack Query (pairs naturally
with generated TS types and the REST + WebSocket hybrid). Charting library
selection is explicitly deferred to Checkpoint 14 (Frontend) — not decided
here, to avoid a premature choice before real dashboard requirements are
specified.

The frontend consumes only `application/contracts` (via generated types,
§10) — never `domain/` or bounded-context internals directly, per the
Checkpoint 1–2 dependency rule; this is unaffected by the framework choice
(§21.D).

## 9. Contract Generation Architecture

```
domain/*  (business meaning)
      ↓
application/contracts  (DRF serializers/views + drf-spectacular → OpenAPI 3.x schema — SOURCE OF TRUTH)
      ↓
frontend/shared/generated_contracts  (TypeScript types, mechanically generated from the OpenAPI schema — e.g. via openapi-typescript)
      ↓
frontend/*  (UI, consumes only the generated types)
```

- **Source of truth:** the OpenAPI 3.x schema generated from DRF
  serializers/viewsets via `drf-spectacular`.
- **Generation process:** a CI/dev-tooling step runs `drf-spectacular`'s
  schema command to produce `openapi.json`, then a TypeScript codegen step
  (`openapi-typescript` or equivalent) produces the types written into
  `frontend/shared/generated_contracts`.
- **Generated artifacts:** `openapi.json` (checked in as the canonical
  schema snapshot) and the generated `.ts` type files.
- **Validation/CI enforcement:** CI regenerates both artifacts from the
  current codebase and diffs them against what's committed; any diff fails
  the build (§18). This is the concrete mechanism that turns "frontend/
  backend contract drift" from a documentation promise (Checkpoint 2 §9)
  into an actual CI failure (§21.H).
- **Why not GraphQL:** no demonstrated need for flexible ad hoc querying
  beyond the fixed set of typed DTOs the frontend needs; GraphQL would also
  complicate the REST+WebSocket hybrid and caching story for no offsetting
  benefit here.
- **Why not a custom mechanism:** OpenAPI + drf-spectacular + established
  codegen tooling is the smallest solution that is also well-supported and
  boring — a custom generator would be unjustified engineering effort.

WebSocket/live-channel message shapes (Django Channels consumers) are
documented as an OpenAPI extension / supplementary schema alongside the REST
contract, generating corresponding TS types the same way — this avoids a
second, undocumented contract surface for the live-data path.

## 10. Testing Architecture

| Concern | Tool | Why |
|---|---|---|
| Unit (domain/business rules) | pytest + pytest-django | Fast, expressive, standard for the whole codebase — one runner for everything below |
| Contract (API/frontend compatibility) | drf-spectacular schema validation + schemathesis (property-based OpenAPI contract testing) + the generated-contract drift check (§9) | Verifies the API actually matches its declared schema, not just that the schema itself is well-formed |
| Integration (DB, cache, broker/market-data adapters) | pytest + testcontainers-python (real Postgres/Redis in CI, not mocks) | Adapter correctness must be verified against real dependency behavior, not mocks that can silently drift from reality |
| Backtest validation | pytest suite in `tests/backtest_validation` with deterministic, hand-computed known-answer datasets | Catches backtest-engine regressions that unit tests on isolated functions would miss |
| End-to-end | Playwright (frontend, once it exists) + pytest-driven workflow tests against a broker sandbox/paper environment (backend) | Playwright is the current mature, CI-friendly standard for browser E2E; backend E2E needs a broker sandbox, not a browser |
| Safety (risk engine / kill switch) | pytest + Hypothesis (property-based) | Adversarial/property-based cases assert no signal can ever produce an order violating configured risk limits, and kill-switch state is always honored |
| Reconciliation | pytest with synthetic broker-state-vs-internal-state divergence fixtures | Verifies `control_plane/reconciliation` actually detects the divergences it's meant to catch |
| Property-based testing | **Hypothesis** | Standard, pytest-integrated; applied especially to Decimal-based financial calculations (position sizing, P&L, risk limit math) where edge cases are easy to miss by hand |

## 11. Observability Architecture

| Concern | Tool | Maps to |
|---|---|---|
| Structured logging | `structlog` (JSON output) | **Operational Logs** only — debugging/ops visibility, not the system of record for anything |
| Metrics | Prometheus client + self-hosted Prometheus | `control_plane/monitoring`, `control_plane/system_health` |
| Tracing | OpenTelemetry SDK wired in now, backend (e.g. Tempo/Jaeger) deferred | Optional at current team size; low cost to instrument early, avoids re-instrumentation later |
| Error tracking | Sentry | Unhandled exceptions, low-effort for a small team vs. building in-house aggregation |
| Health checks | `/healthz` (liveness), `/readyz` (readiness) | `control_plane/system_health`, `broker_health`, `market_data_health` |
| Audit logging | Durable, append-only PostgreSQL tables (never log files) | `control_plane/audit` — every risk decision, order, signal, AI proposal, kill-switch action, with actor/timestamp/before-after state |

**Four-way distinction (must not be mixed):**

- **Operational Logs** — `structlog` JSON logs, ops-facing, ephemeral/rotated, not queried for business decisions.
- **Audit Records** — durable Postgres rows in `control_plane/audit`, immutable, the legal/operational source of truth for "what happened and who/what did it."
- **Trading Events** — domain events (signal generated, order placed, position changed) that *feed* audit records but may also be mirrored to operational logs for live debugging; the audit record is authoritative, the log line is not.
- **Research Artifacts** — `research/research_reports`, `reports/*` — human-readable documents, not logs at all, generated from research/backtest data, not written by the logging system.

## 12. Security Architecture

- **Authentication:** Django's built-in auth (session-based, CSRF-protected)
  for the SPA — appropriate for a small internal-team/single-operator
  platform rather than a public multi-tenant SaaS at this stage. Token/JWT
  (`djangorestframework-simplejwt`) can be added later if third-party API
  access is needed, without restructuring `application/`.
- **Authorization:** Django's permission framework + DRF permission
  classes, mapped to roles (e.g. "operator" vs. "viewer"). The Checkpoint 2
  AI-governance gate is enforced exactly here: only an "operator" role may
  perform the approval action that copies an `ai_agent/proposals` entry
  into a real domain location (`research/`, `config/`).
- **Secret management:** broker API keys/tokens, DB credentials, third-party
  API keys — **never** in source, Git, logs, frontend bundles, or generated
  contracts. Injected via environment variables sourced from a secrets
  mechanism appropriate to the deployment target (local `.env`, excluded via
  `.gitignore`, for development; a proper secret store for
  staging/production — the specific product, e.g. a cloud secret manager or
  self-hosted Vault, is a Checkpoint 17 hosting decision, not resolved here).
  `config/broker` holds only non-secret configuration (which broker, which
  environment) — credentials are injected at runtime, never committed.
- **Encryption:** TLS in transit everywhere (enforced at the reverse
  proxy). Any broker token that must be persisted is encrypted at rest
  (e.g. `django-fernet-fields`) or kept short-lived and not persisted at all
  where the broker's auth flow allows it.
- **API security:** DRF's standard protections — CSRF for session auth,
  rate limiting/throttling, input validation via serializers. No bespoke
  security code.
- **Session security:** Django's secure cookie defaults (HttpOnly, Secure,
  SameSite) enforced.
- **Auditability:** covered by `control_plane/audit` (§11).
- **Sensitive configuration:** kept structurally separate from `config/*`
  (public, non-secret) — see §13.
- **Environment separation:** distinct Django settings modules per
  environment plus the `TRADING_MODE` safety flag (§14) — the mechanism
  that makes accidental live trading from a dev environment structurally
  impossible (§21 compatibility test, §15).

## 13. Configuration Architecture

Four kinds, never mixed:

| Kind | Example | Where it lives |
|---|---|---|
| **Static application configuration** | installed apps, middleware, logging format | Django settings modules per environment (`settings/base.py`, `settings/development.py`, `settings/paper.py`, `settings/production.py`), version-controlled, non-secret |
| **Runtime configuration** | feature flags, active market-data provider, maintenance mode | A small `runtime_config` table in PostgreSQL (or env vars), editable via Django admin, takes effect without redeploy |
| **User-configurable trading parameters** | `config/strategies`, `config/risk`, `config/universe` | PostgreSQL, instances validated against `application/config_schema` (which itself derives from `domain/strategy`/`domain/risk` — never redefined independently, Rule 13) |
| **Secrets** | broker credentials, DB password, third-party API keys | Environment variables / secret store only — never in Postgres `config` tables, never in Django settings files, never in Git |

`config/environments` maps to the Django settings-module split.
`config/broker` maps to non-secret broker configuration only (which broker,
sandbox vs. live endpoint); credentials are injected separately per the
Security section above.

## 14. Deployment Architecture

- **Docker** for every environment (dev via `docker-compose`,
  staging/production via the same images) — ensures dev/paper/production
  parity. Kubernetes is explicitly rejected as unjustified for the current
  team size (Section 34 quality standard).
- **Environments:**
  - *Development* — local `docker-compose`, `TRADING_MODE=RESEARCH`, broker
    sandbox or mock adapter only, never real credentials.
  - *Testing* — CI-only, ephemeral containers.
  - *Staging/Paper* — `TRADING_MODE=PAPER`, broker's paper/sandbox API (or
    an internal paper-execution simulator), configuration mirrors
    production except credentials.
  - *Production* — `TRADING_MODE=LIVE`, real broker credentials, a single
    appropriately-sized Linux VM/cloud VM (no managed Kubernetes needed at
    this scale).
- **`TRADING_MODE` safety flag:** the trading engine reads this flag and
  refuses to place a real order unless `TRADING_MODE=LIVE` **and** the
  running settings module is the production module **and** live broker
  credentials are present — all three simultaneously, which cannot occur
  on a developer's machine by accident. This is the concrete mechanism
  satisfying "LIVE trading must be impossible to accidentally start from a
  development environment" (§17 of the checkpoint brief, verified in §21).
- **Managed vs. self-hosted Postgres/Redis:** either is acceptable; the
  specific hosting provider is explicitly deferred to Checkpoint 17
  (Production Readiness) — it does not affect any domain boundary and does
  not need to be resolved now.

## 15. CI/CD Architecture

**Platform: GitHub Actions** (the repository is already hosted on GitHub;
no reason to introduce a second CI system).

Minimum reliable pipeline — on every PR:

1. Format check (`ruff format --check`)
2. Lint (`ruff check`)
3. Type check (`mypy --strict`)
4. Unit tests (`pytest`)
5. Architecture dependency-rule check (`import-linter`, §16)
6. Contract generation + drift check (regenerate OpenAPI + TS types, diff against committed — §9)
7. Migration check (`python manage.py makemigrations --check --dry-run`)
8. Secret scan (e.g. `gitleaks`)
9. Dependency vulnerability check (e.g. `pip-audit`)

On merge to `main`: all of the above, plus integration tests (Postgres/Redis
as CI service containers) and a Docker image build (not pushed/deployed
automatically).

**Deliberately not built yet:** any automatic deployment pipeline to
paper/production — deployment remains a manual, explicitly-gated step at
this checkpoint (Section 18 of the brief: "do not create an elaborate
deployment pipeline yet").

## 16. Architecture Enforcement

Documentation alone (README "Must Not Depend On" fields) is not a
mechanical guarantee. **`import-linter`** is adopted as the CI-enforced
mechanism: a config file (`.importlinter`, to be created at Checkpoint 4)
declares:

- **Layers contract:** `frontend` → `application` → {`research`,
  `signal_intelligence`, `trading_engine`, `control_plane`, `communication`}
  → `domain`, with `infrastructure` forbidden from being imported by
  `domain` or any bounded context.
- **Independence contracts:** bounded contexts must not import each other's
  internals (e.g. `signal_intelligence` independent of
  `trading_engine.order_management`, `trading_engine.execution_management`,
  `trading_engine.broker_abstraction`).
- **Documented exception:** `research.backtesting` is explicitly permitted
  to import `trading_engine.strategy_execution`'s implementation module
  only — `import-linter`'s contract syntax supports scoped exceptions,
  encoding the Checkpoint 2 narrow-dependency rule precisely rather than as
  a blanket allowance.

Run as a required CI check (§15, step 5) — any violation of the approved
dependency direction fails the build, not just a README.

**Known limitation:** `import-linter` contracts are typically
package-level; the "implementation module only, not
order_management/execution_management/broker_abstraction/risk_engine/
session_management" granularity inside `trading_engine.strategy_execution`
may need a supplementary custom pytest-based architecture test (walking
the import graph at module granularity) if package-level contracts prove
too coarse once real code exists. Flagged here as a Checkpoint 4/5 follow-up,
not resolved with fake code now.

## 17. Versioning and Reproducibility

| Version | Where recorded | Mechanism |
|---|---|---|
| Application version | `pyproject.toml` version field + Git tag | Semantic versioning (`vMAJOR.MINOR.PATCH`), exposed via `/version` |
| Strategy version | `domain/strategy` record, immutable once created | Any parameter/logic change creates a new version, never an in-place mutation |
| Configuration version | Versioned rows in PostgreSQL for `config/strategies`/`config/risk`/`config/universe` | Never mutate a config instance already referenced by a past experiment/trade — create a new version |
| Dataset version | Content-hash or timestamp-scoped identifier for a `data/historical_data` snapshot (date range + adjustment-version used) | Stamped onto `research/experiments` records |
| Experiment version/lineage | `research/experiments`' `experiment_id` + `parent_experiment_id` (Checkpoint 2) | Stamped with all versions in this table via `domain/shared_kernel`'s generic version primitive |
| API contract version | OpenAPI schema version, reflected in the URL (`/api/v1/`) | Bumped on breaking changes |

Taken together, an `Experiment` record's version fields let anyone
reconstruct "exactly which code + strategy + configuration + dataset
produced this result" — the explicit reproducibility requirement — using
only technology already selected above (PostgreSQL rows + Git tags), no new
infrastructure.

## 18. Financial / Trading Precision Standards

- **Money, prices, quantities, percentages:** Python `Decimal` everywhere —
  never `float`, which introduces non-deterministic rounding unacceptable
  for risk/P&L math. PostgreSQL `NUMERIC` columns; DRF `DecimalField`
  serializers (never `FloatField`) for anything financial.
- **Percentages** are stored as `Decimal` ratios with explicit
  precision/scale (e.g. `0.0050` for 0.5%), never a raw float.

## 19. Time Architecture

- **Canonical internal representation: UTC.** All storage
  (`TIMESTAMPTZ` in Postgres, `USE_TZ=True` in Django, timezone-aware
  Python `datetime` everywhere) and inter-service communication uses UTC.
- **IST (`Asia/Kolkata`) is a presentation/session-boundary concern only** —
  applied when formatting for the frontend/notifications and when
  evaluating exchange-session logic (market open/close are defined in IST
  wall-clock time per the NSE/BSE calendar). `domain/session` owns the
  IST-session-to-UTC-instant conversion.
- **External timestamps** (broker execution reports, market-data ticks,
  historical vendor data) are normalized to UTC at the earliest possible
  point — inside the provider-specific normalization layer in
  `infrastructure/market_data_providers/*` and `infrastructure/brokers/*` —
  nothing downstream ever handles a non-UTC or naive timestamp.
- **DST:** India does not observe daylight saving time, which materially
  simplifies exchange-session math versus other markets. The exchange
  calendar must still explicitly encode special/reduced sessions (e.g.
  Muhurat trading) as *calendar data*, not code logic — consistent with the
  corporate-action-handling principle in §6.

---

## 20. Technology Decision Matrix (consolidated)

| Area | Candidate | Advantages | Disadvantages | Decision | Reason |
|---|---|---|---|---|---|
| Backend | Django+DRF+Channels | Admin/governance fit, mature ORM/auth, one deployable for REST+WebSocket | Heavier than a minimal framework | **SELECTED** | Matches control-plane-heavy + live-dashboard needs without a second service |
| Backend | FastAPI | Native async, strong typing, auto OpenAPI | No admin, less mature auth/ORM ecosystem | Rejected (documented escape hatch) | No demonstrated throughput need FastAPI uniquely solves |
| API contract tooling | drf-spectacular (OpenAPI) | Mature, standard, integrates with DRF | — | **SELECTED** | Smallest mechanism to guarantee drift-as-CI-failure |
| API contract tooling | GraphQL | Flexible querying | Complicates caching/WebSocket duality, no demonstrated need | Rejected | No flexible-query requirement |
| Database (system of record) | PostgreSQL | ACID, rich types, fintech track record | — | **SELECTED** | Best fit for financial invariants |
| Database (system of record) | MySQL | Mature, popular | Weaker type system for financial data | Rejected | Postgres better fits domain needs |
| Time-series storage | TimescaleDB (Postgres ext.) | Same engine, hypertables | Not as fast as dedicated TSDB at huge scale | **SELECTED** | One DB technology, sufficient at intraday cash-equity scale |
| Time-series storage | ClickHouse/InfluxDB | Purpose-built performance | Second DB technology to operate | Rejected | No demonstrated scale need |
| Cache | Redis | Simple, fast, reused for Celery/Channels | Not a system of record (by design) | **SELECTED** | Covers all transient needs with one piece of infra |
| Async workers | Celery (Redis-backed) | Mature, simple, reuses Redis | Weaker guarantees than RabbitMQ in edge cases | **SELECTED** | Smallest reliable solution |
| Message broker | RabbitMQ | Stronger delivery guarantees | Extra infra, no demonstrated routing need | Rejected | Not justified at current scale |
| Message broker | Kafka | High-throughput event streaming | Heavy ops overhead | Rejected | Explicitly the "don't add Kafka just because trading platform" case |
| Frontend | React+TypeScript+Vite | Ecosystem depth for dashboards/charts, best TS-contract synergy | Larger tooling surface | **SELECTED** | Matches live-dashboard/chart requirements |
| Frontend | Vue+TypeScript | Lighter | Smaller financial-charting ecosystem | Rejected | Not a strong enough differentiator |
| Market data | Provider-abstracted (Dhan first) | Swappable, no vendor lock-in on semantics | — | **SELECTED** | Rule 5.3-equivalent abstraction for market data |
| Broker | Dhan first, via `domain/broker` | Confirmed initial integration | — | **SELECTED** | Per founding brief |
| Testing | pytest + Hypothesis + schemathesis + Playwright | Comprehensive, standard, well-integrated | — | **SELECTED** | Covers unit→E2E→property-based→contract in one coherent toolchain |
| Contract generation | OpenAPI → TS codegen | CI-diffable, standard | — | **SELECTED** | Simplest mechanism guaranteeing drift-as-CI-failure |
| Observability | structlog+Prometheus+OTel+Sentry | Each boring/standard in its niche | Several tools to wire | **SELECTED** | Matches the four-way log/audit/event/artifact distinction cleanly |
| CI/CD | GitHub Actions | Already hosting on GitHub, no new platform | — | **SELECTED** | Zero additional platform to adopt |
| Deployment | Docker + single VM per environment | Dev/paper/prod parity, no K8s overhead | Manual scaling if ever needed | **SELECTED** | Matches small-team scale; K8s explicitly rejected as premature |

---

## 21. Architecture Compatibility Tests

- **A. New strategy** — new `research/strategy_specifications` spec + new
  implementation module in `trading_engine/strategy_execution` + registry
  row. No change to Django app structure, database schema (beyond a new
  strategy row), broker adapters, or frontend framework. ✅
- **B. New broker (Zerodha)** — new `infrastructure/brokers/zerodha`
  Python module implementing `domain/broker`; zero change to
  `trading_engine/risk_engine`, `signal_intelligence`, or Django
  views/serializers. ✅
- **C. New database technology** — swapping PostgreSQL requires only new
  `infrastructure/persistence` repository implementations; `domain/*`
  contracts and Django models' *field-level* types stay conceptually
  identical (Decimal/UUID/datetime), no bounded context changes. ✅
- **D. New frontend** — React can be replaced because the frontend consumes
  only generated TypeScript types from `application/contracts`; no domain
  logic exists in the frontend to port. ✅
- **E. Backtesting reuses live strategy semantics** — `research/backtesting`
  imports the exact same `trading_engine/strategy_execution` implementation
  module (narrow documented exception) — Celery/Django infrastructure
  choices don't affect this, since the exception is a Python import, not a
  service boundary. ✅
- **F. AI cannot obtain trading authority** — Django's permission system
  enforces that only an "operator" role can perform the governance-approval
  action; `ai_agent/` has no code path to `trading_engine/execution_management`
  or `infrastructure/brokers` regardless of which web framework or database
  is chosen — the guarantee is structural (import graph), not
  framework-specific. ✅
- **G. Kill switch independent of strategy code** — `control_plane/kill_switch`
  is a Django app/module with its own DB-backed state, checked by
  `trading_engine/risk_engine` before any order — halting it requires no
  strategy code change, and works identically regardless of which strategy
  is running. ✅
- **H. Contract drift detected automatically** — CI step (§9, §15) fails the
  build on any diff between the committed generated TypeScript types and a
  fresh regeneration from the current OpenAPI schema. ✅
- **I. Reproducibility** — an `Experiment` record's stamped versions
  (§17) plus Git tags for code version are sufficient to reconstruct any
  past result using only PostgreSQL + Git — no additional infrastructure
  required. ✅

All nine tests pass without requiring any change to the Checkpoint 1–2
architecture — confirming technology was mapped onto the architecture, not
the reverse.

---

## 22. What Remains Deferred

- Specific charting library (Checkpoint 14).
- Specific secret-store product and cloud/VM hosting provider (Checkpoint 17).
- Whether/when to adopt Python 3.13+.
- Whether `uv` replaces Poetry once its ecosystem track record lengthens.
- Automatic deployment pipeline (explicitly out of scope this checkpoint).
- OpenTelemetry backend selection (SDK wired, backend not chosen).

None of these are architecturally blocking — each can be decided at its
named future checkpoint without revisiting anything LOCKED here.
