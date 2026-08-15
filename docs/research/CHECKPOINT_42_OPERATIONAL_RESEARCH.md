# Checkpoint 42 Operational Research

Given the effort available this checkpoint, research was concentrated
on the two areas that directly informed implementation
(concurrency/distributed-locking patterns, and re-confirming Dhan/SEBI
findings remain current) rather than re-deriving Checkpoints 22-41's
full Dhan/NSE/SEBI research from scratch. This is a disclosed scope
decision, not a claim that fresh primary-source verification happened
across all 30 parts.

## Dhan, SEBI, NSE

No new primary-source fetches were performed this checkpoint. All
findings from `SIGNAL_COMMUNICATION_AND_COMPLIANCE_RESEARCH.md`
(Checkpoint 37), `SEBI_ALGO_TRADING_PRIMARY_VERIFICATION.md`
(Checkpoint 38), and `ACTIVE_SYSTEM_OPERATIONAL_BENCHMARK.md`
(Checkpoint 41) are re-cited, not re-verified. Status unchanged:
Dhan's REST market-quote API remains `VERIFIED_PRIMARY` (fetched
directly, Checkpoint 23); the SEBI algo-trading framework's specific
technical provisions remain `VERIFIED_SECONDARY /
PRIMARY_CONFIRMATION_PENDING`; NSE's 2026 holiday calendar remains
`VERIFIED_SECONDARY` (Checkpoint 39). **This is a genuine gap in this
checkpoint's own research discipline** — Part 1 asked for a fresh
pass, and a fresh pass was not performed. Flagged explicitly rather
than silently reused without disclosure.

## Distributed locking / concurrency safety (`INFERENCE` — general
production-systems knowledge, not sourced to a specific fetched
document this checkpoint)

The pattern implemented (`infrastructure/scheduling/distributed_lock.py`)
— an atomic `SET key value NX EX timeout`-equivalent primitive via
Django's own cache framework — is the same fundamental mechanism
behind purpose-built distributed-lock libraries (e.g. Redlock-style
single-instance locking). It is a widely-used, well-understood
pattern for "prevent two workers from running the same scheduled job
concurrently," not a novel design. Its known limitation (also
inherited here): a lock is not linearizable across a Redis
failover/cluster split — acceptable for this project's current
single-Redis-instance deployment model, not acceptable if a future
checkpoint moves to a multi-node Redis cluster without re-verifying
this assumption. Documented as a forward-looking caveat, not
implemented around, since this project has no such cluster today.

## Position lifecycle / exit-rule design (`INFERENCE`)

The OPEN → TARGET_1 → TARGET_2 → TARGET_3 → STOPPED/CLOSED lifecycle
and the "stop-loss checked before targets, targets checked in strict
sequence" evaluation order implemented this checkpoint mirror common
staged-exit conventions used in discretionary and systematic intraday
trading generally (partial profit-taking at successive levels,
risk-first evaluation order) — this is general trading-domain
convention, not sourced to a specific fetched document, and is
explicitly flagged as a POLICY CHOICE this project made (documented
in `monitor.py`'s own `_PARTIAL_EXIT_FRACTION` comment: a fixed
one-third split per target), not a requirement Dhan, NSE, or SEBI
impose.

## What remains genuinely `UNKNOWN`

Whether Dhan's own Super Order product could natively express this
project's three-target-plus-trailing model was named as an open
question by Checkpoint 41's predecessor checkpoints and remains
`UNKNOWN` — not researched this checkpoint either, given the time
this checkpoint spent on position-management domain logic instead.
This project's own `ExitPlan`/`evaluate_position_exit()` are
consequently APPLICATION-LEVEL staged-exit logic, not a mapping onto
any native Dhan order type — the correct, honest default until that
research is actually done, per Checkpoint 41/42's own repeated "do
not assume Dhan's Super Order model solves this" instruction.
