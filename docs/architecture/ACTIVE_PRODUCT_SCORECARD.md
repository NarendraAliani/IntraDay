# Active Product Scorecard (Checkpoint 58)

The authoritative "how close are we to a real product?" document, per
the user's own explicit ask this checkpoint. Tracked going forward
after every checkpoint. Color legend:

- 🟢 **GREEN** — executable + verified (real test exercises real behavior)
- 🟡 **YELLOW** — executable but insufficiently validated (works, proven only against synthetic/replay input, not live)
- 🟠 **ORANGE** — synthetic/fixture only (the shape exists, the substance doesn't)
- 🔴 **RED** — missing
- 🔵 **BLUE** — externally blocked (this environment's Dhan credential is unusable for live verification, Checkpoint 41)

## Part 7's explicit ask: is "everything from RISK APPROVED onward is missing" STILL TRUE after Checkpoint 57?

**No. That claim is stale and this checkpoint corrects it with evidence, not assertion.**

The user's cumulative task-report summary carried forward a finding from
an EARLIER audit (before Checkpoints 42-51 existed). Since then, this
project built and tested, with real code and real tests, not contracts:

| Claim in the stale audit | Actual current evidence |
|---|---|
| "Risk enforcement may be only configuration" | `trading_engine/risk_engine/evaluator.py::evaluate_order_risk()` has **ten** real rejection checks (kill switch, market session, strategy active, stale data, duplicate order ×2, max daily loss, max position size, max exposure, max concurrent positions, instrument allowed ×2, daily trade limit, per-trade risk unknown/exceeded) - grep-verified this checkpoint, not merely cited from memory. |
| "Paper trading may be a toy simulator" | `PaperBroker` (Checkpoint 34/35) implements the full order lifecycle (CREATED→SUBMITTED→...→FILLED/REJECTED/CANCELLED), realistic MARKET/LIMIT/STOP fills with slippage, partial fills, a real trade ledger, and realized/unrealized P&L computed from actual fills (Decision 206 found and fixed a real P&L bug this session, proving the P&L path is exercised, not decorative). |
| "Order/position lifecycle missing" | `domain.position` + `trading_engine.position_management` (Checkpoint 42/43) give a real `ManagedPosition` lifecycle (OPEN→TARGET_1→TARGET_2→TARGET_3/STOPPED→CLOSED) driven by `run_position_monitor_tick()`, proven end-to-end by `test_full_entry_to_monitored_exit_lifecycle_through_real_orchestration`. |
| "Reconciliation missing" | `control_plane.reconciliation::reconcile_positions()` (Checkpoint 34/38) is called automatically after every order (Checkpoint 42) and again inside `run_eod_sequence()` (Checkpoint 51) - a real, root-caused bug (Decision 199) was found and fixed in this exact path this session. |
| "Kill switch / emergency safety missing" | `KillSwitchService` + `run_emergency_square_off()` + `EmergencySquareOffEvent` durable state machine (Checkpoints 34, 45, 46, 47, 48, 49) - crash-recovery tested, idempotent, reused by EOD. |
| "EOD missing" | `run_eod_sequence()` (Checkpoint 51) - durable, idempotent, reuses square-off + reconciliation, proven by a real end-to-end acceptance test. |

**The corrected picture**: the RIGHT half of the lifecycle chain (signal
→ risk → paper order → position → monitor → reconciliation → EOD) is
substantially real and tested. It is proven **only against deterministic
replay/synthetic bars**, never live market data - that is the genuine,
still-true gap, and it is a narrower, more specific gap than "everything
is missing." The LEFT half of the chain (live market data → canonical
bar → TRADING_GRADE_BAR) is the part that is genuinely thin.

## Full lifecycle scorecard

| Stage | Status | Evidence |
|---|---|---|
| Market session determination | 🟢 GREEN | `domain.session.calendar` - 2026 NSE holiday calendar, session state machine, used throughout. |
| Market data ingestion (REST, Checkpoint 23) | 🟢 GREEN | `market_data_ingestion_runtime.py`, scheduled via Celery Beat, tested against contract fixtures. |
| Market data ingestion (WebSocket) | 🟠 ORANGE | Real socket + decoder + worker loop (Ch. 53-57), but only synthetic data; `--provider fake` is the only mode. No real Dhan connection - 🔵 BLUE (credential unusable, Ch. 41). |
| Canonical `Quote`/`Bar` contracts | 🟢 GREEN | Used identically by REST and (new) WebSocket paths (Decision 209). |
| `BarSource` boundary | 🟢 GREEN | Protocol + `DeterministicReplayBarSource` (Ch. 52), swappable, tested. |
| Live WebSocket quotes → bar aggregation | 🟡 YELLOW (upgraded from 🔴 RED, Checkpoint 58, then corrected Checkpoint 59) | Checkpoint 58 wired `on_quote` to `BarAggregationService`, but aggregation ran ONLY ONCE, after the stream ended - proving "quotes can eventually become bars," not "bars form continuously while the worker runs." **Corrected Checkpoint 59**: aggregation now fires every `_AGGREGATION_BATCH_SIZE` (5) quotes WHILE the packet loop is still running, plus a final cleanup pass - directly observed (`--packet-count 12` produced 3 separate "aggregated N bar(s) so far" lines, at quotes 5, 10, and the final 2) and proven by a dedicated test asserting ≥3 aggregation passes occur. Still YELLOW, not GREEN: this is periodic batch-triggered aggregation against a SYNTHETIC feed, not genuinely incremental single-bar-close-detection, and still not against live data. |
| `SAMPLE_BAR` → `TRADING_GRADE_BAR` promotion | 🟠 ORANGE | Six-condition gate exists and is enforced (never silently promoted, Decision 143), but only 2/6 conditions have ever been satisfied against a real feed - unchanged since Checkpoint 41, still 🔵 BLUE on the remaining conditions. |
| Feature engine / signal generation | 🟢 GREEN | `ema_crossover`, no-lookahead + property-based tests, real. Proven only against replay bars, not live-derived ones - 🟡 YELLOW for the live path specifically. |
| Risk enforcement | 🟢 GREEN | See table above - ten real checks, tested. |
| Paper order execution | 🟢 GREEN | See table above. |
| Position lifecycle + monitoring | 🟢 GREEN | See table above. |
| Reconciliation | 🟢 GREEN | See table above. |
| Kill switch / emergency square-off | 🟢 GREEN | See table above - the most heavily hardened path in this project (5 checkpoints of crash-recovery work). |
| EOD | 🟢 GREEN | See table above. |
| Daily report / reporting | 🟠 ORANGE | Report contracts exist (`application/reporting/`), several explicitly marked `PLANNED`/`NOT_YET_IMPLEMENTED` via the project's own `CapabilityStatus` discipline - honestly labelled, not fabricated, but real content is thin. |
| Token lifecycle | 🔴 RED | Only a state NAME (`WorkerState.TOKEN_EXPIRED`) exists - no renewal logic. |
| Instrument master | 🟠 ORANGE | Four hand-verified symbols only (Ch. 23) - real, but not a general ingestion pipeline. |
| Watchdog | 🔴 RED | Not implemented. |
| Reconnect/recovery | 🟠 ORANGE | The worker correctly DETECTS a disconnect and stops (Ch. 57) - it does not attempt to reconnect. |
| Operator observability | 🟠 ORANGE | `system_readiness` endpoint (Ch. 50) composes real signals but does not include the market-data worker's own state. |
| Performance/load testing | 🔴 RED | Never attempted this session. 1197 passing tests is a correctness signal, not a performance one. |
| Long-running stability | 🔴 RED | Never attempted. |
| Live/backtest bar-path parity | 🔴 RED | Named as a real, unaddressed risk since before this session began - the REST/replay bar path and any future live path have never been cross-tested against identical input. |
| Clock/timestamp integrity | 🟡 YELLOW | Every domain contract enforces UTC and distinguishes event/receive time by construction (Decision throughout) - but no explicit drift-detection runtime exists. |
| Frontend / operator UI | 🔴 RED | Zero frontend work across this entire 15-checkpoint sequence (Ch. 44-58). |

## The corrected critical path

```
Live WebSocket data (still synthetic, real Dhan blocked by credential)
    │
    ▼
async_worker's Quote callback  ──────►  🔴 NOT WIRED to bar aggregation (the one concrete missing link)
    │
    ▼
BarAggregationService (real, Ch. 24A)
    │
    ▼
TRADING_GRADE_BAR gate (real, blocked on live-data conditions)
    │
    ▼
Feature engine → Signal → Risk → Paper order → Position → Reconciliation → EOD
    (ALL REAL AND TESTED - proven only against replay bars, not live-derived ones)
```

**The honest conclusion**: this project is NOT missing "everything from
risk approved onward." It is missing exactly one concrete wire (live
Quote → bar aggregation) plus the still-unresolved WebSocket technology
decision upstream of it, plus operational hardening (watchdog, reconnect,
token lifecycle, performance, long-run stability) that matters once a
real feed exists. The downstream trading lifecycle does not need to be
built - it needs to be fed.

