# ARCHITECTURE.md

## Project

Intraday Indian Cash-Equity Algorithmic Trading Platform

## Status

REPOSITORY BOOTSTRAP / TOOLING PHASE. Checkpoint 1 established the
foundational file structure; Checkpoint 2 reviewed and refined it (minimum-
viable shared kernel, explicit Signal/Order/Position/Trade model, strategy
spec-vs-implementation split, AI authority model, control-plane authority
boundary, clarified data-ownership/application-layer distinctions);
Checkpoint 3 mapped the now-approved architecture onto a concrete technology
stack (Django/DRF/Channels, PostgreSQL+TimescaleDB, Redis, Celery, React,
OpenAPI-driven contract generation — full detail in
[TECHNOLOGY_MAPPING.md](TECHNOLOGY_MAPPING.md)) and established Git/CI
governance; Checkpoint 4 bootstrapped that stack into a real, installable,
CI-validated project — Django/Celery/Channels boot, `/healthz`/`/readyz`/
`/version` exist, and the approved dependency-direction rules are now
mechanically enforced by `import-linter` (`.importlinter`); Checkpoint 5
implemented all 14 shared-kernel domain contracts as real, immutable,
Decimal/UTC-enforcing, broker-neutral Python code — see
[DOMAIN_CONTRACTS.md](DOMAIN_CONTRACTS.md); Checkpoint 6 implemented the
configuration-management layer (`application/config_schema`), deriving
validated config schemas directly from those domain contracts — see
[CONFIGURATION_MANAGEMENT.md](CONFIGURATION_MANAGEMENT.md); Checkpoint 7
implemented the persistence foundation (`application/repositories` Protocol
interfaces + `infrastructure/persistence` Django ORM implementations) for
exactly three concepts — risk configuration, universe, strategy version —
each versioned and immutable with a separately-modeled active pointer, and
retired Checkpoint 4's temporary SQLite testing exception now that real
PostgreSQL-specific models exist — see
[PERSISTENCE_ARCHITECTURE.md](PERSISTENCE_ARCHITECTURE.md); Checkpoint 8
implemented the first business API — read + version-activate endpoints for
risk configuration, universe, and strategy version under
`/api/v1/config/`, via two new directories (`application/services`,
`infrastructure/api`) and a new `.importlinter` contract confirming
`application` still never depends on `infrastructure` even with the API
layer composing both — see
[docs/api/CONFIGURATION_API.md](../api/CONFIGURATION_API.md). Still no
strategy, signal, risk-evaluation, order-placement, broker, market-data,
backtesting, or frontend business logic exists. See
[ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md) decisions #11–#42 for
everything that changed and why.

## 1. Product Scope

Exclusively **intraday trading of Indian cash equities/stocks**.

Permanently out of scope: futures, options, positional/swing/carry-forward trading,
overnight positions, commodity derivatives, currency derivatives, crypto and crypto
derivatives. NIFTY/SENSEX and other indices may be used only for market context,
regime detection, analytical filters and benchmarking — never as tradable instruments.
This boundary is encoded architecturally in `domain/instrument` and `domain/universe`,
which cannot represent non-equity, non-intraday instrument types.

## 2. Architectural Philosophy

The platform is built as a **domain-first, technology-neutral, layered architecture**
with clearly bounded contexts, not as a single trading script. Five major domains
(Section 4 of the founding brief) are each isolated as a top-level bounded context:

- **Quant Research Lab** (`research/`)
- **Signal Intelligence** (`signal_intelligence/`)
- **Trading Engine** (`trading_engine/`)
- **Production Control Plane** (`control_plane/`)
- **Communication Layer** (`communication/`)

These bounded contexts communicate only through the canonical contracts defined in
`domain/` — never through direct imports of one another's internals, direct broker
SDK calls, or direct notification-provider SDK calls. This gives:

- **Low coupling** — a bounded context can change internally without breaking others.
- **High cohesion** — each directory has one clear reason to change.
- **Strategy isolation** (Rule 5.1) — strategies depend only on domain contracts.
- **Centralized risk** (Rule 5.2) — every signal must pass `trading_engine/risk_engine`.
- **Broker abstraction** (Rule 5.3) — `domain/broker` is implemented by swappable
  adapters under `infrastructure/brokers/*`, starting with Dhan.
- **Backtest/paper/live parity** (Rule 5.5) — research, signal intelligence and the
  trading engine all consume the same `domain/market_data`, `domain/feature`,
  `domain/strategy`, `domain/signal`, `domain/risk`, `domain/order`,
  `domain/position` and `domain/trade` contracts, and `research/backtesting`
  invokes the single canonical strategy implementation in
  `trading_engine/strategy_execution` (narrow, documented exception — see
  [DOMAIN_BOUNDARIES.md](DOMAIN_BOUNDARIES.md)) rather than re-implementing it.
- **Reproducibility** (Rule 5.6) — `research/experiments` (the full Experiment
  contract moved here from `domain/` at Checkpoint 2) gives every backtest a
  traceable code/strategy/config/dataset/universe version, using generic
  version identifiers from `domain/shared_kernel`.
- **AI safety** (Rule 5.7) — `ai_agent/` holds AI proposals and guardrail
  definitions; it cannot reach live execution, which is additionally enforced at
  the infrastructure boundary (`infrastructure/ai_execution_guardrail`) and by
  `control_plane/kill_switch`.

