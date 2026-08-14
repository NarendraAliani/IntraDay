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

**EMA / recursive feature computation** (Checkpoint 16): adds Exponential
Moving Average, proving the Feature Engine architecture generalizes from
a fixed-window calculation (SMA) to a recursive/stateful one, without any
new abstraction beyond a single local accumulator. See
[FEATURE_ENGINE_ARCHITECTURE.md](FEATURE_ENGINE_ARCHITECTURE.md#checkpoint-16--exponential-moving-average-recursivestateful-computation)
for the EMA seed/initialization decision and its rationale.

**Signal generation** (Checkpoint 18): the first real code in
`signal_intelligence/signal_generation` — a deterministic
`DirectionalIndication` (BULLISH/BEARISH/NEUTRAL) interpreted from
SMA/EMA/ATR feature state, deliberately NOT `domain.signal.Signal`
(which requires a `strategy_id` no strategy exists yet to supply). See
[SIGNAL_GENERATION_ARCHITECTURE.md](SIGNAL_GENERATION_ARCHITECTURE.md)
for the full contract, the reasoning behind not yet producing the
canonical `Signal`, and the feature-alignment/no-look-ahead rules.

**Signal verification** (Checkpoint 19): the first real code in
`signal_intelligence/signal_verification` — evaluates whether a
`DirectionalIndication` was subsequently supported by actual price
movement (SUPPORTED/NOT_SUPPORTED/INCONCLUSIVE), at an explicit
evaluation horizon. A second real consumer of `DirectionalIndication`
within `signal_intelligence` — evaluated for `domain/` promotion and
found not yet justified (no consumer outside `signal_intelligence`
yet). See
[SIGNAL_VERIFICATION_ARCHITECTURE.md](SIGNAL_VERIFICATION_ARCHITECTURE.md)
for outcome semantics, horizon/incomplete-horizon rules, and the
promotion assessment.

**Signal lifecycle** (Checkpoint 20): the first real code in
`signal_intelligence/signal_lifecycle` — a two-state (ACTIVE/EXPIRED)
temporal-validity model for a `DirectionalIndication`, with explicit
expiry (no magic default) and deterministic, immutable transitions.
Deliberately independent of `signal_verification` — validity and
outcome-correctness are orthogonal questions, evaluated separately. A
third intra-context consumer of `DirectionalIndication`; `domain/`
promotion re-evaluated and still not yet justified. See
[SIGNAL_LIFECYCLE_ARCHITECTURE.md](SIGNAL_LIFECYCLE_ARCHITECTURE.md)
for the full state model, expiry semantics, and the
verification-independence rationale.

**Theoretical outcome** (Checkpoint 21): the first real code in
`signal_intelligence/theoretical_outcome` — measures maximum favorable/
adverse price excursion (MFE/MAE) a `DirectionalIndication` experienced
over an explicit observation window, clamped so MFE ≥ 0 and MAE ≤ 0
always hold. Deliberately independent of both `signal_verification` and
`signal_lifecycle`. Conditional expectancy explicitly deferred (requires
a trading policy this bounded context has no authority to invent). A
fourth intra-context consumer of `DirectionalIndication`; `domain/`
promotion re-evaluated and still not yet justified. See
[SIGNAL_THEORETICAL_OUTCOME_ARCHITECTURE.md](SIGNAL_THEORETICAL_OUTCOME_ARCHITECTURE.md)
for the full MFE/MAE definition and the expectancy-deferral rationale.

**Operational settings & provider connectivity** (Checkpoint 22): the
first real code in `infrastructure/brokers/dhan`,
`communication/adapters/telegram`, and `communication/adapters/discord`
— encrypted-at-rest credential storage (Dhan, Telegram, Discord),
database-primary/environment-fallback configuration precedence, a
write-only secret-replacement API contract, and an honest
Configured-≠-Connected connection-status model, reusing the existing
RBAC/audit-trail mechanisms verbatim. Dhan connectivity is strictly
read-only this checkpoint (`GET /v2/profile` only) — no order/trading
capability exists. See
[SETTINGS_ARCHITECTURE.md](SETTINGS_ARCHITECTURE.md) and
[PROVIDER_CONNECTIVITY_ARCHITECTURE.md](PROVIDER_CONNECTIVITY_ARCHITECTURE.md).

**Live market data foundation** (Checkpoint 23): the first real code in
`control_plane/market_data_health` and the first live (non-fixture)
market-data path this platform has ever had — a small, configuration-
driven observation universe (default RELIANCE/TCS/INFY/HDFCBANK) fetched
via Dhan's read-only Market Quote REST endpoint, NSE cash-equity session
awareness (`domain/session/calendar.py`, the first market-hours
computation in this codebase), and a three-state-richer health model
(Configured ≠ Connected ≠ Fresh) than Checkpoint 22's. Explicitly
unwired from signal generation (`signal_intelligence.signal_generation`
still consumes only the Checkpoint 14 synthetic fixture repository,
unchanged) and from every `trading_engine/*` module, which remain empty
Checkpoint-4 scaffolding. See
[LIVE_MARKET_DATA_ARCHITECTURE.md](LIVE_MARKET_DATA_ARCHITECTURE.md)
for the full REST-vs-WebSocket rationale, health model, and manual
live-market validation record.

**Live bar aggregation foundation** (Checkpoint 24A): bridges
Checkpoint 23's `Quote` observations to the canonical `Bar` contract
(Checkpoint 5/14, reused completely unmodified) that
`SignalGenerationService`/`FeatureEngineService` already expect — a
pure, deterministic, replay-safe Quote→Bar aggregation function
(`domain/market_data/aggregation.py`), explicit FORMING/CLOSED bar
status, gap detection, and anomalous-observation reporting, all
read-only and still explicitly unwired from signal generation
(mechanically proven by a dedicated architecture test). Introduced as
an intermediate step specifically to avoid the invalid architectural
shortcut of connecting `Quote`s directly to a pipeline that requires
`Bar`s. See
[LIVE_BAR_AGGREGATION_ARCHITECTURE.md](LIVE_BAR_AGGREGATION_ARCHITECTURE.md)
for the full aggregation rule, volume limitation, and upsert-persistence
rationale.

**Dhan market-data capability research** (Checkpoint 25.1, research
only — no code changed): confirmed against Dhan's own official
documentation that both a WebSocket tick-by-tick feed and a
historical/intraday OHLC REST endpoint exist, and that a **hybrid** of
the two (WebSocket for real-time forming bars, historical OHLC for
authoritative closed-bar reconciliation and gap backfill) is the
correct target architecture for eventually replacing `SAMPLE_BAR` —
but three material facts about Dhan's actual behavior (same-day
intraday candle availability, candle authority, exact timestamp
timezone) remain unconfirmed by documentation alone and require direct
API verification before any implementation begins. See
[DHAN_MARKET_DATA_CAPABILITY_RESEARCH.md](DHAN_MARKET_DATA_CAPABILITY_RESEARCH.md)
for the full evidence, and its six-condition `TRADING_GRADE_BAR`
promotion checklist. `SAMPLE_BAR` remains the classification;
`SignalGenerationService`/`FeatureEngineService` remain unwired.

