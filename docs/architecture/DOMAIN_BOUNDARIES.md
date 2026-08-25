# DOMAIN_BOUNDARIES.md

Defines the relationships and allowed communication paths between the five
major domains plus the supporting layers.

> **Checkpoint 2 (Architecture Review) update:** this document was revised
> during the architecture-refinement checkpoint. See
> [ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md) decisions #11–#16 for
> the full rationale behind each change below. The original Checkpoint 1
> structure was preserved except where explicitly called out.

## Domains

| Domain | Directory | Owns |
|---|---|---|
| Quant Research Lab | `research/` | Idea → production research lifecycle, backtesting, validation |
| Signal Intelligence | `signal_intelligence/` | Feature computation → scored, attributed, verifiable signals |
| Trading Engine | `trading_engine/` | Risk-gated order/position lifecycle, execution, square-off |
| Production Control Plane | `control_plane/` | Health, reconciliation, audit, kill switch, alerts |
| Communication Layer | `communication/` | Outbound notifications via adapters |
| Frontend | `frontend/` | Presentation for a non-technical user |
| Data Layer | `data/` | Logical data-category boundaries |

## Canonical Contract Flow (Rule 5.2)

```
Market Data (domain/market_data)
    ↓
Feature Engine (signal_intelligence/feature_engine, using domain/feature)
    ↓
Strategy (domain/strategy, executed via trading_engine/strategy_execution)
    ↓
Signal (domain/signal, produced by signal_intelligence/signal_generation)
    ↓
Signal Validation (signal_intelligence/signal_verification, signal_lifecycle)
    ↓
Risk Engine (trading_engine/risk_engine)  ← NON-BYPASSABLE, all signals pass here
    ↓
Order Management (trading_engine/order_management)
    ↓
Execution (trading_engine/execution_management)
    ↓
Broker Adapter (infrastructure/brokers/*, via trading_engine/broker_abstraction → domain/broker)
```

No shortcut path exists in the file structure: `signal_intelligence` has no
directory that reaches into `infrastructure/brokers`, and `trading_engine`'s
order/execution directories only reach brokers through `broker_abstraction`,
which in turn only knows the `domain/broker` interface.

`trading_engine/execution_management` additionally closes the loop by
producing `domain/trade` records once a round-trip completes — see "Signal /
Order / Position / Trade" below.

## Signal / Order / Position / Trade (Checkpoint 2, Section 5)

Four concepts must never collapse into one another:

| Concept | Definition | Owner |
|---|---|---|
| Signal | A research/trading decision **candidate** | `domain/signal`, produced by `signal_intelligence/signal_generation` |
| Order | An execution request **approved by risk** | `domain/order`, produced by `trading_engine/order_management` after `trading_engine/risk_engine` |
| Position | Actual broker/account **exposure** at a point in time | `domain/position`, tracked by `trading_engine/position_lifecycle` |
| Trade | A **completed, closed** execution outcome (entry+exit, realized P&L) | `domain/trade` (new at Checkpoint 2), produced by `trading_engine/execution_management` |
| Signal Outcome | What would have happened **theoretically** after the signal | `signal_intelligence/theoretical_outcome`, compared in `signal_intelligence/signal_verification` |

This separation is what lets the platform answer two different diagnostic
questions independently:

- **"Was the strategy wrong?"** → `signal_intelligence/signal_verification`
  compares the Signal's prediction against its theoretical outcome. No
  execution data involved.
- **"Was the execution poor?"** → `trading_engine/execution_management`
  compares the realized Trade against the risk-approved Order's intent
  (price/quantity/timing slippage). No strategy-correctness judgment involved.

## Strategy Lifecycle — Spec vs. Implementation (Checkpoint 2, Section 4)

```
IDEA (research/ideas)
  ↓
HYPOTHESIS (research/hypotheses)
  ↓
SPECIFICATION (research/strategy_specifications — declarative, non-executable)
  ↓
IMPLEMENTATION (trading_engine/strategy_execution — the ONLY executable code
                 satisfying domain/strategy; single-sourced for backtest/paper/live)
  ↓
BASELINE BACKTEST (research/backtesting, invokes the implementation above
                    read-only — narrow, documented exception, see below)
  ↓
DEEP ANALYSIS (research/deep_analysis)
  ↓
ROBUSTNESS VALIDATION (research/parameter_stability, walk_forward,
                        monte_carlo, robustness_validation)
  ↓
PROMOTION DECISION (research/strategy_promotion, records evidence)
  ↓
STRATEGY VERSION / MATURITY STATE (trading_engine/strategy_registry —
                                    authoritative current state: PAPER,
                                    LIMITED_LIVE, PRODUCTION, SUSPENDED, ...)
  ↓
PRODUCTION STRATEGY RUNTIME (trading_engine/strategy_execution, now invoked
                              live under trading_engine/session_management
                              and gated by trading_engine/risk_engine)
```

