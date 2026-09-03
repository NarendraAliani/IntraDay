# Checkpoint LIVE-1-POSTMORTEM — Why Did the Connection Die Five Times?

```
checkpoint: LIVE-1-POSTMORTEM
verdict: STILL_GENUINELY_UNDETERMINED
crash_count: 5
interval_pattern: IRREGULAR (run durations: ~24.5min, ~0min, ~8.75min, ~0min, ~6.9min — no periodic/heartbeat-multiple pattern, no evidence of a fixed cadence)
close_codes_observed: [] (NONE logged anywhere in the session's own output — a real, confirmed diagnosability gap, not a negative finding)
recommended_fix: instrument the transport layer to log a per-attempt close_code/reason line (not just the final aggregate summary) before any further live attempt — without it, the actual mechanism cannot be determined from evidence, only guessed
commit: (recorded below)
blockers: []
```

## A. Reconstructed timeline

`[F]` Directly from the supervisor's own event log
(`$TEMP/checkpoint_LIVE-1_supervisor.log`, cross-referenced against the
worker's own per-process output):

| Process instance | Started | Last successful quote / outcome | Ended (worker's own `attempts=5` summary) | Duration | Quotes processed |
|---|---|---|---|---|---|
| Initial | 06:58:33 | ~07:22:35 | ~07:22:35 (`crash_detected` logged 07:23:12) | ~24m 2s | 17,302 |
| Restart 1/4 | 07:23:42.608 | — (no quote line found before its own summary) | `crash_detected` logged 07:23:42.609 — **1ms after its own restart timestamp** | effectively instantaneous | not captured |
| Restart 2/4 | 07:24:12 | ~07:30:25 | ~07:30:25 (`crash_detected` logged 07:32:58 — a ~2m33s gap between the last observed quote and the supervisor noticing; plausible if each of the 5 in-process reconnect attempts individually stalled toward a connection timeout rather than failing fast, unlike the initial run's tighter ~37s gap) | ~8m 13s–8m 46s | 2,906 |
| Restart 3/4 | 07:33:28.211 | — (no quote line found before its own summary) | `crash_detected` logged 07:33:28.213 — **2ms after its own restart timestamp** | effectively instantaneous | not captured |
| Restart 4/4 | 07:33:58 | ~07:39:22 | 07:40:51 (`max_restarts_exhausted`) | ~6m 53s | 2,155 |

`[F]` **Two distinct failure shapes, not one uniform pattern**:
1. **Three substantive runs** (initial, restart 2, restart 4) each
   connected successfully, streamed real quotes for a meaningful
   period (6m53s to 24m2s), then eventually exhausted the in-process
   5-reconnect-attempt ceiling and died.
2. **Two near-instantaneous failures** (restart 1, restart 3) — the
   supervisor's `crash_detected` log line appears only **1-2
   milliseconds** after its own `worker_restarted` line for the same
   cycle. No quote or aggregation line was found in the log for either
   of these two process instances at all. This is too fast to be a
   genuine reconnect-attempt-exhaustion sequence completing normally
   (even a maximally-fast 5-attempt backoff sequence takes several
   seconds minimum per `reconnect_supervisor.py`'s own formula). `[I]`
   The most likely explanation is a **detection artifact, not a second
   real connection failure**: the supervisor's poll may have read a
   `WorkerRuntimeStatus` row that hadn't yet been reset/cleared by the
   newly-spawned process before the next poll cycle observed it,
   re-triggering `crash_detected` against stale state. This is
   plausible but **not confirmed** — flagged as a separate, real
   finding worth its own investigation, distinct from the underlying
   network-disconnect question this checkpoint is centrally about.

`[I]` **Irregular interval, no clear periodicity**: run durations of
~24, ~9, and ~7 minutes show no common factor and no relationship to
Dhan's documented 10-second ping interval or 40-second unresponsive
threshold (neither ~24min nor ~9min nor ~7min is any small multiple of
10s or 40s). This argues against a simple, fixed-period heartbeat
mismatch as the sole mechanism.

## B. Close-code / pattern analysis

`[F]` **No per-attempt WebSocket close code or disconnect reason was
logged anywhere in today's session output.** Searched the entire
40,969-line supervisor log for `close_code`/`connection_lost` —
**zero matches**. Only the final, aggregate
`reconnect_count=5 attempts=5 last_disconnect_reason=reconnect_attempts_exhausted`
line exists per process instance — exactly the same diagnosability gap
67.12.2-E already named (`mark_reconnecting()` doesn't call
`self.stdout.write()` per attempt, only the supervisor's own summary
line does). **This checkpoint cannot report real close codes because
none exist to report** — this is stated as a fact about the evidence,
not filled in with an inference dressed as a fact.

`[F]` Re-read `docs/research/CHECKPOINT_53_DHAN_WEBSOCKET_PROTOCOL_RESEARCH.md`
in full again: server ping every 10s, client unresponsive timeout
>40s, max 100 instruments/subscription message (15 symbols, one
message, well under this), max 5000 instruments/connection (15, far
under), max 5 connections/user, and disconnect reason 805 ("if more
than 5 websockets are established, the first socket will be
disconnected"). **No documented per-connection message-rate limit
exists in this project's own research** — checked again, not newly
found. Only one WebSocket connection was ever active at a time
(the supervisor runs processes sequentially, never concurrently), so
the 5-connection/805 limit is not directly implicated by today's
evidence, though it cannot be fully ruled out without knowing whether
Dhan's server briefly double-counts a just-closed connection.

`[I]` **No correlation found with a specific symbol** — quote lines
for all 15 symbols appear continuously up to the last logged quote in
every substantive run; no single symbol's subscription is
disproportionately represented near any failure point.

`[I]` **No correlation found with message volume/rate** — the
aggregation cadence (every 5 quotes, per `_AGGREGATION_BATCH_SIZE`)
looks steady throughout every run right up to its failure, with no
visible slowdown or backlog beforehand.

## C. Revised verdict, with evidence

**`STILL_GENUINELY_UNDETERMINED`** — stated plainly rather than forcing
a conclusion the evidence doesn't support. What today's real,
timestamped data **does** rule out with reasonable confidence: a
single, simple, fixed-period heartbeat mismatch (durations are
irregular, not periodic); a per-symbol or per-message-rate problem
(no correlation found in either dimension); and, likely, the
documented 5-connection limit (only one connection was ever open at a
time). What it **cannot** determine, for lack of the one piece of
evidence that would actually settle it — a real close code — is
whether the underlying cause is a genuine, recurring Dhan-side or
network-path instability (this session's leading hypothesis, given
three independent runs each eventually failed the same way regardless
of how long they'd been stable) or something else entirely. Yesterday's
`LIKELY_TRANSIENT_NETWORK_EVENT` guess is **not confirmed or
contradicted** by today's data — today shows the same failure mode is
**recurring**, which argues against "transient, one-off event," but
without a close code there is no way to distinguish "Dhan's feed is
genuinely unstable for this account/session" from "something about
this project's own reconnect/subscribe sequence provokes a
disconnect" from "a local network path issue."

## D. Recommendation for a future checkpoint — not implemented here

1. **Highest priority, cheap and safe**: add a per-attempt log line at
   the point `mark_reconnecting()` is called in
   `run_market_data_worker.py`, including the real WebSocket close
   code/reason from `websocket_transport.py`'s own already-captured
   `close_code` (this data already exists in-process per
   67.12.2-E's own citation of `close_code=1006` from an earlier
   session — it is being captured but not logged per-attempt today).
   Without this, any future postmortem is stuck at the same
   `STILL_GENUINELY_UNDETERMINED` verdict regardless of how much
   session data accumulates.
2. **Investigate the near-instantaneous "phantom" restart pattern**
   (Section A) separately — if confirmed as a stale-DB-read detection
   artifact rather than a second real disconnect, it inflates the
   apparent crash count and wastes restart budget on cycles that
   never had a real connection to lose; if it turns out to be a real,
   second distinct failure mode, that itself is worth knowing.
3. **Do not raise `--max-restarts`** as a substitute for understanding
   the cause, per this checkpoint's own prohibition — today's 5
   crashes in ~42 minutes, even with the "phantom" pair set aside,
   still show 3 genuine failures in that window; a higher restart
   budget would only mean the same undiagnosed problem burns more
   restarts before eventually exhausting them anyway.
4. Once per-attempt close codes exist, re-run a real supervised
   session and revisit this same investigation with the evidence this
   one was missing.
