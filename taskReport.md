# Task Report

## Task
Foundational Project File Structure

## Objective

Establish the foundational architecture and repository/file structure for a
new institutional-grade, production-oriented algorithmic trading platform for
Indian cash-equity intraday trading, so future development can proceed in a
controlled, modular, testable, maintainable and auditable manner. This
checkpoint intentionally contains no business logic and no locked technology
stack (other than the confirmed initial broker target, Dhan).

## Repository State Before Task

`d:\IntraDay` existed as an empty directory: not a git repository, no files,
no subdirectories, and no prior technology decisions of any kind. Nothing
needed to be preserved or reconciled.

## Architectural Approach

Domain-first, technology-neutral, layered architecture:

- A shared `domain/` layer holds canonical, technology-neutral contracts
  (market data, feature, strategy, signal, risk, portfolio, order, position,
  broker, session, experiment, instrument, universe) that every other part of
  the system depends on.
- Five bounded contexts implement the major domains from the brief:
  `research/` (Quant Research Lab), `signal_intelligence/`, `trading_engine/`,
  `control_plane/` (Production Control Plane), `communication/`.
- `application/` sits between the bounded contexts and `frontend/`, holding
  API/schema contracts and orchestration gateways, so backend and frontend
  parameter definitions are never duplicated.
- `infrastructure/` holds technology-specific adapters (brokers, market-data
  providers, persistence, messaging) that implement `domain/` interfaces —
  nothing in `domain/` or the bounded contexts depends on `infrastructure/`.
- `data/` defines seven logical data-category boundaries independent of
  storage technology.
- `config/`, `ai_agent/`, `tests/`, `docs/`, `scripts/`, `deployment/`,
  `reports/` round out configuration, AI-safety, QA, documentation, tooling,
  ops and generated-artifact concerns.
- Every directory received a `README.md` stating its Responsibility, Depends
  On, and Must Not Depend On — documentation-as-scaffolding instead of
  placeholder business logic (per the task's Rule 14).

## Major Domains

- **A. Quant Research Lab** — `research/` (16 subdirectories covering the full
  idea → production lifecycle from Section 6).
- **B. Signal Intelligence** — `signal_intelligence/` (feature engine, signal
  generation/scoring/attribution/lifecycle/verification, theoretical outcome).
- **C. Trading Engine** — `trading_engine/` (session management, strategy
  execution/registry, risk engine, sizing, portfolio/order/execution
  management, broker abstraction, position lifecycle, square-off).
- **D. Production Control Plane** — `control_plane/` (reconciliation,
  monitoring, system/broker/market-data health, audit, structured logging,
  kill switch, alerts, diagnostics).
- **E. Communication Layer** — `communication/` (provider-agnostic contracts,
  notification router, adapters for Telegram/Discord, reserved WhatsApp slot).

## Files/Folders Created

- 137 directories, each containing a `README.md` (Responsibility / Depends On
  / Must Not Depend On), spanning `domain/`, `research/`,
  `signal_intelligence/`, `trading_engine/`, `control_plane/`,
  `communication/`, `application/`, `infrastructure/`, `data/`, `frontend/`,
  `config/`, `ai_agent/`, `tests/`, `scripts/`, `deployment/`, `reports/`.
- `docs/architecture/ARCHITECTURE.md`
- `docs/architecture/DOMAIN_BOUNDARIES.md`
- `docs/architecture/ARCHITECTURE_DECISIONS.md`
- `docs/research/`, `docs/api/`, `docs/runbooks/` (empty, reserved — no
  content created yet; no immediate content was in scope for this checkpoint)
- `README.md` (repository root)
- `taskReport.md` (this file)

## Files/Modified

None. The repository was empty prior to this task, so no existing files were
modified, renamed, or removed.

## Architectural Decisions

See [docs/architecture/ARCHITECTURE_DECISIONS.md](docs/architecture/ARCHITECTURE_DECISIONS.md)
for the full log with reasons, alternatives considered, and status. Summary:
9 decisions LOCKED (bounded-context organization, shared domain-contract
layer, application layer, infrastructure/domain separation, logical data
boundaries, dedicated ai_agent boundary, domain-aligned frontend structure,
README-as-scaffolding instead of placeholder code, no git/CI setup this
checkpoint); 1 decision (concrete technology stack selection) is PENDING
APPROVAL.

## Decisions Pending Approval

1. **Technology stack selection** — API framework/language, database(s),
   cache, message queue, frontend framework, cloud/hosting provider,
   market-data provider(s), CI/CD platform, IaC tool, and the mechanism used
   to generate frontend contracts from `application/contracts`. None of these
   were assumed per the brief's explicit instruction (Section 3). This should
   be the subject of the next architecture checkpoint ("Technology Mapping").
2. **Version control initialization** — whether/when to `git init`, adopt a
   branching strategy, and add `.gitignore`/license/CI config. Not requested
   in this checkpoint; flagged as PROPOSED, not performed.
3. **Frontend-contract generation mechanism** — how `application/contracts`
   concretely produces `frontend/shared/generated_contracts` (e.g. OpenAPI
   codegen, GraphQL codegen, or a custom generator) depends on the technology
   stack decision above.

## Potential Risks

- If a future contributor adds strategy code directly under
  `trading_engine/strategy_execution` without going through
  `domain/strategy`'s contract, Rule 5.1 isolation could be silently broken;
  this should be enforced later by lint/CI rules once the stack is chosen.
- The `data/` vs `infrastructure/persistence` split is intentional but could
  be misread as duplication by a future agent unfamiliar with the rationale —
  both `README.md` files and `ARCHITECTURE.md` §4 explain the distinction
  explicitly to mitigate this.
- Because no repository (git) exists yet, this directory structure has no
  version history; recommend initializing version control before further
  work accumulates.

## Assumptions Avoided

- Did not choose an API framework, database, cache, message queue, frontend
  framework, cloud provider, or CI/CD platform.
- Did not implement the strategy maturity or signal lifecycle state machines
  — only reserved their architectural home (`trading_engine/strategy_registry`,
  `signal_intelligence/signal_lifecycle`).
- Did not create the canonical Signal, Experiment, or other domain objects —
  only reserved their location and documented their eventual shape from the
  brief.
- Did not write any placeholder source/business-logic code, per Rule 14.
- Did not initialize git or assume a VCS/branching workflow.

## Validation Performed

- Confirmed `d:\IntraDay` was empty and not a git repository before making
  any changes (`git status`, directory listing).
- Regenerated and listed the top two levels of the created tree to confirm
  all 17 top-level domains and their immediate children were created as
  designed, with no accidental duplicates or omissions.
- Cross-checked every directory listed in this report's manifest against the
  brief's Sections 4–13 to confirm each required concept (research lifecycle
  stages, signal fields, experiment fields, production safety domains, data
  categories, frontend areas) has an explicit architectural home.

## Tests

> No business-logic tests were executed because this checkpoint intentionally
> contains no business logic.

## Current Architecture Status

Foundational directory structure and architecture documentation are complete
and committed to disk (not yet to version control). The platform has zero
lines of business logic, zero chosen runtime technologies (beyond Dhan as the
confirmed initial broker target), and zero implemented contracts — only their
directory homes and documented responsibilities exist.

## Recommended Next Checkpoint

**"Technology Mapping" checkpoint**: resolve the PENDING APPROVAL decisions
above (language/framework per layer, database(s), cache, queue, frontend
framework, hosting, market-data provider, CI/CD), then map each already-named
directory to the chosen technology without changing the domain boundaries
established here. Only after that should canonical `domain/` contracts
(Signal, Experiment, Strategy, Risk, Order, Position, Broker interfaces) be
formally specified in code.

## Notes for Next AI Agent

- Do not restructure the top-level domain boundaries without re-reading
  `docs/architecture/DOMAIN_BOUNDARIES.md` and updating the decision log —
  they were deliberately chosen to match Rules 5.1–5.7 from the founding
  brief, not arbitrarily.
- Every directory's `README.md` already states what it may and must not
  depend on; treat violations of "Must Not Depend On" as architecture bugs,
  not implementation details.
- The next checkpoint should resolve technology choices *before* any
  `domain/` contract is implemented in code, so the contract can be written
  once, correctly, in the chosen language/framework.
- Do not implement strategy math, broker integration, or frontend screens
  until the corresponding PENDING decisions are explicitly approved by the
  user — this was a hard constraint of this checkpoint and remains one.

---

# Checkpoint 2 — Architecture Review & Refinement (2026-08-12)

## Review Performed

A rigorous, question-by-question architecture review of the Checkpoint 1
structure was performed before any change was made: shared-kernel minimality,
strategy lifecycle (idea → production), Signal/Order/Position/Trade
separation, data ownership (domain vs. logical category vs. physical
storage), application layer (domain contract vs. API contract vs. config
schema), frontend contract generation/drift detection, control-plane
authority boundary, AI agent authority model, communication-layer
abstraction, research-lab fragmentation, experiment lineage, a five-question
simplification test applied to every one of the 17 top-level directories, a
ten-scenario extensibility test, and a 12-dimension architectural fitness
score. Repository state was verified beforehand: the local `d:\IntraDay`
tree exactly matched the 137-directory Checkpoint 1 manifest (no drift), and
the GitHub remote `https://github.com/NarendraAliani/IntraDay` was confirmed
empty (no separate state to reconcile).

