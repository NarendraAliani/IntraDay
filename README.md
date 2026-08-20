# IntraDay — Intraday Indian Cash-Equity Algorithmic Trading Platform

> **New user? Start here → [docs/user-guide/index.html](docs/user-guide/index.html)**
> A non-technical, interactive walkthrough covering installation, starting
> the app with `app.bat`, logging in, configuring Dhan/Telegram/Discord,
> observing live market data, and safe shutdown — written for developers,
> technically comfortable users, and complete beginners alike. Double-click
> the file to open it; no server required.

> **Status: COMPLETE CONFIGURATION CONTROL-PLANE GOVERNANCE (Checkpoint
> 13).** The project installs and boots (Django, Celery, Channels,
> React/Vite), and is protected by CI-enforced formatting, linting, strict
> typing, tests, and mechanical architecture enforcement (import-linter).
> The first business API exists — read + version-activate endpoints for
> risk configuration, universe, and strategy version under
> `/api/v1/config/` — the frontend has a read-only Configuration Viewer
> with a real activation workflow (Checkpoint 10), protected by
> session-cookie authentication and Group-based authorization (Checkpoint
> 11), with login-CSRF closed and a durable, append-only audit trail added
> for risk-configuration activation (Checkpoint 12). **Checkpoint 13
> extended the identical governance pattern — authenticated actor →
> authorization → activation → durable audit event, all transactionally
> coupled — to Universe and Strategy Version**, so all three configuration
> resources now share one consistent control-plane model (see
> [docs/architecture/AUDITABILITY.md](docs/architecture/AUDITABILITY.md)).
> No strategies, indicators, signals, risk engine, order management, broker
> integration, market-data ingestion, backtesting, or live trading have
> been implemented yet. Several limitations remain (no audit UI yet, no
> account lockout beyond rate-limiting, no MFA, 403s still not audited,
> database-level audit immutability still deferred — full list in that
> document and
> [docs/architecture/AUTHENTICATION_AUTHORIZATION.md](docs/architecture/AUTHENTICATION_AUTHORIZATION.md))
> — **not yet production-ready.**

## Scope

This platform is exclusively for **intraday trading of Indian cash
equities/stocks**. Futures, options, positional/swing/carry-forward trading,
overnight positions, commodity derivatives, currency derivatives, and crypto
are permanently out of scope. Indices (e.g. NIFTY, SENSEX) may be used only
for market context and research — never as tradable instruments.

> **The full, current authoritative scope statement** — execution modes,
> in-scope capabilities, the permanent real-trading safety boundary, and
> the platform's strategy-extensibility commitment — lives at
> [docs/architecture/PRODUCT_SCOPE.md](docs/architecture/PRODUCT_SCOPE.md)
> (Checkpoint 64.20). This section predates that document and is kept
> for historical continuity; `PRODUCT_SCOPE.md` is authoritative where
> the two differ.

## Start Here (Developers / Architecture)

> Looking to install and run the app instead? See the new-user pointer
> at the top of this page.