**Strategy engine, multi-strategy registry, dynamic configuration**
(Checkpoint 26): the first real executable strategies (EMA Crossover,
SMA Trend Filter, ATR Volatility Breakout), a canonical field registry,
a generic parameter-schema/validation system, a strategy registry with
activation semantics, a multi-strategy execution coordinator (shared
feature computation, per-strategy failure isolation), versioned
configuration persistence, an OpenAPI-backed API surface, and a
schema-driven frontend renderer. Strictly diagnostic/fixture-only —
`DiagnosticStrategyExecutionService` depends solely on
`HistoricalMarketDataService`, structurally unable to reach live/
SAMPLE_BAR data (proven by
`tests/unit/architecture/test_strategy_execution_sample_bar_boundary.py`).
Registry "activation" governs diagnostic eligibility only and is
explicitly not live-trading authorization. See
[STRATEGY_ENGINE_ARCHITECTURE.md](STRATEGY_ENGINE_ARCHITECTURE.md) and
[STRATEGY_CONFIGURATION.md](STRATEGY_CONFIGURATION.md) for the full
design, including a real architecture-boundary violation found and
fixed during this checkpoint's own Part 2 audit (an early draft broke
`.importlinter` contract 4 by importing `signal_intelligence` directly
from `trading_engine`).