## Changes Made

- **Removed** `domain/experiment` from the shared kernel — moved to
  `research/experiments` as its sole owner (it was consumed by only one
  bounded context, failing the "minimum viable shared kernel" bar).
- **Added** `domain/trade` — a new canonical contract closing a real gap:
  without it, the architecture could not separate "was the strategy wrong?"
  from "was the execution poor?" (Section 5 requirement).
- **Added** a generic version/lineage identifier primitive to
  `domain/shared_kernel`, replacing the need for a full shared `experiment`
  contract for cross-context version references.
- Updated **13 directory READMEs** to reflect the above and to add the
  clarifications below: `domain/README.md`, `domain/shared_kernel/README.md`,
  `domain/trade/README.md` (new), `research/experiments/README.md`,
  `ai_agent/proposals/README.md`, `data/research_data/README.md`,
  `research/strategy_specifications/README.md`,
  `trading_engine/strategy_execution/README.md`,
  `research/backtesting/README.md`,
  `signal_intelligence/signal_verification/README.md`,
  `trading_engine/execution_management/README.md`,
  `control_plane/reconciliation/README.md`, `reports/production/README.md`,
  `control_plane/kill_switch/README.md`, `ai_agent/README.md`,
  `ai_agent/guardrails/README.md`, `application/contracts/README.md`,
  `application/config_schema/README.md`,
  `frontend/shared/generated_contracts/README.md`, `data/README.md`,
  `reports/README.md`.
- Updated `docs/architecture/DOMAIN_BOUNDARIES.md`: added the
  Signal/Order/Position/Trade model, the Strategy Lifecycle (spec vs.
  implementation) diagram with its one narrow documented dependency
  exception, the Minimum Viable Shared Kernel table with justification per
  contract, the Data Ownership three-layer model, the Control Plane
  authority boundary, and the AI Agent write-isolation model.
- Updated `docs/architecture/ARCHITECTURE.md`: added a "Checkpoint 2 —
  Architecture Review Refinements" section summarizing all changes, and
  updated the parity/reproducibility bullets to reference `domain/trade` and
  the moved `research/experiments` contract.
- Updated `docs/architecture/ARCHITECTURE_DECISIONS.md`: added decisions
  #11–#16 (shared-kernel trim, `domain/trade` addition, strategy spec/impl
  split, control-plane authority bound, AI authority model, research-lab
  no-merge finding) with reasons, alternatives considered, and LOCKED status.

Total directory count: **137** (unchanged — one child removed from `domain/`,
one added; no top-level directory added or removed).

## Decisions

See `docs/architecture/ARCHITECTURE_DECISIONS.md` decisions #11–#16. All six
are LOCKED (structural clarifications/refinements, not technology choices).
Decision #10 (technology stack) remains PENDING APPROVAL and was
intentionally untouched by this checkpoint.

## Simplifications Considered But Rejected

- Nesting `research/walk_forward` and `research/monte_carlo` under
  `research/robustness_validation/` — rejected because the Checkpoint 1
  brief (Section 6) stages them as sequential peer lifecycle steps, not
  parent/child; merging would contradict an explicit prior requirement
  without a strong enough justification.
- Merging `research/ideas` and `research/discovery` — rejected, each
  produces a genuinely distinct artifact (a specific pitch vs. a broader
  exploratory scan that may yield many ideas).
- Removing any of the 17 top-level directories — none failed the
  five-question simplification test; all were kept.

## Unresolved Items