See [DOMAIN_BOUNDARIES.md](DOMAIN_BOUNDARIES.md) for the full domain map and
dependency-direction rules, and [ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md)
for the decision log.

**Auditability** (Checkpoint 12): `control_plane/audit` holds the first
real control-plane governance code — a durable, append-only PostgreSQL
audit trail for state-changing control-plane actions, currently scoped to
risk-configuration activation. See
[AUDITABILITY.md](AUDITABILITY.md) for the full model (schema, actor
identity, transactional coupling, outcome semantics, retention policy).

**Market data & instrument foundation** (Checkpoint 14): the platform's
first trading-domain capability, deliberately data-only — a provider-
neutral historical-bar contract (`application/repositories.
HistoricalMarketDataRepository`) and application service, backed by a
deterministic fixture adapter (no live provider, no Dhan code yet). See
[MARKET_DATA_ARCHITECTURE.md](MARKET_DATA_ARCHITECTURE.md) for instrument
identity, bar/timeframe/timezone semantics, raw-vs-adjusted pricing, and
the deliberately-deferred persistence/API boundaries.

**Feature engine** (Checkpoint 15): the first technology-neutral feature
computation (Simple Moving Average), populating `signal_intelligence/
feature_engine` (a Checkpoint-1-era placeholder bounded context) for the
first time, with `application/services/feature_engine.py` orchestrating
it together with the Checkpoint 14 market-data service. See
[FEATURE_ENGINE_ARCHITECTURE.md](FEATURE_ENGINE_ARCHITECTURE.md) for
feature identity, warm-up semantics, the no-look-ahead guarantee, and how
the bounded-context/application layering was reconciled.

## 3. Layering

```
Presentation   frontend/
                    ↓
Application    application/   (contracts, gateways, config_schema)
                    ↓
Domain         domain/        (entities, value objects, interfaces — innermost)
                    ↑
Infrastructure infrastructure/ (implements domain interfaces; injected, not imported by domain)
```

Bounded contexts (`research/`, `signal_intelligence/`, `trading_engine/`,
`control_plane/`, `communication/`) sit between `domain/` and `application/`: they
depend inward on `domain/` and are orchestrated outward through `application/`.
`infrastructure/` depends on `domain/` (to implement its interfaces) but nothing
in `domain/` or the bounded contexts may depend on `infrastructure/` directly —
concrete technology is always received through dependency injection against a
domain-defined interface.

## 4. Data Boundaries

`data/` defines seven logical data categories (market, historical, cache/transient,
trading state, research, analytics/reports, audit) independent of storage
technology, per Section 11. `infrastructure/persistence` will provide the
technology-specific implementation for each once a database/store decision is
locked (currently PENDING).

## 5. Frontend / Backend Consistency

Per Rule 13, strategy parameters, risk limits, and other configurable domain
state are defined once, in `application/config_schema` (validated against
`domain/strategy` and `domain/risk`), and consumed by `config/strategies` /
`config/risk` on the backend and by `frontend/shared/generated_contracts` on the
frontend. No independent duplicate parameter definitions are permitted.

## 6. Checkpoint 2 — Architecture Review Refinements

A full architecture review (not a redesign) produced these changes; see
[DOMAIN_BOUNDARIES.md](DOMAIN_BOUNDARIES.md) for full detail and
[ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md) #11–#16 for rationale:

1. **Minimum viable shared kernel** — `domain/experiment` removed (moved to
   `research/experiments`, the concept's true single owner); every remaining
   `domain/*` contract justified by "consumed identically by 2+ bounded
   contexts."
2. **`domain/trade` added** — closes a real gap: without it there was no way
   to separate "was the strategy wrong?" (signal_intelligence's job) from
   "was the execution poor?" (trading_engine's job).
3. **Strategy spec vs. implementation** — `research/strategy_specifications`
   is now explicitly non-executable; `trading_engine/strategy_execution` is
   the single canonical executable, with `research/backtesting` granted one
   narrow, documented read-only exception to reach it for parity.
4. **Control-plane authority boundary** — made explicit and binary
   (stop/allow, disable/enable, block/unblock) so it can never become a
   second trading engine.
5. **AI authority model** — Capability → Governance/Approval → Trading
   Authority made explicit; `ai_agent/` is write-isolated by construction,
   backed by a second, independent runtime guardrail.
6. **Data ownership three-way split** — `domain/` (meaning) vs. `data/`
   (lifecycle category) vs. `infrastructure/persistence` (physical storage,
   still PENDING) stated explicitly to prevent the layers being read as
   redundant.
7. **Application layer three-way split** — domain contract vs. API contract
   (`application/contracts`) vs. config schema (`application/config_schema`)
   clarified to prevent accidental duplication of parameter definitions.
8. **Research Lab structure reviewed, not merged** — all 16
   `research/*` subdirectories were checked against the simplification test
   and kept: each maps 1:1 to an explicit lifecycle stage mandated at
   Checkpoint 1 and produces a genuinely distinct artifact type.

No top-level directory (of the original 17) was removed; the review found
the top-level boundaries sound. Total directories: 137 (unchanged; `domain/`
lost one child, `domain/trade` was added, net zero at that level).

## 7. What This Checkpoint Does Not Do

No API framework, database, frontend framework, message queue, or cloud
provider has been chosen. No strategy math, indicators, database models, API
endpoints, broker integration code, or frontend components have been written.
Those are explicitly deferred to future architecture checkpoints once the
relevant PENDING decisions are approved (see
[ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md)).