- [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md) — architectural philosophy and layering
- [docs/architecture/DOMAIN_BOUNDARIES.md](docs/architecture/DOMAIN_BOUNDARIES.md) — how the major domains relate
- [docs/architecture/ARCHITECTURE_DECISIONS.md](docs/architecture/ARCHITECTURE_DECISIONS.md) — decision log
- [docs/architecture/TECHNOLOGY_MAPPING.md](docs/architecture/TECHNOLOGY_MAPPING.md) — the concrete technology stack and why
- [docs/architecture/DOMAIN_CONTRACTS.md](docs/architecture/DOMAIN_CONTRACTS.md) — the 14 canonical domain contracts, field by field
- [docs/architecture/CONFIGURATION_MANAGEMENT.md](docs/architecture/CONFIGURATION_MANAGEMENT.md) — how `config/*.yaml` validates against domain contracts
- [docs/architecture/PERSISTENCE_ARCHITECTURE.md](docs/architecture/PERSISTENCE_ARCHITECTURE.md) — repository interfaces, Django models, versioning, PostgreSQL strategy
- [docs/architecture/AUTHENTICATION_AUTHORIZATION.md](docs/architecture/AUTHENTICATION_AUTHORIZATION.md) — session auth, Group-based authorization, CSRF, session security, known limitations
- [docs/architecture/AUDITABILITY.md](docs/architecture/AUDITABILITY.md) — the append-only control-plane audit trail: schema, actor identity, transactional coupling, outcome semantics, retention
- [docs/api/CONFIGURATION_API.md](docs/api/CONFIGURATION_API.md) — the first business API: endpoints, contracts, errors, activation semantics
- [docs/api/FRONTEND_API_CONSUMPTION.md](docs/api/FRONTEND_API_CONSUMPTION.md) — how the frontend consumes it: OpenAPI→TypeScript contract generation, API client, CI drift detection
- [docs/development/LOCAL_DEVELOPMENT.md](docs/development/LOCAL_DEVELOPMENT.md) — developer commands (install, test, lint, Docker)
- [taskReport.md](taskReport.md) — handoff report across all checkpoints

Every directory in this repository contains its own `README.md` describing
its responsibility, its allowed dependencies, and what it must never depend
on — start with the directory closest to what you're working on.

## Quick Start

```bash
poetry install && cp .env.example .env   # backend
cd frontend && npm install && npm run generate:api && cd ..  # frontend + contract generation
make check                               # format, lint, typecheck, architecture-check, test
```

Or, on Windows, run [`app.bat`](app.bat) to install missing dependencies
and start both dev servers (development mode only — see the status note
above).

Full command reference: [docs/development/LOCAL_DEVELOPMENT.md](docs/development/LOCAL_DEVELOPMENT.md).

## Top-Level Map

| Directory | What it is |
|---|---|
| `domain/` | Canonical, technology-neutral contracts shared by every domain |
| `research/` | Quant Research Lab (idea → production lifecycle) |
| `signal_intelligence/` | Feature → signal generation, scoring, attribution, verification |
| `trading_engine/` | Risk-gated order/position lifecycle and execution |
| `control_plane/` | Health, reconciliation, audit, kill switch, alerts |
| `communication/` | Telegram/Discord/WhatsApp notification adapters |
| `application/` | API/contract orchestration layer between domains and frontend |
| `infrastructure/` | Concrete technology adapters (brokers, persistence, market data) |
| `data/` | Logical data-category boundaries |
| `frontend/` | Presentation layer for a non-technical end user |
| `config/` | Environment/strategy/universe/risk configuration data |
| `ai_agent/` | AI-agent proposal and guardrail boundary |
| `tests/` | Test structure (unit/integration/contract/backtest validation) |
| `docs/` | Architecture and project documentation |
| `scripts/` | Non-business-logic developer/operational tooling |
| `deployment/` | Release/ops concerns |
| `reports/` | Generated, reproducible output artifacts |

## Technology Stack

Locked at Checkpoint 3 — see
[TECHNOLOGY_MAPPING.md](docs/architecture/TECHNOLOGY_MAPPING.md) for full
rationale and decision matrices. At a glance: **Python 3.12, Django + DRF +
Channels, PostgreSQL (+ TimescaleDB) system of record, Redis cache, Celery
async workers, React + TypeScript frontend, OpenAPI-driven contract
generation, GitHub Actions CI, Docker deployment.** A small number of items
remain explicitly deferred (charting library, hosting provider, secret-store
product) — see TECHNOLOGY_MAPPING.md §22.

## Repository Governance

- Version control: Git, hosted at [github.com/NarendraAliani/IntraDay](https://github.com/NarendraAliani/IntraDay).
- Default branch: `main`. Short-lived feature branches, PR + CI required before merge.
- Commit convention: [Conventional Commits](https://www.conventionalcommits.org/).
- See [TECHNOLOGY_MAPPING.md §15, §18](docs/architecture/TECHNOLOGY_MAPPING.md) and `taskReport.md`'s Checkpoint 3 section for the full governance model.
