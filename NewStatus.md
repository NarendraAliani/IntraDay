# IntraDay — Project Status (as of 2026-08-19)

Honest, evidence-based status of the Automated Algo Trading System for Indian
cash-equity intraday trading, covering both Paper and (eventually) Live
trading. This supersedes the scattered checkpoint-era documents in
`docs/architecture/` and `docs/research/` for a single current picture —
those documents remain as historical record but are stale in places (most
notably `ACTIVE_PRODUCT_SCORECARD.md`, which predates almost all of the
frontend and the real Dhan historical-data integration).

**Standing rule, revised 2026-08-19 (was "permanent PAPER-only," corrected
after review against the project's actual stated goal — real AND paper
trading on the live Indian market):**

> **PAPER-first safety boundary; LIVE execution is a future controlled
> phase requiring explicit approval and separate certification.**

There is no live-order-placement code path anywhere in this codebase today
(`PaperBroker.submit_order()` is the only `submit_order` implementation
that exists), and none will be added as a side effect of other work. The
architecture should be *designed so LIVE execution is reachable later*
(Dhan's own API already supports real order placement, order-update
postbacks, and positions/portfolio endpoints), but the *runtime* stays
PAPER-only until a deliberate, explicitly-approved, separately-certified
decision turns it on. This document's "Live trading readiness" scores
below measure "is the platform capable of running against real market
data," never "has live order placement been built" — that remains a future
gate, not a current gap.

---

## 1. Executive summary

| Question | Answer |
|---|---|
| Can you paper-trade against **historical/replay data** today? | **Yes** — real backtesting engine, real risk/position/reconciliation/EOD lifecycle, real Dhan historical-data fetch (as of this session), a working frontend. |
| Can you paper-trade against **live intraday market data** today? | **No** — the live WebSocket connection to Dhan does not exist yet; only a synthetic/local-socket stand-in has been built and tested. |
| Can you place a **real (live) order** today? | **No, and this was never attempted** — by design, per the project's PAPER-first safety boundary. The architecture leaves room for it later; the runtime does not do it now. |
| Is the historical backtest data **real** or **fabricated**? | **Real, as of this session.** Until this session, all backtests ran on a deterministic *synthetic* generator. A genuine Dhan historical-candle REST integration was built and is now used automatically whenever Dhan credentials are configured. |
| Is there a working **frontend**? | **Yes** — 8 feature areas (Configuration, Settings, Market Data, Strategies/Backtesting/Compare/Watchlists/Strategy Monitor, Paper Trading, Reports), all backed by real APIs, not mocked. |
| Test health? | **1300 backend tests / 126 frontend tests, all passing.** Clean under ruff, mypy, import-linter, Django system checks, and OpenAPI schema validation. |
| Overall maturity | **Engineering maturity ~8.8–9.0/10. Active-product maturity ~6.0/10** (the gap is "well-built" vs. "has run continuously against real data"). Live trading readiness ~1.0/10, by design. See the full scorecard in §5. |

---

## 2. What's genuinely done and tested