**Backtesting proof of concept and Strategy Workbench** (Checkpoint 27):
a full historical-bars -> features -> strategy -> simulated execution ->
trade ledger -> equity curve -> metrics pipeline, reusing the
Checkpoint 26 strategy engine end-to-end (same `StrategyRegistry`, same
parameter schema/renderer, same feature dispatcher) - no duplicate
strategy, indicator, or signal model. Deterministic, look-ahead-free
execution (signals fill at the next bar's open, proven by dedicated
tests); Sharpe/Sortino explicitly labeled trade-level/non-annualized to
avoid a misleading figure. Frontend: a Discover -> Configure -> Backtest
-> Review workflow, a comparison/leaderboard view, research watchlists,
and a strategy research pause/resume monitor - deliberately no
"Buy"/"Sell"/"Deploy Live" control anywhere. Strictly backtesting/
research only; SAMPLE_BAR remains blocked from live action, and no
broker/order-execution import exists in the new code (proven by
`tests/unit/architecture/test_backtesting_sample_bar_boundary.py`). See
[BACKTESTING_ARCHITECTURE.md](BACKTESTING_ARCHITECTURE.md) for the full
design, including a real `.importlinter` narrow-exception granularity
issue found and fixed during this checkpoint's own Part 1 audit.

**Roadmap note (post-Checkpoint 27):** the next named checkpoint
should be the **narrow, read-only Dhan API verification step**
recommended at Checkpoint 25.1 (resolving same-day intraday candle
availability, candle authority, and exact timestamp timezone via
direct, live API calls) — not yet "Live Signal Observation", not yet a
hybrid-architecture implementation, and not yet `TRADING_GRADE_BAR`
promotion, all of which remain premature until that verification
completes. Paper trading, a real order API, and controlled live trading
remain deliberately un-numbered — each depends on `trading_engine/*`
components (order management, execution management, risk engine) that
do not exist yet, and assigning checkpoint numbers to them before that
dependency is real would misrepresent how much design work those
numbers actually cover.

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

## Note on this document's currency

This document's "Status" narrative above was kept current through
Checkpoint 8; from Checkpoint 9 onward, `taskReport.md` (session log)
and per-topic documents under `docs/architecture/` are the current
source of truth for what exists - this file is preserved as the
original architecture-review record, not rewritten each checkpoint.
Checkpoint 32 added `REPORTING_ARCHITECTURE.md`,
`PLACEHOLDER_AND_FEATURE_STATE_ARCHITECTURE.md`, and
`RUNTIME_ARCHITECTURE_DECISION.md` - see `ARCHITECTURE_DECISIONS.md`'s
Checkpoint 32 entries and `taskReport.md` for what they establish.
Checkpoint 33 is a critical, evidence-based product-readiness audit -
see `docs/architecture/PRODUCT_READINESS_GAP_ANALYSIS.md` and
`docs/research/ACTIVE_PRODUCT_READINESS_RESEARCH.md`. Its headline
finding: this codebase is a disciplined, well-tested research/
backtesting platform with a live-data observation front end - it is
**not yet an operable trading system**. `risk_engine`, `order_management`,
`execution_management`, `session_management`, and `broker_abstraction`
remain empty scaffolding; no order has ever been placed; no
reconciliation, paper trading, or risk gating exists. This is not a
regression - every prior checkpoint correctly kept these boundaries
untouched per its own safety rules - but it means the distance between
"architecturally sound" and "operationally ready" is large and should
not be assumed closed by the volume of work completed so far.

Checkpoint 34 closes a real slice of that gap - PAPER mode only,
TRADING_MODE=LIVE remains unavailable. A genuine, broker-neutral
order state machine and event model (`docs/architecture/
ORDER_LIFECYCLE.md`), the first real risk engine and kill switch
(`docs/architecture/RISK_ENGINE_ARCHITECTURE.md`), a broker-neutral
reconciliation service, and an event-driven `PaperBroker` implementing
`domain.broker.BrokerGateway` (`docs/architecture/
PAPER_TRADING_ARCHITECTURE.md`) now exist, tested, and orchestrated
through one non-bypassable `PaperTradingService`
(kill switch -> risk -> broker). `trading_engine/order_management`,
`execution_management`, and `broker_abstraction` remain otherwise
untouched scaffolding - this checkpoint's new code lives in
`domain/order`, `trading_engine/risk_engine`, `control_plane/kill_switch`
and `control_plane/reconciliation`, `infrastructure/brokers/paper`, and
`application/services/paper_trading.py`. No real order has been placed;
LIVE mode does not exist anywhere in this codebase.