## Executive answer

1. **Is IntraDay currently an active product?** No - it can run one
   complete PAPER session end-to-end against **replay/synthetic** data
   (proven, Checkpoint 51/57), but not yet against anything resembling
   live market data.
2. **What exactly prevents that?** Two things, in order: (a) a real
   `DhanWebSocketTransport` does not exist yet - the WebSocket
   TECHNOLOGY DECISION was resolved Checkpoint 60 (`websockets`
   library, see Decision 215 and `MARKET_DATA_RUNTIME_ARCHITECTURE.md`)
   but the transport itself is not yet built; (b) this environment's
   Dhan credential remains unusable for live verification (Checkpoint
   41, unchanged) regardless of transport readiness.
3. **Top 5 blockers**: `DhanWebSocketTransport` implementation ·
   token lifecycle · watchdog/reconnect · instrument master ·
   this environment's Dhan credential (live verification only).
4. **Critical path**: real transport built against the now-locked
   `websockets` decision → Quote→bar wiring (already real, Checkpoint
   58/59) → TRADING_GRADE_BAR conditions → (everything downstream
   already exists).
5. **What can run in parallel?** Performance/load testing and long-run
   stability testing can be built against the SYNTHETIC provider today,
   independent of the real transport's completion.
6. **What did CP58 implement?** The Quote→bar wiring - real, bounded.
   **What did CP59 correct?** Aggregation now runs periodically WHILE
   the worker runs, not only at stream end. **What did CP60 resolve?**
   The WebSocket technology decision itself (`websockets` library),
   with real primary-source research - not yet implemented.
