# Task Report

## Checkpoint

Checkpoint 62

## Objective

Close the specific gap Checkpoint 61's own report named as unclosed:
the real RFC 6455 WebSocket transport existed and was proven only
through unit tests, never through the actual operator-facing
`manage.py run_market_data_worker` command. Wire it in, while
remaining 100% PAPER-only and without re-researching the already-
resolved WebSocket technology decision.

## Research Performed

None new this checkpoint. This was an implementation checkpoint,
consistent with the user's own explicit "stop researching, this is an
implementation checkpoint" instruction from Checkpoint 61's review.

## Official Sources Consulted

None this checkpoint.

## Research Findings

None new.

## Hidden Gaps Discovered

None new beyond what was already documented. The already-known gaps
(reconnect-with-backoff, token lifecycle, watchdog, correct minute-
boundary bar semantics, instrument master, performance measurement,
frontend) remain exactly as previously documented - not rediscovered,
not silently expanded, not reduced.

## Architecture Decisions

- **Decision 217** (new, locked): `manage.py run_market_data_worker`
  gained `--provider fake-ws`, using the real `DhanWebSocketTransport`/
  `FakeDhanWebSocketServer` (Decision 216) through the actual
  operator-facing command. Quote-persistence/periodic-aggregation
  logic (Checkpoint 58/59) extracted into a shared `_QuoteSink` used
  identically by both `--provider fake` (raw TCP) and `--provider
  fake-ws` (real WebSocket).

## Implementation Performed

Refactored `run_market_data_worker.py`: extracted the existing quote-
persistence + periodic-bar-aggregation logic (previously inline in a
single `_run()` method, Checkpoint 58/59) into a `_QuoteSink` class
with `on_quote()`, `aggregate_now()`, and `flush_remainder()` methods.
Added `_run_fake_tcp()` and `_run_fake_ws()` branch methods, both
constructing a `_QuoteSink` and passing its `on_quote` as the
callback to the respective transport's worker loop
(`run_worker_against_stream()` for raw TCP, `run_worker_against_websocket()`
for real WebSocket - both from Checkpoint 57/61, unmodified). Added
`--provider fake-ws` to the CLI's `--provider` choices (previously
only `fake`).

## Files Created

None.

## Files Modified

- `src/intraday/infrastructure/persistence/management/commands/run_market_data_worker.py`
  (refactored to share persistence/aggregation logic across two
  providers; added `--provider fake-ws`)
- `tests/unit/infrastructure/persistence/management/test_run_market_data_worker_command.py`
  (2 new tests)
- `docs/architecture/ARCHITECTURE_DECISIONS.md` (Decision 217)
- `docs/architecture/ACTIVE_PRODUCT_GAP_REGISTER.md`
- `docs/architecture/ACTIVE_PRODUCT_SCORECARD.md`
- `taskReport.md` (true overwrite - this file, Checkpoint 62 content
  only)

## Files Deleted

None.

## Tests Added

2 new tests in `test_run_market_data_worker_command.py`:

- `test_command_runs_end_to_end_over_the_real_websocket_provider` -
  mirrors the existing raw-TCP acceptance test exactly, but through
  `--provider fake-ws`.
- `test_command_over_websocket_actually_persists_quotes_and_aggregates_bars` -
  mirrors the existing raw-TCP persistence-proof test, checking real
  database row deltas, not just printed output.

## Tests Executed

- Manual runs: `python manage.py run_market_data_worker --provider
  fake-ws --packet-count 12` executed directly this checkpoint,
  producing real quotes over a real WebSocket handshake and 3 real
  periodic bar-aggregation passes. `--provider fake --packet-count 6`
  re-run afterward to confirm the `_QuoteSink` refactor did not
  regress the pre-existing raw-TCP path.
- `poetry run pytest tests/unit/infrastructure/persistence/management/test_run_market_data_worker_command.py -q`
  → **7 passed** (5 pre-existing + 2 new).
- `poetry run pytest tests/unit/architecture/test_live_market_data_boundaries.py -q`
  → **4 passed** (safety boundary test, re-confirmed against the
  refactored command).
- `poetry run pytest -q` (full backend suite) → **1210 passed**
  (1208 pre-existing + 2 new; every pre-existing test remains green).
- `ruff format --check`, `ruff check`: clean.
- `mypy` (strict, project code) on every touched file: clean.
- `lint-imports` (`.importlinter`, 6 contracts): 6/6 kept.
- `manage.py check`: clean. `makemigrations --check --dry-run`: no
  pending migrations. `spectacular --fail-on-warn`: clean.

