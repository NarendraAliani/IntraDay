# ARCHITECTURE_DECISIONS.md

Decision log for the foundational architecture checkpoint (2026-08-12).

| # | Decision | Reason | Alternatives Considered | Status |
|---|---|---|---|---|
| 1 | Organize the repository as bounded-context directories (`research`, `signal_intelligence`, `trading_engine`, `control_plane`, `communication`) around a shared `domain/` contract layer, instead of a flat/layered-only or "trading bot" structure. | Matches Section 4's mandated domain separation; keeps strategy logic isolated from broker/notification/frontend concerns (Rule 5.1); makes the risk-engine chokepoint (Rule 5.2) structurally obvious. | (a) Flat `src/` with type-based folders (models/, services/, utils/); (b) Single monolithic `trading/` package. Both rejected — they don't express bounded-context isolation or make it hard to accidentally couple strategies to brokers/notifications. | LOCKED |
| 2 | Introduce a top-level `domain/` shared-kernel layer holding canonical, technology-neutral contracts (market data, feature, strategy, signal, risk, order, position, broker, session, experiment, universe, instrument). | Required for backtest/paper/live parity (Rule 5.5) and reproducibility (Rule 5.6); gives every bounded context one unambiguous place to depend on instead of depending on each other. | Duplicating contracts per bounded context (rejected — violates parity/DRY); putting contracts inside `application/` (rejected — application is an orchestration layer, not the domain's home). | LOCKED |
| 3 | Add an `application/` layer (`contracts`, `gateways`, `config_schema`) between `domain`/bounded contexts and `frontend`. | Satisfies Rule 13 (single-sourced backend↔frontend parameter definitions) and gives the future API a technology-neutral home before a framework is chosen. | Exposing bounded-context modules directly to the frontend (rejected — couples presentation to internal domain structure and would duplicate parameter definitions). | LOCKED |
| 4 | Separate `infrastructure/` (technology-specific adapters) from `domain/` and the bounded contexts, with `infrastructure/brokers/dhan` as the only broker adapter given concrete initial scaffolding intent, plus reserved empty `zerodha` and `angel_one` folders. | Rule 5.3 requires broker abstraction; Dhan is confirmed as the initial integration but the structure must not be Dhan-shaped. | Building broker logic directly inside `trading_engine/broker_abstraction` (rejected — mixes interface and implementation, breaks future multi-broker support). | LOCKED |
| 5 | Model `data/` as logical, technology-neutral data-category boundaries (market, historical, cache/transient, trading state, research, analytics/reports, audit), separate from `infrastructure/persistence` which will hold the concrete storage technology later. | Section 11 explicitly asks for these boundaries without picking a database. Separating "what data exists" from "how it's stored" lets the storage decision be made later without touching consumers. | Folding data boundaries into `infrastructure/persistence` directly (rejected — conflates logical and physical concerns, and consumers would need to know storage tech prematurely). | LOCKED |
| 6 | Add a dedicated `ai_agent/` top-level directory (`proposals`, `research_assist`, `guardrails`, `session_state`), reinforced by `infrastructure/ai_execution_guardrail` and `control_plane/kill_switch`. | Rule 5.7 requires AI agents to research/propose without ever bypassing risk, validation, deployment, auth or audit gates, and to never reach live execution directly. A single directory makes this boundary auditable rather than implicit. | Treating AI-agent concerns as an implicit convention with no dedicated home (rejected — not auditable, easy to violate accidentally). | LOCKED |
| 7 | Give `frontend/` a domain-aligned directory-per-screen-area structure (dashboard, strategy_management, research_lab, backtesting, experiments, signals, positions, orders, risk, reports, system_health, broker_settings, notification_settings, audit_history) without designing screens. | Section 12 lists these areas explicitly and asks only for an architectural location, not UI design. Aligning frontend folders to backend bounded contexts keeps Rule 13 traceable. | Generic `pages/` + `components/` split with no domain alignment (rejected — harder to keep frontend/backend contracts synchronized long-term). | LOCKED |
| 8 | Every generated directory receives a README.md stating Responsibility / Depends On / Must Not Depend On instead of any placeholder source/config code. | Rule 14 forbids business-logic/placeholder code at this checkpoint; documentation-as-scaffolding satisfies "developer can understand the architecture immediately" (Section 15) without pretending logic exists. | Using empty directories with only `.gitkeep` (rejected — gives no architectural guidance to the next developer/agent); writing stub source files (explicitly forbidden by Rule 14). | LOCKED |
| 9 | Do not initialize git, add a `.gitignore`, choose a license, or add CI config in this checkpoint. | Out of scope for "foundational file structure + architectural organization" (Section 16); no tooling/dependency decisions requested. | Initializing git now for convenience (rejected — not requested, and repository/VCS strategy may itself be a future decision point). | PROPOSED (deferred to a DevOps checkpoint) |
| 10 | Leave all concrete technology choices (API framework, database(s), cache, message queue, frontend framework, cloud/hosting, market-data provider(s), CI/CD platform, IaC tool, contract-generation tooling) unselected and marked PENDING ARCHITECTURAL DECISION in the relevant README files. | Section 3 explicitly forbids assuming a stack; the repository had no prior technology decisions to preserve. | Pre-selecting a "reasonable default" stack (rejected — explicitly disallowed by the brief; would also bias the next architecture checkpoint). | **RESOLVED at Checkpoint 3** — see [TECHNOLOGY_MAPPING.md](TECHNOLOGY_MAPPING.md) and decisions #17–#28 below. |

## Checkpoint 2 — Architecture Review (2026-08-12)

An explicit architecture-review checkpoint (not a redesign). Every question
in the review brief (shared kernel, strategy lifecycle, signal/order/
position/trade, data ownership, application layer, frontend contracts,
control-plane authority, AI boundary, communication layer, research lab
fragmentation, experiment lineage, simplification test, extensibility test)
was evaluated against the Checkpoint 1 structure before any change was made.

| # | Decision | Reason | Alternatives Considered | Status |
|---|---|---|---|---|
| 11 | Remove `domain/experiment` from the shared kernel; its full contract now lives at `research/experiments`. A generic version/lineage identifier primitive was added to `domain/shared_kernel` for the few cross-context references that need to stamp/compare a version. | Applying "minimum viable shared kernel": a concept only belongs in `domain/` if 2+ bounded contexts need the *identical* contract. `experiment` was consumed by exactly one bounded context (`research/`); other contexts only ever needed an id reference, not the full aggregate. | (a) Leave it in `domain/` for "consistency with other lifecycle concepts" (rejected — inflates the shared kernel without a genuine cross-context need, the exact anti-pattern the review was asked to catch); (b) Duplicate a lightweight experiment reference in `domain/` AND keep the full contract in `research/` (rejected — the shared_kernel version primitive already covers the only genuine cross-context need, a second definition would be redundant). | LOCKED |
| 12 | Add `domain/trade` — a new canonical contract for a completed, closed execution outcome (entry+exit, realized P&L), distinct from Signal/Order/Position. | Review of Section 5 found a genuine gap: without a Trade concept, the architecture could not structurally separate "was the strategy wrong?" (signal_intelligence's job) from "was the execution poor?" (trading_engine's job) — both diagnostic questions are explicitly required. Needed identically by live execution, backtest simulation, and reporting, meeting the shared-kernel bar. | (a) Fold "trade" semantics into `domain/order` as a terminal order state (rejected — an Order is a *request*; conflating it with the *realized outcome* would make slippage/fill analysis structurally impossible to separate from order intent); (b) Fold into `domain/position` as a closed-position variant (rejected — a Position is point-in-time exposure, not a round-trip outcome record; the semantics differ). | LOCKED |
| 13 | Split "Strategy Specification" (declarative, non-executable, `research/strategy_specifications`) from "Strategy Implementation" (the one canonical executable, `trading_engine/strategy_execution`), and grant `research/backtesting` a narrow, documented, read-only dependency on the implementation module only (not order/execution/broker/risk/session modules) for backtest/live code-path parity. | Section 4 explicitly requires the architecture to make it "difficult or impossible to confuse a research artifact with a production executable." Without this split, nothing prevented a future contributor from writing runnable strategy code inside `research/` and drifting from what runs live. The narrow exception is required by Rule 5.5 (identical code path in backtest and live) and is preferable to duplicating strategy logic in two places. | (a) Let each strategy be implemented twice (once for backtest, once for live) — rejected, directly violates Rule 5.5 parity and is a known source of research/production behavior drift in trading systems; (b) Make the dependency bidirectional or blanket (`research/` may depend on all of `trading_engine/`) — rejected, would erase the isolation Rule 5.1 and 5.2 rely on. | LOCKED |
| 14 | Explicitly bound Control Plane authority to binary/supervisory actions only (stop/allow, disable/enable a strategy's *state*, block/unblock new orders, detect/report failures) and forbid it from ever originating a signal, sizing a position, or choosing an order. | Section 10 explicitly requires the Control Plane "must not become a second trading engine." The Checkpoint 1 structure implied this but never stated the boundary explicitly enough to prevent future scope creep into `control_plane/kill_switch`. | (a) Leave the boundary implicit (rejected — Section 10 explicitly asked for it to be made explicit); (b) Give Control Plane its own signal/order authority for emergency unwind trades (rejected — that would require it to duplicate risk_engine/order_management logic, i.e. become a second trading engine, explicitly forbidden). | LOCKED |
| 15 | Formalize the AI Authority Model as Capability (`ai_agent/proposals`, `research_assist`) → Governance/Approval (a human or governed process copying an approved proposal into its real domain home — an *action*, not a directory) → Trading Authority (`trading_engine/`, entirely outside `ai_agent/`'s reach). `ai_agent/` is declared write-isolated: it may write only inside itself. | Section 11 requires "AI → Broker direct access" to be impossible by design, not merely documented, and asks for an explicit Capability vs. Governance vs. Trading-Authority distinction. Making "approval" an action rather than a directory avoids inventing a fake "approval data model" that doesn't correspond to anything real at this checkpoint (no business logic yet). | (a) Create an `ai_agent/approvals/` directory (rejected — approval is an action performed by an external actor/process, not a data record `ai_agent/` itself owns; owning it there would blur who has authority); (b) Leave the boundary as convention only (rejected — Section 11 explicitly requires "impossible by design"). | LOCKED |
| 16 | Reviewed `research/`'s 16 subdirectories against the simplification test (Section 15) and the extensibility test (Section 16) and made **no merges**. | Each subdirectory maps 1:1 to an explicit sequential lifecycle stage mandated in the Checkpoint 1 brief (Section 6: IDEA → DISCOVERY → ... → ROBUSTNESS VALIDATION) and produces a genuinely distinct artifact type (idea note vs. discovery scan vs. hypothesis doc vs. backtest result vs. walk-forward result vs. Monte Carlo result vs. robustness-gate decision, etc.). Nesting walk_forward/monte_carlo under robustness_validation was considered and rejected because the brief stages them as sequential peers, not parent/child. | (a) Nest `walk_forward` and `monte_carlo` under `robustness_validation/` to reduce top-level count (rejected — contradicts the explicit sequential staging in the Checkpoint 1 brief and the peer relationship between "producing a robustness result" and "gating on the aggregate of all robustness results"); (b) Merge `ideas` and `discovery` (rejected — distinct artifact types: a one-line pitch vs. a broader exploratory scan that may produce many ideas). | LOCKED |

## Checkpoint 3 — Technology Mapping, Repository Governance & Implementation Blueprint (2026-08-12)

Full rationale, decision matrices, and architectural-compatibility test
results for every row below are in
[TECHNOLOGY_MAPPING.md](TECHNOLOGY_MAPPING.md) — this table records only the
decision, one-line reason, and top alternatives for the change-log format
consistent with #1–#16 above.

| # | Decision | Reason | Alternatives Considered | Status |
|---|---|---|---|---|
| 17 | Backend/API: Django + Django REST Framework + Django Channels (ASGI) on Python 3.12. | Best fit for the platform's control-plane/governance/admin-heavy surface plus live WebSocket dashboards in one deployable, without adding a second service. | FastAPI (rejected as primary — no admin/mature-ORM equivalent; kept as a documented future escape hatch for a single demonstrated-need hot path only). | LOCKED |
| 18 | Dependency management: Poetry. Linting/formatting: Ruff. Static typing: mypy strict. | "Boring, reliable" over trendy; one lockfile tool, one lint/format tool, mandatory strict typing for a financial codebase. | `uv` (rejected for now — shorter production track record; revisit later without structural cost). | LOCKED |
| 19 | Database: PostgreSQL as the single relational engine, with the TimescaleDB extension for historical/time-series market data; Redis for cache/transient only; Parquet files (+ Postgres metadata rows) for bulk research datasets. | Keeps the system-of-record and time-series store on one engine (lower ops burden); avoids adding ClickHouse/InfluxDB/Kafka without a demonstrated scale need at Indian cash-equity intraday volumes. | MySQL (weaker type system for financial invariants); dedicated TSDB (unjustified second database technology); Postgres-only bulk research storage (would bloat the transactional DB). | LOCKED |
| 20 | Async/background processing: Celery with Redis as broker + result backend; Celery Beat for scheduled tasks. Live tick fan-out via Redis Pub/Sub. | Reuses the Redis already required for cache — smallest reliable solution; sufficient for reconciliation/notification/backtest-job/scheduled-task volumes at this platform's scale. | RabbitMQ (extra infra, no demonstrated routing need); Kafka (explicitly rejected — high-throughput event streaming not justified for cash-equity intraday, this is the brief's named anti-pattern to avoid). | LOCKED |
| 21 | Frontend: React + TypeScript + Vite. | Largest ecosystem for real-time dashboard/charting components; strongest pairing with generated TypeScript contract types for drift detection. | Vue+TypeScript (lighter but smaller financial-charting ecosystem); server-rendered Django templates (fights directly against the live, WebSocket-driven dashboard requirement). | LOCKED |
| 22 | Contract generation: `application/contracts` → OpenAPI 3.x (via drf-spectacular) → generated TypeScript types in `frontend/shared/generated_contracts`, diffed in CI. | Smallest mechanism that turns "frontend/backend contract drift" into an actual CI failure rather than a documentation promise. | GraphQL (no demonstrated flexible-query need, complicates the REST+WebSocket hybrid); a custom generator (unjustified engineering effort given mature OpenAPI tooling). | LOCKED |
| 23 | Testing stack: pytest + pytest-django (unit/integration), Hypothesis (property-based, esp. Decimal financial math), schemathesis (contract), testcontainers-python (integration against real Postgres/Redis), Playwright (E2E). | Covers unit → integration → contract → property-based → E2E in one coherent, pytest-centered toolchain; testcontainers avoids adapter tests silently drifting from real dependency behavior via over-mocking. | Mocked-only integration tests (rejected — risk of drifting from real DB/broker/market-data behavior). | LOCKED |
| 24 | Observability: `structlog` (structured operational logs), Prometheus (metrics), OpenTelemetry SDK wired in now with backend deferred, Sentry (error tracking); audit records stored durably in PostgreSQL, never as log files. | Matches the required four-way distinction (Operational Logs vs. Audit Records vs. Trading Events vs. Research Artifacts) with each tool boring/standard in its own niche. | Logging-as-audit-trail (rejected — audit records must be durable/queryable/joinable, not log-file-based). | LOCKED |
| 25 | Architecture enforcement: `import-linter`, run as a required CI check, encoding the Presentation→Application→Bounded-Context→Domain←Infrastructure layering and the narrow `research.backtesting → trading_engine.strategy_execution` exception as explicit, CI-enforced contracts. | Turns `DOMAIN_BOUNDARIES.md`'s dependency rules from documentation into a build failure on violation, per Section 19's explicit requirement not to rely solely on README documentation. | Custom static-analysis tooling built in-house (rejected as unjustified effort given `import-linter` already exists and fits); relying on code review alone (rejected — not mechanical enough for a financial platform). | LOCKED |
| 26 | CI/CD: GitHub Actions running format/lint/type-check/unit-tests/architecture-check/contract-drift-check/migration-check/secret-scan/dependency-audit on every PR, plus integration tests and a Docker build on merge to `main`. No automatic deployment pipeline yet. | Minimum reliable pipeline; GitHub Actions avoids adopting a second CI platform since the repository is already GitHub-hosted. | A more elaborate deploy pipeline now (explicitly rejected — Section 18 of the brief: "do not create an elaborate deployment pipeline yet"). | LOCKED |
| 27 | Deployment: Docker/`docker-compose` for all environments, single Linux VM per environment (dev/testing/staging-paper/production), with a `TRADING_MODE` (RESEARCH/PAPER/LIVE) safety flag that the trading engine enforces alongside environment-specific settings modules and credential sets. | Ensures dev/paper/prod parity without Kubernetes overhead unjustified at current team size; the three-way simultaneous condition (LIVE flag + production settings + live credentials) makes accidental live trading from a dev machine structurally impossible, satisfying the brief's explicit safety requirement. | Kubernetes (rejected as premature for team size); a single shared environment with a config flag only (rejected — insufficient isolation, one accidental flag flip could reach production). | LOCKED |
| 28 | Financial/time standards: Python `Decimal` (never `float`) for all money/price/quantity/percentage values, backed by PostgreSQL `NUMERIC`; UTC as the sole canonical internal timestamp representation, with IST conversion confined to `domain/session` and the presentation boundary. | Deterministic decimal arithmetic is mandatory for risk/P&L correctness; a single canonical UTC representation with clearly bounded IST conversion points prevents timestamp ambiguity bugs, and India's lack of DST simplifies (but does not eliminate) the exchange-session calendar work. | Float-based financial math (rejected — non-deterministic rounding unacceptable for a trading system); IST as the internal representation (rejected — ambiguous across DST-observing external systems/vendors even though India itself has none). | LOCKED |

## Checkpoint 4 — Repository Bootstrap, Development Tooling & Architecture Enforcement (2026-08-12)

Bootstraps the Checkpoint 3 technology mapping into a real, installable,
CI-validated project. All items below were validated by actually running
the tool, not just configuring it — see taskReport.md's Checkpoint 4
section for the full validation log.

| # | Decision | Reason | Alternatives Considered | Status |
|---|---|---|---|---|
| 29 | Package layout: `src/intraday/` with sub-packages matching the approved bounded contexts (`domain`, `research`, `signal_intelligence`, `trading_engine`, `control_plane`, `communication`, `application`, `infrastructure`); Django settings live in `intraday/settings/` — deliberately NOT named `config/` — to avoid colliding with the repository's already-approved top-level `config/` (configuration *data*, Checkpoints 1-3). | Technology (Django's conventional `config/` settings-package naming) must not distort the approved architecture (Checkpoint 3 §3); renaming avoids a real naming collision without touching either directory's actual responsibility. | Naming the Django settings package `config/` per Django convention (rejected — would collide with and blur the meaning of the approved `config/` data directory); putting settings inside `domain/` or `application/` (rejected — settings are neither a domain contract nor an application gateway). | LOCKED |
| 30 | Integration tests (`tests/integration/*`) connect directly via `psycopg`/`redis-py` and skip gracefully (`pytest.skip`) when PostgreSQL/Redis are unreachable, rather than using `testcontainers-python` to spin up ephemeral containers per test run. | The validation environment for this checkpoint has no Docker daemon available; direct-connect-and-skip achieves the same goal (real dependency behavior, not mocks) when run against the GitHub Actions service containers in CI or a local `docker compose up`, without requiring Docker-in-Docker or a container runtime to be present just to run `pytest`. | `testcontainers-python` as originally listed in decision #23 (deferred, not rejected outright — worth reconsidering once integration tests need per-test container isolation, e.g. testing against multiple Postgres versions; not needed yet). | LOCKED (supersedes the testcontainers detail in decision #23 for this checkpoint) |
| 31 | Playwright is added to `frontend/package.json`'s future devDependencies conceptually (documented) but not installed or configured at this checkpoint. | No frontend screens exist yet to drive with browser E2E tests — installing and configuring Playwright now would have nothing real to exercise, violating "do not create fake implementations to exercise tools" (Checkpoint 4 §5, §33). | Installing Playwright now with a placeholder test (rejected — indistinguishable from faking E2E coverage). | LOCKED (deferred to Checkpoint 14 — Frontend) |
| 32 | `settings/testing.py` uses SQLite for Django's own test-database bootstrap, as an explicitly documented, temporary exception to the PostgreSQL system-of-record decision (#19). | No business models/migrations exist yet — there is nothing PostgreSQL/TimescaleDB-specific to test against, and requiring live PostgreSQL for every `pytest` run would block the "pytest passes" success criterion in any sandboxed/offline environment. Must be revisited at the first checkpoint introducing real domain models. | Requiring PostgreSQL for `settings.testing` from day one (rejected — makes routine test runs dependent on Docker/a live service with no corresponding correctness benefit yet, since no Postgres-specific behavior exists to test). | LOCKED, WITH A MANDATORY FOLLOW-UP at Checkpoint 5+ |
| 33 | CI's `pip-audit` step ignores six specific, currently-unfixable, transitive dev/test-only vulnerability findings (pytest 8.4.2, starlette 0.52.1 via schemathesis) via `--ignore-vuln`, each with an inline comment and an expiry condition (re-evaluate on next dependency bump). | Both findings are in dev-only tooling never shipped in the runtime Docker image; forcing a major-version bump of pytest or exceeding schemathesis's own `starlette<1` constraint right now risks destabilizing a foundational tooling checkpoint for a risk that doesn't reach production. | Blindly force-upgrading pytest/starlette past compatible constraints (rejected — could break pytest-django/hypothesis/schemathesis compatibility without notice); silently accepting the audit failure with no CI gate (rejected — hides the finding instead of tracking it). | LOCKED, TRACKED FOR REMOVAL on next dependency bump |
| 34 | Shared-kernel contract count confirmed as **14**, not 13 (see Checkpoint 4 §29 of the review brief). Both `domain/README.md` and `DOMAIN_BOUNDARIES.md` were updated to state the count explicitly. | The correct count was already implicit in both files' item lists (all 14 were always listed); only the Checkpoint 2 **chat response summary** stated "13" — an off-by-one error never written to a file. This decision closes the discrepancy formally rather than leaving it ambiguous. | Leaving the count unstated / implicit (rejected — Checkpoint 4 explicitly required verifying and correcting it). | LOCKED |
| 35 | Directory-count discrepancy (137 architectural vs. 143 filesystem) resolved and documented precisely: 137 manifest-driven directories (each with a README) + 5 `docs/` subdirectories (created via a separate `mkdir` in Checkpoint 1, not part of the domain manifest) + 1 (`find .`'s own report of the repository root) = 143. Zero `.git/` internals were ever included in that count. | Checkpoint 4 explicitly required resolving this discrepancy without artificially deleting anything to force the numbers to match. | Deleting the 5 `docs/` subdirectories to make the count exactly 137 (rejected — destructive and pointless; they are legitimate, approved documentation homes, just not part of the domain-boundary manifest). | LOCKED |

## Notes

- LOCKED decisions are structural/organizational and do not commit the project
  to any specific technology; they can be revisited only via a deliberate
  restructuring, not silently.
- PENDING APPROVAL decisions require explicit user/stakeholder sign-off before
  the next checkpoint (typically a "Technology Mapping" architecture
  checkpoint) proceeds.
- Decision #10 (technology stack) is now **RESOLVED** — superseded by
  decisions #17–#28 and [TECHNOLOGY_MAPPING.md](TECHNOLOGY_MAPPING.md).
- No decision in this checkpoint required changing any Checkpoint 1–2
  architecture boundary; see TECHNOLOGY_MAPPING.md §21 for the nine
  architecture-compatibility tests confirming this.
- Items still explicitly deferred (not blocking): specific charting library,
  secret-store product and cloud/VM hosting provider, Python 3.13+ adoption
  timing, `uv` vs. Poetry re-evaluation, OpenTelemetry backend selection —
  see TECHNOLOGY_MAPPING.md §22.
- Checkpoint 4 adds two more mandatory follow-ups (decisions #32 and #33)
  that must be revisited at specific future triggers (first domain model;
  next dependency bump) — tracked in taskReport.md's Checkpoint 4 "Known
  Issues / Deferred Items", not merely here.

## Checkpoint 5 — Canonical Domain Contracts (2026-08-12)

Implements the 14 approved shared-kernel contracts as real Python code.
Full contract-by-contract documentation is in
[DOMAIN_CONTRACTS.md](DOMAIN_CONTRACTS.md) — this table records only the
decisions with genuine alternatives.

| # | Decision | Reason | Alternatives Considered | Status |
|---|---|---|---|---|
| 36 | Domain contracts implemented as `@dataclass(frozen=True, slots=True)` value objects (plain Python, not Pydantic/attrs), with `NewType`-based string identifiers rather than UUIDs, and validation performed in `__post_init__` rather than a separate validation layer. | Stdlib-only keeps the domain layer's zero-infrastructure-dependency guarantee trivially true (no third-party validation library to audit for hidden I/O); `frozen=True` gives immutability for free; most domain identities (instrument, strategy) are naturally derivable/human-legible, so opaque UUIDs would be implementation convenience, not a domain requirement (Checkpoint 5 Section 6 test: "why does more than one bounded context require this?" applies equally to *how* an identifier is shaped). | Pydantic (rejected — adds a third-party dependency and its own validation framework where stdlib dataclasses already suffice; also blurs the "domain vs. serialization" line Checkpoint 5 Section 24 explicitly warns against, since Pydantic models double as serializers); UUID identifiers everywhere (rejected — no domain requirement demands opacity; human-legible IDs aid debugging and reproducibility). | LOCKED |

## Notes (Checkpoint 5)

- No new contract was added to the shared kernel beyond the 14 approved at
  Checkpoint 2/3 — the "ask before expanding the kernel" rule (Checkpoint 5
  Section 3) was not triggered; every field needed fit inside an existing
  contract.
- All 14 domain subpackages under `src/intraday/domain/` now have both an
  explicit `__init__.py` (package marker) and a `contracts.py` (the actual
  contract) — a real gap (missing `__init__.py`, relying on implicit
  namespace packages) was found and fixed during this checkpoint's
  `import-linter` validation; see taskReport.md's Checkpoint 5 section.
- `import-linter`'s 5 contracts remain unchanged and still pass 5/5 —
  no architecture rule was weakened to accommodate the new code.

## Checkpoint 6 — Configuration Management & Parameter Governance (2026-08-12)

Implements `application/config_schema`: schema derivation + validated
loaders bridging `config/*.yaml` instances to the Checkpoint 5 domain
contracts. Full detail: [CONFIGURATION_MANAGEMENT.md](CONFIGURATION_MANAGEMENT.md).

| # | Decision | Reason | Alternatives Considered | Status |
|---|---|---|---|---|
| 37 | Config schemas are derived by **introspecting domain dataclasses** (`dataclasses.fields()` + `typing.get_type_hints`) rather than hand-written schema classes (e.g. separate Pydantic/marshmallow models per contract); config instances are static YAML files under `config/*`, parsed by a contract-agnostic `loader.py` and validated by each contract's own `__post_init__` (never re-implemented in the config layer). Strategy *parameters* were explicitly left unmodeled — only `StrategyVersion`'s lineage/maturity shape is configurable. | Introspection is the only mechanism that makes Rule 13 ("never redefine a parameter independently of its domain contract") structurally true rather than a convention to remember; YAML is human-editable, needs no database (none exists yet), and keeps configuration in version control alongside the code it configures — appropriate for this checkpoint's pre-persistence stage. Strategy parameters have no domain contract yet (Checkpoint 5 scope), so schematizing them now would invent unjustified fields. | Hand-written Pydantic/marshmallow schema classes per contract (rejected — a second, independently-maintained field list that WILL drift from the domain dataclass, the exact anti-pattern Rule 13 forbids); JSON instead of YAML (rejected — no comment support, worse human-editability for operator-facing risk/universe config); modeling a generic strategy-parameters dict now (rejected — no domain contract justifies its shape yet). | LOCKED |

## Notes (Checkpoint 6)

- No domain contract was added or modified — `application/config_schema`
  only *consumes* the 14 Checkpoint 5 contracts.
- A real test-collection bug was found and fixed: two unrelated test
  files both named `test_risk.py` (and `test_universe.py`, `test_strategy.py`)
  in different `tests/unit/` subdirectories caused a pytest basename
  collision. Fixed by adding `__init__.py` package markers to every
  `tests/` subdirectory, making each test module's fully-qualified name
  unique — the standard fix for this class of collision, not a
  workaround. See taskReport.md's Checkpoint 6 section.
- `import-linter` remains 5/5 kept, 0 broken (81 files analyzed, up from
  72) — no architecture rule changed.
- **Frontend UX Testing Readiness gate evaluated and NOT triggered**: no
  API endpoint exposes these config schemas yet (`application/contracts`
  is still empty of business content), no persistence layer exists, and
  no frontend screen exists to configure anything through. The gate
  remains open for a future checkpoint once at least one real API
  endpoint + persistence + a corresponding frontend screen exist together.

## Checkpoint 7 — Persistence Foundation & Repository Architecture (2026-08-12)

Implements `application/repositories` + `infrastructure/persistence` for
exactly three concepts (risk configuration, universe, strategy version).
Full detail: [PERSISTENCE_ARCHITECTURE.md](PERSISTENCE_ARCHITECTURE.md).

| # | Decision | Reason | Alternatives Considered | Status |
|---|---|---|---|---|
| 38 | Added `application/repositories/` as a new directory under the approved `application/` layer, holding `typing.Protocol` repository interfaces (one per persisted concept), and added `.importlinter` contract #6 ("application must not depend on infrastructure") to mechanically enforce the dependency-inversion direction. | Checkpoint 7 explicitly required repository/application interfaces; `application/gateways` (existing) is described as "orchestration entry points," a different concept from a persistence-abstraction interface — reusing it would conflate two responsibilities. Contract #2 already forbade domain/bounded-contexts from depending on infrastructure but never covered `application` — a real, previously-latent gap this checkpoint's code would otherwise have silently permitted. | Putting repository interfaces inside `application/gateways` (rejected — conflates orchestration with persistence abstraction); putting them in `domain/` (rejected — domain must stay persistence-unaware, Checkpoint 7 §1); skipping a dedicated interface and having application code import Django models directly (rejected — the explicit anti-pattern Checkpoint 7 §2 forbids). | LOCKED |
| 39 | `settings/testing.py`'s SQLite exception (Checkpoint 4 decision #32) is retired — testing now uses the same PostgreSQL configuration as `settings/base.py`. DB-touching tests are gated by a `requires_postgres` collection-time `skipif` (`tests/postgres_utils.py`) alongside `@pytest.mark.django_db`, so an unreachable PostgreSQL server produces individually-reported skips, not a session-wide failure. Additionally, `DATABASES.OPTIONS.connect_timeout` (default 5s, env-overridable) was added to `settings/base.py` after discovering psycopg has no default connect timeout, which caused `manage.py makemigrations` itself to hang indefinitely against an unreachable host. | Checkpoint 7 explicitly required revisiting the SQLite exception now that real PostgreSQL-specific models exist (NUMERIC precision, JSONB, CHECK constraints) that SQLite cannot faithfully test. A collection-time skipif (not a runtime `pytest.skip()`) is required because pytest-django's session-level test-database creation triggers on the first `django_db`-marked test that actually runs, not merely on marker presence — a body-level skip is too late. The connect-timeout fix is a permanent production-safety improvement (fail fast on an unreachable DB), not merely a workaround for this checkpoint's sandboxed validation. | Keeping SQLite for testing indefinitely (rejected — Checkpoint 7 explicitly forbids this: "do not simply change the test settings back to SQLite to make tests easier"); a runtime `pytest.skip()` inside each test body (rejected — evaluated too late, session-level db setup would already have been attempted and failed hard). | LOCKED |
| 40 | Persistence scope limited to exactly three concepts (RiskLimits via a new `RiskConfigurationRecord` application-layer wrapper, Universe, StrategyVersion), each as one immutable "version" table + one separately-modeled mutable "active pointer" table. `RiskLimits` itself (locked domain contract) was NOT modified to add identity/version fields — those live only in the new application-layer `RiskConfigurationRecord` wrapper. | Checkpoint 7 explicitly required starting with "the smallest justified persistence scope" and explicitly forbade tables for every domain dataclass. Modifying `RiskLimits` to add identity/version would have expanded a locked, approved domain contract for a persistence-layer need — the wrapper pattern keeps the domain contract exactly as approved at Checkpoint 5 while still meeting Checkpoint 7's requirement that "a historical configuration must remain reconstructable." | Persisting every domain contract "for completeness" (rejected — explicitly forbidden, Checkpoint 7 §4); adding `id`/`version` fields directly to `RiskLimits` (rejected — would silently expand a locked Checkpoint 5 contract for a concern, persistence, that Checkpoint 7 §1 says the domain must remain unaware of). | LOCKED |

## Notes (Checkpoint 7)

- `migrate --plan` and an actual `migrate` require a live PostgreSQL
  connection and were **not** run successfully in this environment — no
  PostgreSQL server was available (consistent with every prior checkpoint's
  finding). `makemigrations` (generation) and `makemigrations --check`
  (drift detection) do not require a live connection and were both
  validated successfully. This is reported as a real limitation, not
  papered over — see taskReport.md's Checkpoint 7 section for exact
  commands and results.
- `import-linter` contract count is now 6 (was 5) — the new contract #6 was
  adversarially verified the same way every prior contract has been: a
  violation was deliberately injected, confirmed to break the contract,
  then removed.
- Frontend UX Testing Readiness gate evaluated again — still **NOT
  triggered**: persistence now exists, but no business API endpoint and no
  frontend screen exist yet. `app.bat` was not created. See taskReport.md.

## Checkpoint 8 — Business API & Application Contracts (2026-08-12)

Implements the first business API: read + version-activate endpoints for
risk configuration, universe, and strategy version, under
`/api/v1/config/`. Full detail:
[docs/api/CONFIGURATION_API.md](../api/CONFIGURATION_API.md).

| # | Decision | Reason | Alternatives Considered | Status |
|---|---|---|---|---|
| 41 | Added `application/services/` (use-case orchestration, depends only on repository Protocols) and `infrastructure/api/` (DRF views + URL routing, the HTTP delivery adapter) as two new directories. `infrastructure/api` composes concrete `infrastructure.persistence` repositories with `application.services` — the composition root lives there, not in `application/`, because `.importlinter` contract #6 forbids `application` from depending on `infrastructure`. | An HTTP API is a delivery mechanism ("driving adapter" in ports-and-adapters terms) — architecturally the same category as `infrastructure/persistence` ("driven adapter"), both allowed to depend on `application`, never the reverse. This resolves a genuine tension: something has to wire a concrete repository into a service for a view to use it, and that wiring cannot legally live inside `application/`. | A separate top-level `intraday.composition` module outside every layer (considered — would work, since import-linter's forbidden-module checks are scoped to named layers, but adds a new architectural concept not needed once `infrastructure/api` already provides a legitimate home); putting views inside `application/gateways` (rejected — would require `application/gateways` to import `infrastructure`, directly violating contract #6, confirmed by attempting the equivalent adversarial test pattern used for contract #6 itself at Checkpoint 7). | LOCKED |
| 42 | Extended the Checkpoint 7 `UniverseRepository`/`StrategyVersionRepository` Protocol return types from bare `Universe`/`StrategyVersion` to new wrapper types `UniverseRecord`/`StrategyVersionSnapshot` (adding only `created_at`), mirroring `RiskConfigurationRecord`'s existing pattern. Checkpoint 7's own tests were updated to match. | The Checkpoint 8 API surface needs "when was this version created" for all three resources — a genuine, newly-surfaced requirement (Checkpoint 7 didn't expose a created_at API for universe/strategy, only for risk, since only `RiskConfigurationRecord` needed a wrapper at that checkpoint for a different reason — identity). Not scope creep: the alternative (querying persistence a second time from the view layer to get a timestamp) would leak persistence concerns into `infrastructure/api`. | Adding `created_at` directly to `domain.universe.Universe`/`domain.strategy.StrategyVersion` (rejected — would expand two locked Checkpoint 5 domain contracts for an API/persistence-layer need, the exact anti-pattern avoided for `RiskLimits` at Checkpoint 7); having the view issue a second repository call for the timestamp (rejected — unnecessary complexity when the repository already has the row in hand). | LOCKED |
| 43 | Response bodies are plain Python dicts (`Response(body)`), not `Serializer(...).data` — the `@extend_schema` decorator's declared `responses=` schema drives the OpenAPI shape independently of whether a serializer instance is constructed at runtime, the exact pattern Checkpoint 4's `health.py` already established. Response serializers therefore use `serializers.Serializer[None]` (mypy strict requires a concrete type argument; `None` signals "not instantiated against a model/dataclass instance at runtime"). | Instantiating a DRF `Serializer` purely to call `.data` on a dict that's already in the exact right shape is redundant — the serializer's only job here is to describe the schema for OpenAPI generation. Discovered this was necessary when mypy strict correctly rejected passing a `dict`/`list[dict]` as the `instance` argument to a `Serializer[None]`. | Typing serializers as `Serializer[dict[str, object]]` to permit dict instances (rejected — weakens the type parameter's meaning project-wide for a single-checkpoint convenience); reverting to actually rendering through serializer instances (rejected — reintroduces the exact redundancy just removed, and re-couples response construction to DRF's instance/attribute-access machinery when a plain dict already matches the contract). | LOCKED |

## Notes (Checkpoint 8)

- `import-linter` remains 6 contracts (unchanged) — re-verified 6/6 kept
  with 106 files analyzed (up from 89), confirming `application/services`
  and `infrastructure/api` introduced no violation.
- A real, stale-documentation gap was found and fixed: `application/contracts/README.md`
  still said "Must Not Depend On: Any specific API framework" — written at
  Checkpoint 1 before Checkpoint 3 locked DRF. Updated to reflect that DRF
  is now the locked technology, not a violation of the original intent
  (never invent business meaning untraceable to a domain contract).
- `SPECTACULAR_SETTINGS`'s `DESCRIPTION`/`VERSION` were still Checkpoint-4-era
  ("no domain contracts have been added yet") — found while inspecting the
  generated OpenAPI schema output, corrected to describe the real API.
- Frontend TypeScript contract generation remains deliberately deferred —
  no codegen tool is installed in `frontend/package.json` yet; generating
  types for an API with no frontend consumer would be premature. Named as
  the trigger for the next frontend-focused checkpoint.
- Frontend UX Testing Readiness gate evaluated again: **Persistence YES,
  Business API YES (new this checkpoint), Frontend NO, Human workflow
  NO — overall gate NO.** `app.bat` was not created. See taskReport.md.

## Checkpoint 11 — Authentication, Authorization & Control-Plane Access Boundary (2026-08-12)

Establishes the first-generation authentication/authorization boundary
protecting the Checkpoint 8 configuration API and the Checkpoint 9/10
frontend. Full detail:
[docs/architecture/AUTHENTICATION_AUTHORIZATION.md](AUTHENTICATION_AUTHORIZATION.md).

| # | Decision | Reason | Alternatives Considered | Status |
|---|---|---|---|---|
| 44 | Authentication mechanism: Django session authentication (DRF `SessionAuthentication`) with secure, HttpOnly cookies, not JWT or DRF token auth. | Django's session framework was already installed (Checkpoint 4); HttpOnly cookies are immune to XSS-based token theft (unlike a JWT/token stored where JS can read it); Django's session store gives real, immediate server-side revocation on logout, which a bare JWT cannot provide without a denylist. No cross-service/stateless-token requirement exists yet to justify JWT's added complexity. | JWT (rejected — no demonstrated need for a stateless cross-service token; would require inventing frontend token storage and a refresh/revocation scheme Django sessions already provide); DRF Token auth (rejected — still requires JS-readable token storage, no built-in expiry); OAuth2/SSO (rejected — no external identity provider exists or is planned, explicitly out of scope). | LOCKED |
| 45 | Authorization model: Django's built-in `Group` mechanism (a single `configuration-operators` group, seeded by data migration) plus `is_superuser`, not a bespoke permission table or Django's per-model custom-permission mechanism. | `configuration.activate` is a capability over an application-layer use case spanning three resource types (risk/universe/strategy) — no single Django model naturally owns it, so Django's per-model `Meta.permissions` mechanism doesn't fit. Groups are the standard, simplest Django mechanism for a capability not tied to one model and require zero new tables (reusing `django.contrib.auth`'s existing Group table). | Per-model custom permissions (rejected — no natural owning model); a new bespoke `Capability`/`Role` model (rejected — reinvents what Django's Group model already provides, no demonstrated need for anything Groups can't express yet). | LOCKED |
| 46 | No custom Django user model was introduced — `django.contrib.auth.models.User`, unmodified, is the identity model. | No genuine domain requirement (e.g. email-only login, mandatory extra profile fields) exists yet to justify the migration cost and reduced flexibility of swapping Django's user model this late (Django strongly recommends deciding this before the first migration, and `auth.User` already existed since Checkpoint 4). | A custom `AUTH_USER_MODEL` (considered and rejected per the checkpoint brief's explicit instruction to stop and justify before doing this — no such justification exists yet). | LOCKED |
| 47 | Login/logout/current-user live in `infrastructure/api/auth_views.py`, calling `django.contrib.auth`'s `authenticate()`/`login()`/`logout()` directly — no `application/services` use-case layer, unlike the risk/universe/strategy resources. | Authentication is inherently a framework concern here (Django's session/auth machinery), not a business use case with a repository Protocol to abstract over — there is nothing to swap out via dependency inversion the way a persistence backend is swapped in the configuration resources. Adding a service layer would be indirection with no corresponding architectural benefit. | Routing authentication through an `application/services/auth.py` use-case + repository Protocol, mirroring risk/universe/strategy (rejected — no second "authentication backend" implementation is anticipated or justified; would add ceremony without a real abstraction need). | LOCKED |
| 48 | Added `django-cors-headers` as a new backend dependency, rather than hand-writing CORS header logic. | CORS is a security-sensitive concern (misconfiguration can silently defeat same-origin protection); a mature, minimal, widely-used library is preferable to hand-rolled header logic for something this easy to get subtly wrong. | Hand-written CORS middleware (rejected — reinvents a solved, security-sensitive problem for no benefit). | LOCKED |
| 49 | Rate limiting: DRF's built-in, cache-backed `ScopedRateThrottle` on the login endpoint only (5/min), reusing the existing per-environment `CACHES` backend — no new distributed rate-limiting infrastructure. | Bounds brute-force login attempts without new infrastructure, consistent with "do not add an elaborate distributed security subsystem unnecessarily" (checkpoint brief §26). Sufficient for a single-instance/small-deployment control plane; revisit if the platform gains multiple backend instances needing a shared, IP-reputation-aware view. | A dedicated distributed rate-limiting service (rejected — unjustified infrastructure for current scale); no rate limiting at all (rejected — leaves login open to unbounded brute-force attempts). | LOCKED |

## Notes (Checkpoint 11)

- No backend business logic (risk/universe/strategy services, views'
  response shapes) changed — only `permission_classes` were added to
  existing views. The OpenAPI schema was regenerated and the generated
  TypeScript contract was re-diffed; both changed only by the addition of
  the three new `/api/v1/auth/*` operations, confirmed by direct
  inspection.
- `app.bat` was updated (not recreated) to stop implying "no
  authentication" and to print manual `createsuperuser`/group-assignment
  instructions instead of silently creating any default user — a fixed,
  hard-coded credential in a launcher script would defeat the point of
  adding authentication.
- Frontend UX Testing Readiness gate: unaffected by this checkpoint
  (already YES since Checkpoint 10); this checkpoint protects the
  existing human workflow rather than adding a new one. See
  taskReport.md's Checkpoint 11 section for the full gate re-evaluation.

## Checkpoint 12 — Control-Plane Auditability & Authentication Security Completion (2026-08-13)

Establishes a durable, append-only PostgreSQL audit trail for
risk-configuration activation and closes the login-CSRF gap Checkpoint
11 deliberately deferred. Full detail:
[docs/architecture/AUDITABILITY.md](AUDITABILITY.md).

| # | Decision | Reason | Alternatives Considered | Status |
|---|---|---|---|---|
| 50 | Durable audit storage: a new PostgreSQL table (`AuditLogEntry`, `infrastructure/persistence`), not operational structured logs (`structlog`) and not a new/second database technology. | The architecture already distinguishes operational logs from durable audit records (Checkpoint 3 §11 observability decision); log lines are not queryable/joinable/durable in the way a governance record needs to be. Reuses the existing PostgreSQL system-of-record rather than introducing a new storage technology for one table. | Writing audit events only to structured logs (rejected — not durable/queryable in the sense an audit trail requires); a separate audit-specific database (rejected — unjustified operational complexity for one table). | LOCKED |
| 51 | Append-only enforcement at the Django model layer (`AuditLogEntry.save()`/`.delete()` override, checked via `self._state.adding`), not a database-level trigger or `REVOKE` grant. | Achieves real, test-verified enforcement (not merely "no edit button in the UI") with no new database-administration surface (grants/triggers) for a first implementation. Explicitly documented as a weaker guarantee than DB-level immutability — a raw SQL statement or a QuerySet `.update()` could still bypass it. | Database-level `REVOKE UPDATE, DELETE` / a rejecting trigger (deferred, not rejected — a stronger guarantee worth adding if the threat model, e.g. a compromised application DB credential, later justifies the added operational complexity). | LOCKED, WITH A DOCUMENTED LIMITATION |
| 52 | Actor identity stored as plain `actor_username`/`actor_user_id` columns, not `ForeignKey(auth.User)`. | A ForeignKey forces cascade-deleting audit history on user deletion (destroying exactly what an audit trail exists to preserve) or `on_delete=PROTECT` (blocking user deletion permanently, an operational trap). A snapshot survives both user deletion and username reuse — the standard trade-off for append-only logs (the same one `git blame` makes with historical author names). | `ForeignKey(User, on_delete=CASCADE)` (rejected — destroys historical accountability, the opposite of the checkpoint's goal); `ForeignKey(User, on_delete=PROTECT)` (rejected — makes user deletion operationally impossible, discovered too late by an administrator). | LOCKED |
| 53 | State change + audit append committed in ONE `transaction.atomic()` block inside `DjangoRiskConfigurationRepository.activate()` — the write path is not exposed through a separate `AuditRepository` Protocol method at all. | The checkpoint's core requirement ("a successful activation cannot exist without its audit record") can only be guaranteed if both writes share one transaction; exposing a generic, independently-callable `AuditRepository.append()` would make that coupling optional rather than structural. Verified by a real-transaction rollback test (`test_activation_rolls_back_if_audit_write_fails`), not a mocked service. | A generic, callable `AuditRepository.write()` used by the service after a separate `repository.activate()` call (rejected — two independent writes cannot be atomically guaranteed from the application layer, which cannot depend on `django.db.transaction`, an infrastructure API, per contract #6). | LOCKED |
| 54 | `ActivationOutcome` has exactly three values (`activated`/`already_active`/`rejected`), and a rejected (invalid-target) attempt is recorded in its own, independently-committed write — deliberately NOT inside the same atomic block as a successful activation (there is no successful state change to couple it to). | Checkpoint 10 already established idempotent activation as a real "no state change occurred" case; recording it as `activated` would be a false claim. A rejected attempt must survive its own request even though nothing changed, which requires it to commit independently of the (never-attempted) state-change transaction. | A single generic "attempted" outcome with no further distinction (rejected — loses exactly the "did this actually change anything" signal the brief asks the audit trail to answer honestly). | LOCKED |
| 55 | Authorization-denied (HTTP 403) activation attempts are NOT written to the durable audit table — only requests that reach an authenticated, authorized principal are recorded (success, no-op, or invalid-target rejection). | DRF's permission classes reject the request before the view body — and therefore the write path — ever runs; writing audit rows from inside a permission class would mix an authorization check with a persistence side effect and add write I/O to every rejected request, including anonymous scans. Judged not worth the complexity/cost for this checkpoint against the brief's own "do not create an audit record for every anonymous rejected HTTP request." | Writing a 403 audit event from a permission class or a global exception handler (deferred, not rejected outright — revisit if a future checkpoint's threat model specifically requires visibility into authorization-denial attempts). | LOCKED, DOCUMENTED BOUNDARY |
| 56 | Login-CSRF fixed by resetting `login_view.csrf_exempt = False` (re-enabling Django's real `CsrfViewMiddleware` for that one view), not a hand-rolled token scheme. | DRF's `APIView.as_view()` wraps every view in `csrf_exempt()` by default, delegating CSRF enforcement to `SessionAuthentication.enforce_csrf()` - which only checks once a session user is already resolved, so `login` (necessarily anonymous) was never checked. Un-exempting the one view re-enables the SAME real, framework-provided middleware protecting every other endpoint - no new mechanism, no `@csrf_exempt` used (the opposite - an exemption is removed), no frontend change needed (the CSRF cookie/header flow already existed). | A custom "login token" issued out-of-band (rejected — reinvents CSRF protection Django already provides); leaving login unprotected with a documented risk-acceptance note only (rejected once a real, low-cost fix — one attribute flip — was found; risk-acceptance is for cases with no cheap fix, not this one). | LOCKED |

## Notes (Checkpoint 12)

- Real regression found and fixed: `tests/unit/infrastructure/api/{test_risk_api,test_universe_api,test_strategy_api}.py`
  never authenticated their test `Client` before calling endpoints that
  Checkpoint 11 protected with `IsAuthenticated`/`IsConfigurationOperator`.
  Because these tests are always `requires_postgres`-skipped in every
  sandbox this project has been validated in, the regression was never
  actually exercised or caught until this checkpoint's audit-focused
  review inspected them directly (not merely re-run). Fixed by adding
  `client.login(...)` (reader or operator, as each test needs) before
  every protected-endpoint call.
- `app.bat` gained a `manage.py migrate` step — a separate, real,
  pre-existing gap found while touching this file: it never applied
  database migrations at all, so a fresh checkout's first run would be
  missing every table, including this checkpoint's new `AuditLogEntry`.
  Idempotent, safe to re-run, consistent with the rest of the script.
- Frontend UX Testing Readiness gate: unaffected by this checkpoint
  (already YES since Checkpoint 10) — this checkpoint adds governance/
  security depth to the existing workflow rather than a new one. No
  frontend functional change was required; only the generated contract
  was regenerated (new audit types, unconsumed by any screen yet).

## Checkpoint 13 — Complete Configuration Control-Plane Governance (2026-08-13)

Extends the Checkpoint 12 authenticated-actor + authorization + durable-
audit pattern, established for risk-configuration activation, to Universe
and Strategy Version activation. Full detail:
[docs/architecture/AUDITABILITY.md](AUDITABILITY.md).

| # | Decision | Reason | Alternatives Considered | Status |
|---|---|---|---|---|
| 57 | `AuditLogEntry`/`ActivationOutcome`/`AuditEvent` (Checkpoint 12) reused verbatim for Universe and Strategy Version — no new model, no new enum values, no schema migration. `resource_type`/`resource_id` (already generic) absorb the new resource types directly. | Checkpoint 12's vocabulary was deliberately kept generic for exactly this extension. Confirming it required zero schema change validates that design decision rather than requiring a new one. | A per-resource `RiskAuditEvent`/`UniverseAuditEvent`/`StrategyAuditEvent` model hierarchy (rejected — the checkpoint brief explicitly warns against this, and no field genuinely differs by resource type). | LOCKED |
| 58 | Strategy Version's 3-tuple identity (`specification_version`, `code_version`, `configuration_version`) is flattened into `AuditLogEntry.version_identifier` as `"{spec}:{code}:{config}"` for the audit row only — the domain/application identity itself is never flattened. | `version_identifier` is a single `CharField`; adding three additional nullable columns for one resource type's compound identity was judged unjustified schema complexity for what only needs to be a readable audit label, not an independently structured/queryable key. | Three additional nullable columns on `AuditLogEntry` used only by strategy-version rows (rejected — schema complexity for a single resource type, when a lossy-in-theory-only string label is sufficient for every actual current use). A separate `StrategyActivationAuditEntry` model (rejected — reintroduces the per-resource-model duplication decision #57 explicitly avoided). | LOCKED, WITH A DOCUMENTED LIMITATION (a version value containing `:` could make the flattened string ambiguous to parse back — not currently exercised or required) |
| 59 | Audit read API: three resource-specific endpoints (`/api/v1/audit/risk-configuration/{id}/`, `/api/v1/audit/universe/{id}/`, `/api/v1/audit/strategy/{id}/`), not one generic `/api/v1/audit/{resource_type}/{resource_id}/` route. | Evaluated explicitly per the checkpoint brief's instruction. A generic route would accept an arbitrary `resource_type` string with no OpenAPI-level documentation of valid values, and would be inconsistent with the configuration API's own existing resource-specific convention (`/api/v1/config/risk/...`, never `/api/v1/config/{resource_type}/...`). The three views share one private helper to avoid duplicating response-shaping logic. | A single generic `/api/v1/audit/{resource_type}/{resource_id}/` route (rejected — weaker OpenAPI schema clarity, inconsistent with the existing configuration-API convention). | LOCKED |
| 60 | The three `DjangoXRepository.activate()` method bodies (existence check → `get_or_create` → outcome determination → audit append, all in one `transaction.atomic()`) remain independently written per resource, not factored into a shared/generic activation helper. | The three methods differ in identity shape (single version vs. 3-tuple) and pointer model (`ActiveUniverse` vs. `ActiveStrategyVersion`'s three columns); a generic version would need type parameters or a callback-based extraction step costing more in indirection than the ~15 duplicated lines it would save. Explicitness over premature abstraction, per the checkpoint brief's own instruction. | A `GenericActivationService<T>`/shared activation-with-audit helper (rejected — the brief explicitly warns against this; the actual duplication is small and the resource-specific differences are real, not incidental). | LOCKED |
| 61 | The Checkpoint 12 decision not to audit HTTP 403 (authorization-denied) attempts, and to keep audit append-only enforcement at the application level (not database-level), were both re-reviewed for this checkpoint and explicitly retained unchanged. | Extending the pattern to two more resources introduced no new information that would change either tradeoff — the same cost/value analysis (I/O-on-every-403; migration/portability/admin-access complexity for DB-level triggers) applies identically across all three resources. Documented as a deliberate re-affirmation, not a default carry-over. | Auditing 403s now that three resources are covered (rejected — no new justification emerged); adding DB-level immutability now (rejected — same reasoning as Checkpoint 12, re-verified not newly required). | LOCKED (re-affirmed) |

## Notes (Checkpoint 13)

- A second, independent, DB-free regression guard was added:
  `tests/unit/architecture/test_activation_authorization_wiring.py`
  introspects every read/activate/audit view's DRF `permission_classes`
  directly (no database, no Django test client) - runs unconditionally
  in every environment, unlike the `requires_postgres`-gated integration
  tests that hid the Checkpoint 12 regression. Confirms all three
  resources' activate/audit permission sets are identical.
- No schema migration was required this checkpoint - `AuditLogEntry`
  and its indexes, created at Checkpoint 12, needed no changes to serve
  Universe and Strategy Version as well.
- Frontend UX Testing Readiness gate: unaffected (already YES since
  Checkpoint 10) - no frontend functional change was made; only the
  generated contract was regenerated (two new audit read operations,
  unconsumed by any screen yet). All 30 pre-existing frontend tests
  re-verified passing, unchanged.

## Checkpoint 14 — Market Data & Instrument Foundation (2026-08-13)

Establishes the provider-neutral historical market-data foundation
future indicator/signal/backtesting/strategy checkpoints will consume.
Full detail: [docs/architecture/MARKET_DATA_ARCHITECTURE.md](MARKET_DATA_ARCHITECTURE.md).

| # | Decision | Reason | Alternatives Considered | Status |
|---|---|---|---|---|
| 62 | `Bar` (Checkpoint 5) extended with `adjustment: PriceAdjustment` (`RAW`/`ADJUSTED`, default `RAW`) — a genuine extension of a locked domain contract, same precedent as Checkpoint 7's `RiskLimits` extension. | Whether a bar's prices are raw or corporate-action-adjusted is intrinsic to the bar itself, not a wrapper-layer concern — and the checkpoint brief explicitly requires an "explicit contract/field/decision" rather than silent adjustment. No adjustment computation exists anywhere; `ADJUSTED` is not reachable from any code path yet. | A wrapper type (`AdjustedBar`) instead of extending `Bar` directly (rejected — every consumer would need to know two Bar-like types instead of one, for a property every bar genuinely has). | LOCKED |
| 63 | `Bar.timestamp`'s existing Checkpoint 5 meaning (bar CLOSE time) is re-confirmed explicitly, not re-decided, and pinned with a dedicated regression test. | The checkpoint brief required the semantics not be left ambiguous; inspection showed Checkpoint 5 had already made and documented this decision correctly — re-litigating it would be pointless, but leaving it undocumented at THIS checkpoint (which builds arithmetic directly on it, in `expected_bar_timestamps()`) would risk a future silent drift. | Redefining timestamp as bar OPEN time (rejected — would contradict Checkpoint 5's existing, working contract and the convention Indian market-data vendors already use). | LOCKED (re-affirmed) |
| 64 | Market-data integrity functions (`ensure_chronological`, `timeframe_to_timedelta`, `expected_bar_timestamps`, `missing_bar_timestamps`) live in `domain/market_data/quality.py` — domain layer, not application layer. | These rules are intrinsic to what a valid Bar *series* means (parallel to `Bar.__post_init__` validating what a valid single Bar means) and must be identically true for every future consumer (research, live, backtesting) per Rule 5.5 parity — the same reason single-bar validation already lived in the domain layer. | Putting series validation in `application/services/market_data.py` instead (rejected — would let a different bounded context reimplement slightly different ordering rules, breaking parity). | LOCKED |
| 65 | Series-ordering violations (out-of-order, duplicate timestamps) are REJECTED (raise), never silently reordered or flagged-and-kept — but series *completeness* (missing intervals) is reported as a value, not rejected. | Ordering/duplication has no legitimate reason to occur and silently tolerating it would let corrupted data reach a future strategy calculation undetected. Incompleteness, by contrast, can be legitimate (a session in progress, data not yet ingested) — the domain layer cannot judge whether that's an error for a given caller's use case, so it reports the gap and lets the caller decide. | Rejecting incomplete series too (rejected — over-broad; a live, in-progress session is never "complete" by definition, and treating that as an error would make the function unusable for its main purpose). | LOCKED |
| 66 | Historical market-data persistence (a real TimescaleDB-backed table) is deliberately NOT built this checkpoint — only an in-memory/fixture-backed path exists. | No real ingestion pipeline exists yet to populate a persistence table; building schema for zero real data would be premature relative to the existing TimescaleDB decision (#19), which this checkpoint does not redesign. The fixture adapter already makes the domain->application->infrastructure path fully testable without a database. | Building the hypertable now, ahead of ingestion (rejected — the checkpoint brief explicitly warns against "production-scale partitioning" and "ingesting large historical datasets" this checkpoint; premature schema with no real consumer). | LOCKED, WITH A MANDATORY FOLLOW-UP when real ingestion is authorized |
| 67 | No API view, URL, or OpenAPI/frontend surface was added for market data this checkpoint. | No real consumer (feature engine, backtester, dashboard) exists yet to justify one; the checkpoint brief explicitly warns against building UI/API merely to prove a capability works. Confirmed by diffing the regenerated OpenAPI schema — byte-identical to before this checkpoint. | Adding a minimal read-only market-data endpoint anyway "for completeness" (rejected — no consumer, and Checkpoint 8's own precedent already established endpoints are added only when a real API boundary is genuinely needed). | LOCKED |

## Notes (Checkpoint 14)

- Instrument identity (Checkpoint 5's `Instrument`/`make_instrument_id`)
  needed NO changes — already correctly distinguishes NSE from BSE
  listings of the same symbol and already keeps `symbol` distinct from
  `instrument_id`. No ISIN, segment, or provider-token field was added
  speculatively; confirmed nothing in this checkpoint's scope requires
  one.
- `TradingSession` gained one method (`.contains()`) but no new fields
  and no calendar/holiday logic — it remains "the shape of one already-
  determined session" exactly as Checkpoint 5 defined it.
- `import-linter` remains 6/6 kept (123 files analyzed, up from 119) —
  the new `domain/market_data/quality.py`,
  `application/services/market_data.py`, and
  `infrastructure/market_data_providers/fixtures.py` all respect the
  existing layering with no new contract needed.
- All 38 new tests pass genuinely (not skipped) - none require
  PostgreSQL, since this checkpoint's entire scope (domain contracts,
  application service, fixture adapter) is deliberately DB-free. This is
  the first checkpoint since Checkpoint 6 where new functionality is
  100% testable without PostgreSQL.
- Frontend UX Testing Readiness gate: unaffected - no frontend or API
  surface exists for market data yet, so there is nothing new for a
  human to interact with via the control plane. Gate remains YES from
  Checkpoint 10 for the existing configuration workflow; market data
  itself has no UI/API boundary to evaluate against the gate yet.

## Checkpoint 15 — Feature Engine Foundation (2026-08-13)

Establishes the first technology-neutral feature computation (Simple
Moving Average) and the architecture future EMA/RSI/ATR/VWAP/Supertrend/
Bollinger Bands features will follow. Full detail:
[docs/architecture/FEATURE_ENGINE_ARCHITECTURE.md](FEATURE_ENGINE_ARCHITECTURE.md).

| # | Decision | Reason | Alternatives Considered | Status |
|---|---|---|---|---|
| 68 | The actual feature computation (`compute_simple_moving_average`) lives in `signal_intelligence/feature_engine` (a bounded context), depending only on `domain/feature`+`domain/market_data`; a separate `application/services/feature_engine.py` (`FeatureEngineService`) orchestrates it together with `HistoricalMarketDataService`. | Reconciles the checkpoint brief's instruction ("Feature Engine -> HistoricalMarketDataService -> Repository -> Infrastructure") with this project's own pre-existing, locked architecture (`signal_intelligence/feature_engine/README.md`, Checkpoint 1: "Depends On: domain/feature, domain/market_data" - not `application`) and `.importlinter` contract #3's `layers` type (`application` above `signal_intelligence` above `domain` - a bounded context may never import `application`). Splitting calculation (bounded context) from orchestration (application) satisfies both simultaneously; verified by `lint-imports` 6/6 kept - the first real exercise of contract #3's `signal_intelligence` layer in this codebase. | Putting the whole Feature Engine (calculation + orchestration) inside `application/services/` (rejected - would leave `signal_intelligence/feature_engine`'s already-decided-at-Checkpoint-1 responsibility unfulfilled, and contradicts its own README's dependency list); putting the whole thing inside `signal_intelligence/feature_engine` including the `HistoricalMarketDataService` call (rejected - `.importlinter` contract #3 forbids a bounded context from importing `application` at all). | LOCKED |
| 69 | Feature identity (`SimpleMovingAverageDefinition`) is a single-field frozen dataclass (`lookback: int`) with `feature_name`/`feature_version` properties, deriving `"sma_{lookback}"` - not a generic `FeatureDefinition` registry/framework. | SMA has exactly one parameter; a registry/generic-definition framework would be built for a "someday" second feature that doesn't exist yet in this checkpoint's scope. Follows `FeatureValue`'s own Checkpoint 5 docstring convention (`"ema_20"` as the worked example of a name baking its parameter in) rather than inventing a new identity scheme. | A generic `FeatureDefinition(name: str, parameters: dict)` framework (rejected - the checkpoint brief explicitly warns against this; no second feature exists yet to prove the framework's shape is even correct). | LOCKED |
| 70 | Warm-up semantics: the first `lookback - 1` bars produce NO output (not `None`, not a shorter-period average) - exactly `lookback` observations are required before the first `FeatureValue` is emitted. | Matches the checkpoint brief's own explicit recommendation and the standard, unambiguous convention for a fixed-window indicator - a shorter-period average during warm-up would be a silently different (and silently degrading) calculation being presented as the same one. | Emitting a shorter-period average during warm-up (rejected - explicitly warned against, "do not silently calculate a shorter-period average"); emitting `None`/a zero value during warm-up (rejected - `FeatureValue.value` is typed `Decimal`, not optional; inventing a sentinel would contradict the existing Checkpoint 5 contract). | LOCKED |
| 71 | `FeatureValue.timestamp` for SMA equals the source bar's own timestamp (itself the bar's CLOSE time, per Checkpoint 14) - no second timestamp convention. | The checkpoint brief required an explicit, non-ambiguous timestamp-alignment decision; reusing the bar's own already-decided CLOSE-time convention is the only choice that doesn't introduce a second, potentially-conflicting notion of "when" a value belongs to. | A feature-specific timestamp offset (e.g. "N bars after the window start") (rejected - unnecessary complexity, and would make aligning multiple simultaneous features to the same instant harder for a future consumer, not easier). | LOCKED |

## Notes (Checkpoint 15)

- `domain/feature/contracts.py`'s `FeatureValue` (Checkpoint 5) required
  ZERO changes - already exactly the right shape. Confirms Checkpoint 5's
  own forward-looking design (an OUTPUT-only contract, explicitly
  deferring computation to "a later checkpoint") was correct in practice,
  not just in intent.
- `import-linter` remains 6/6 kept (128 files analyzed, up from 123) -
  `signal_intelligence/feature_engine`'s new code and
  `application/services/feature_engine.py` both respect the existing
  layering with no new contract needed.
- All 31 new tests pass genuinely (not skipped) - continuing Checkpoint
  14's discipline of keeping new functionality 100% testable without
  PostgreSQL.
- No API/frontend surface was added - confirmed via a regenerated,
  byte-unchanged-in-substance OpenAPI schema (zero feature/SMA
  references). Frontend UX Testing Readiness gate unaffected (already
  YES since Checkpoint 10; nothing new for a human to interact with).
- Versioning: `pyproject.toml` (0.8.0) and `SPECTACULAR_SETTINGS["VERSION"]`
  (0.11.0) both checked and left unchanged - no API surface changed this
  checkpoint.

## Checkpoint 16 — EMA Feature & Recursive/Stateful Feature Computation (2026-08-13)

Proves the Feature Engine architecture generalizes from a fixed-window
calculation (SMA) to a recursive/stateful one (EMA). Full detail:
[docs/architecture/FEATURE_ENGINE_ARCHITECTURE.md](FEATURE_ENGINE_ARCHITECTURE.md#checkpoint-16--exponential-moving-average-recursivestateful-computation).

| # | Decision | Reason | Alternatives Considered | Status |
|---|---|---|---|---|
| 72 | EMA is seeded with `SMA(N)` of the first `N` closes (`EMA_N = mean(close_1..close_N)`), then the standard recursive relationship applies for every bar after the seed. The first `N-1` bars produce no output; the `N`th bar's timestamp carries the seed value. | Gives stable, cross-checkable, widely reproducible results (the standard convention used by the overwhelming majority of charting/quant platforms), aligns naturally with this project's existing SMA foundation, and gives EMA the identical warm-up length as SMA of the same period - satisfying the checkpoint brief's explicit instruction to prefer the convention with these properties. | Seeding with the first close alone, `EMA_1 = close_1` (rejected - permanently biases the entire recursive series toward one noisy observation, and the "first EMA value" at bar 1 isn't meaningfully a period-N value, just a mislabeled raw close). | LOCKED |
| 73 | The EMA seed (mean of the first `N` closes) is computed LOCALLY inside `ema.py`, not by calling `sma.compute_simple_moving_average`. `sma.py` and `ema.py` have no dependency edge on each other. | Calling the SMA function to derive EMA's seed would couple EMA's internal seed to SMA's own public output type and versioning - a future rounding-policy change to SMA would then silently change EMA's seed too (action-at-a-distance). Keeping the two computations independent, each depending only on `domain/feature`+`domain/market_data`, means a future removal or rewrite of either can never break the other. | Calling `compute_simple_moving_average` internally and discarding the `FeatureValue` wrapper to extract just the numeric mean (rejected - still creates a semantic coupling between two independently-versioned features, and adds an unnecessary intermediate `FeatureValue` construction/discard for a private internal computation). | LOCKED |
| 74 | No new stateful abstraction (`FeatureStateMachine`/`IndicatorFramework`/`GenericRecursiveEngine`) was introduced. `compute_exponential_moving_average` keeps the identical `compute_*(definition, bars) -> tuple[FeatureValue, ...]` functional shape as SMA; "state" is a single local `Decimal \| None` accumulator scoped to one function call. | The checkpoint's own instruction was "minimum abstraction, maximum correctness" - a single scalar accumulator inside a pure function is sufficient to prove recursive computation works within the existing architecture; building a generic engine for a second data point would be speculative. | A `FeatureCalculator` protocol/class hierarchy generalizing "stateful" vs "stateless" features (rejected - no third calculation exists yet to prove that abstraction's shape is even correct; premature generalization from n=2). | LOCKED |
| 75 | `ExponentialMovingAverageDefinition(lookback: int)` reuses the exact one-off, single-field dataclass pattern `SimpleMovingAverageDefinition` established at Checkpoint 15 - still no generic `FeatureDefinition` registry. | Confirms the Checkpoint 15 prediction that this pattern scales to a second feature without a framework; `feature_name` follows the identical `"ema_{lookback}"` convention `FeatureValue`'s own Checkpoint 5 docstring already specified as its worked example. | A shared `FeatureDefinition` base class for the now-two definitions (considered, rejected for now - two nearly-identical one-line classes do not yet justify inheritance machinery; a small shared `_validate_lookback()` helper function was extracted instead, the minimum de-duplication that doesn't build a framework). | LOCKED |

## Notes (Checkpoint 16)

- `domain/feature/contracts.py`'s `FeatureValue` (Checkpoint 5) again
  required ZERO changes for EMA - the same OUTPUT-only contract serves
  both a fixed-window and a recursive calculation without modification,
  confirming its design generalizes as intended.
- `import-linter` remains 6/6 kept - `ema.py` and the extended
  `FeatureEngineService` respect the existing layering with no new
  contract needed; no new dependency edge was introduced between
  `sma.py` and `ema.py` (deliberately, decision #73).
- All new tests pass genuinely (not skipped) - continuing the same
  100%-DB-free discipline as Checkpoints 14 and 15.
- No API/frontend/persistence/Dhan surface was added - confirmed via a
  regenerated, byte-unchanged-in-substance OpenAPI schema.
- Versioning: `pyproject.toml` and `SPECTACULAR_SETTINGS["VERSION"]`
  both checked and left unchanged - no API surface changed this
  checkpoint. `FEATURE_ENGINE_VERSION` ("v1") was reused as-is for EMA,
  not bumped - EMA's introduction does not change SMA's own computation
  semantics.

## Checkpoint 17 — ATR Feature & Frontend UX Validation (2026-08-13)

Adds Average True Range - the Feature Engine's first non-close-only
computation, an explicit architectural stress test - and performs the
project's first human-oriented (not merely automated) validation of the
existing authentication/control-plane frontend. Full detail:
[docs/architecture/FEATURE_ENGINE_ARCHITECTURE.md](FEATURE_ENGINE_ARCHITECTURE.md#checkpoint-17--average-true-range-the-first-non-close-only-feature)
and `taskReport.md`'s Checkpoint 17 section for the UX findings.

| # | Decision | Reason | Alternatives Considered | Status |
|---|---|---|---|---|
| 76 | ATR uses the canonical WILDER convention (`ATR_N = mean(TR_1..TR_N)` seed, then `ATR_t = ((ATR_(t-1)*(N-1)) + TR_t)/N`) - not an EMA-based ATR. | Wilder's own 1978 formulation is what "ATR" universally means across charting/quant platforms; no prior architecture decision in this codebase suggested an alternative, and the checkpoint brief explicitly named Wilder as the preferred convention absent contrary evidence. | An EMA-based ATR reusing this project's own `alpha=2/(N+1)` convention applied to True Range (rejected - a different, less-conventional indicator that only some libraries also label "ATR"; would silently redefine what "ATR" means in this codebase without justification). | LOCKED |
| 77 | The first bar in any input series produces NO True Range/ATR value - it has no previous close. `bars[0]` is used only to supply `Close_(t-1)` for `bars[1]`'s TR. Warm-up requires `N+1` bars total (one more than SMA/EMA's `N`), output count is `M-N` (one fewer than SMA/EMA's `M-N+1`). | Inventing a previous close for the first bar (e.g. using its own close) would produce a mathematically dishonest TR (`High_1-Low_1`, not a real true range) presented as genuine - the checkpoint brief explicitly warned against exactly this. | Treating the first bar's own OHLC range as its "TR" (rejected - explicitly warned against as dishonest); requiring a caller to always supply an extra seed bar out-of-band (rejected - unnecessary complexity, the existing `bars` tuple already naturally provides this via the first-bar policy). | LOCKED |
| 78 | ATR's recurrence is implemented independently inside `atr.py`, not by calling `compute_exponential_moving_average` despite superficial similarity between Wilder smoothing and EMA smoothing. | Wilder's `(N-1)/N`/`1/N` weights are numerically distinct from EMA's `alpha=2/(N+1)` - conflating them via a shared code path would either produce wrong ATR values or require a parameterized "generic recursive smoother" built speculatively for two data points. Following the exact precedent of decision #73 (EMA not calling SMA): each computation stays self-contained, no dependency edge between sibling calculations. | A shared `_wilder_smooth()`/generic exponential-smoothing helper parameterized by weight (rejected - two non-identical formulas do not yet justify a shared abstraction; the checkpoint brief explicitly warns against a `GenericRecursiveEngine`). | LOCKED |
| 79 | No new domain contract or Feature Engine abstraction was introduced for ATR - `Bar` (unchanged), `compute_*(definition, bars) -> tuple[FeatureValue, ...]` (unchanged shape), and the one-off definition-dataclass pattern (unchanged) all accommodated ATR's OHLC+previous-close input without modification. | SMA (close/fixed-window) + EMA (close/recursive) + ATR (OHLC+previous-close/recursive) is direct evidence spanning three structurally different calculation shapes that the existing abstraction already generalizes - building a framework now would be solving a problem the evidence shows does not exist. | An `IndicatorFramework`/`FeatureRegistry`/`GenericIndicatorEngine` (rejected - the checkpoint brief's own instruction: only build one if actual evidence from three implementations requires it; it did not). | LOCKED |

## Notes (Checkpoint 17)

- `domain/feature/contracts.py`'s `FeatureValue` and
  `domain/market_data/contracts.py`'s `Bar` (both Checkpoint 5) again
  required ZERO changes for ATR - `Bar` already carried `high`/`low`
  alongside `close`, confirming the domain layer's design absorbed a
  materially different calculation shape without modification.
- `import-linter` remains 6/6 kept (130 files analyzed, up from 129) -
  `atr.py` and the extended `FeatureEngineService` respect the existing
  layering; no new contract needed; no dependency edge introduced
  between `atr.py` and `sma.py`/`ema.py`.
- 42 new backend tests pass genuinely (not skipped) - continuing the
  same 100%-DB-free discipline as Checkpoints 14-16. Full suite: 261
  passed, 81 skipped, 0 failed (up from Checkpoint 16's 225 passed).
- Frontend UX validation (Part B): the first checkpoint to explicitly
  evaluate "can a real human actually use what has already been built,"
  not merely re-run automated tests. Full findings, including the
  concrete blocker encountered, are recorded in `taskReport.md`'s
  Checkpoint 17 section rather than duplicated here.
- No API/persistence/Dhan surface was added for ATR - confirmed via a
  regenerated, byte-unchanged-in-substance OpenAPI schema.
- Versioning: `pyproject.toml` and `SPECTACULAR_SETTINGS["VERSION"]`
  both checked and left unchanged - no API surface changed this
  checkpoint. `FEATURE_ENGINE_VERSION` ("v1") reused as-is for ATR.

## Checkpoint 17.2 — Authentication Status-Code Contract Correction (2026-08-13)

Closes the four defects Checkpoint 17.1 found once real PostgreSQL+Redis
execution became available for the first time. Full detail:
[docs/api/CONFIGURATION_API.md](../api/CONFIGURATION_API.md) §8-9,
[docs/architecture/AUTHENTICATION_AUTHORIZATION.md](AUTHENTICATION_AUTHORIZATION.md)
§4, and `taskReport.md`'s Checkpoint 17.2 section (test-debt fixes,
which are implementation-detail corrections, not separate architectural
decisions).

| # | Decision | Reason | Alternatives Considered | Status |
|---|---|---|---|---|
| 80 | Unauthenticated requests to a protected endpoint now return a genuine 401, not DRF's default 403-downgrade - via `infrastructure/api/authentication.Http401SessionAuthentication`, a thin `SessionAuthentication` subclass supplying a real `authenticate_header`. Authorization denials (authenticated, insufficient capability) remain 403, completely unaffected. | Restores the distinction the frontend's session-expiry contract (`setSessionExpiredHandler`, 401-only by design, Checkpoint 11) always assumed but never actually got - DRF's stock behavior silently made both conditions indistinguishable. The smallest correct fix: authentication-vs-authorization is decided entirely by DRF's own `APIView.permission_denied()` before this class is even relevant (`if request.authenticators and not request.successful_authenticator: raise NotAuthenticated() else: raise PermissionDenied()`) - supplying a non-`None` `authenticate_header` only stops DRF's *separate* `handle_exception()` step from downgrading the already-correct `NotAuthenticated` (401) to 403. | (B) Have the frontend treat 403 as a possible session-expiry signal too (rejected - the checkpoint's own explicit warning: this would convert every legitimate permission denial into an incorrect logout, which is a worse outcome, not a fix); (C) introduce JWT/refresh-token infrastructure (rejected - explicitly out of scope, solves a different problem, and this project's session-cookie model is otherwise working correctly). | LOCKED |
| 81 | Risk-configuration API responses are now serialized through `RiskConfigurationResponseSerializer(...).data` instead of being returned as a raw, un-serialized dict. | The raw-dict `Response(...)` path bypassed `DecimalField`/`COERCE_DECIMAL_TO_STRING` entirely, letting DRF's own `JSONEncoder` silently convert `Decimal` to `float` - a financial-precision regression in the one place this project has repeatedly promised it would never happen. The already-declared serializer (Checkpoint 8) was correct; it was simply never used for real serialization, only for `@extend_schema` documentation (a pattern every *other* serializer in this codebase still follows, since none of them carry Decimal fields and are therefore unaffected by this bug). | Manually `str()`-formatting each Decimal field in the hand-built dict (rejected - duplicates precision/scale rules the `DecimalField` declarations already encode correctly; two independently-maintained sources of the same rounding/precision policy is exactly the drift risk a serializer exists to prevent). | LOCKED |

## Notes (Checkpoint 17.2)

- All 8 real test failures Checkpoint 17.1 surfaced are now fixed: 3
  stale repository-test signatures (updated to the Checkpoint 12/13
  `activate()` contract, with new assertions on the actual `AuditLogEntry`
  row created - not just that the call no longer raises), 4 auth-flow
  tests that were failing due to throttle-cache state leaking between
  tests (fixed via a new `tests/conftest.py` autouse fixture that clears
  the cache before every test - production throttle behavior itself is
  completely unchanged), and 1 Decimal-serialization test (see decision
  #81).
- A ninth, previously-unknown issue was found and fixed while re-running
  `manage.py makemigrations --check --dry-run` for the first time against
  reachable PostgreSQL: a stale auto-generated index name on
  `AuditLogEntry` (Django's index-name hash for an unnamed
  `models.Index` differs slightly across Django versions) - a no-op
  `RenameIndex` migration (`0004_...`) resolves it. Purely a naming
  drift; no column, constraint, or data changed.
- `import-linter` remains 6/6 kept (132 files analyzed, up from 130).
- Full regression, first time ever at "genuinely clean" rather than
  "skipped": `pytest` 351 passed / 0 failed / 0 skipped;
  `makemigrations --check --dry-run` reports "No changes detected";
  `manage.py spectacular --fail-on-warn` succeeds cleanly (a new
  `OpenApiAuthenticationExtension` was required for
  `Http401SessionAuthentication` - drf-spectacular does not auto-detect
  custom `SessionAuthentication` subclasses); frontend `typecheck`/
  `build`/`test -- --run` all clean, 32 tests passing (up from 30 - two
  new tests proving the 401/403 distinction at the client layer).
- OpenAPI schema and generated frontend types verified deterministic:
  regenerated twice, byte-identical both times.
- Versioning: `pyproject.toml` and `SPECTACULAR_SETTINGS["VERSION"]`
  both checked and left unchanged - no new API surface, only a status-
  code correction on existing endpoints and a response-serialization fix.

## Checkpoint 18 — Signal Generation Contract (2026-08-13)

Establishes the first real code in `signal_intelligence/signal_generation`
- a deterministic interpretation of SMA/EMA/ATR feature state into
BULLISH/BEARISH/NEUTRAL. Full detail:
[docs/architecture/SIGNAL_GENERATION_ARCHITECTURE.md](SIGNAL_GENERATION_ARCHITECTURE.md).

| # | Decision | Reason | Alternatives Considered | Status |
|---|---|---|---|---|
| 82 | The Checkpoint 18 output is a new `DirectionalIndication` contract (`signal_intelligence/signal_generation/contracts.py`), NOT `domain.signal.Signal`. | `Signal` (Checkpoint 5) requires `strategy_id`/`strategy_version`/`theoretical_entry`/`theoretical_stop_loss`/`theoretical_targets` - fields this checkpoint has no authority to populate honestly (no strategy exists yet; the checkpoint brief explicitly forbids inventing stop-loss/target values). Confirmed by this bounded context's own Checkpoint-1 README, which already named the future responsibility as "converts strategy output into canonical Signal objects" - not yet meaningful. | Reusing `Signal` with fabricated `strategy_id`/price-level placeholders (rejected - dishonest, matches the exact class of placeholder this project has refused at every prior checkpoint); extending `Signal` with optional strategy fields to make it usable without a strategy (rejected - would weaken `Signal`'s own invariants for every other future caller that DOES have a real strategy, to accommodate one that doesn't yet). | LOCKED |
| 83 | `DirectionalIndication` lives in `signal_intelligence/signal_generation`, not `domain/signal`. | The project's own minimum-viable-shared-kernel rule (Checkpoint 2 §3.1): `domain/` membership requires 2+ bounded contexts needing the identical contract today - only `signal_intelligence/signal_generation` needs this one right now. Exactly mirrors why `SimpleMovingAverageDefinition`/`ExponentialMovingAverageDefinition`/`AverageTrueRangeDefinition` (Checkpoints 15-17) live in `feature_engine`, not `domain/feature`. | Adding it to `domain/signal` speculatively, anticipating a future `signal_verification`/`research.backtesting` consumer (rejected - no confirmed second consumer exists yet; promotion is a natural future step once one does, not a decision to front-load). | LOCKED |
| 84 | ATR does not participate in the BULLISH/BEARISH comparison itself - only EMA-vs-SMA and price-vs-EMA do. ATR must exist, be non-negative, and be aligned for an indication to be produced at all. | No existing architecture decision establishes an ATR threshold (e.g. "ATR > 2%"), and inventing one would be an arbitrary magic number the checkpoint brief explicitly forbade. Proves Signal Generation can consume a non-directional, non-close-only feature without embedding its computation - the same architectural point Checkpoint 17 proved for the Feature Engine itself. | Inventing a volatility threshold to gate signal validity (rejected - no mathematical/architectural basis given yet); ignoring ATR entirely this checkpoint (rejected - the brief explicitly required demonstrating multi-feature consumption). | LOCKED |
| 85 | All four inputs (price bar, SMA, EMA, ATR) must share the exact same instrument/timeframe/timestamp - raises a specific `Misaligned*Error` otherwise, never silently blends "the latest value we happen to have" for each. | Mirrors `ensure_chronological()`'s own "reject, never silently paper over" policy (Checkpoint 14 §16); a trading-adjacent system must never form a directional read from a mix of different market states. | Joining on "most recent value at or before timestamp T" (a looser, `asof`-style join) (rejected - the checkpoint brief's own explicit warning against exactly this: "do not silently mix feature observations from different market states"; the exact SMA@10:15/EMA@10:16/ATR@10:14 example given in the brief is a rejected case, not a case to tolerate). | LOCKED |

## Notes (Checkpoint 18)

- `domain/feature/contracts.py`'s `FeatureValue`, `domain/market_data/contracts.py`'s
  `Bar`, and `domain/signal/contracts.py`'s `Signal` all required ZERO
  changes - `Signal` remains fully reserved, untouched, for a future
  strategy-level output.
- `import-linter` remains 6/6 kept (138 files analyzed, up from 132) -
  no new contract needed; the existing generic infrastructure-isolation
  contracts already cover the new package. A dedicated static-scan
  architecture test (`tests/unit/architecture/test_signal_generation_boundaries.py`)
  additionally, independently re-verifies that `signal_generation` never
  imports `feature_engine` or infrastructure - only
  `application/services/signal_generation.py` composes both.
- 41 new backend tests (33 core + 5 application-service + 3 architecture)
  pass genuinely (not skipped) - continuing the 100%-DB-free discipline
  of every feature-engine checkpoint. Full suite: see regression section
  of `taskReport.md`'s Checkpoint 18 entry.
- No API/persistence/frontend surface was added - confirmed via a
  regenerated, byte-unchanged-in-substance OpenAPI schema.
- Versioning: `pyproject.toml` and `SPECTACULAR_SETTINGS["VERSION"]`
  both checked and left unchanged - no API surface changed. A new
  `DIRECTIONAL_INDICATION_DEFINITION_VERSION` ("v1") was introduced,
  reusing the existing `Version` primitive - no second versioning system.

## Checkpoint 19 — Signal Verification Foundation (2026-08-13)

Establishes the first real code in `signal_intelligence/signal_verification`
- a deterministic evaluation of whether a `DirectionalIndication`
(Checkpoint 18) was subsequently supported by actual price movement.
Full detail:
[docs/architecture/SIGNAL_VERIFICATION_ARCHITECTURE.md](SIGNAL_VERIFICATION_ARCHITECTURE.md).

| # | Decision | Reason | Alternatives Considered | Status |
|---|---|---|---|---|
| 86 | Verification outcome is `SUPPORTED`/`NOT_SUPPORTED`/`INCONCLUSIVE`, evaluated by a single price observation at an explicit, required `horizon_bars` bars after the signal - not a path/MFE/MAE analysis across the whole horizon. | The checkpoint brief explicitly prefers the smallest deterministic implementation and explicitly excludes MFE/MAE/drawdown/path analysis this checkpoint (reserved for `signal_intelligence/theoretical_outcome`, a distinct, not-yet-built bounded context per its own Checkpoint-1 README). | Evaluating every bar across the horizon and computing MFE/MAE (rejected - explicitly out of scope, a materially larger and different contract belonging to `theoretical_outcome`); a hard-coded horizon default like "5 bars" (rejected - the brief explicitly forbids an unjustified magic number; `horizon_bars` is a required, explicit parameter instead). | LOCKED |
| 87 | A `NEUTRAL` indication verifies to `INCONCLUSIVE`, never `NOT_SUPPORTED`, regardless of subsequent price movement. Equal prices (`observed == reference`) for BULLISH/BEARISH verify to `NOT_SUPPORTED`, not `SUPPORTED` or `INCONCLUSIVE`. | A NEUTRAL indication made no directional prediction to support or refute - collapsing it into NOT_SUPPORTED would fabricate a claim the indication never made. "No net movement," by contrast, is a real, known observation that cannot honestly support a call that specifically predicted movement - mirrors `generate_directional_indication`'s own equality-is-not-a-directional-signal treatment. | Treating NEUTRAL as NOT_SUPPORTED (rejected - the checkpoint brief's own explicit warning); treating equal-price BULLISH/BEARISH as INCONCLUSIVE rather than NOT_SUPPORTED (considered - rejected because the observation IS complete and conclusive, just not supportive; INCONCLUSIVE is reserved for genuinely incomplete data, not a completed-but-negative result). | LOCKED |
| 88 | An incomplete horizon (fewer than `horizon_bars` future bars available) verifies to `INCONCLUSIVE`, never `NOT_SUPPORTED`. | End-of-day signals, holidays, missing data, and interrupted feeds are legitimate, expected situations, not evidence the market moved against the call - conflating "we don't yet know" with "we know it failed" would be dishonest. | Raising an exception for an incomplete horizon (rejected - this is expected, ordinary data shape, not a caller error, unlike a genuinely misaligned instrument/timeframe/timestamp, which still raises). | LOCKED |
| 89 | `DirectionalIndication` is NOT promoted to `domain/` this checkpoint, despite `signal_verification` becoming a second real consumer. | The project's minimum-viable-shared-kernel rule sets the bar at two BOUNDED CONTEXTS (the five major divisions) - `signal_generation` and `signal_verification` are both submodules of the same bounded context (`signal_intelligence`), so this is intra-context reuse, not cross-context evidence. No consumer outside `signal_intelligence` exists yet. | Promoting now, anticipating a future `research/backtesting` or `control_plane` consumer (rejected - no confirmed need exists yet; this is exactly the speculative promotion the checkpoint brief explicitly forbade); leaving the finding undocumented (rejected - the checkpoint brief explicitly required documenting the finding even when promotion is deferred). | LOCKED |

## Notes (Checkpoint 19)

- `domain/market_data/contracts.py`'s `Bar` required ZERO changes.
  `domain/signal/contracts.py` was not touched at all this checkpoint -
  confirmed by the new architecture test's own domain-import allowlist
  (only `domain.market_data`/`domain.shared_kernel` permitted).
- `import-linter` remains 6/6 kept (143 files analyzed, up from 138) -
  no new contract needed. A dedicated static-scan architecture test
  (`tests/unit/architecture/test_signal_verification_boundaries.py`)
  independently re-verifies that `signal_verification` never imports
  `trading_engine`/`feature_engine`/infrastructure, and that its only
  `signal_intelligence.*` import is `signal_generation` (documented,
  deliberate, intra-context reuse - see decision #89).
- 39 new backend tests (32 core + 4 application-service + 3
  architecture) pass genuinely (not skipped) - continuing the
  100%-DB-free discipline of every prior signal-intelligence checkpoint.
  Full suite: 431 passed / 0 failed / 0 skipped (up from Checkpoint 18's
  392).
- No API/persistence/frontend surface was added - confirmed via a
  regenerated, byte-unchanged-in-substance OpenAPI schema.
- Versioning: `pyproject.toml` and `SPECTACULAR_SETTINGS["VERSION"]`
  both checked and left unchanged - no API surface changed. A new
  `VERIFICATION_DEFINITION_VERSION` ("v1") reuses the existing `Version`
  primitive - no second versioning system, and deliberately distinct
  from (never confused with) `DirectionalIndication`'s own
  `definition_name`/`definition_version`.

## Checkpoint 20 — Signal Lifecycle Foundation (2026-08-13)

Establishes the first real code in `signal_intelligence/signal_lifecycle`
- a two-state (ACTIVE/EXPIRED) temporal-validity model for a
`DirectionalIndication`. Full detail:
[docs/architecture/SIGNAL_LIFECYCLE_ARCHITECTURE.md](SIGNAL_LIFECYCLE_ARCHITECTURE.md).

| # | Decision | Reason | Alternatives Considered | Status |
|---|---|---|---|---|
| 90 | State model is exactly `ACTIVE`/`EXPIRED` - no `CREATED` state. | `DirectionalIndication` already carries its own creation instant (`timestamp`); a separate `CREATED` lifecycle state would duplicate it or imply a staging/approval gate this system has no mechanism for yet (unlike a future `Order`'s genuine risk-approval gate). The lifecycle begins directly `ACTIVE`, computed purely from `(expires_at, as_of)`. | A 3-state `CREATED -> ACTIVE -> EXPIRED` model (rejected - no real-world condition distinguishes CREATED from ACTIVE in this system's current scope; would be state invented for its own sake). | LOCKED |
| 91 | `VERIFIED` is NOT a lifecycle state. `signal_lifecycle` does not import `signal_verification` at all - mechanically enforced by a dedicated architecture test. | Lifecycle (temporal validity) and verification (outcome correctness) are orthogonal, independently-answerable questions - an indication can be EXPIRED and never verified, or ACTIVE and already SUPPORTED. Collapsing them would force every lifecycle consumer to also depend on verification even when it has no reason to, and vice versa. | Adding `VERIFIED`/`SUPPORTED`/`NOT_SUPPORTED` as lifecycle states once a `VerificationResult` exists (rejected - the checkpoint brief's own explicit warning: "do not assume correlation equals dependency"; no architectural proof requires this coupling). | LOCKED |
| 92 | State is a pure function of `(expires_at, as_of)`: `as_of >= expires_at -> EXPIRED`, else `ACTIVE` (half-open interval). The only illegal transition is passing an earlier `as_of` than a lifecycle's own last-evaluated `as_of` (`NonMonotonicTimeError`) - not a hand-written state-transition table. | Because state is a pure function of monotonically-comparable inputs, `EXPIRED -> ACTIVE` is structurally impossible through forward-moving time alone - enforcing "time may only move forward" is a strictly stronger, more general guarantee than enumerating individual forbidden state pairs, and naturally extends to any future third state without needing a new transition rule. | An explicit state-transition table (e.g. `{ACTIVE: {EXPIRED}, EXPIRED: {}}`) (rejected - more machinery than the pure-function model needs, and doesn't generalize as cleanly if a third state is ever added). | LOCKED |
| 93 | `expires_at` is a required, explicit argument to `create_lifecycle()` - no default expiry constant exists. `compute_expiry_from_bars()` is an optional, explicit-opt-in helper only. | No existing architecture decision establishes a universal "how long should a directional read stay meaningful" policy - that is a strategy-level/research decision this checkpoint has no authority to invent, exactly matching the brief's explicit prohibition on a magic default. | A `DEFAULT_EXPIRY_BARS`/`DEFAULT_EXPIRY_MINUTES` constant (rejected - explicitly forbidden by the checkpoint brief; no research/strategy evidence yet justifies any particular number). | LOCKED |
| 94 | No `application/services/signal_lifecycle.py` was created. | Every prior application service existed to compose a bounded-context's pure function with `HistoricalMarketDataService` (real retrieval). Lifecycle's only external input is "the current instant," which a caller already has - there is nothing genuine to orchestrate. | Building one anyway for consistency with Checkpoints 18/19 (rejected - the checkpoint brief's own explicit warning against creating an application service "merely because previous checkpoints have one"). | LOCKED |

## Notes (Checkpoint 20)

- `domain/market_data/contracts.py`'s `Bar` (via `timeframe_to_timedelta`
  reuse) required ZERO changes. `domain/signal/contracts.py` was not
  touched at all - confirmed by the new architecture test's own
  domain-import allowlist (only `domain.market_data`/`domain.shared_kernel`
  permitted).
- `import-linter` remains 6/6 kept (147 files analyzed, up from 143) -
  no new contract needed. A dedicated static-scan architecture test
  (`tests/unit/architecture/test_signal_lifecycle_boundaries.py`)
  independently re-verifies that `signal_lifecycle` never imports
  `signal_verification`, `trading_engine`, `feature_engine`, or
  infrastructure, and that its only `signal_intelligence.*` import is
  `signal_generation`.
- 33 new backend tests (30 core + 3 architecture) pass genuinely (not
  skipped) - continuing the 100%-DB-free discipline of every prior
  signal-intelligence checkpoint. Full suite: see regression section of
  `taskReport.md`'s Checkpoint 20 entry.
- Domain promotion re-assessed (§27): `signal_lifecycle` is now a THIRD
  intra-context consumer of `DirectionalIndication` - stronger
  intra-context evidence, but still not a second bounded context, so
  still not promoted. See decision context in
  SIGNAL_LIFECYCLE_ARCHITECTURE.md.
- No API/persistence/frontend surface was added - confirmed via a
  regenerated, byte-unchanged-in-substance OpenAPI schema.
- Versioning: `pyproject.toml` and `SPECTACULAR_SETTINGS["VERSION"]`
  both checked and left unchanged - no API surface changed. A new
  `LIFECYCLE_DEFINITION_VERSION` ("v1") reuses the existing `Version`
  primitive - no second versioning system, kept explicitly distinct from
  `DirectionalIndication`'s and `VerificationResult`'s own definition
  fields.

## Checkpoint 21 — Theoretical Outcome Foundation (2026-08-13)

Establishes the first real code in `signal_intelligence/theoretical_outcome`
- MFE/MAE price-excursion measurement for a `DirectionalIndication`.
Full detail:
[docs/architecture/SIGNAL_THEORETICAL_OUTCOME_ARCHITECTURE.md](SIGNAL_THEORETICAL_OUTCOME_ARCHITECTURE.md).

| # | Decision | Reason | Alternatives Considered | Status |
|---|---|---|---|---|
| 95 | MFE/MAE are clamped at zero: `MFE = max(0, ...)`, `MAE = min(0, ...)` - not the checkpoint brief's raw illustrative formula. | MFE ("favorable excursion") can never legitimately be negative; MAE ("adverse excursion") can never legitimately be positive - a "negative favorable" or "positive adverse" value is a contradiction in terms, not a real measurement. Without clamping, a BULLISH indication whose price only ever rose would report a spuriously positive MAE (implying a favorable minimum) instead of correctly reporting "no adverse movement occurred" (0). Makes `MFE >= 0`/`MAE <= 0` universal invariants, directly testable as Hypothesis properties. | The brief's raw unclamped formula (rejected - produces a sign-inverted, misleading value exactly in the "price only moved one way" case, which is a common and important real scenario, not an edge case to ignore). | LOCKED |
| 96 | Reference price is `indication.price` - the same value `VerificationResult` (Checkpoint 19) already uses - never a future bar's open/close. | Keeps every signal-intelligence measurement anchored to the one canonical "what price was known at signal time" value; a second reference-price convention would let two measurements silently disagree about what "the signal price" means. | "First future bar close/open" as reference (rejected - the checkpoint brief explicitly warned against inventing an entry price; the indication already carries the correct canonical value). | LOCKED |
| 97 | `mfe`/`mae` are `None` for NEUTRAL indications and for `NO_DATA` completeness - never `0`. `PARTIAL` completeness still computes a real MFE/MAE from the bars that exist, explicitly flagged as partial. | `0` is a real, distinct measurement (genuine zero excursion) - collapsing "not applicable" (NEUTRAL) or "unknown" (no data) into the same value as "measured and found to be zero" would be dishonest and irreversibly lose information a consumer needs (Checkpoint 21 §14's own explicit warning). | Silently returning `0` for NEUTRAL/NO_DATA (rejected - explicitly forbidden by the brief); withholding PARTIAL results entirely until the full horizon completes (rejected - throws away a real, honestly-labeled measurement that is genuinely useful, e.g. for end-of-day signals). | LOCKED |
| 98 | `theoretical_outcome` depends on neither `signal_verification` nor `signal_lifecycle` - mechanically enforced by a dedicated architecture test. | Verification asks a narrower single-point question; lifecycle asks a validity question; theoretical outcome measures windowed price-path extremes - three genuinely independent questions with independent answers (an EXPIRED indication's historical outcome remains fully measurable). Coupling any pair would force a consumer of one to depend on concepts it doesn't need. | Reusing `VerificationResult`'s `INCONCLUSIVE`/outcome shape for theoretical outcome's own completeness concept (rejected - the checkpoint brief's own explicit instruction: "do not import VerificationResult just to reuse its enum"; the two enums answer differently-shaped questions). | LOCKED |
| 99 | Conditional expectancy is NOT implemented this checkpoint. | Expectancy requires a defined trading policy (entry/exit/position-size/costs/win-loss classification) this bounded context has no authority to invent - exactly the checkpoint brief's own mandatory architectural question. MFE/MAE are policy-free objective measurements; expectancy is a statistic ABOUT a policy's results. | Implementing a "generic" expectancy formula parameterized by an invented policy (rejected - would still require inventing the policy parameters, which is exactly what's forbidden; belongs to a future strategy/research-evaluation bounded context once `trading_engine/strategy_execution` exists). | LOCKED |
| 100 | Configuration precedence is Database > Environment > Unconfigured, resolved fresh on every read; a database value is never overwritten by an environment value. | Matches how every prior configuration checkpoint (8-10) already treats the database as authoritative once a value exists there, while still letting `.env` bootstrap a fresh deployment. Resolving per-field (not per-provider) lets a partially-migrated provider (e.g. client id saved in the DB, access token still from `.env`) report its state honestly instead of forcing an all-or-nothing migration. | Environment always wins (rejected - would let a stale `.env` value silently override an operator's deliberate Settings-UI change); one-time migration from `.env` into the database on first read (rejected - an implicit write-back the checkpoint brief never authorized, and surprising if the sysadmin still expects `.env` to be authoritative). | LOCKED |
| 101 | Provider credentials use a `get_or_create(pk=1)` singleton, an application-level convention, not a database uniqueness constraint. | Matches this codebase's own existing precedent (`AuditLogEntry`'s append-only invariant is likewise application-level, not DB-enforced) rather than introducing a second, inconsistent enforcement style. One account/bot/webhook per deployment is the only case this checkpoint's brief describes. | A `UNIQUE` constraint plus a `get_or_create`-style upsert (rejected as unnecessary complexity for a single-row table with no concurrent-insert race the application layer doesn't already serialize through Django's ORM); a dedicated `Singleton` base model/manager (rejected - three near-identical repository classes are clearer than a shared abstraction for exactly three uses). | LOCKED |
| 102 | Secrets are never returned to the frontend in any form - not full, not partially-masked, not encrypted-but-decodable. Only booleans (`access_token_configured`) and a source enum are exposed. Non-secret identifiers (Dhan client id, Telegram channel id) ARE returned, but masked. | A masked-but-recognizable secret (e.g. `sk-***abc`) is still a partial leak an attacker with API access could use for social engineering or to confirm a guess; a boolean carries everything a legitimate UI needs (know that something is configured) with zero of what an attacker needs. | Returning a masked prefix/suffix for secrets, matching what's done for non-secret identifiers (rejected - explicitly forbidden by the checkpoint brief's "never" list; a secret and an account identifier have different threat models even though both get partial UI treatment). | LOCKED |
| 103 | A blank/omitted field in a save request means "leave unchanged" (`None` at the repository layer); the frontend never pre-fills a secret field with a masked placeholder that looks real. | The alternative (pre-filling with a masked value, and treating an unedited pre-filled value as "no change") requires the frontend to distinguish "unedited masked placeholder" from "user typed something that happens to look similar" - a fragile, easy-to-get-wrong UX contract. An always-blank field with "blank = unchanged" is unambiguous in both directions. | Pre-filling with a masked placeholder and diffing on submit (rejected - fragile, and risks accidentally submitting the placeholder string itself as a new "secret" on a careless implementation); requiring an explicit "change credential" toggle before showing the input (rejected - extra click for no safety benefit the blank-means-unchanged convention doesn't already provide). | LOCKED |
| 104 | No new RBAC capability tokens were introduced. Provider-settings read reuses `configuration.read`; save/test-connection reuse `configuration.activate`. | Provider credentials are exactly the class of security-sensitive configuration change `configuration.activate`/`IsConfigurationOperator` already exists to gate (risk/universe/strategy activation, Checkpoints 8-10) - a second permission system for functionally the same access-control question would fragment authorization logic without adding real precision. Verified compatible with existing capability-list assertions in `test_auth_api.py` before implementation. | New `settings.read`/`settings.write` capability tokens (rejected - the checkpoint brief's own explicit "reuse the existing RBAC model" instruction, and would have broken `test_auth_api.py`'s exact capability-list assertions for zero functional gain). | LOCKED |
| 105 | Connection-test orchestration (calling concrete `infrastructure.brokers.dhan.client`/`communication.adapters.*.client` HTTP clients) lives in the DRF view layer (`infrastructure/api/settings_views.py`), not in `application/services/`. | `.importlinter` contract #6 ("Application must not depend on infrastructure") forbids `application/*` from importing `intraday.infrastructure.*` - confirmed by reading `application/gateways/health.py`, which clarified the contract only forbids importing this project's OWN infrastructure package, not third-party frameworks in general. `infrastructure/api` is documented as the layer that composes application + infrastructure (Checkpoint 8's own established pattern, e.g. `risk_views.py`'s `_service()`). | Adding an application-layer gateway Protocol the view implements with a concrete infrastructure adapter, mirroring `application/gateways/health.py`'s own pattern (considered, not implemented - the checkpoint's connectivity clients are simple enough, and few enough call sites, that the extra Protocol layer would be indirection without a second implementation ever needing to exist). | LOCKED |

## Notes (Checkpoint 21)

- `domain/market_data/contracts.py`'s `Bar` (via `ensure_chronological`/
  `timeframe_to_timedelta` reuse) required ZERO changes.
  `domain/signal/contracts.py` was not touched at all - confirmed by
  the new architecture test's own domain-import allowlist.
- `import-linter` remains 6/6 kept (152 files analyzed, up from 147) -
  no new contract needed. A dedicated static-scan architecture test
  (`tests/unit/architecture/test_theoretical_outcome_boundaries.py`)
  independently re-verifies that `theoretical_outcome` never imports
  `signal_verification`, `signal_lifecycle`, `trading_engine`,
  `feature_engine`, or infrastructure, and that its only
  `signal_intelligence.*` import is `signal_generation`.
- 45 new backend tests (38 core + 4 application-service + 3
  architecture) pass genuinely (not skipped) - continuing the
  100%-DB-free discipline of every prior signal-intelligence checkpoint.
  Full suite: 509 passed / 0 failed / 0 skipped (up from Checkpoint 20's
  464).
- `application/services/theoretical_outcome.py` WAS created (unlike
  Checkpoint 20's `signal_lifecycle`) - real orchestration (future-bar
  retrieval via `HistoricalMarketDataService`) is genuinely needed here,
  mirroring `SignalVerificationService`'s exact precedent.
- Domain promotion re-assessed (§35): `theoretical_outcome` is now a
  FOURTH intra-context consumer of `DirectionalIndication` - stronger
  intra-context evidence, but still not a second bounded context, so
  still not promoted. This remains an open question tracked across
  Checkpoints 19-21, not resolved.
- No API/persistence/frontend surface was added - confirmed via a
  regenerated, byte-unchanged-in-substance OpenAPI schema.
- Versioning: `pyproject.toml` and `SPECTACULAR_SETTINGS["VERSION"]`
  both checked and left unchanged - no API surface changed. A new
  `OUTCOME_DEFINITION_VERSION` ("v1") reuses the existing `Version`
  primitive - no second versioning system.

## Notes (Checkpoint 22)

- First checkpoint to touch `infrastructure/brokers/dhan`,
  `communication/adapters/telegram`, and `communication/adapters/discord`
  with real code - all three had been unpopulated Checkpoint-1
  placeholders until now.
- `.env`/`.env.example`: `DHAN_API_KEY` (a Checkpoint 3/4-era misnamed
  variable that never matched Dhan's real field name) was corrected to
  `DHAN_CLIENT_ID`, matching the official `dhanClientId` field
  confirmed via direct fetch of Dhan's own documentation. `production.py`
  updated to match.
- `pyproject.toml`: `httpx` and `cryptography` added as explicit direct
  dependencies (both were already transitively available via existing
  dependencies, but declared explicitly per this project's convention
  of not relying on transitive-only availability for anything imported
  directly).
- `SPECTACULAR_SETTINGS["ENUM_NAME_OVERRIDES"]` added - the five
  provider-settings fields sharing the identical `["DATABASE",
  "ENVIRONMENT", "UNCONFIGURED"]` choice set otherwise produced a
  spurious drf-spectacular "multiple names for the same choice set"
  warning; the override collapses them to one canonical
  `ProviderConfigurationSourceEnum` name. `spectacular --fail-on-warn`
  is clean.
- Migration `0005_provider_settings.py` adds `DhanCredential`,
  `TelegramCredential`, `DiscordCredential`, `ProviderConnectionStatus`,
  and widens `AuditLogEntry.outcome`'s choices with a new `"updated"`
  value (alongside the existing `"activated"`/`"already_active"`/
  `"rejected"`) - the first outcome value not tied to a
  risk/universe/strategy activation workflow.
- A real, non-synthetic defect was found and fixed via manual live-server
  smoke testing (not first caught by an automated test, since none
  existed yet at the time): each provider's `*_settings_save` POST view
  originally called its sibling GET view function directly as a plain
  Python function to reuse response-building logic - `@api_view`-wrapped
  functions cannot be safely called this way (`AssertionError: The
  'request' argument must be an instance of 'django.http.HttpRequest'`).
  Fixed by extracting plain, undecorated `_dhan_settings_response()` /
  `_telegram_settings_response()` / `_discord_settings_response()`
  helpers that both the GET and POST-save views call directly.
- The local sandbox's OS-level environment (distinct from `.env`, which
  was blank) had a real `DHAN_ACCESS_TOKEN` and `TELEGRAM_BOT_TOKEN`
  set. This was treated as sensitive throughout: never written to any
  file, test, or log; used only to confirm the configuration-precedence
  resolver's `ENVIRONMENT`-source behavior was correct (see Decision
  100), never used to perform any real Dhan/Telegram action against a
  live account.
- `import-linter` remains 6/6 kept - no new contract needed. The
  connectivity clients (`infrastructure/brokers/dhan/client.py`,
  `communication/adapters/{telegram,discord}/client.py`) are called
  only from `infrastructure/api/settings_views.py` (Decision 105),
  never from `application/*`.
- 66 new backend tests (17 encryption/repository + 12 application-service
  precedence + 25 API vertical-slice + 12 connectivity-client) pass
  genuinely. Full suite: 575 passed / 0 failed / 0 skipped (up from
  Checkpoint 21's 509).
- 13 new frontend tests (7 Dhan + 3 Telegram + 3 Discord card tests),
  exercising the real generated OpenAPI contract types and the real
  `settingsApi.ts` client functions against a mocked `fetch` boundary
  only - matching `RiskConfigurationPanel.test.tsx`'s established
  philosophy. Full frontend suite: 45 passed / 0 failed.
- Frontend: one new top-level "Settings" navigation entry added to
  `App.tsx` alongside the existing "Configuration" entry. No routing
  library introduced - a single piece of local state toggles between
  the two screens, consistent with the project's existing
  no-heavy-framework convention for a small, fixed number of screens.
- `app.bat` required no changes - it already runs `manage.py migrate`
  unconditionally on every launch (added defensively at Checkpoint 12),
  which picks up this checkpoint's new migration with no
  checkpoint-specific edits.
- Docker remains explicitly deferred, unchanged from every prior
  checkpoint.
| 106 | REST polling (explicit-trigger, rate-limited) was chosen over WebSocket streaming for live market-data ingestion. | This Django/WSGI app has no already-running persistent process to host a WebSocket client safely (asgi.py is an unused stub; no Celery beat schedule exists). Building that infrastructure purely for this checkpoint would exceed "the smallest production-safe implementation." Dhan's own documented rate limit (1000 instruments/request, 1/sec) comfortably fits the four-symbol universe. | A continuous WebSocket tick stream (rejected - requires new long-lived-process infrastructure this checkpoint should not introduce); an automatic Celery-beat polling schedule (rejected - no beat schedule exists yet in this repo, and an unattended, always-running external HTTP call is a larger safety surface than an explicit, rate-limited, operator-triggered one for a first live-data checkpoint). | LOCKED |
| 107 | The Market Quote ("full quote") Dhan endpoint was used instead of the narrower LTP/OHLC variants. | Only the full quote variant includes `last_trade_time`, required by the checkpoint's explicit "preserve source timestamps" requirement - the narrower endpoints have no source timestamp at all. | `/marketfeed/ltp` or `/marketfeed/ohlc` (rejected - neither carries a source timestamp, which this checkpoint treats as a hard requirement, not a nice-to-have). | LOCKED |
| 108 | The observation universe's symbol -> Dhan security_id mapping is a small, hand-maintained, explicitly-verified table (`infrastructure/market_data_providers/dhan/instruments.py`), not a full scrip-master ingestion pipeline. | A four-symbol, configuration-driven universe (per the checkpoint's own explicit brief) does not justify downloading/parsing Dhan's full instrument master CSV on every startup. Each entry was individually verified against Dhan's official published CSV during this checkpoint, not guessed. | A full scrip-master ingestion/caching pipeline (rejected as premature machinery for four symbols - explicitly named as the natural next increment if the universe grows); hard-coding security_ids directly into business logic rather than a configuration-driven symbol list (rejected - the checkpoint brief's own explicit "must be configuration-driven" instruction). | LOCKED |
| 109 | Market-hours computation (`domain/session/calendar.py`) is fixed-hours (09:15-15:30 IST), with NO exchange holiday calendar. | The checkpoint brief explicitly asked for "the minimum market-session awareness necessary" - PRE_OPEN/OPEN/CLOSED classification does not require knowing which calendar dates are holidays, only what today's fixed hours are assumed to be. A holiday calendar is separate, larger, and independently useful work. | Integrating a real NSE holiday calendar (rejected as scope creep beyond "minimum... necessary" - explicitly named as a future increment, not silently dropped). | LOCKED |
| 110 | "Not configured" (no Dhan credentials at all) is never recorded as a health failure - a refresh attempt with no credentials records nothing and simply reflects whatever the health record already was. | Mirrors Checkpoint 22's own Configured != Connected honesty principle: no attempt was made, so nothing failed. Recording a synthetic "failure" for a condition that isn't really an attempt would pollute `consecutive_failures` and misrepresent what actually happened. | Recording "Dhan is not configured" as a generic ERROR-classified failure (rejected during this checkpoint's own test-writing process - initially implemented this way, then corrected once the resulting DISCONNECTED-vs-ERROR precedence conflict was discovered via a failing test). | LOCKED |
| 111 | `FRESHNESS_THRESHOLD_SECONDS = 120` (2 minutes) for CONNECTED_FRESH vs. CONNECTED_STALE classification. | This checkpoint's adapter is explicit-trigger REST polling, not a continuous stream - "staleness" means "the last successful Refresh is old enough a human should press Refresh again," not "a live feed silently stopped." 120s is short enough to flag a genuinely abandoned session, long enough that normal operator pacing (reading a quote, thinking) never falsely flags stale. | A much shorter threshold matched to a hypothetical continuous-stream cadence (rejected - this checkpoint has no continuous stream, so a sub-10-second threshold would flag CONNECTED_STALE almost immediately after every manual refresh, which is not useful information). | LOCKED |

## Notes (Checkpoint 23)

- First checkpoint to introduce real content in
  `control_plane/market_data_health` and
  `infrastructure/market_data_providers/dhan` - both were unpopulated
  Checkpoint-1/22 placeholders until now.
- First checkpoint to implement any market-hours computation
  (`domain/session/calendar.py`) - `domain/session/contracts.py`'s own
  docstring ("no market-hours computation exists here") was true
  through Checkpoint 22; this checkpoint explicitly authorized the
  minimum needed for session awareness.
- `tzdata` added as an explicit direct dependency (was already
  transitively available, likely via Django, but declared explicitly
  per this project's convention, matching `httpx`/`cryptography` at
  Checkpoint 22) - needed for `zoneinfo.ZoneInfo("Asia/Kolkata")` to
  resolve correctly across platforms.
- A real, pre-existing test-isolation gap (not introduced by this
  checkpoint) was found and fixed while re-running the full regression
  suite: `test_dhan_test_connection_when_unconfigured_returns_not_
  configured_status` (Checkpoint 22) assumed a blank ambient
  environment, which broke once real Dhan credentials became present
  in `.env` (added by the project owner between sessions, exactly as
  anticipated). Fixed via the same `monkeypatch.delenv()` isolation
  pattern already used elsewhere in the Checkpoint 22 test suite - not
  a Checkpoint 23 regression, a latent gap this checkpoint's own full
  regression run surfaced.
- A real design bug was found and fixed during this checkpoint's own
  test-writing (not by manual testing this time): the health
  evaluator's original precedence classified "never succeeded" as
  DISCONNECTED unconditionally, which incorrectly swallowed a genuine
  AUTHENTICATION_FAILED/ERROR result on the very first refresh attempt
  (before any success has ever been recorded). Fixed by changing the
  precedence to "never attempted at all" (no success AND no failure) ->
  DISCONNECTED, with any recorded failure taking priority regardless of
  whether a prior success exists (Decision 110's related fix).
- `import-linter` remains 6/6 kept (188 files analyzed, up from 174) -
  no new contract needed; `control_plane/market_data_health` and the
  Dhan market-data adapter fit cleanly within the existing layering
  contracts (application -> bounded contexts -> domain).
- Two dedicated architecture boundary tests added
  (`test_market_data_health_boundaries.py`,
  `test_live_market_data_boundaries.py`), mirroring the
  signal_intelligence checkpoints' own `ast`-based static-scan
  technique - independently re-verifying that no file on the live
  market-data path imports `trading_engine`, `domain.broker`,
  `domain.order`, `domain.position`, or `signal_intelligence`, and that
  the Dhan client's source contains no order/position/trading endpoint
  reference.
- 74 new backend tests (14 domain/session + 8 market_data_health
  evaluator + 14 Dhan client + 5 instruments + 7 application-service +
  9 persistence + 20 API vertical-slice + 7 architecture) pass
  genuinely. Full suite: 651 passed / 0 failed / 0 skipped (up from
  Checkpoint 22's 575) - includes the one pre-existing test-isolation
  fix above.
- 7 new frontend tests for `LiveMarketDataMonitor.tsx`, including a
  dedicated test asserting no Buy/Sell/Order/Quantity/Stop Loss/Target/
  Position/P&L/Execute/Trade text is ever rendered. Full frontend
  suite: 52 passed / 0 failed (up from Checkpoint 22's 45).
- OpenAPI schema regeneration proven deterministic (byte-identical
  across two independent runs) and confirmed synchronized with the
  regenerated frontend TypeScript contract.
- Manual live-market validation was genuinely performed against the
  real Dhan API during actual NSE market hours (13:31 IST, a trading
  Friday) using the project owner's real credentials (already present
  via `.env`, never requested or exposed) - session detection correctly
  reported OPEN, debounce/RBAC were confirmed live end-to-end, and the
  live connectivity path was proven working, though the specific
  credential was rejected by Dhan (AUTHENTICATION_FAILED, HTTP 401) -
  the identical result independently observed against Dhan's
  `/v2/profile` endpoint at Checkpoint 22, confirming this is a fact
  about the credential, not new Checkpoint-23 behavior.
- `app.bat` required no changes - it already runs `manage.py migrate`
  unconditionally on every launch, which picks up this checkpoint's new
  `0006_live_market_data` migration automatically.
- Docker remains explicitly deferred, unchanged from every prior
  checkpoint.
- Signal generation was verified, via a dedicated `ast`-based test, to
  remain completely unwired from this checkpoint's live feed - it still
  imports and consumes only the Checkpoint 14 synthetic fixture
  repository, exactly as before this checkpoint.
| 112 | Bar aggregation is a PURE, stateless function recomputed from scratch on every run over the full recent observation history - not an incrementally-updated, independently-mutable accumulator. | The observation log (`LiveQuoteObservation`, Checkpoint 23) is already the single source of truth and already append-only; a stateful accumulator would need its own revision/consistency logic to stay correct against that log, which is more machinery than this checkpoint's scope justifies. A pure recomputation is trivially correct by construction and trivially testable without mocking any state. | A stateful, incrementally-updated `BarBuilder` that reacts to each new quote as it arrives (rejected - requires solving a harder correctness problem - "what happens when a late quote arrives after the builder already moved on" - that pure recomputation sidesteps entirely). | LOCKED |
| 113 | A late-arriving observation for an already-CLOSED interval correctly REVISES that bar's OHLC on the next aggregation run - this is intended behavior, not a bug. | Direct, necessary consequence of Decision 112: if bars are always recomputed from the observation log, and the observation log has genuinely gained a new fact, the recomputed bar must reflect that fact. Silently ignoring late data to keep a bar "final" would make bars diverge from what was actually observed. | Locking a bar's OHLC permanently once first computed, ignoring later data for that interval (rejected - produces bars that are provably wrong once contradicted by data that arrives even one refresh cycle later; explicitly against the checkpoint's own "must fail safely and visibly" principle - silently wrong is not safe). | LOCKED |
| 114 | `AggregatedBarObservation` (bar persistence) is UPSERTED by `(instrument, timeframe, interval_start)`, unlike `LiveQuoteObservation`'s append-only design. | A bar is a derived, recomputable projection of the observation log, not an independent observation itself (see Decisions 112-113) - revising a stored bar in place when new data changes it is correct, not data corruption, and matches how the pure aggregation function itself behaves. | Append-only bar history, keeping every historical revision of each interval (rejected as unnecessary for this checkpoint's scope - the full revision history is already recoverable by re-running aggregation over the still-append-only quote log, so nothing is actually lost by upserting the derived projection). | LOCKED |
| 115 | Volume is never computed or fabricated this checkpoint - `AggregatedBar`/`Bar.volume` is always `Decimal("0")`, and the frontend renders it as an explicit "—", not a number. | Dhan's Market Quote volume field is cumulative day-volume, not a per-tick trade size; deriving a correct per-bar delta from it requires either session-reset-aware cumulative-delta logic or genuine tick-level data, neither of which this checkpoint implements. Fabricating a plausible-looking volume number would be actively misleading - exactly what Checkpoint 24A §4's "do NOT invent volume" forbids. | Approximating volume from the cumulative field via naive differencing between refreshes (rejected - explicitly unsafe per the session-reset/correction problem above; would produce numbers that look authoritative but are not verified correct). | LOCKED |
| 116 | Bar aggregation is chained into Checkpoint 23's existing `POST refresh/` endpoint (after a successful quote save) rather than exposed as its own separate write endpoint. | Aggregation itself makes zero additional broker calls (it only reads already-persisted quotes) - chaining it costs nothing in terms of the "no extra Dhan call" safety property, and keeps bars automatically in sync with quotes without requiring the operator to remember a second manual trigger. A bug in aggregation is isolated with its own try/except so it can never mask the refresh's own success/failure result. | A separate `POST bars/aggregate/` endpoint (rejected - adds a second manual step for no safety benefit, since aggregation has no broker-call cost of its own to justify gating behind an explicit trigger the way refresh's real Dhan call does). | LOCKED |

## Notes (Checkpoint 24A)

- First checkpoint to introduce a canonical Bar-producing pipeline
  since Checkpoint 14's `Bar` contract itself - `domain/market_data/
  contracts.py`'s `Bar` was reused completely unmodified, proving it
  was correctly designed generically enough at Checkpoint 5/14 to serve
  a live-data consumer four checkpoints later without any change.
- First Django-backed persistence for anything `Bar`-shaped -
  `HistoricalMarketDataRepository` (Checkpoint 14) remains implemented
  only by the in-memory fixture; `AggregatedBarObservation` is a
  deliberately separate, CP24A-scoped table (Decision 114's upsert
  design differs fundamentally from what a historical-archive
  implementation of `HistoricalMarketDataRepository` would need), not
  an implementation of that Protocol - explicitly not conflated.
- `import-linter` remains 6/6 kept (191 files analyzed, up from 188) -
  no new contract needed; the aggregation domain module and application
  service fit cleanly within the existing layering.
- A dedicated architecture boundary test
  (`test_bar_aggregation_boundaries.py`) independently re-verifies that
  `domain/market_data/aggregation.py` is pure (no infrastructure/
  Django/HTTP import) and that neither it nor
  `application/services/bar_aggregation.py` imports
  `signal_intelligence` or `trading_engine` - mechanically proving
  Checkpoint 24A §15's "do not connect bars to FeatureEngine/
  SignalGenerationService/StrategyExecution yet."
- 44 new backend tests (22 domain aggregation - including 9 explicitly
  adversarial: duplicate/out-of-order/same-timestamp/delayed/future-
  timestamp/gap/invalid-construction cases - 4 application-service, 6
  persistence, 8 API vertical-slice/chaining, 4 architecture) pass
  genuinely, all passing on the first real test run (no aggregation
  logic bug was found needing a fix, unlike Checkpoint 23's evaluator).
  Full suite: 695 passed / 0 failed / 0 skipped (up from Checkpoint
  23's 651).
- 5 new frontend tests for the "Recent Bars" table extension (empty
  state, rendered bars with correct FORMING/CLOSED badges, explicit
  non-fabricated volume placeholder). Full frontend suite: 55 passed /
  0 failed (up from Checkpoint 23's 52).
- OpenAPI schema regeneration re-confirmed deterministic (byte-
  identical across two independent runs) after the new `BarResponse`
  schema and `/market-data/bars/` route were added.
- No new dependency was added this checkpoint - `pip-audit`'s 8
  pre-existing `pytest`/`starlette` vulnerabilities are unchanged from
  Checkpoint 23, confirming nothing new was introduced.
- Docker remains explicitly deferred, unchanged from every prior
  checkpoint. `trading_engine/*` re-confirmed untouched (every file
  still its original Checkpoint-4 scaffolding line count).
