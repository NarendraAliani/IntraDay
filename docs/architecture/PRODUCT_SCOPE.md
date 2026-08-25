# Product Scope

Checkpoint 64.20. The authoritative statement of what this system is,
its execution modes, and its permanent safety boundary. Superseding
scope language should link here rather than duplicate it.

## What this system is

```
Automated Algo Trading System
for the Indian Equity Market
focused on Intraday Trading
```

Indian NSE intraday trading.

**Scope resolution, Checkpoint 64.77.** Checkpoint 64.76's Dhan
capability research surfaced a genuine conflict: this document and
several code-level invariants recorded the platform as "permanently
Indian cash equities only", while the actual product intent is NSE
stock options as the primary trading instrument. That is a product
decision, and it is resolved here as follows — this section supersedes
the earlier "cash equities only" wording wherever it appears.

| | |
|---|---|
| Platform | Indian NSE intraday trading platform |
| **Primary trading instrument** | **NSE STOCK OPTIONS (OPTSTK, NSE_FNO segment)** |
| Supporting / reference instrument | NSE CASH EQUITIES — retained in full, and used for underlying price, reference and derived features |
| Not enabled | NSE INDEX OPTIONS (OPTIDX), BSE OPTIONS, BSE EQUITIES |

Index options are *representable but never active*: an OPTIDX contract
must be parseable so it can be excluded on purpose rather than misread
as a stock option, and every stock-option selector rejects it
(`domain/instrument/options.py::require_stock_option`).

Still permanently out of scope: futures, positional/swing/carry-forward
trading, overnight positions, commodity derivatives, currency
derivatives, and crypto. Indices (e.g. NIFTY, SENSEX) may be used only
for market context and research — never as tradable instruments, and
index *options* are not enabled.

The existing cash-equity data pipeline (equity WebSocket, `Quote`,
`Bar`, aggregation, archive) is unchanged by this decision: only the
scope *statement* changed, not the equity machinery.

## Capabilities in scope

```
Historical Research
Backtesting
Replay
Strategy Evaluation
Live Market Data
Signal Generation
Signal Evidence
TradePlan
Risk Management
Paper Trading
Telegram Communication
Discord Communication
Reporting
Operational Monitoring
Strategy Research
Strategy Extensibility
```

Every item above is either a real, tested, already-shipped capability
(Historical Research/Backtesting/Replay/Strategy Evaluation/Live Market
Data/Signal Generation/Signal Evidence/TradePlan/Risk Management/Paper
Trading/Telegram/Discord/Reporting/Operational Monitoring — see
`taskReport.md` history, Checkpoints 26-64.19) or an architectural
property this checkpoint formally audited and confirmed
(Strategy Research/Strategy Extensibility — see
`STRATEGY_EXTENSIBILITY_AND_RESEARCH_ARCHITECTURE.md`).

## Primary execution modes

```
PAPER
LIVE-MARKET-DATA + PAPER-EXECUTION
```

`PAPER`: strategies evaluated against historical/replayed data, orders
simulated through `PaperBroker` (the ONLY concrete broker implementation
in this codebase — re-verified every checkpoint since 64.11).
`LIVE-MARKET-DATA + PAPER-EXECUTION`: the live Dhan WebSocket feed drives
the same strategy/risk/paper pipeline in real time (Checkpoint 64.1
onward) — still exclusively `PaperBroker` execution, never a real order.

## Real trading — explicitly out of scope

```
Real broker order placement remains:
    OUT OF CURRENT IMPLEMENTATION SCOPE
    EXPLICITLY DISABLED
    REQUIRES FUTURE SEPARATE APPROVAL
```

This is a structural property, not a configuration flag: `real_trading_
state` is a constant `"DISABLED"` on every code path in `application.
services.live_paper_readiness` (Checkpoint 64.12), and `PaperBroker` is
the only class in this entire codebase implementing order submission —
there is no code path to a real broker order API anywhere (mechanically
re-verified, e.g. `tests/unit/architecture/test_live_market_data_
boundaries.py` scans the live-worker command directory for a forbidden
`trading_engine` import). Enabling real trading in the future would
require a new, separately-approved capability — not a setting change,
not a strategy reaching any lifecycle stage (see
`STRATEGY_EXTENSIBILITY_AND_RESEARCH_ARCHITECTURE.md`'s "Strategy
Approval Lifecycle" section — `LIVE_ELIGIBLE != LIVE_ENABLED`), and not
an implicit consequence of any checkpoint in this project's history.

## Extensibility commitment

The platform is intended to support the addition of many future
strategies without changing the core scanner, backtesting engine, risk
engine, PaperBroker, communication engine, or reporting engine. This is
not an aspiration stated without evidence — Checkpoint 64.20 formally
audited this claim and proved it mechanically with a real, deterministic
proof-of-extensibility strategy (`TEST_MOMENTUM`, NON_PRODUCTION,
never registered in the real strategy list) moving through the entire
pipeline — registry → configuration → strategy execution → signal →
evidence → risk → paper execution → communication → report — with zero
core-engine strategy-specific branching required. See
`STRATEGY_EXTENSIBILITY_AND_RESEARCH_ARCHITECTURE.md` for the full audit,
change-surface accounting, and the honest gaps that DO still require a
real (small, identified) extension for certain future strategy types
(e.g. a new technical-indicator feature function for VWAP/RSI-based
strategies).