A research artifact (spec) is never runnable; the runtime executable exists
in exactly one place. This makes it structurally difficult — not merely a
convention — to confuse a research artifact with a production executable.

**Narrow dependency exception:** `research/backtesting` depends read-only on
the strategy-implementation module of `trading_engine/strategy_execution`
(and nothing else in `trading_engine`) to guarantee backtest/live code-path
parity (Rule 5.5). This is the one deliberate exception to "research must not
depend on trading_engine" and must never become bidirectional.

## Domain Relationships

- **Research → Signal Intelligence / Trading Engine**: one-directional, via
  promotion. `research/strategy_promotion` records the evidence trail that
  allows a `domain/strategy` to move from research maturity states toward
  `trading_engine/strategy_registry`. Research never calls live broker or
  communication adapters (`research/` must not depend on
  `infrastructure/brokers` or `communication/`). The single documented
  exception is `research/backtesting`'s narrow, read-only dependency on
  `trading_engine/strategy_execution`'s implementation module (see Strategy
  Lifecycle above) — this exists solely for Rule 5.5 parity and does not
  extend to any other part of `trading_engine`.

- **Signal Intelligence → Trading Engine**: signal intelligence hands
  validated `domain/signal` instances to the trading engine's risk engine. It
  never constructs orders or talks to brokers itself.

- **Trading Engine → Control Plane**: the trading engine emits order/position/
  trade state that `control_plane/reconciliation` and `control_plane/audit`
  observe. Control plane can *halt* the trading engine
  (`control_plane/kill_switch`) but does not implement strategy or execution
  logic itself. Its authority is strictly binary/supervisory (stop trading,
  disable a strategy's state, trigger the global kill switch, block new
  orders, detect reconciliation failures, report critical failures) — it must
  never choose *what* to trade, which would make it a second trading engine
  (Checkpoint 2, Section 10).

- **Control Plane → Communication**: operational alerts flow from
  `control_plane/alerts` to `communication/notification_router` through the
  provider-agnostic `communication/contracts` — never through a direct
  Telegram/Discord SDK call from control_plane.

- **All bounded contexts → Application → Frontend**: the frontend never
  imports domain or bounded-context internals; it consumes only
  `application/contracts` and `application/config_schema`, keeping backend and
  frontend parameter definitions single-sourced (Rule 13).

- **AI Agent boundary**: `ai_agent/` may read from `research/` and write only
  inside `ai_agent/` (proposals, session state) — it is write-isolated from
  every other directory. It has no directory path into
  `trading_engine/execution_management`, `infrastructure/brokers`,
  `control_plane/kill_switch` (write access), or `application` auth concerns.
  A proposal becomes effective only via human/governed-process approval that
  copies it into its real domain home (Checkpoint 2, Section 11 — see
  `ai_agent/README.md` for the full AI Authority Model diagram). This is
  enforced structurally here (no dependency edge exists) and additionally at
  the infrastructure boundary (`infrastructure/ai_execution_guardrail`) as an
  independent second enforcement layer.

## Minimum Viable Shared Kernel (Checkpoint 2, Section 3.1; count corrected at Checkpoint 3 §29)

**Implemented at Checkpoint 5** — see [DOMAIN_CONTRACTS.md](DOMAIN_CONTRACTS.md)
for full field-level documentation of every contract below.

`domain/` retains **14 contracts**: `shared_kernel`, `market_data`,
`instrument`, `universe`, `feature`, `strategy`, `signal`, `risk`,
`portfolio`, `order`, `position`, `trade`, `broker`, `session`. Each is
included only because it is consumed **identically by two or more bounded
contexts**, most often to preserve backtest/paper/live parity (Rule 5.5).

> **Checkpoint 3 correction:** the Checkpoint 2 chat response summarized this
> list as "Retained (13)" — an off-by-one error in the conversational summary
> only. This document and `domain/README.md` always listed all 14 items
> correctly; no file ever stated the wrong number. This note exists purely to
> close out the discrepancy raised in Checkpoint 3 §29.

