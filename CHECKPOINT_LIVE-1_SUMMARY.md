# Checkpoint LIVE-1 — Today's Real Supervised Session: HALTED at Part 0

```
checkpoint: LIVE-1
verdict: HALTED
pid_reconciliation_exercised_live: NO (row was already clean — WorkerRuntimeStatus(dhan).worker_state=STOPPED, owner_pid=None — nothing stale existed to reconcile)
crash_occurred: NOT_APPLICABLE
restart_exercised_live: NOT_APPLICABLE
config_restored: NOT_APPLICABLE (ScannerConfiguration never touched)
bars_captured_5m: 0
provenance_confirmed: NOT_APPLICABLE
canonicalization_confirmed: NOT_APPLICABLE
commit: (this file only)
blockers: [DHAN credential expires 2026-09-03 06:49:34 UTC — checked at 06:44:46 UTC, ~4m48s of validity remaining, far short of the ~3.5 hour session this checkpoint requires]
```

## A. Part 0 findings

1. **Time check**: 2026-09-03 06:43:56 UTC (12:13:56 IST) at start.
   Minutes to ~15:40 IST close: **~206 minutes** — well above the
   20-minute threshold. Full Part 0 executed.

2. **Credential check, correct source** (`effective_credentials()`,
   the DB-first path, never `.env` directly):
   - `creds_resolved: True`
   - `exp_utc: 2026-09-03 06:49:34`
   - `now_utc` at check: `2026-09-03 06:44:19` (re-confirmed again at
     `06:44:46`)
   - **`VALID_NOW: True`** at the instant of the check — but only by
     **~4-5 minutes**.

   **This is the actual finding this checkpoint HALTs on.** A literal
   reading of "is the credential valid right now" passes. But this
   checkpoint requires a session running until ~15:40 IST (~10:10
   UTC) — roughly **3.5 hours** past this token's expiry. Starting the
   supervisor now would mean it fails authentication within minutes of
   starting, producing a confusing, immediately-degraded capture
   rather than a clean, honest halt. Per this session's own governing
   principle ("verify the data before spending rigor protecting it")
   and the established precedent from 67.12.2-C/E of checking a
   knowable precondition before spending a live action on a call
   already known to be doomed, **this checkpoint stops here rather
   than starting a supervised session with a credential guaranteed to
   expire almost immediately.**

   No renewal was attempted. `token_renewal_client.py`'s
   `renew_dhan_token()` exists in this codebase, but calling it is a
   real Dhan network action **not authorized by this checkpoint's own
   scope** (LIVE-1 authorizes historical-candle/live-feed capture, not
   credential renewal) — improvising that call here would be exactly
   the kind of scope expansion this session's discipline prohibits.
   Renewal is reported as the required operator-level next step, not
   performed.

3. **`WorkerRuntimeStatus(dhan)` state**: `worker_state=STOPPED`,
   `owner_pid=None` — **already clean**, not stale. 67.12.2-S's PID
   reconciliation mechanism was therefore **not exercised live this
   run** — there was nothing stale for it to catch. This is reported
   honestly rather than claimed as a live proof of the mechanism: the
   row's cleanliness is consistent with the mechanism having worked at
   some point, or simply with no crash having left a stale row behind
   since the last clean stop — not distinguishable from this check
   alone.

4. **Already-running check**: not reached — moot once the credential
   blocker was found; no need to check for a competing capture when
   this run cannot start.

5. **Trading-day check**: not reached, same reason.

**No `ScannerConfiguration` write was attempted. No `AskUserQuestion`
approval was sought — there was nothing to approve, since the session
cannot proceed regardless of scope decisions. No supervisor was
started. No Dhan network call was made beyond the credential-validity
check itself (a safe, local JWT decode — no network request).**

## B. The capture window and what actually happened

Nothing was captured. The supervisor was never started.

## C. Config restoration

Not applicable — `ScannerConfiguration(dhan)` was never touched by
this checkpoint. It remains at whatever value it held before this
checkpoint began (confirmed elsewhere in this session's history to be
`ALL_CONFIGURED`/`3m`, the restored default).

## D. Final counts and canonicalization confirmation

Not applicable — zero rows captured.

## E. Honest assessment — is the supervisor now genuinely proven?

**No, still not proven against a real live session** — this checkpoint
adds no new evidence either way. 67.12.2-H's supervisor and
67.12.2-S's PID reconciliation remain proven only against fakes. Today
was meant to be the first real test; a credential expiring in ~5
minutes at the moment of checking made that test impossible to run
safely, so the test is deferred again, not failed — this is a
precondition failure caught before any live action, the same honest
outcome pattern as 67.12.2-C.

## Recommendation

1. **Renew the Dhan credential** — an operator-level action outside
   any checkpoint's remit, exactly as previously concluded in
   67.12.2-C/E. The credential's very short (~24h) validity window is
   now a recurring, structural obstacle to any multi-hour live session
   attempt — worth flagging as a standing operational fact, not a
   one-off inconvenience.
2. Once renewed, re-attempt this exact checkpoint (or the next
   trading day's equivalent) from Part 0, with the same corrected
   `effective_credentials()` check first — and this time, if the
   fresh token's expiry comfortably covers the full session window,
   proceed through Part 1's `AskUserQuestion` gate as originally
   specified.
3. Consider, as a separate, future, deliberately-scoped checkpoint:
   whether automating token renewal at session start (using the
   existing `token_renewal_client.py`, with explicit authorization)
   would close this recurring gap — not decided or implemented here.
