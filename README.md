# IntraDay — Intraday Indian Cash-Equity Algorithmic Trading Platform

> **Status: ARCHITECTURE / TECHNOLOGY MAPPING PHASE (Checkpoint 3).** This
> repository currently contains the foundational directory structure,
> architecture documentation, and an approved technology mapping. No
> business logic, database schema, API, broker integration, or frontend
> screens have been implemented yet.

## Scope

This platform is exclusively for **intraday trading of Indian cash
equities/stocks**. Futures, options, positional/swing/carry-forward trading,
overnight positions, commodity derivatives, currency derivatives, and crypto
are permanently out of scope. Indices (e.g. NIFTY, SENSEX) may be used only
for market context and research — never as tradable instruments.

## Start Here

- [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md) — architectural philosophy and layering
- [docs/architecture/DOMAIN_BOUNDARIES.md](docs/architecture/DOMAIN_BOUNDARIES.md) — how the major domains relate
- [docs/architecture/ARCHITECTURE_DECISIONS.md](docs/architecture/ARCHITECTURE_DECISIONS.md) — decision log
- [docs/architecture/TECHNOLOGY_MAPPING.md](docs/architecture/TECHNOLOGY_MAPPING.md) — the concrete technology stack and why
- [taskReport.md](taskReport.md) — handoff report across all checkpoints

Every directory in this repository contains its own `README.md` describing
its responsibility, its allowed dependencies, and what it must never depend
on — start with the directory closest to what you're working on.

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