### 2.1 Backtesting (the strongest, most complete part of the system)
- **Real Dhan historical market data** (built this session): a genuine REST client for Dhan's `/v2/charts/historical` (daily) and `/v2/charts/intraday` (1/5/15/60-min) endpoints, verified against Dhan's own documentation. Used automatically for every backtest once Dhan credentials are configured in Settings; falls back to a synthetic generator only when no credentials exist (never silently, always logged).
- **DB-first historical pipeline**: coverage-check → fetch-only-what's-missing → validate → persist → verify → scan. Proven to never re-fetch already-cached data, to survive the data provider being disabled after preparation, and to never report a falsely-complete result on partial/failed fetches.
- **3 real strategies**: `ema_crossover`, `sma_trend_filter`, `atr_volatility_breakout` — all schema-driven (parameters, validation, suggested defaults), no hardcoded per-strategy UI.
- **Multi-instrument, multi-timeframe runs**: pick one stock, several, or an entire exchange (NSE/BSE); daily and intraday timeframes; real, incrementally-updated progress (never a fake timer bar) with per-instrument/per-combination failure disclosure.
- **Full instrument master**: the real Dhan scrip master (~3,100 genuine NSE/BSE cash-equity shares, correctly excluding bonds, derivatives, and Dhan's own dummy test scrips), with real company display names and real security IDs.
- **Cost modeling**: flat-percentage and a verified NSE cash-equity intraday statutory cost schedule (STT, exchange charges, SEBI turnover fee, GST, stamp duty).
- **Live/backtest code parity by construction**: the same strategy execution and feature-computation code path is used for both backtesting and (eventual) live signal generation — not two parallel implementations.

### 2.2 Paper trading order/position lifecycle (built pre-session, still standing and tested)
- **Risk engine**: 10 real rejection checks (kill switch, market session, strategy active, stale data, duplicate order, max daily loss, max position size, max exposure, max concurrent positions, instrument allow/deny list, daily trade limit, per-trade risk).
- **`PaperBroker`**: full order lifecycle (CREATED → SUBMITTED → ... → FILLED/REJECTED/CANCELLED), MARKET/LIMIT/STOP fills with slippage, partial fills, a real trade ledger, real realized/unrealized P&L.
- **Position management**: a full `ManagedPosition` lifecycle (OPEN → TARGET_1 → TARGET_2 → TARGET_3/STOPPED → CLOSED), driven by a position-monitor tick.
- **Reconciliation**: broker-vs-ledger drift detection, run automatically after every order and again at end-of-day.
- **Kill switch / emergency square-off**: a durable, crash-recovery-tested state machine that force-closes every open position, independent of the market-data pipeline's own health.
- **End-of-day sequence**: durable, idempotent, force-closes remaining positions, reconciles, totals realized P&L.

### 2.3 Frontend (extensive, not "zero" as older docs claimed)
Real, API-backed pages exist for: Configuration, Settings (broker/notification credentials **plus** the new manual Historical Market Data fetch card), Market Data, Strategies, Backtesting (single- and multi-instrument, with per-instrument results inline), Compare, Watchlists, Strategy Monitor, Paper Trading, and Reports. Instrument selection throughout uses one shared, real, searchable picker (never free text, never a fabricated stock list).

### 2.4 Engineering hygiene
- 1300 backend tests, 126 frontend tests, all passing.
- Clean under `ruff format`/`ruff check`, `mypy` (271 source files, zero errors), `lint-imports` (6/6 architecture contracts kept — domain/application/infrastructure layering genuinely enforced, not just documented), Django `check`, `makemigrations --check`, and `drf-spectacular --fail-on-warn` (OpenAPI schema stays in sync with the real API).
- Every commit this session was local-only, per the standing rule — nothing has been pushed to a remote.

---

## 3. What's honestly still missing or unproven

### 3.1 The live-market-data pipeline (the real blocker for genuine live paper trading)
- **No real Dhan WebSocket connection has ever been established.** A real RFC 6455 WebSocket *transport* was built and tested — but only against a local, synthetic test server, never against Dhan's actual endpoint. This environment's Dhan credential has never been usable for live verification.
- **No reconnect-with-backoff.** The worker detects a disconnect and stops; it does not attempt to reconnect.
- **No token lifecycle.** Only a state *name* (`TOKEN_EXPIRED`) exists — no renewal logic.
- **No watchdog / health monitoring** for the market-data worker process itself.
- **The live-quote "observation universe" is still hardcoded to 4 symbols** (RELIANCE, TCS, INFY, HDFCBANK) via an environment variable — unlike the *historical/backtesting* instrument list, which now covers the full ~3,100-stock exchange (built this session). Widening the live-quote universe to the same full list is a small, mechanical follow-up now that both use the same underlying scrip master with security IDs.
- **`SAMPLE_BAR` → `TRADING_GRADE_BAR` promotion** logic exists and is enforced, but has only ever been exercised against 2 of its 6 real-world conditions, since no live feed has ever driven it.
- No performance/load testing, no long-running-stability testing, ever — the 1300 passing tests are a correctness signal, not a throughput or endurance one.

### 3.2 Reporting
Only 3 of ~11 catalogued report types have real data behind them (Backtest Report, Market Data Quality Report, Communication Delivery Report). Signal Report, Portfolio Report, Risk Report, Production Report, Audit Report, System Health Report, and Strategy Research Report remain placeholder/partial — honestly labelled as such in the UI (`CapabilityStatus` component), never faked.

### 3.3 Smaller, named gaps
- Backtest cancellation: the state machine reserves a `CANCELLED` status but nothing lets an operator actually trigger it.
- No SSE/WebSocket push for backtest progress — polling only (an accepted tradeoff, not an oversight).
- Only one strategy per backtest run (no multi-strategy comparison in a single run).
- No dedicated multi-instrument/multi-month performance benchmark with measured numbers.
- No automated accessibility (contrast/keyboard) audit has been performed on the frontend.
- SEBI algo-trading framework compliance (Algo-ID / broker strategy registration) has been researched (the relevant SEBI circular identified) but nothing in this codebase implements or tracks it — irrelevant for PAPER trading, would become relevant only if real order placement were ever pursued.

### 3.4 Live order placement — not a gap, a deliberate boundary
No live/real broker order-placement code exists anywhere, and none should be built without an explicit, separate decision — this is the project's permanent safety rule, not an item on the "to-do" list in the usual sense.

---

## 4. Recommended priority order for what's next

1. **Widen the live-quote observation universe** beyond 4 hardcoded symbols, reusing the scrip-master `security_id` work already done for historical data this session — small effort, meaningful unblock.
2. **Build the real Dhan WebSocket connection** against Dhan's actual endpoint (requires a working, verified Dhan credential in this environment — currently the practical blocker) — everything downstream of it (bar aggregation, signal generation, risk, paper execution, position monitoring, reconciliation, EOD) already exists and is tested against synthetic bars; it needs to be *fed* real data, not rebuilt.
3. **Reconnect-with-backoff + token lifecycle + a worker watchdog** — required before any unattended live paper-trading session could be trusted to run for a full trading day.
4. **Close out the remaining report types** using data that already exists (paper orders/trades/positions, risk decisions) but has no report assembler reading it yet.
5. **A real performance/load benchmark** (multi-instrument, multi-month backtest; sustained live-tick throughput) before calling any part of this "production-grade."
6. Only after all of the above: a deliberate, explicitly-approved decision on whether/how to ever place a real (live) order — a fundamentally different risk category from anything built so far.

---

## 5. External review (2026-08-19) and the revised scorecard

The status above was independently reviewed against current DhanHQ API
documentation. The review's verdict: the architecture is not fabricated,
the backtesting/paper-trading half is genuinely strong, and the live
market-data half is the correctly-identified weak point. Two changes came
out of that review and are incorporated into this document:

1. **The "permanent PAPER-only" framing was a product-goal mismatch**,
   corrected above to "PAPER-first safety boundary; LIVE execution is a
   future controlled phase requiring explicit approval."
2. **A more granular scorecard**, replacing the single "7/10 backtesting,
   3/10 live" summary in Section 1:

| Area | Score /10 | Note |
|---|---:|---|
| Architecture (layering, contracts, test discipline) | 9.2 | Import-linter-enforced boundaries, not just documented |
| Backtesting engine | 8.0 | |
| Historical data (real Dhan integration) | 7.5 | Built this session; no provenance metadata yet (see below) |
| Strategy engine | 8.0 | 3 real strategies, schema-driven |
| Risk engine | 8.5 | 10 real checks |
| Paper trading | 8.5 | Full order/fill/P&L lifecycle |
| Reconciliation | 8.0 | |
| Frontend | 7.0 | Real, API-backed, not yet a full observability console |
| Reporting | 4.5 | Only 3/11 report types have real data |
| Live market feed | 3.5 | Transport built, never connected to Dhan's real endpoint |
| Token lifecycle | 2.5 | State name only, no renewal logic |
| Reconnect/recovery | 3.0 | Detects disconnect, does not reconnect |
| Watchdog | 2.0 | Does not exist |
| Observability | 4.5 | `system_readiness` endpoint exists; no worker-process health signal |
| Performance/load testing | 2.0 | Never attempted |
| Scalability | 2.0 | Never attempted |
| Long-run stability | 2.0 | Never attempted |
| Production readiness | 4.5 | |
| **Active paper trading (composite)** | **5.8** | |
| **Live trading readiness (composite)** | **1.0** | By design — see the PAPER-first rule above |

**Overall engineering maturity: ~8.8–9.0/10. Overall active-product
maturity: ~6.0/10.** The gap between those two numbers is the honest
finding: this is very good software engineering that is not yet an
operationally mature *autonomous* trading platform — it has never run
continuously against real market data.

### The next milestone the review recommends: "Checkpoint 64 — Live Paper Trading Runtime"

Not another round of backtesting/UI features. The proposed sequence turns
the already-built signal→risk→paper-execution pipeline into something that
runs continuously against real Dhan data, in this order:

```
1. Dhan authentication lifecycle (token state machine + renewal)
2. Real Dhan WebSocket connection (against the actual endpoint, not a local test server)
3. Full, configurable universe subscription (not blindly all ~3,100 instruments —
   watchlist / configured stocks / scanner universe, dynamically subscribed)
4. Correct tick → bar aggregation
5. Reconnect + backoff
6. Token renewal
7. Watchdog (process-alive vs. system-healthy are different questions)
8. Live data quality / reconciliation
9. Strategy evaluation → 10. Signal audit → 11. Telegram/Discord publication
   (published as an event even when execution is later rejected by risk)
12. Risk → 13. PaperBroker → 14. Position management → 15. Reconciliation → 16. EOD → 17. Reports
```

Followed by a **full-day deterministic session simulation** (09:15 connect
→ ticks → bars → signal → risk → paper order → position → target/SL →
a deliberately-injected mid-day WebSocket disconnect → reconnect →
resubscribe → a second signal → close-of-session exit handling →
reconciliation → EOD) — the review's argument being that one honest
full-session test, including an injected failure, reveals more than
another hundred isolated unit tests. This has not been built yet.

Smaller points the review raised that are worth tracking even though they
don't change current scope:
- **Historical data provenance** isn't recorded per backtest yet (provider,
  API version, security ID, requested vs. actual range, fetched-at,
  data-quality status) — without it, two backtests run months apart on the
  same nominal inputs may be unexplainably different.