- Technology stack selection (decision #10) — still PENDING APPROVAL,
  unchanged from Checkpoint 1.
- Frontend-contract generation/drift-detection mechanism — the
  *responsibility* was clarified this checkpoint (CI must regenerate
  `frontend/shared/generated_contracts` and fail on diff), but the concrete
  tool remains PENDING, dependent on the technology stack decision.
- Version control initialization — still not performed; still recommended
  before further work accumulates.

## Next Checkpoint

Unchanged recommendation from Checkpoint 1: a **"Technology Mapping"**
checkpoint to resolve the PENDING technology decisions and map concrete
technology onto the now-refined directory structure, followed only then by
formal code-level specification of the `domain/*` contracts (now including
`domain/trade`) and the Signal/Order/Position/Trade, strategy spec/
implementation, and AI authority models clarified in this checkpoint.

---

# Checkpoint 3 — Technology Mapping, Repository Governance & Implementation Blueprint (2026-08-12)

## Review Performed

Before any change: re-read `README.md`, this file, `ARCHITECTURE.md`,
`DOMAIN_BOUNDARIES.md`, `ARCHITECTURE_DECISIONS.md`; verified the local
filesystem tree (143 directories) exactly matched what those documents
claimed — no drift since Checkpoint 2. Verified local Git state (`git
status` → "not a git repository", confirming Git was never initialized) and
the GitHub remote `https://github.com/NarendraAliani/IntraDay` (fetched
live — confirmed still empty: no commits, files, or branches). No
reconciliation between local and remote was needed since the remote has no
independent state.

## Technology Mapping Performed

Resolved every technology decision deferred at Checkpoints 1–2 — backend/
API, language/tooling, database(s), cache, async/message-queue, market data,
broker architecture, frontend, contract generation, testing, observability,
security, configuration, deployment, CI/CD, architecture enforcement,
versioning/reproducibility, financial precision, and time architecture.
Full detail, decision matrices, and nine architecture-compatibility tests
are recorded in the new authoritative document
`docs/architecture/TECHNOLOGY_MAPPING.md`. Selected stack: Python 3.12,
Django + DRF + Channels, PostgreSQL (+TimescaleDB) as the sole relational
engine, Parquet for bulk research data, Redis for cache only, Celery
(Redis-backed) for async/scheduled work, React+TypeScript+Vite frontend,
OpenAPI→TypeScript contract generation with CI drift enforcement,
import-linter for mechanical architecture enforcement, GitHub Actions CI,
and Docker/single-VM-per-environment deployment with a `TRADING_MODE` safety
flag. Every choice was tested against the existing architecture (§21 of
TECHNOLOGY_MAPPING.md) rather than the architecture being adjusted for the
technology — no domain boundary changed as a result of this checkpoint.

## Shared-Kernel Count Correction

Verified: the shared kernel correctly contains **14** contracts
(`shared_kernel`, `market_data`, `instrument`, `universe`, `feature`,
`strategy`, `signal`, `risk`, `portfolio`, `order`, `position`, `trade`,
`broker`, `session`). No architecture document ever stated an incorrect
count — `domain/README.md` and `DOMAIN_BOUNDARIES.md` always listed all 14
items. The "Retained (13)" figure was an off-by-one error in the
Checkpoint 2 **chat response summary only**, not a file. Both documents were
updated with an explicit "(14 contracts)" callout to close out the ambiguity
raised in this checkpoint's review.

## Repository Governance Established

- **Git initialized** at `d:\IntraDay` (was not previously initialized).
- **`.gitignore`** added — excludes secrets/`.env`, Python/Node/Django
  build artifacts, local databases, and IDE/OS files; explicitly keeps
  `frontend/shared/generated_contracts` tracked (needed for CI drift
  diffing, per Checkpoint 2/3 contract-generation design).
- **Default branch:** `main`. **Branch strategy:** short-lived feature/
  checkpoint branches merged via PR — no long-lived `develop` branch
  (avoids unnecessary Git ceremony for a small team). **Commit convention:**
  Conventional Commits. **PR/review expectations:** CI must pass; review
  required for changes touching `domain/`, `trading_engine/risk_engine`,
  `trading_engine/order_management`, `control_plane/kill_switch`, or broker
  credential handling. **Protected branch:** `main` requires CI passing (+
  review once the team is more than one person). **Tagging:** semantic
  versioning (`vMAJOR.MINOR.PATCH`) tags mark each deployable release.
  Full detail in `docs/architecture/TECHNOLOGY_MAPPING.md` and
  `ARCHITECTURE_DECISIONS.md`.
- **Remote:** `origin` set to `https://github.com/NarendraAliani/IntraDay`
  (documented/configured only — confirmed empty on GitHub, so this is safe
  and non-destructive). **No push was performed** — pushing requires
  explicit authorization not given in this checkpoint's brief.
- **First commit:** an initial "Checkpoint 1–3: foundational architecture,
  review, and technology mapping" commit capturing the full current
  repository state (all three checkpoints' work) was made on `main` locally.

## Files/Folders Created

- `docs/architecture/TECHNOLOGY_MAPPING.md` (new authoritative technology
  document).
- `.gitignore` (repository root).
- `.git/` (local repository, not pushed).

## Files/Folders Modified

- `docs/architecture/ARCHITECTURE_DECISIONS.md` — decision #10 marked
  RESOLVED; decisions #17–#28 appended (all LOCKED) for the technology
  choices above.
- `docs/architecture/ARCHITECTURE.md` — status section updated to reflect
  the Technology Mapping phase.
- `docs/architecture/DOMAIN_BOUNDARIES.md` — shared-kernel count corrected
  to explicitly state 14, with a note closing out the Checkpoint 2 chat
  summary's off-by-one error.
- `domain/README.md` — same count clarification.
- `README.md` — technology stack section resolved (was "Not yet locked"),
  new Repository Governance section, link to TECHNOLOGY_MAPPING.md added.
- 18 directory READMEs that previously said "PENDING ARCHITECTURAL
  DECISION" or similar updated to reference the now-locked technology and
  `TECHNOLOGY_MAPPING.md`, without adding any implementation code:
  `data/README.md`, `frontend/README.md`,
  `frontend/shared/generated_contracts/README.md`, `application/README.md`,
  `infrastructure/README.md`, `infrastructure/persistence/README.md`,
  `infrastructure/messaging/README.md`,
  `infrastructure/market_data_providers/README.md`,
  `infrastructure/brokers/dhan/README.md`, `deployment/README.md`,
  `deployment/environments/README.md`, `deployment/ci_cd/README.md`,
  `deployment/observability/README.md`, `scripts/data/README.md`,
  `scripts/ci/README.md`, `scripts/dev/README.md`,
  `communication/adapters/discord/README.md`,
  `communication/adapters/telegram/README.md`.
- This file (`taskReport.md`) — this section.

Total directory count: **137** (unchanged — no directories added or removed
this checkpoint; only `docs/architecture/TECHNOLOGY_MAPPING.md` and
`.gitignore` were added as files).

## Decisions

Decisions #17–#28 in `ARCHITECTURE_DECISIONS.md`, all LOCKED. Decision #10
(technology stack, previously PENDING APPROVAL) is now RESOLVED —
superseded by #17–#28.

## Explicitly Deferred (Non-Blocking)

- Specific charting library (Checkpoint 14).
- Specific secret-store product and cloud/VM hosting provider (Checkpoint 17).
- Whether/when to adopt Python 3.13+.
- Whether `uv` replaces Poetry once its ecosystem track record lengthens.
- Automatic deployment pipeline (explicitly out of scope this checkpoint).
- OpenTelemetry backend selection (SDK wired, backend not chosen).
- `import-linter`'s package-level granularity may need a supplementary
  custom architecture test for the narrow
  `research.backtesting → trading_engine.strategy_execution` exception —
  flagged for Checkpoint 4/5, not resolved with placeholder code now.

## Validation Performed

- Confirmed local filesystem tree (143 directories) unchanged from
  Checkpoint 2's end state before making any edit.
- Confirmed via live fetch that the GitHub remote is still empty — no
  remote-state reconciliation was required.
- Verified no business logic, strategy code, broker calls, database models,
  or frontend screens were added — this checkpoint is documentation, a
  `.gitignore`, and Git initialization only.
- Verified no secrets were introduced anywhere (no `.env` file, no
  credentials in any committed file or in `.gitignore`'s allowlist).
- Verified the shared-kernel count (14) against both `domain/README.md` and
  `DOMAIN_BOUNDARIES.md` and corrected the ambiguity from the Checkpoint 2
  chat summary.
- Verified no stale `domain/experiment` references remain outside
  historical/decision-log context (unchanged from Checkpoint 2's
  verification; re-checked, still true).
- Verified `domain/trade` still exists and is correctly documented
  (unchanged from Checkpoint 2).
- Confirmed all nine architecture-compatibility tests
  (`TECHNOLOGY_MAPPING.md` §21) pass without requiring any Checkpoint 1–2
  boundary change.

## Tests

> No business-logic tests were executed because this checkpoint intentionally
> contains no business logic. A testing *architecture* was defined
> (`TECHNOLOGY_MAPPING.md` §10) but no test code exists yet.

## Current Architecture Status

Foundational structure (Checkpoint 1), architecture review and refinement
(Checkpoint 2), and technology mapping with repository governance
(Checkpoint 3) are complete. The repository is now Git-version-controlled
locally (not yet pushed), has a fully specified — but not yet
implemented — technology stack, and zero lines of business logic.

## Recommended Next Checkpoint

**Checkpoint 4 — Repository Bootstrap + Tooling**: initialize the Poetry
project (`pyproject.toml`), Django project skeleton (settings modules per
environment), Ruff/mypy/pytest configuration, the `import-linter` contract
file, the GitHub Actions workflow files, and the `docker-compose.yml` for
local development — all tooling/bootstrap, still no business logic. Only
after that should Checkpoint 5 (Canonical Domain Contracts) formally
specify `domain/*` in code.

## Notes for Next AI Agent

- `docs/architecture/TECHNOLOGY_MAPPING.md` is now the authoritative source
  for every technology choice — read it before proposing any tool, library,
  or infrastructure component not already listed there; if something isn't
  covered, treat it as an open, non-blocking decision, not a license to pick
  freely without noting it.
- Local Git exists but has **not been pushed** to
  `https://github.com/NarendraAliani/IntraDay` — do not push without
  explicit authorization from the user in whatever future checkpoint
  actually asks for it.
- `import-linter` is the chosen mechanical enforcement tool for the
  dependency-direction rules — set up its config file as one of the first
  things in Checkpoint 4, before any real code makes violations possible.
- Do not implement strategies, broker calls, database models, or frontend
  screens until Checkpoint 4's tooling bootstrap is in place — code without
  the enforcement/testing scaffolding around it risks silently violating
  the architecture this and the prior two checkpoints established.

---

# Checkpoint 4 — Repository Bootstrap, Development Tooling & Architecture Enforcement (2026-08-12)

## Review Performed

Re-read `README.md`, this file, `ARCHITECTURE.md`, `DOMAIN_BOUNDARIES.md`,
`ARCHITECTURE_DECISIONS.md`, `TECHNOLOGY_MAPPING.md` before changing
anything. Independently verified — not assumed — the following:

- **Git**: local repo existed on branch `main` at commit `447d789`
  ("Checkpoints 1-3..."), remote `origin` correctly pointed at
  `https://github.com/NarendraAliani/IntraDay.git`, working tree clean, no
  push had ever occurred. A live fetch of the GitHub URL confirmed the
  remote repository is still empty.
- **Architecture**: all 17 approved top-level directories intact;
  `domain/trade/` exists; `domain/experiment/` does not exist;
  `research/experiments/` owns the experiment contract; the shared kernel
  lists all 14 contracts in both `domain/README.md` and
  `DOMAIN_BOUNDARIES.md`.
- **Directory-count discrepancy resolved precisely**: 137 manifest-driven
  architectural directories (each with a README) + 5 `docs/` subdirectories
  (`docs`, `docs/architecture`, `docs/research`, `docs/api`,
  `docs/runbooks` — created via a separate `mkdir` in Checkpoint 1, never
  part of the domain-boundary manifest) + 1 (`find .`'s own report of the
  repository root, which is not itself a directory in the architectural
  sense) = **143**, exactly matching the filesystem count with zero
  unexplained directories and zero `.git/` internals counted. This is
  distinct from the **183** directories now on disk after this checkpoint —
  the additional ~40 are `src/intraday/*` Python packages,
  `tests/unit/architecture/`, `.github/workflows/`, and `frontend/src/` —
  real *code* package directories bootstrapped inside the already-approved
  `application/`, `domain/`, `research/`, `signal_intelligence/`,
  `trading_engine/`, `control_plane/`, `communication/`, `infrastructure/`
  boundaries (via `src/intraday/`), not new top-level architectural areas.
  No architecture directory was added, removed, or renamed at the top
  level.
- **Redis terminology**: `TECHNOLOGY_MAPPING.md` §5 already stated Redis
  "is never a system of record" but did not enumerate its distinct roles;
  added an explicit 7-role taxonomy (cache, Channels layer, Celery broker,
  Celery result backend, Pub/Sub, distributed locks, rate-limit counters)
  to remove any ambiguity, per this checkpoint's §3.
- **Technology mapping**: confirmed the plan (Python 3.12, Django, DRF,
  Channels, PostgreSQL, TimescaleDB, Redis, Celery, React+TypeScript+Vite,
  Poetry, Ruff, mypy, pytest, Hypothesis, Schemathesis, import-linter,
  GitHub Actions, Docker) and implemented against it. Two deliberate,
  documented deviations were required during implementation — see
  Architecture Decisions #30 and #31 below (testcontainers-python →
  direct-connect-and-skip; Playwright deferred, not installed).

## What Was Built

- **Poetry project**: `pyproject.toml` (Python 3.12, runtime + dev
  dependency groups, Ruff/mypy/pytest config inline), `poetry.lock`
  committed.
- **Package skeleton**: `src/intraday/` with one Python package per
  approved bounded context (`domain`, `research` incl. `backtesting`,
  `signal_intelligence`, `trading_engine` incl. its 6 submodules
  referenced by the narrow-exception rule, `control_plane`,
  `communication`, `application` incl. `gateways`, `infrastructure`) —
  every `__init__.py` carries a Rule-14-compliant header and contains no
  business logic.
- **Django project**: `intraday/settings/{base,development,testing,paper,production}.py`
  (deliberately named `settings/`, not `config/`, to avoid colliding with
  the approved `config/` data directory — Decision #29), `urls.py`,
  `asgi.py` (the real serving entrypoint, Channels-wrapped), `wsgi.py`
  (compatibility only), `celery.py` (app bootstrap + one infrastructure-only
  smoke task), `manage.py`.
- **TRADING_MODE safety mechanism**: `settings/trading_mode.py` — a single
  authoritative `resolve_trading_mode()` function enforcing "LIVE requires
  production settings + TRADING_MODE=LIVE + live broker credentials,
  simultaneously," called once by every settings module. Verified by 6 unit
  tests covering every branch (default, PAPER outside production, LIVE
  rejected outside production, LIVE rejected without credentials, LIVE
  allowed only with both conditions, unrecognized mode rejected).
- **Infrastructure endpoints**: `/healthz` (liveness, no dependencies),
  `/readyz` (readiness, checks DB + cache without leaking secrets),
  `/version` (reads `intraday.__version__`, itself sourced from package
  metadata — no second version source), each with an OpenAPI response
  schema via `drf-spectacular`.
- **Architecture enforcement**: `.importlinter` with 5 contracts (domain
  isolation, infrastructure isolation, application→bounded-context→domain
  layering, bounded-context independence, and the narrow
  `research.backtesting → trading_engine.strategy_execution` exception
  scoped to that one submodule only) plus a supplementary, independent
  `tests/unit/architecture/test_narrow_dependency_exception.py` using `ast`
  static analysis.
- **Tests**: 16 passing infrastructure/unit tests + 3 integration tests
  that correctly skip without live Postgres/Redis (`tests/unit/`,
  `tests/unit/architecture/`, `tests/integration/`). No business-logic
  tests, per the hard boundary.
- **Docker**: `Dockerfile` (dev-oriented, labeled as such),
  `docker-compose.yml` (db, redis, web, celery_worker, celery_beat — all
  hardcoded to `intraday.settings.development`, cannot reach production),
  `.dockerignore`.
- **CI**: `.github/workflows/ci.yml` — Ruff format/lint, mypy strict,
  pytest (with real Postgres/Redis service containers), import-linter,
  Django migration check, gitleaks secret scan, pip-audit dependency audit
  (with 6 documented, tracked ignores — Decision #33), and an OpenAPI
  schema-generation smoke check. No deployment step.
- **Secrets**: `.env.example` (placeholders only) committed; `.env`
  confirmed gitignored via `git check-ignore`.
- **Frontend bootstrap**: `frontend/package.json`, `tsconfig.json`,
  `vite.config.ts`, `index.html`, `src/main.tsx`, `src/BootstrapPlaceholder.tsx`
  — no screens, no business logic, just enough to prove the toolchain
  builds.
- **Developer tooling**: `Makefile` (`install`, `format`, `lint`,
  `typecheck`, `test`, `architecture-check`, `check`, `migrate`, `dev-up`,
  `dev-down`, `dev-logs`) and `docs/development/LOCAL_DEVELOPMENT.md`.

## Validation Performed (all commands actually executed, not assumed)

| Check | Result |
|---|---|
| `poetry install` | ✅ succeeded (see Known Issues re: disk space) |
| `python manage.py check` | ✅ "System check identified no issues" |
| ASGI import (`intraday.asgi:application`) | ✅ `ProtocolTypeRouter` constructed |
| WSGI import (`intraday.wsgi:application`) | ✅ `WSGIHandler` constructed |
| `ruff format --check .` | ✅ 37 files formatted (2 initial violations fixed) |
| `ruff check .` | ✅ all checks passed (4 initial violations fixed) |
| `mypy` (strict) | ✅ no issues in 29 source files (3 initial errors fixed) |
| `pytest` | ✅ 16 passed, 3 skipped (no live Postgres/Redis in this sandbox), 0 failed |
| `lint-imports` (import-linter) | ✅ 5/5 contracts kept |
| **Adversarial re-test**: injected a forbidden `trading_engine.risk_engine` import into `research.backtesting` | ✅ import-linter correctly failed (3 contracts broken); the `ast`-based pytest test **initially missed it** (a real gap — see Known Issues), was fixed, then correctly failed too; both restored to green afterward |
| `manage.py makemigrations --check --dry-run` | ✅ "No changes detected" |
| `manage.py spectacular --fail-on-warn` | ✅ succeeded after adding response serializers to the health endpoints |
| `pip-audit` | ✅ clean with 6 documented, tracked ignores (Decision #33) |
| YAML syntax (`ci.yml`, `docker-compose.yml`) | ✅ both parse |
| `npm install`, `tsc --noEmit`, `vite build` (frontend) | ✅ all succeeded; 2 known npm audit findings (esbuild/vite dev-server CORS issue, dev-only) — see Known Issues |
| Docker container startup | ⚠️ **not run** — no Docker daemon available in this environment (see Known Issues) |

## Files Created

`pyproject.toml`, `poetry.lock`, `manage.py`, `.env.example`,
`.importlinter`, `Makefile`, `Dockerfile`, `.dockerignore`,
`docker-compose.yml`, `.github/workflows/ci.yml`,
`docs/development/LOCAL_DEVELOPMENT.md`; the full `src/intraday/` package
tree (24 files: `__init__.py`/`celery.py`/`urls.py`/`asgi.py`/`wsgi.py` at
the root, 5 settings modules + `trading_mode.py`, one `__init__.py` per
bounded-context package and trading_engine submodule, plus
`application/gateways/health.py`); `tests/unit/test_django_boot.py`,
`tests/unit/test_trading_mode.py`, `tests/unit/test_health_endpoints.py`,
`tests/unit/architecture/test_narrow_dependency_exception.py`,
`tests/integration/test_postgres_connectivity.py`,
`tests/integration/test_redis_connectivity.py`,
`tests/integration/test_celery_bootstrap.py`;
`frontend/package.json`, `frontend/package-lock.json`,
`frontend/tsconfig.json`, `frontend/vite.config.ts`, `frontend/index.html`,
`frontend/src/main.tsx`, `frontend/src/BootstrapPlaceholder.tsx`,
`frontend/src/vite-env.d.ts`.

## Files Modified

`docs/architecture/TECHNOLOGY_MAPPING.md` (Redis role taxonomy),
`docs/architecture/ARCHITECTURE_DECISIONS.md` (decisions #29–#35),
`docs/architecture/ARCHITECTURE.md` (status), `README.md` (status, Quick
Start, LOCAL_DEVELOPMENT link), `frontend/shared/generated_contracts/README.md`
(explains why still empty at Checkpoint 4), this file.

No top-level architecture directory was created, removed, or renamed.

## Known Issues / Deferred Items

- **D: drive was found essentially full (233G/233G, ~99M free) before any
  work in this checkpoint** — a pre-existing condition on the user's
  machine, unrelated to this project's own footprint (a few MB of text
  files). The Python virtualenv was redirected to `E:\poetry-venvs` (74G
  free) to avoid making this worse; frontend `node_modules`/`dist` were
  removed after validating the build, since they are regenerable and not
  committed. **This should be flagged to the user directly — a full system
  drive can cause failures well beyond this repository.**
- **Docker containers were not actually started** — no Docker daemon is
  available in this validation environment. `docker-compose.yml` and
  `Dockerfile` were validated for YAML/syntax correctness only, not a live
  `docker compose up`. Recommend the user (or the next checkpoint, if it
  has Docker access) run `make dev-up` and confirm all five services reach
  a healthy state.
- **`settings/testing.py` uses SQLite** as a documented, temporary
  exception (Decision #32) — must be revisited the moment real domain
  models exist (Checkpoint 5+).
- **`tests/integration/*` use direct connections + `pytest.skip`** instead
  of `testcontainers-python` as Checkpoint 3 originally anticipated
  (Decision #30) — reconsider testcontainers once tests need per-run
  container isolation.
- **Playwright was not installed** (Decision #31) — deferred to Checkpoint
  14 once real frontend screens exist to test.
- **pip-audit has 6 tracked, ignored findings** (pytest 8.4.2, starlette
  0.52.1 via schemathesis) — dev-only, not shipped in the runtime image,
  but must be re-evaluated on the next dependency bump (Decision #33).
- **npm audit reports 2 findings** (esbuild ≤0.24.2 / Vite ≤6.4.2 dev-server
  CORS issue, GHSA-67mh-4wv8-2f99) — affects the Vite *development* server
  only, not production build output; fixing requires a breaking Vite 5→8
  major-version bump not attempted at this bootstrap checkpoint. Tracked
  for the next frontend-focused checkpoint.
- **A real bug was found and fixed during this checkpoint**: the initial
  `ast`-based supplementary architecture test only checked
  `ImportFrom.module`, missing the `from trading_engine import risk_engine`
  form (where the forbidden submodule is a *name*, not part of the module
  path). Caught by deliberately injecting a forbidden import and observing
  the test still passed when it should have failed; fixed to also check
  `f"{module}.{alias.name}"` for every imported name. Documented in the
  test file's own docstring so this class of gap doesn't regress silently.

## Tests

16 infrastructure/unit tests pass; 3 integration tests correctly skip in
this sandbox (no live Postgres/Redis) and are designed to run for real in
CI (GitHub Actions service containers) and in a docker-compose-backed local
environment. No business-logic tests were written or run, per the hard
boundary for this checkpoint.

## Current Architecture Status

The platform now installs reproducibly (`poetry install`, `npm install`),
boots (Django, Celery, Channels all verified), exposes three infrastructure
endpoints, and has its Checkpoint 1–2 dependency-direction rules
mechanically enforced by CI rather than relying on README documentation
alone. Zero business logic, zero domain models, zero API endpoints beyond
health/version, zero broker or market-data code exist. All Checkpoint 1–3
architectural decisions remain unchanged; Checkpoint 4 only implemented the
tooling around them.

## Recommended Checkpoint 5

**Canonical Domain Contracts**: formally implement the 14 shared-kernel
contracts (`domain/shared_kernel`, `market_data`, `instrument`, `universe`,
`feature`, `strategy`, `signal`, `risk`, `portfolio`, `order`, `position`,
`trade`, `broker`, `session`) as real Python types (dataclasses or Pydantic
models — a choice this checkpoint deliberately did not make), with mypy
strict passing and unit tests for every contract's invariants. This is the
first checkpoint where `settings/testing.py`'s SQLite exception (Decision
#32) must be revisited, since real models will exist to migrate and test
against PostgreSQL-specific behavior (NUMERIC precision, JSONB, etc.).

## Notes for Next AI Agent

- Read `docs/architecture/TECHNOLOGY_MAPPING.md` and this checkpoint's
  section before adding any dependency — the dependency set here was
  deliberately minimal ("only what's required for this checkpoint");
  justify anything new the same way.
- `.importlinter` and `tests/unit/architecture/test_narrow_dependency_exception.py`
  are both live and enforced — a new domain contract or bounded-context
  module will automatically be checked against them. If you add a new
  `trading_engine` submodule, decide explicitly whether `research.backtesting`
  needs it and update contract #5 and the forbidden-list constant together
  — don't let them drift apart.
- The D: drive space issue (see Known Issues) may still be a problem —
  check `df -h` before any large install/build step, and prefer redirecting
  large caches/venvs to a drive with headroom (this checkpoint used
  `E:\poetry-venvs`) rather than assuming D: has room.
- `settings/testing.py`'s SQLite exception is not permission to keep
  avoiding real PostgreSQL testing — Checkpoint 5 must address it head-on
  once models exist.
- Do not implement strategies, broker calls, or frontend screens yet — the
  tooling exists now specifically so the next checkpoint's real code is
  checked by it from the first commit.

---

# Checkpoint 4 — Environment Restoration & Validation Correction (2026-08-12)

Corrective/validation task only — no Checkpoint 5 domain contracts were
implemented. The historical Checkpoint 4 report above is preserved
unchanged; this section documents the follow-up.

## Background

The original Checkpoint 4 work found D: essentially full (233G/233G, ~99M
free) and redirected the Poetry virtualenv to `E:\poetry-venvs` to avoid
worsening that condition. The user subsequently confirmed the D: disk-space
problem was resolved and required the environment be recreated at the
project's intended location.

## Environment Recreation

- Inspected the existing environment (`poetry env info`, `poetry config
  --list`) — confirmed it was still at `E:\poetry-venvs\intraday-WL9yTOeM-py3.12`.
- Removed it cleanly via `poetry env remove --all` (not a manual directory
  delete).
- Reconfigured Poetry: `virtualenvs.in-project = true`,
  `virtualenvs.path` reset to its default.
- No stale `.venv` existed on D: to clean up first.
- Ran `poetry install --no-interaction`; Poetry recreated the environment
  from scratch — not copied — at `D:\IntraDay\.venv`.
- Verified: `poetry env info --path` → `D:\IntraDay\.venv`; `python
  --version` → 3.12.0; `pip --version` → resolves inside
  `D:\IntraDay\.venv\Lib\site-packages\pip`; `.venv` size ≈ 208M.
- All package versions (Django 5.2.17, DRF 3.18.0, Channels 4.3.2, Celery
  5.6.3, redis-py 5.3.1, psycopg 3.3.4, Ruff 0.6.9, mypy 1.20.2, pytest
  8.4.2, import-linter 2.13) matched exactly what `poetry.lock` had already
  resolved — no re-resolution, no version drift, nothing upgraded.
- `E:\poetry-venvs` confirmed empty (only `.`/`..`) after cleanup — no
  project-specific environment left behind; E: itself untouched otherwise.
- D: free space: ~9.9G before this task's install, ~9.7G after (≈208M
  consumed by `.venv`, consistent with its measured size) — confirms the
  disk-space problem is genuinely resolved and D: now has real headroom.

## Full Validation Re-Run (from the new D:\IntraDay\.venv)

Every check from the original Checkpoint 4 validation matrix was re-run
from the newly recreated environment and produced identical results:
`manage.py check`, ASGI/WSGI imports, `ruff format --check`, `ruff check`,
`mypy` (strict), `pytest` (16 passed, 3 skipped — same as before, no live
Postgres/Redis in this sandbox), `lint-imports` (5/5 contracts kept),
`makemigrations --check --dry-run` ("No changes detected"), `manage.py
spectacular --fail-on-warn` (succeeded), frontend `tsc --noEmit` and `vite
build` (both succeeded; same 2 known npm audit findings as before,
unchanged). All five `TRADING_MODE` safety branches were explicitly
re-tested: RESEARCH boots, PAPER boots, LIVE+non-production settings
raises `UnsafeLiveConfigurationError`, LIVE+production+missing credentials
raises the same, and LIVE+production+credentials-present resolves the mode
only — no broker call exists anywhere in the codebase to make. Docker
containers were **not started** — no Docker daemon is available in this
environment; only `Dockerfile`/`docker-compose.yml` syntax was previously
validated, and that remains unchanged.

## Business Logic Status

Re-confirmed: no strategies, indicators, signal generation, risk
calculations, order/position management logic, broker API calls, Dhan
integration, market-data ingestion, backtesting implementation, business
database models, or frontend trading screens exist anywhere in the
repository. Checkpoint 5 was not started.

## SQLite Testing Exception

Unchanged and still explicitly temporary — `settings/testing.py`'s
docstring and Decision #32 in `ARCHITECTURE_DECISIONS.md` both state it
must be revisited the moment real domain models exist (Checkpoint 5+). Not
converted into a permanent decision.

## Git / Remote Audit (objective findings only — no repair action taken)

Ran the exact diagnostic commands requested, including a live
`git ls-remote --heads origin` (not a cached tracking ref):

- `git status`: on branch `main`, up to date with `origin/main`, clean
  working tree.
- `git rev-parse HEAD` and `git rev-parse origin/main`: **identical**
  (`0dc3693...`).
- `git log origin/main..HEAD` / `git log HEAD..origin/main`: both empty —
  local and remote are exactly in sync.
- `git branch --list "checkpoint*"` (local) and `git ls-remote --heads
  origin` (remote): `checkpoint/4-repository-bootstrap` exists in
  **neither** location; only `main` exists on both.

**Finding: a second unauthorized push occurred.** The commit
`0dc3693` ("Checkpoint 4: fix formatting/typing/architecture-test gaps
found during validation") — which was explicitly reported as local-only,
not pushed, at the end of the prior turn — is now confirmed present on the
real GitHub remote. No `git push` was executed by this agent in this
corrective task, nor was one executed in the prior turn. This is
consistent with the same external mechanism (most likely an IDE/editor
auto-sync feature operating outside this agent's tool calls) responsible
for the first unauthorized push reported previously. **No corrective
action was taken on the remote** — per instruction, this is an audit-only
finding for the user to decide how to handle.

## Files Modified

Only `taskReport.md` (this section) and `docs/architecture/*` were touched
in terms of tracked repository content — no source code, test, or
configuration file required correction. `pyproject.toml`, `poetry.lock`,
`.gitignore`, and all `src/`/`tests/` files are byte-for-byte unchanged
from the prior committed state; only local Poetry configuration
(`virtualenvs.in-project`, `virtualenvs.path`) and the physical location of
the (gitignored, never-committed) `.venv` directory changed.

---

# Checkpoint 5 — Canonical Domain Contracts (2026-08-12)

## Contracts Implemented

All 14 approved shared-kernel contracts, as real, immutable
(`@dataclass(frozen=True, slots=True)`), stdlib-only Python code under
`src/intraday/domain/*/contracts.py`: `shared_kernel` (identifiers,
`Version`, `Exchange`, `Side`, `Timeframe`, `Price`, `Quantity`,
`ensure_utc`), `instrument`, `universe`, `market_data` (`Bar`, `Quote`),
`feature`, `strategy` (`StrategyIdentity`, `StrategyVersion`,
`StrategyMaturityState`), `signal`, `risk` (`RiskLimits`, `RiskDecision`,
`TradingHaltState`), `portfolio`, `order` (`OrderIntent`), `position`,
`trade`, `broker` (`BrokerGateway` Protocol, `BrokerOrderStatusReport`),
`session`. Full field-level documentation:
`docs/architecture/DOMAIN_CONTRACTS.md`.

## Contracts Intentionally Not Implemented

No 15th contract was added — the shared kernel remains exactly the 14
approved at Checkpoint 2/3. No strategy runtime, indicator math, risk
evaluation, order placement, broker HTTP/WebSocket code, market-data
ingestion, backtesting engine, database model, API endpoint, or frontend
screen was implemented, per the hard boundary.

## Design Decisions

- Plain stdlib `dataclasses`, not Pydantic/attrs — keeps the domain layer's
  zero-third-party-dependency guarantee trivially auditable and avoids
  blurring domain vs. serialization (Decision #36).
- String `NewType` identifiers, not UUIDs — most domain identities are
  naturally derivable (e.g. `instrument_id` from exchange+symbol via
  `make_instrument_id`), so opacity would be convenience, not requirement.
- Validation lives in each contract's own `__post_init__` — no separate
  validation framework/layer.

## Invariants Enforced (representative, not exhaustive — see DOMAIN_CONTRACTS.md)

Every timestamp field rejects naive or non-UTC datetimes
(`shared_kernel.ensure_utc`). Every money/quantity field rejects `float`/
`int` in favor of `Decimal`. `Bar` enforces `low <= open,close <= high`.
`Signal` enforces stop-loss on the correct side of entry per direction and
confidence within [0,1]. `OrderIntent` enforces `idempotency_key` presence
and order-type-specific required fields (limit/trigger price).
`RiskDecision`/`TradingHaltState` require `reasons`/`reason` when rejecting/
halting. `Position`/`Trade` enforce closed-at-not-before-opened-at and
status/closed_at consistency. `Instrument.is_tradable` is `True` only for
`EQUITY` + `ACTIVE` — `INDEX` (NIFTY/SENSEX-style) is never tradable,
regardless of status.

## Tests

68 new unit tests across `tests/unit/domain/` (one file per contract, 14
files), including targeted Hypothesis property-based tests for `Price`
(any positive/negative `Decimal`) and `Bar`'s OHLC invariant across
generated ranges, plus a structural test asserting `BrokerGateway`'s
methods are all unimplemented stubs and a test asserting `InstrumentType`
contains no derivative/F&O member. Combined with the 16 infrastructure
tests from Checkpoint 4: **84 passed, 3 correctly skipped** (no live
Postgres/Redis in this sandbox), 0 failed.

## Architecture Validation

`import-linter`: **5/5 contracts kept, 0 broken** — unchanged from
Checkpoint 4, confirming the new domain code introduced no dependency
violation. A grep audit confirmed zero imports of `django`,
`rest_framework`, `celery`, `redis`, `psycopg`, `requests`, or `httpx`
anywhere under `src/intraday/domain/`. A separate grep confirmed no
accidental futures/options/derivatives terminology exists outside
deliberate "this must never exist" exclusion comments.

**A real gap was found and fixed during this checkpoint**: the 14 new
domain subpackages initially had only `contracts.py`, no `__init__.py` —
Python's implicit namespace packages made imports/tests/mypy work anyway,
but `import-linter` under-counted the codebase ("Analyzed 40 files" instead
of the correct 72) as a symptom. Fixed by adding an explicit,
Rule-14-compliant `__init__.py` to all 14 subpackages, matching every other
subpackage's convention in the codebase; `import-linter` then correctly
reported "Analyzed 72 files, 123 dependencies," still 5/5 contracts kept.

## Files Created

`docs/architecture/DOMAIN_CONTRACTS.md`; 14 `contracts.py` files and 14
`__init__.py` files under `src/intraday/domain/*/`; 14 test files under
`tests/unit/domain/`.

## Files Modified

`docs/architecture/ARCHITECTURE.md` (status), `docs/architecture/DOMAIN_BOUNDARIES.md`
(link to DOMAIN_CONTRACTS.md), `docs/architecture/ARCHITECTURE_DECISIONS.md`
(decision #36), `domain/README.md` (implementation status), `README.md`
(doc link), this file.

## Deferred Items

Everything explicitly out of scope per Checkpoint 5 Section 1 remains
deferred to its named future checkpoint: strategy runtime, feature
computation, signal generation, risk evaluation, order/broker execution,
market-data ingestion, backtesting, persistence/migrations, API endpoints,
frontend screens. Docker remains deferred per the roadmap change
(untouched, not validated, not run). The `settings/testing.py` SQLite
exception (Decision #32) is **not yet triggered** — these are pure Python
value objects with no database mapping, so no PostgreSQL-specific behavior
exists to test yet; it will be triggered at the first checkpoint that adds
persistence (repository implementations in `infrastructure/persistence`).

## Next Checkpoint

Recommend **Configuration Management** (mapping `config/strategies`,
`config/risk`, `config/universe` to `application/config_schema`-validated
instances against the now-implemented `domain.strategy`/`domain.risk`
contracts) before introducing market-data ingestion or persistence — this
keeps the "domain contract → config schema → frontend form" pipeline
(Rule 13) grounded in real contracts before more consumers are added.

---

# Checkpoint 6 — Configuration Management & Parameter Governance (2026-08-12)

## Implemented

`src/intraday/application/config_schema/`: `schema.py` (generic
introspection-based schema derivation from any domain dataclass —
`build_schema_for()`), `errors.py` (`ConfigValidationError`), `loader.py`
(contract-agnostic YAML file → dict), and three concrete schema+loader
modules: `risk.py` (`RiskLimits`), `universe.py` (`Universe`), `strategy.py`
(`StrategyVersion`, deliberately scoped to version/lineage/maturity only —
no strategy-parameter schema, since no domain contract models parameters
yet). Three example config instances committed:
`config/risk/default.yaml`, `config/universe/example.yaml`,
`config/strategies/example.yaml`. Full documentation:
`docs/architecture/CONFIGURATION_MANAGEMENT.md`.

## Configuration Boundaries Preserved

Domain Contracts / Configuration / Application Schema / Runtime Settings /
Secrets were kept as five separate concepts (see
CONFIGURATION_MANAGEMENT.md §1) — `application/config_schema` never reads
an environment variable or Django setting, and never duplicates a domain
invariant (all actual validation happens inside the domain contract's own
`__post_init__`; the config layer only adds source-file context via
`ConfigValidationError`).

## Tests

19 new tests (`tests/unit/application/config_schema/`, 5 files): schema
derivation, all three loaders' valid/invalid paths, and an end-to-end test
loading the actual committed YAML example files (not just synthetic dicts)
through the full `config/*.yaml → domain contract` pipeline. Combined
total: **103 passed, 3 correctly skipped** (no live Postgres/Redis in this
sandbox), 0 failed.

## Bug Found and Fixed

Adding `tests/unit/application/config_schema/test_risk.py` collided with
the pre-existing `tests/unit/domain/test_risk.py` (same basename, no
`__init__.py` in either directory) — pytest refused to collect with an
"import file mismatch" error. Fixed by adding `__init__.py` package
markers to every `tests/` subdirectory (`tests/`, `tests/unit/`,
`tests/unit/domain/`, `tests/unit/application/`,
`tests/unit/application/config_schema/`, `tests/unit/architecture/`,
`tests/integration/`), giving every test module a unique fully-qualified
name. This is the standard, correct fix for this pytest collision class,
not a workaround.

## Architecture Validation

Ruff ✅ · mypy strict ✅ (64 files) · pytest ✅ 103 passed/3 skipped ·
import-linter ✅ **5/5 kept, 0 broken** (81 files analyzed, up from 72 —
consistent growth, no contract weakened) · `manage.py check` ✅ ·
`manage.py makemigrations --check` ✅ "No changes detected" ·
`manage.py spectacular --fail-on-warn` ✅. **Docker: deferred by project
decision — not installed, not run, not touched.**

## Frontend UX Testing Readiness — Evaluated, NOT Triggered

Per the standing instruction to continuously evaluate this gate: **not
ready this checkpoint.** No `application/contracts` API endpoint exposes
business content yet (only `/healthz`/`/readyz`/`/version` exist), no
persistence layer stores anything, and no frontend screen exists to
configure through. `app.bat` was correspondingly **not created** — creating
it now would provide a doorway into a system with nothing behind it. The
gate will most plausibly trigger once a checkpoint adds: (a) at least one
real `application/contracts` endpoint exposing a config schema or domain
read model, (b) a persistence layer so state survives a restart, and (c) a
corresponding frontend screen — likely 2-3 checkpoints out (after
persistence and a first API surface).

## Files Created

`docs/architecture/CONFIGURATION_MANAGEMENT.md`; 6 files under
`src/intraday/application/config_schema/` (`__init__.py`, `schema.py`,
`errors.py`, `loader.py`, `risk.py`, `universe.py`, `strategy.py` — 7
total); 3 example YAML files under `config/{risk,universe,strategies}/`;
5 test files under `tests/unit/application/config_schema/`; 7
`__init__.py` package markers under `tests/` (the collision fix).

## Files Modified

`pyproject.toml` (added `pyyaml`, `types-pyyaml`; version bump to 0.6.0),
`poetry.lock`, `docs/architecture/ARCHITECTURE.md` (status),
`docs/architecture/ARCHITECTURE_DECISIONS.md` (decision #37),
`application/config_schema/README.md`, `config/risk/README.md`,
`config/universe/README.md`, `config/strategies/README.md`, `README.md`
(doc link), this file.

## Deferred Items

Strategy parameter schema (no domain contract yet); `config/broker` and
`config/environments` (no consumer yet / already handled by Django
settings); persistence of config instances; frontend config forms;
runtime config reload. Docker remains deferred per the roadmap. `app.bat`
remains deferred pending the Frontend UX Testing Readiness gate (not
triggered this checkpoint — see above).

## Next Checkpoint

Recommend **Market Data Abstraction** or **Persistence Foundation** next
— both were named as prerequisites for the Frontend UX Testing Readiness
gate above. Persistence first is likely the better sequencing: it lets
config instances (and eventually domain state generally) survive a
restart, which is a precondition for any meaningful API surface, which is
itself a precondition for frontend UX testing.

---

# Checkpoint 7 — Persistence Foundation & Repository Architecture (2026-08-12)

## Implemented

- `application/repositories/__init__.py`: three `typing.Protocol`
  interfaces (`RiskConfigurationRepository`, `UniverseRepository`,
  `StrategyVersionRepository`) + `DuplicateVersionError`. New directory
  under the approved `application/` layer — justified in
  ARCHITECTURE_DECISIONS.md decision #38.
- `application/config_schema/records.py`: `RiskConfigurationRecord`, a
  small application-layer versioning envelope for the identity/version-free
  `RiskLimits` domain contract (which was NOT modified).
- `infrastructure/persistence/` Django app: `apps.py`, `models.py` (6
  models — 3 immutable version tables + 3 mutable active-pointer tables),
  `repositories.py` (3 Django-ORM Protocol implementations),
  `migrations/0001_initial.py`.
- `settings/base.py`: registered the persistence app in `INSTALLED_APPS`;
  added `DATABASES.OPTIONS.connect_timeout` (fail-fast fix, see below).
- `settings/testing.py`: retired the Checkpoint 4 SQLite exception — now
  uses real PostgreSQL configuration, matching `base.py`.
- `.importlinter`: new contract #6 ("application must not depend on
  infrastructure"), adversarially verified.
- `docs/architecture/PERSISTENCE_ARCHITECTURE.md`: full documentation.

## Domain Remains ORM-Free — Verified

Grep/AST-based architecture test
(`tests/unit/architecture/test_persistence_boundaries.py`) confirms zero
imports of `django`, `rest_framework`, `psycopg`, `celery`, `redis`, or
`channels` anywhere under `src/intraday/domain/`, and confirms
`application/repositories`' three interfaces remain structural
`Protocol`s (every method is a stub). No domain dataclass was converted
into or annotated as a Django model.

## Persisted Domain Concepts (and why only these)

`RiskLimits` (via `RiskConfigurationRecord`), `Universe`, `StrategyVersion`
— the three concepts Checkpoint 7 §4 explicitly named. Every other domain
contract, every config-schema introspection object, and every transient
value object was deliberately left unpersisted — no current consumer
needs them to survive a restart. Full justification table in
`PERSISTENCE_ARCHITECTURE.md` §2.

## A Real Hang Was Found and Fixed

`manage.py makemigrations` (and any DB-touching command) hung
indefinitely against an unreachable PostgreSQL host, because psycopg has
no default connect timeout. Diagnosed by testing against `localhost`,
`127.0.0.1`, and even a definitely-closed port (1) — all hung past a 15s
`timeout` wrapper. Fixed by adding `DATABASES.OPTIONS.connect_timeout`
(default 5s, `POSTGRES_CONNECT_TIMEOUT`-overridable) to `settings/base.py`
— a permanent production fail-fast improvement, not a one-off workaround.

## PostgreSQL Availability — Honestly Reported

**No PostgreSQL server is available in this validation environment**
(confirmed absent since Checkpoint 4; re-confirmed this checkpoint via
`psql` absence and connection timeouts against loopback). Consequently:

| Command | Result |
|---|---|
| `manage.py makemigrations persistence` | ✅ **Succeeded** — generated `0001_initial.py` with all 6 models, indexes, constraints (does not require a live connection; the migration-history consistency check warns and continues on `OperationalError`) |
| `manage.py makemigrations --check --dry-run` | ✅ **Succeeded** — "No changes detected" |
| `manage.py migrate --plan` | ❌ **Failed with `OperationalError: connection timeout expired`** — this command genuinely requires a live connection. **Not run successfully. Not faked as passing.** |
| `manage.py migrate` (actual apply) | **Not attempted** — would fail identically to `--plan` |
| 18 new persistence tests (`tests/unit/infrastructure/persistence/`) | **All skipped** via `@requires_postgres`, individually reported, never claimed as passed |
| 2 pre-existing `readyz` DB tests | **Now also skipped** (previously passed against SQLite; testing.py no longer has a SQLite fallback) |
| 3 `tests/integration/` tests | Skipped, as in every prior checkpoint |

In CI (GitHub Actions, real Postgres service container), all of the above
run for real — this is a validation-environment limitation, not a design
flaw; the CI workflow's Postgres service container was already provisioned
at Checkpoint 4 for exactly this purpose.

## Tests

**105 passed, 21 skipped, 0 failed** (up from 103 passed/3 skipped at
Checkpoint 6 — 18 new persistence tests, all appropriately skipped, plus 2
previously-passing tests now also correctly skipped for the reason above).
Test categories added: model tests (constraints, Decimal precision,
JSONB), repository tests (create/read/version-resolution/duplicate-
rejection/activation), full YAML→domain→persistence→repository round-trip
tests verifying semantic equality (not just row existence), and the
domain-ORM-free architecture test (always runs, no DB needed).

## Architecture Validation

Ruff ✅ · mypy strict ✅ (70 files) · pytest ✅ 105 passed/21 skipped/0
failed · import-linter ✅ **6/6 kept, 0 broken** (89 files analyzed, up
from 81; new contract #6 adversarially verified — injected violation
confirmed broken, then removed and re-verified clean) · `manage.py check`
✅ · `makemigrations --check` ✅ · `spectacular --fail-on-warn` ✅ ·
`migrate --plan` — **honestly reported as failed/unrunnable, no live
PostgreSQL available**. **Docker: deferred by project decision** — not
installed, not run, not touched.

## Frontend UX Testing Readiness — Evaluated

| Criterion | Status |
|---|---|
| Persistence exists (state survives restart) | ✅ Yes, for 3 configuration concepts |
| Business API exists (real domain data exposed) | ❌ No — only `/healthz`/`/readyz`/`/version` |
| Frontend exists (real screen consuming that API) | ❌ No — only the Checkpoint 4 bootstrap placeholder |
| Human workflow exists (meaningful action, not just viewing health) | ❌ No |

**Result: `NO — NOT YET`.** Three of four criteria remain unmet.
`app.bat` was **not created**. Persistence (criterion 1) is now the piece
that just became true — the next checkpoint that adds a real
`application/contracts` endpoint exposing the persisted configuration
would satisfy criterion 2, moving the gate meaningfully closer.

## Security Review

`.gitignore` re-checked: `.env`/secrets still correctly ignored. No
credentials, passwords, or real broker/database URLs appear in any file
created this checkpoint — `config/risk/default.yaml` etc. remain
illustrative placeholders (unchanged from Checkpoint 6); test fixtures use
literal, obviously-fake values (`"intraday"`/`"test-secret-key..."`,
already present in `.github/workflows/ci.yml` since Checkpoint 4).

## Files Created

`src/intraday/application/repositories/__init__.py`,
`src/intraday/application/config_schema/records.py`,
`src/intraday/infrastructure/persistence/{apps.py, models.py, repositories.py}`,
`src/intraday/infrastructure/persistence/migrations/{__init__.py, 0001_initial.py}`,
`tests/postgres_utils.py`,
`tests/unit/infrastructure/{__init__.py, persistence/__init__.py, persistence/test_models.py, persistence/test_repositories.py, persistence/test_round_trip.py}`,
`tests/unit/architecture/test_persistence_boundaries.py`,
`docs/architecture/PERSISTENCE_ARCHITECTURE.md`,
`application/repositories/README.md`.

## Files Modified

`src/intraday/settings/base.py` (INSTALLED_APPS, connect_timeout),
`src/intraday/settings/testing.py` (SQLite exception retired),
`tests/unit/test_health_endpoints.py` (requires_postgres guard added),
`.importlinter` (contract #6), `docs/architecture/ARCHITECTURE.md`,
`docs/architecture/DOMAIN_BOUNDARIES.md`,
`docs/architecture/ARCHITECTURE_DECISIONS.md` (decisions #38-#40),
`infrastructure/persistence/README.md`,
`application/config_schema/README.md`, `README.md`, this file.

## Deferred Items

Instrument master persistence (no consumer yet); market data, signal,
order, position, trade persistence (no producing engine yet); repository
caching; concurrency beyond `transaction.atomic()` (no demonstrated
contention); `application/contracts` API exposure of persisted
configuration (identified as future work, not built); frontend
consumption. Docker remains deferred. `app.bat` remains deferred — gate
not yet triggered.

## Git Status

Committed locally to `main`. **Not pushed.**

## Next Checkpoint

Recommend **Business API — Application Contracts**: expose the now-
persisted risk/universe/strategy-version configuration (read + versioned-
activate) through `application/contracts` (DRF + OpenAPI), which would
satisfy the Frontend UX Testing Readiness gate's second criterion and set
up the third (a real frontend screen) as the natural following checkpoint.

---

# Checkpoint 8 — Business API & Application Contracts (2026-08-12)

## Implemented

Full vertical slice: `application/services/` (3 use-case services +
shared errors), `application/contracts/` (DRF serializers: risk, universe,
strategy, plus `ApiErrorSerializer`), `infrastructure/api/` (DRF views +
error mapping + URL routing for all 3 resources), wired into
`intraday/urls.py` under `/api/v1/config/`. 12 endpoints total (4 per
resource × 3 resources): list, get-active, get-version, activate.

## A Necessary Interface Extension (Checkpoint 7 → 8)

Building the API surfaced a real gap: Checkpoint 7's
`UniverseRepository`/`StrategyVersionRepository` returned bare domain
objects with no `created_at`, but the API needs it (like
`RiskConfigurationRecord` already had). Extended both Protocol return
types to new wrapper types `UniverseRecord`/`StrategyVersionSnapshot`
(adding only `created_at`, mirroring the existing pattern) — updated the
Django ORM implementations and **all of Checkpoint 7's own tests** to
match. This is a deliberate, documented interface evolution (Decision
#42), not a silent regression — Checkpoint 7's tests still assert the
same behavior, just through the new wrapper's `.universe`/
`.strategy_version` attribute.

## Where Views Live — a Real Architectural Question Resolved

Composing a concrete (Django-backed) repository with an application
service — necessary for any view to actually do anything — requires
importing `infrastructure.persistence`. `.importlinter` contract #6
forbids `application` from depending on `infrastructure`. Resolution:
placed views under **`infrastructure/api/`**, not `application/gateways/`
— an HTTP API is a delivery mechanism (a "driving adapter"), the same
category as `infrastructure/persistence` (a "driven adapter"), both
legitimately allowed to depend on `application`. Verified: `import-linter`
still reports **6/6 kept** with this composition in place, and a new
architecture test (`test_api_boundaries.py`) independently re-confirms
`application/services` and `application/contracts` import zero
`infrastructure` code.

## Response Serialization Approach

Views return plain dicts via `Response(body)`, not
`Serializer(...).data` — `@extend_schema`'s declared `responses=` drives
the OpenAPI shape independently of runtime instantiation, the same
pattern Checkpoint 4's `health.py` already used. Discovered this was
necessary (not just a style choice) when mypy strict correctly rejected
passing a `dict` as the `instance` argument to a `Serializer[None]`.

## Two Stale-Documentation Gaps Found and Fixed

1. `application/contracts/README.md` still said "Must Not Depend On: Any
   specific API framework" — written at Checkpoint 1, before Checkpoint 3
   locked DRF. Updated to explain DRF is now the locked technology, not a
   violation of the original intent.
2. `SPECTACULAR_SETTINGS`'s `DESCRIPTION`/`VERSION` in `settings/base.py`
   were still Checkpoint-4-era text ("no domain contracts have been added
   yet") — found by actually inspecting the generated OpenAPI schema
   output, not just checking that generation succeeded. Corrected, and
   `pyproject.toml`'s version bumped to `0.8.0` to match (it had not been
   bumped at Checkpoint 7 either — a minor, now-corrected drift).

## Tests

23 new tests: 7 pure-Python application-service tests (in-memory fake
repository — no Django, no database, proving the DI/testability claim),
13 Postgres-gated API endpoint tests (`test_risk_api.py` — the "most
important test in this checkpoint" per the brief, a full vertical slice
plus list/active/404/idempotent-activation/error-shape coverage;
`test_universe_api.py`, `test_strategy_api.py` — lighter parity coverage),
2 architecture boundary tests, 1 additional. **114 passed, 34 skipped, 0
failed** (up from 105 passed/21 skipped at Checkpoint 7 — the 9 new
passes are the pure-Python service tests, which genuinely ran; the 13 new
skips are the Postgres-gated API tests, honestly reported as skipped, not
claimed as passed).

## PostgreSQL Validation Status

**No PostgreSQL server available in this environment** (consistent with
every prior checkpoint). `manage.py check`, `makemigrations --check`
("No changes detected" — no model changes this checkpoint), and
`spectacular --fail-on-warn` (succeeded, inspected the actual output, not
just the exit code) all ran successfully without a live connection. The
13 API endpoint tests and all persistence tests from Checkpoint 7 are
**skipped**, individually reported, never claimed as passed. In CI (real
Postgres service container), all of these run for real.

## Architecture Validation

Ruff ✅ · mypy strict ✅ (86 files) · pytest ✅ **114 passed, 34 skipped, 0
failed** · import-linter ✅ **6/6 kept, 0 broken** (106 files analyzed, up
from 89) · `manage.py check` ✅ · `makemigrations --check` ✅ ("No changes
detected") · `spectacular --fail-on-warn` ✅ (output inspected, not just
exit code). **Docker: deferred by project decision** — untouched.

## Frontend Contract Generation — Deferred, Documented Why

Not generated this checkpoint. No codegen tool (`openapi-typescript` or
equivalent) is installed in `frontend/package.json` yet — only the
toolchain itself was bootstrapped at Checkpoint 4. Generating TypeScript
types for an API with no frontend consumer would be premature, and CI's
current OpenAPI step is a "smoke check," not yet a real drift-diff check —
upgrading it is a discrete change deserving its own checkpoint's
attention. Both named as triggers for the next frontend-focused checkpoint.

## Security Review

No SQL injection surface (ORM-only, no raw SQL). No mass assignment
(hand-constructed response dicts, never `ModelSerializer.data`). No
internal Django `id` primary keys exposed in any response — only
domain/application identity fields. Activation accepts only a
configuration id + version from the URL path, validated against existing
rows. No credentials, passwords, or real database URLs in any file. Error
responses verified (by test) to never contain `traceback`, `django.db`,
`select `, or `integrityerror`.

## Files Created

`src/intraday/application/services/{__init__,errors,risk,universe,strategy}.py`,
`src/intraday/application/contracts/{__init__,errors,risk,universe,strategy}.py`,
`src/intraday/infrastructure/api/{__init__,errors,risk_views,universe_views,strategy_views,urls}.py`,
`application/services/README.md`, `infrastructure/api/README.md`,
`docs/api/CONFIGURATION_API.md`,
`tests/unit/application/services/{__init__,test_risk_service}.py`,
`tests/unit/infrastructure/api/{__init__,test_risk_api,test_universe_api,test_strategy_api}.py`,
`tests/unit/architecture/test_api_boundaries.py`.

## Files Modified

`src/intraday/application/config_schema/records.py` (added
`UniverseRecord`, `StrategyVersionSnapshot`),
`src/intraday/application/repositories/__init__.py` (Protocol return-type
extension), `src/intraday/infrastructure/persistence/repositories.py`
(matching implementation update), `src/intraday/settings/base.py`
(`SPECTACULAR_SETTINGS` correction), `src/intraday/urls.py` (mounted
`/api/v1/config/`), `pyproject.toml` (version bump),
`tests/unit/infrastructure/persistence/{test_repositories,test_round_trip}.py`
(updated to match the new wrapper return types),
`docs/architecture/{ARCHITECTURE.md,DOMAIN_BOUNDARIES.md,ARCHITECTURE_DECISIONS.md}`,
`application/contracts/README.md` (stale guardrail correction), `README.md`,
this file.

## Frontend UX Testing Readiness

| Criterion | Status |
|---|---|
| Persistence | ✅ YES |
| Business API | ✅ **YES (new this checkpoint)** |
| Frontend | ❌ NO |
| Human workflow | ❌ NO |

**Overall gate: `NO — NOT YET`.** Two of four criteria now met. `app.bat`
was **not created** — the brief's explicit condition (all four criteria)
is not satisfied.

## Deferred Items

Frontend TypeScript contract generation (documented why above); CI drift
enforcement upgrade from smoke-check to real diff; authentication/
authorization (endpoints remain open, explicitly not "production secure" —
documented); a bare `GET /api/v1/config/risk/` listing all configuration
families (no repository method exists, no demonstrated need); pagination
(not yet justified by resource size); caching (not yet justified).
Docker remains deferred. `app.bat` remains deferred — gate not yet fully
triggered.

## Git Status

Committed locally to `main`. **Not pushed.**

## Next Checkpoint

Recommend **Frontend Bootstrap for the Configuration API**: wire
`openapi-typescript` (or equivalent) into `frontend/package.json`, generate
real TypeScript types into `frontend/shared/generated_contracts`, upgrade
CI's OpenAPI step to a real drift-diff check, and build the first real
React screen (read-only configuration viewer) consuming the Checkpoint 8
API. That would satisfy Frontend UX Testing Readiness criterion 3, and a
subsequent activation-capable screen would satisfy criterion 4 — likely
triggering `app.bat`'s creation at that point.