| Contract | Kept because | Would break if removed |
|---|---|---|
| `market_data` | research (EDA/backtest), signal_intelligence, control_plane all need one Bar/Tick/Quote shape | Feature/backtest parity breaks; duplicate market-data schemas drift |
| `instrument` | identity referenced by every other contract (signal, order, position, universe) | No common way to identify "which stock" across contexts |
| `universe` | trading_engine needs live eligibility checks; research needs identical universe definition for backtest parity | Live risk engine and backtest could trade different universes silently |
| `feature` | signal_intelligence computes live, research computes offline — same schema required for parity | Backtested features could diverge from live features unnoticed |
| `strategy` | the interface every strategy implementation satisfies, referenced by research, trading_engine, application/config_schema | Strategy isolation (Rule 5.1) has no enforceable contract |
| `signal` | produced by signal_intelligence, consumed by trading_engine and control_plane/audit | No common candidate-decision shape across the risk chokepoint |
| `risk` | trading_engine/risk_engine's own contract, but also needed by research/backtesting (parity) and config/risk, application/config_schema | Backtest could not simulate the same risk gate as live |
| `portfolio` | needed by live portfolio_management AND backtest P&L simulation | Backtest and live portfolio math could diverge |
| `order` | needed by live order_management AND backtest order simulation AND control_plane/reconciliation | No common order shape to reconcile broker vs. internal state |
| `position` | needed by live position_lifecycle AND backtest simulation AND reconciliation | Same as `order` |
| `trade` | **added at Checkpoint 2** — needed by execution_management (live), research/backtesting (simulated), reporting | No way to separate "was execution poor?" from "was the strategy wrong?" |
| `broker` | the published interface `infrastructure/brokers/*` implements and `trading_engine/broker_abstraction` consumes | Multi-broker support (Rule 5.3) collapses to one broker's shape |
| `session` | needed by trading_engine (live cutoff enforcement) AND research (realistic backtest session simulation) | Backtest could trade outside real market hours undetected |

**Removed at Checkpoint 2:** `experiment`. It was consumed by exactly one
bounded context (`research/`), with only references (an id) needed
elsewhere — it did not meet the "consumed identically by 2+ contexts" bar
for shared-kernel membership. Its full contract now lives at
`research/experiments`; a generic version/lineage identifier primitive
remains in `domain/shared_kernel` for the few cross-context references that
need to stamp/compare a version. **Rule going forward:** a concept is added
to `domain/` only when at least two bounded contexts need the *identical*
contract (not just a reference to it) — otherwise it belongs to the single
owning bounded context.

## Data Ownership Model (Checkpoint 2, Section 6)

```
domain/*            — business meaning: what does this data mean, semantically?
      ↓ (consumed by)
data/*               — logical category: what lifecycle/retention rules govern it?
      ↓ (implemented by)
infrastructure/persistence — physical storage: how is it technically stored? (PENDING)
```

`domain/` never imports `data/` or `infrastructure/persistence`. `data/`
imports only `domain/` contract types to describe which category they fall
into. `infrastructure/persistence` implements repository interfaces defined
in `domain/`, informed by the lifecycle semantics documented in `data/` (e.g.
`data/historical_data`'s "immutable, append-only" constrains what storage
technology is even eligible) — the physical choice is always downstream of,
never upstream of, the logical category.

## Persistence Boundary (Checkpoint 7)

```
domain contracts → application/config_schema → application/repositories (Protocol interfaces)
      → infrastructure/persistence (Django ORM implementations) → PostgreSQL
```

`application/repositories` is a **new directory** added to the approved
`application/` layer at Checkpoint 7 (alongside `contracts/`, `gateways/`,
`config_schema/`) — see
[ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md) decision #38 for the
justification. It holds `typing.Protocol` repository interfaces;
`infrastructure/persistence` implements them. `.importlinter` contract #6
(new this checkpoint) mechanically enforces that `application` must never
depend on `infrastructure` — the dependency inversion runs the other way.
Full detail: [PERSISTENCE_ARCHITECTURE.md](PERSISTENCE_ARCHITECTURE.md).

## API Boundary (Checkpoint 8)

```
HTTP → infrastructure/api (views, composes application + infrastructure.persistence)
     → application/contracts (DRF serializer shape) + application/services (use cases)
     → application/repositories → infrastructure/persistence → PostgreSQL
```

Two more directories were added: `application/services` (use-case
orchestration, depends only on repository Protocols) and
`infrastructure/api` (the HTTP delivery adapter — a "driving adapter" in
ports-and-adapters terms, the same category as `infrastructure/persistence`,
allowed to depend on `application` and compose it with concrete
infrastructure, which `application` itself must never do). See
[ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md) decisions #41–#42
and [docs/api/CONFIGURATION_API.md](../api/CONFIGURATION_API.md).

## Explicit Non-Dependencies (Guardrails)

- `domain/instrument` represents exactly two instrument identities, as
  siblings: `contracts.Instrument` (NSE cash equities + reference indices)
  and `options.OptionContract` (NSE **stock** options — the primary trading
  instrument since the Checkpoint 64.77 scope resolution). `Instrument`
  itself still cannot represent a derivative, by design — an option's
  identity is (underlying, expiry, strike, CE/PE), so it gets its own
  contract instead of nullable derivative columns on the shared equity one.
  NSE index options are parseable but excluded from the active universe;
  commodities, currency, futures and crypto have no contract location at
  all, by design.
- `domain/position` and `trading_engine/position_lifecycle` model intraday
  positions only; there is no "carry-forward" or "overnight" state.
- Strategies (future code under `trading_engine/strategy_execution` /
  research strategy implementations) must depend only on `domain/*`
  contracts — never on `infrastructure/brokers`, `communication/adapters`,
  `infrastructure/persistence`, `frontend`, or authentication concerns
  (Rule 5.1).