- **Options data is a real Dhan capability** (expired-options history,
  live option-chain with Greeks/OI/IV) that this project's domain model
  should stay compatible with even while actively targeting equities —
  the domain should not accidentally become equity-only by construction.
- **Signal and execution should be modeled as separable outcomes**: a
  signal can be valid and still have its execution rejected (risk limit,
  stale data, kill switch, etc.) — the signal should still be recorded and
  communicated, not silently absorbed by a rejected order. This project's
  signal-communication direction already points this way; it hasn't been
  fully realized yet.
- **Communication should subscribe to trading *events*, not the engine
  directly** (SignalGenerated → SignalAudited → SignalPublished →
  ExecutionAccepted/Rejected → PositionOpened → Target/SL → PositionClosed),
  for broker independence.

---

## 6. Bottom line

The **backtesting and paper-trading-lifecycle** half of this project is in genuinely good shape: real strategies, real risk enforcement, real position management, real reconciliation, real EOD handling, a working frontend, and — as of this session — real historical market data instead of synthetic fixtures, all backed by a large, passing, architecturally-enforced test suite. The **live-market-data** half is the honest, unresolved gap: the transport-layer pieces have been built and unit-tested, but none of it has ever touched a real Dhan connection, and the operational hardening (reconnect, token renewal, watchdog) a live 24/7 process needs does not exist yet.

**Real (live) order placement was never attempted.** It is not being treated as permanently out of scope — the stated project goal explicitly includes live trading — but it sits behind a deliberate future approval gate, and the immediate next milestone is making the existing paper-trading pipeline run continuously against real Dhan market data (Checkpoint 64, §5), not building live execution. That ordering — real data and operational hardening before real money — is the correct sequence regardless of the end goal.