## Failure Injection

NOT expanded this checkpoint. Coverage remains limited to what
Checkpoint 61's tests already exercised (connection-refused,
malformed-packet, Disconnect-packet, both over raw TCP and real
WebSocket).

## Performance Benchmark

NOT MEASURED this checkpoint.

## Long-Run Stability

NOT tested this checkpoint.

## End-to-End Paper Pipeline

NOT attempted this checkpoint. The new work stops at Quote persistence
and bar aggregation - no signal/risk/paper-order integration was
exercised against either provider.

## Frontend Audit

NOT performed this checkpoint.

## Security Review

No credentials were used, logged, or exposed. Both providers remain
fully synthetic/local. `TRADING_MODE` remains PAPER throughout; the
safety-boundary test (`test_live_market_data_boundaries.py`, which
mechanically scans for forbidden `trading_engine` imports) was
re-confirmed passing against the refactored command file.

## Deployment Review

NOT performed this checkpoint.

## Current Product Readiness

Unchanged in kind from Checkpoint 61, incrementally advanced in one
specific dimension: the real WebSocket transport is now reachable
through the actual operator command, not only through tests. Every
other previously-open gap (reconnect, token lifecycle, watchdog,
correct bar semantics, performance, frontend, real Dhan connectivity)
remains exactly as open as it was.

## Performance Ranking

**ENGINEERING MATURITY: 8.9/10** - unchanged.

**ACTIVE PRODUCT MATURITY: ~5.7-5.8/10** - a small increase from
Checkpoint 61's ~5.7, reflecting that the real transport is now
operator-reachable, not a large jump.

| Area | Score |
|---|---|
| Architecture | 9.3/10 |
| Market Data | 5.5/10 - real transport reachable via both providers; still fully synthetic |
| WebSocket | 7.0/10 - real handshake, real framing, now CLI-wired; no reconnect/token lifecycle |
| Token Lifecycle | 1.5/10 - a state name only |
| Reconnect/Recovery | 3.0/10 - detected, not retried |
| Watchdog | 1.5/10 - not implemented |
| Bar Engine | 5.0/10 - real aggregation, still batch-of-5 triggered, not minute-boundary-driven |
| Signal Pipeline | 7.5/10 - real, proven only against replay data |
| Risk Engine | 8.0/10 - real, ten enforcement checks |
| Paper Trading | 8.0/10 - real, full lifecycle |
| Observability | 3.5/10 - unchanged |
| Performance | 1.5/10 - unmeasured |
| Scalability | 1.5/10 - untested |
| Long-Run Stability | 1.5/10 - untested |
| Frontend | 2.0/10 - unchanged, 17 consecutive checkpoints with none |
| Production Readiness | 3.5/10 |
| Live Trading Readiness | 1.0/10 - deliberately kept near-zero |

## Remaining Gaps

Reconnect-with-backoff integrated into the worker state machine, token
lifecycle, watchdog, correct minute-boundary bar-closure semantics,
instrument master beyond four symbols, performance/load/long-run
testing, live/backtest bar-path parity, frontend/operator console,
real Dhan connectivity (credential-blocked).

## Blocked Items

Real Dhan connectivity - this environment's Dhan credential remains
unusable for live verification (Checkpoint 41, unchanged).

## Risks

Unchanged from Checkpoint 61's own risk list - reconnect absence,
token lifecycle absence, batch-triggered (not boundary-driven) bar
closure, unmeasured performance, and the fact that the entire
WebSocket transport, however well-tested locally, has never touched
Dhan's actual production endpoint.

## Next Checkpoint

Reconnect-with-backoff integrated with the worker state machine
(currently: a Disconnect packet stops the loop, it does not retry),
then token lifecycle - in that dependency order.

## Honest Final Conclusion

The specific gap Checkpoint 61 left open - "the real transport exists
but only tests exercise it" - is now closed: `manage.py
run_market_data_worker --provider fake-ws` runs the identical
production transport code an operator would actually invoke, proven by
directly running it and observing correct output, not merely by unit
tests. This is real, incremental progress, narrowly scoped as intended.
It does not change the larger picture: the market-data runtime remains
synthetic-only, unable to reconnect after a disconnect, without a
token lifecycle, without performance measurement, and without any
contact with Dhan's real production feed.
