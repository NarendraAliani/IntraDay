# Market-Data Runtime Architecture — WebSocket Technology Decision (Checkpoint 60)

This decision has been explicitly deferred across Checkpoints 56, 57,
and 58. Per the user's own explicit instruction this checkpoint ("this
decision has already been deferred for several checkpoints... it must
now be resolved... do not defer the decision again"), it is resolved
here.

## Candidates evaluated

| Option | Description |
|---|---|
| A. `websockets` PyPI package | A dedicated, mature, asyncio-native WebSocket library. |
| B. Dhan's official Python SDK | Wrap Dhan's own SDK, if it bundles a WebSocket client. |
| C. Hand-rolled RFC 6455 | Implement the WebSocket handshake and frame protocol directly. |
| D. Django Channels | Already a project dependency (`channels`, `channels-redis`) - could a Channels consumer serve as the WebSocket client? |
| E. Standalone async worker (current direction) | Keep `manage.py run_market_data_worker` as the persistent process, using whichever transport library Option A/B/C provides. |

## Research findings (fetched directly from primary sources this checkpoint)

| Fact | Source | Classification |
|---|---|---|
| `websockets` latest version: 17.0.1 | pypi.org/project/websockets/ | VERIFIED_PRIMARY |
| Supports Python 3.11-3.15 (this project targets 3.12) | pypi.org/project/websockets/ | VERIFIED_PRIMARY |
| Not pure Python - ships a C extension, pre-compiled for Linux/macOS/Windows | pypi.org/project/websockets/ | VERIFIED_PRIMARY |
| BSD-3-Clause license | pypi.org/project/websockets/ | VERIFIED_PRIMARY |
| Native asyncio support, built on the same event-loop model this project's `async_worker.py` already uses | websockets.readthedocs.io | VERIFIED_PRIMARY |
| Full RFC 6455 handling ("don't worry about the opening/closing handshakes, pings and pongs") | websockets.readthedocs.io | VERIFIED_PRIMARY |
| Built-in automatic reconnection: `connect()` usable as an infinite async iterator, reconnecting on errors with exponential backoff, distinguishing transient vs. fatal errors | websockets.readthedocs.io | VERIFIED_PRIMARY |
| Configurable ping/pong keepalive (`ping_interval`/`ping_timeout`, both default 20s) | websockets.readthedocs.io | VERIFIED_PRIMARY - directly relevant, since Dhan's own documented heartbeat is a 10s server ping / 40s client timeout (Checkpoint 53 research) and needs a client that can be tuned to match |
| `wss://` (TLS) supported out of the box | websockets.readthedocs.io | VERIFIED_PRIMARY - required, since Dhan's endpoint is `wss://api-feed.dhan.co` |
| Actively maintained - v13 rewrote the asyncio implementation, v14 deprecated the legacy implementation with removal planned by 2030 | websockets.readthedocs.io | VERIFIED_PRIMARY |

**Dhan's official Python SDK (Option B)**: NOT independently re-verified
this checkpoint (would require a separate research pass against the
SDK's own repository/PyPI page) - remains UNKNOWN whether it exposes a
usable standalone WebSocket client versus being tightly coupled to
Dhan's own REST+order-placement surface. Given this project's
established discipline of never depending on unverified code near a
safety-critical boundary, Option B is not selected without that
verification - a future checkpoint's task if `websockets` (Option A)
turns out to be insufficient for some Dhan-specific reason discovered
during actual implementation.

## Decision: Option A — the `websockets` PyPI package

**Rationale:**

1. It solves EXACTLY the two things this project's own `stream_framing.py`/`fake_tcp_server.py` (Checkpoint 56) explicitly declined to build by hand: the RFC 6455 opening handshake and frame masking. Building those by hand (Option C) was already rejected in Decision 211/212 as "a materially bigger, riskier undertaking" than this project should take on for a protocol detail a mature library already solves correctly.
2. Its reconnection and heartbeat primitives map directly onto facts already gathered from Dhan's own documentation (Checkpoint 53): a 10s server ping / 40s client timeout is exactly what `ping_interval`/`ping_timeout` are built to handle, and `connect()`'s iterator-based reconnection is exactly the shape `async_worker.py`'s own packet-processing loop (Checkpoint 57/59) already assumes it will eventually be driven from.
3. It is asyncio-native - no new concurrency model is introduced alongside this project's already-asyncio-based worker.
4. Django Channels (Option D) is a SERVER-side ASGI framework (accepting WebSocket connections FROM browsers) - using it as a WebSocket CLIENT (connecting TO Dhan) would be using it backwards against its own design purpose. Rejected.

**What this decision does NOT do**: it does not itself implement a real
Dhan connection this checkpoint. Adding the dependency and building the
actual transport adapter (`DhanWebSocketTransport`, replacing/
supplementing the raw-TCP `FakeDhanTcpServer` test harness with a real
`websockets`-based fake server for integration tests) is real,
separate, substantial work - named as the immediate next checkpoint's
primary objective, not attempted here. This checkpoint's deliverable is
the DECISION itself, made with real evidence, ending three checkpoints
of deferral - not a rushed, undertested implementation built the same
day the dependency was chosen.

## What remains after this decision

- Add `websockets` to `pyproject.toml` (not done this checkpoint -
  the decision is locked, the dependency is not yet added; adding an
  unused dependency with no code exercising it would be worse than
  waiting for the checkpoint that actually builds against it).
- Build `DhanWebSocketTransport` in
  `infrastructure/market_data_providers/dhan/` implementing CONNECT/
  AUTHENTICATE/SUBSCRIBE/RECEIVE/HEARTBEAT/DISCONNECT/RECONNECT against
  the real Dhan v2 protocol facts already gathered (Checkpoint 53).
- Build a REAL `websockets`-based fake server (replacing/supplementing
  `FakeDhanTcpServer`'s raw-TCP approach) so the production transport
  and the test transport are the SAME code path against a genuine
  WebSocket handshake, not two different implementations.
- Wire that transport into `async_worker.py`'s existing packet-loop
  logic, which was deliberately written to be transport-agnostic
  (it already only requires an `asyncio.StreamReader`-shaped
  interface for raw TCP; a `websockets` connection needs a thin
  adapter, not a rewrite).
- Only THEN attempt real Dhan connectivity - still blocked on this
  environment's unusable credential (Checkpoint 41, unchanged).