7. **CP61 update**: `DhanWebSocketTransport` was built and tested
   against a REAL RFC 6455 handshake (`FakeDhanWebSocketServer`, a
   genuine local `websockets` server) - 9 new tests, all passing, all
   exercising a real handshake and real frame protocol, not a mock.
   `run_worker_against_websocket()` reuses the exact same decode/
   convert/state-machine core as the raw-TCP path, proving that core
   was genuinely transport-agnostic. **Not done**: no `--provider
   fake-ws` CLI wiring, no token lifecycle, no watchdog, no reconnect-
   with-backoff, no correct minute-boundary bar semantics (still
   batch-of-5), no performance/load/long-run testing, no real Dhan
   connection.
8. **CP62 update**: `--provider fake-ws` now wires the real WebSocket
   path into the actual `manage.py run_market_data_worker` command -
   directly run and observed with real output (real quotes, real
   periodic bar aggregation, real handshake). Quote-persistence logic
   was extracted into a shared `_QuoteSink` used by both providers. 2
   new tests, 1210 total passing.
9. **What should CP63 implement?** Reconnect-with-backoff integrated
   with the worker state machine (currently: a Disconnect packet stops
   the loop, it does not retry), then token lifecycle - in that order,
   since reconnect logic needs to exist before token-expiry-triggered
   reconnection can be meaningfully tested.
8. **What should NOT be worked on yet?** Frontend polish, additional
   report types, multi-broker expansion - all P2, all premature while
   the live-data critical path is still open.
9. **Evidence required before PAPER_READY** (autonomous unattended
   PAPER session against real intraday timing): a real WebSocket
   connection OR a scheduled synthetic-data long-run proving the full
   chain holds for an entire session without manual intervention.
10. **Evidence required before CONTROLLED_LIVE_READY**: everything
    above, plus token lifecycle, watchdog, reconnect, and a working
    Dhan credential for actual live verification.
11. **Evidence required before PRODUCTION_READY**: all of the above,
    plus performance/load testing at the real production instrument
    count and long-run stability proof.

**Current product maturity: ~5.5/10. Runtime maturity: ~3.5/10.
Production readiness: ~3/10. Live-trading readiness: ~1/10.**
(Consistent with, not inflated relative to, the user's own independent scoring this checkpoint.)
