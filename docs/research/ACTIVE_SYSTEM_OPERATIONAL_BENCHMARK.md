# Active System Operational Benchmark (Checkpoint 41 Part 22)

What a genuinely active retail intraday algo-trading platform needs
operationally, compared against this repository as of Checkpoint 41.
Sources: this project's own accumulated primary-source research
(Checkpoints 22-40, Dhan/SEBI/NSE), general production-trading-system
literature the assistant's training reflects (broker API reliability
patterns, market-data architecture, position lifecycle management —
`INFERENCE`-tagged, not sourced to a specific fetched document this
checkpoint).

| Capability | What a production system needs | What we have | What we partially have | What we do not have |
|---|---|---|---|---|
| Persistent market-data connection | A long-lived WebSocket, reconnect/backoff, subscription restore | — | REST polling on a real Celery Beat schedule (Checkpoint 41), session-gated | No WebSocket client at all |
| Scheduling | A distributed scheduler that survives worker restart | Celery Beat schedule entry (Checkpoint 41), `beat_schedule` dict | — | No distributed lock preventing overlapping runs if beat itself restarts mid-tick; no persistence of "last execution"/"last failure" as a queryable record |
| Bar quality gating | Objective, tested promotion criteria before a bar drives a decision | `evaluate_bar_promotion()` (Checkpoint 40), 6 real conditions | Wired into the new ingestion tick (Checkpoint 41) | Never yet evaluated against a real Dhan response - only against real quotes fetched with a REAL round-trip once credentials work |
| Strategy triggering | Deterministic, idempotent, restart-safe | `run_active_loop_tick()` + `load_processed_signal_ids()` (Checkpoints 39-40) | — | No lock against the SAME instrument being processed twice by two concurrent ticks (single-worker assumption, undocumented until now) |
| Signal communication | Decoupled from execution outcome | Signal Communication Engine (Checkpoints 37-38) | — | Never exercised against a real Telegram/Discord account |
| Risk gating | Every material limit enforced, no silent bypass | 13 real checks (Checkpoints 34, 38, 39) | Per-trade-risk is real but opt-in | No unconditional per-trade-risk enforcement decision has been made for a production strategy |
| Paper execution | Realistic enough fills to trust the P&L | MARKET-order fills proven | — | LIMIT/SL/SL-M fill realism, slippage model, partial fills |
| Position lifecycle | Continuous monitoring, deterministic exit rules | — | — | No position monitoring exists at all - `ema_crossover` computes no stop-loss/targets to monitor in the first place |
| Reconciliation | Continuous, automatic, divergence-only (no silent correction) | `reconcile_paper_state()` exists and is proven correct (Checkpoint 38) | — | Never scheduled - only callable, not called automatically |
| Observability | Answer "is the algo alive?" at a glance | Structured logging (`structlog`) throughout every new module | — | No metrics/counters store, no health endpoint aggregating worker/market-data/strategy/communication/risk/broker state into one answer |
| Failure recovery | Detect → record → recover/retry/halt → resume, never silent | Session gating, restart-safe dedup, HTTP error classification (auth vs. connection vs. malformed) all real | — | No retry policy for the ingestion tick itself if Celery Beat's own process crashes mid-run; no dead-letter/alerting path |
| Clock synchronization | Detect dangerous local-clock drift vs. exchange time | `Bar`/`Quote` timestamps are UTC-disciplined throughout (`ensure_utc()`) | Source-timestamp vs. ingestion-timestamp ARE already distinct fields (`BarProvenance`, Checkpoint 31) | No NTP drift check, no alert if local system clock disagrees with a trusted external time source |
| Instrument master | Structured symbol/security-ID/segment/tick-size/lot-size/validity records | `DhanInstrument` (Checkpoint 23) has symbol/security_id/segment | — | No `active/inactive`, `valid_from/valid_to`, or corporate-action handling - a hardcoded 4-symbol observation universe (`instruments.py`), not a data-driven instrument master |
| Reporting | Real, persisted-data reports across the full trading lifecycle | 4/11 catalogue types real (Checkpoints 32-39) | — | Position/Trade/full Risk/Reconciliation/EOD reports remain catalogued but not built |
| Broker integration | Full read/write lifecycle behind a clean adapter boundary | Read-only connectivity check (`check_dhan_connectivity`, Checkpoint 22), read-only quote poller (Checkpoint 23) | — | No funds/positions/orders/trades read endpoints implemented; no order-update WebSocket; no write-side adapter (correctly, per the absolute safety boundary) |

## What is required before LIVE trading (unchanged conclusion, restated)

1. A working Dhan WebSocket market-data client (not REST polling) -
   REST polling at 1 req/sec cannot realistically support tick-level
   trading-grade bars.
2. A Dhan read/write broker adapter with the full order lifecycle,
   validated first read-only, then via Dhan Sandbox if verified
   suitable, before any real order call is even considered.
3. Position monitoring - meaningless to trade live without it.
4. SEBI Algo-ID / broker registration - a genuine external/regulatory
   dependency, unchanged since Checkpoint 37, still
   `VERIFIED_SECONDARY/PRIMARY_CONFIRMATION_PENDING`.
5. Observability sufficient to know the system is alive without
   reading raw logs.

None of these five exist today. This project remains, honestly, a
well-tested PAPER-mode component set with a real (if still
credential-blocked) scheduling and ingestion skeleton - not yet an
active trading system by the production benchmarks above.
