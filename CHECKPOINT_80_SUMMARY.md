# CHECKPOINT 80 — Crash-Rate Diagnostic + Session-Stop Gap Fix

Scope: two threads following directly from `LIVE-PAPER-1`'s own
findings. No live session launch, no strategy code changes, no
registry change. Market closed throughout.

```
part_1_verdict: SAME_1006_PATTERN_BUT_ONE_REAL_OUTAGE_BURST_FOUND -
                 66% of today's 44 crashes (29) clustered in one
                 ~10-minute window, tighter/more severe than the
                 sparser surrounding pattern; no fix attempted
                 (external, not a code issue)
part_2_verdict: REAL_BUG_FOUND_AND_FIXED - derive_live_paper_session_
                state() never checked for worker_state=="STOPPED";
                the two-independent-controls DESIGN itself is correct,
                confirmed not a gap
part_3_verdict: CONFIRMED_AND_RESOLVED_AS_A_SIDE_EFFECT_OF_PART_2 - the
                same one-clause fix resolves the "STOPPING forever"
                nuance too, proven by a dedicated regression test
tests_before_fix: 12 passed (test_live_paper_session.py baseline)
tests_after_fix: 14 passed (2 new regression tests)
full_suite: see "Verification" below
commit: (recorded below)
```

## Part 1 — Why was today's crash rate so much higher?

`[F]` Extracted every `close_code=` occurrence from today's 3 log
files (`worker.log`, `supervisor.log`, `supervisor2.log`): **all 90
disconnect events share the exact same `close_code=1006`** — the same
signature `LIVE-1`/`LIVE-3` already traced to commit `0f075e4`
(2026-09-03) as a long-standing, real, external failure mode. Not a
new or different close code.

`[F]` Extracted all 44 `crash_detected` timestamps and computed
inter-crash gaps precisely. Found a genuinely distinct pattern within
the day: **29 of the 44 crashes (66%) clustered in one tight window**,
`08:13:14`–`08:23:30 UTC` (`13:43:14`–`13:53:30 IST`, ~10 minutes),
each spaced almost exactly **22 seconds apart** — a striking, uniform
cadence, unlike the sparser 7–17-minute gaps observed both before and
after that window. `[F]` Cross-checked `quotes_processed` for each
worker lifetime in the first supervisor run: **26 of 40 crashes
received zero quotes** before failing (concentrated in this same
window, confirmed by sequence position), versus the surrounding
crashes which each streamed hundreds to thousands of real quotes first
before eventually dropping.

**Interpretation, stated at the confidence this evidence actually
supports**: this reads as a genuine, temporary connectivity outage
(Dhan-side or network-path) for that specific ~10-minute window — the
worker tried to reconnect roughly every 22 seconds (15s cooldown + ~7s
to fail again) and got nothing, rather than the ordinary pattern of
"connects, streams for minutes, then randomly drops." This is
qualitatively different in SEVERITY and TIGHTNESS from the sparser
pattern surrounding it, but shares the identical `close_code=1006`
signature and is consistent with `LIVE-3`'s own established conclusion
that this class of failure is external, not a code defect. **No
time-of-day, instrument, or other correlate was found beyond the
window itself** — reported honestly; no pattern was forced.

**No fix attempted**, per this checkpoint's own rule: the diagnostic
did not reveal a narrowly-scoped, code-fixable cause — it confirmed
the existing bounded-restart supervisor mechanism is the correct,
already-tested response to exactly this kind of event, and it worked
(see `LIVE_PAPER-1_SUMMARY.md`'s own Part 2/3 for how the supervisor
handled it).

## Part 2 — The session-stop gap

**Traced the actual stop flow directly**, per the checkpoint's own
instruction not to assume a code fix is warranted before checking:

- `stop_live_paper_session()`'s own docstring is explicit and correct:
  it "only flips the SAME `ScannerConfiguration.enabled` flag
  `start_live_paper_session()` sets" — it deliberately never touches
  the worker process.
- `supervise_market_data_worker.py`'s own module docstring is equally
  explicit: it "never touches `ScannerConfiguration` itself."
- `live_paper_session.py`'s own module docstring states the design
  intent plainly: "This module adds NOTHING to what happens after that
  write: the already-running worker process (a separate OS process,
  started manually)... picks up the change on its own next
  reconciliation cycle."

**Verdict: the two independent controls (`ScannerConfiguration.
enabled` = operator intent, `WorkerRuntimeStatus` = the worker
process's own real state) are correct-as-designed, not a gap.** An
operator's own INTENT to run a session should not be silently reset
just because the worker process happened to exit (crash, manual
Ctrl+C, or a supervisor's own session-end shutdown) — they might
relaunch the worker moments later within the same intended session.

**But a real, narrower bug WAS found while tracing this**:
`derive_live_paper_session_state()` — the function that answers "what
state is THIS session in" for the UI — never checked for a genuinely,
cleanly stopped worker. Its logic:

```python
if effective is not None and effective.worker_state in _FAILED_WORKER_STATES:
    return LivePaperSessionState.FAILED
...
return LivePaperSessionState.RUNNING if version_reconciled else LivePaperSessionState.STARTING
```

only special-cased `FAILED`/`AUTH_FAILED`/`TOKEN_EXPIRED` — a
genuinely `STOPPED` worker (the real, terminal value the `WorkerState`
state machine reaches via a clean `STOPPING -> STOPPED_CLEANLY`
transition) fell through, and if `effective_configuration_version`
still happened to match `desired`'s (which a clean stop does not
clear), the function reported **`RUNNING`** — exactly what
`LIVE-PAPER-1` observed live after the supervisor's own session-end
stop. This is a real, recurring bug: it will happen every single time
this supervisor pattern reaches session-end and the operator's own
`ScannerConfiguration.enabled` was never separately flipped — not a
one-off.

**Fix, narrowly scoped** (`src/intraday/application/services/
live_paper_session.py`): added one clause, giving a genuinely stopped
worker the same top-priority short-circuit `FAILED` already has:

```python
if effective is not None and effective.worker_state == "STOPPED":
    return LivePaperSessionState.STOPPED
```

Placed immediately after the existing `FAILED` check, before the
`version_reconciled`/`desired.enabled` logic — a worker that has
provably, cleanly exited can never be genuinely RUNNING, regardless of
what the operator's own `enabled` flag says.

`[F]` **Causation proven empirically**: added
`test_derive_state_stopped_when_enabled_but_worker_has_genuinely_
stopped` (reproducing the exact real scenario:
`desired.enabled=True`, versions matching, `worker_state="STOPPED"`),
reverted just the source fix (`git apply`/`git checkout` round-trip,
test file untouched), re-ran: **failed** with
`AssertionError: assert <LivePaperSessionState.RUNNING> is <LivePaperSessionState.STOPPED>`
— the exact live symptom, reproduced precisely. Restored the fix:
passes again.

## Part 3 — The `STOPPING` vs `STOPPED` quirk

**Traced directly, not just accepted the prior description.** The
`STOPPING`-forever behavior `LIVE-PAPER-1` found is caused by the
SAME missing case Part 2 just fixed: when a worker exits cleanly
BEFORE the session-level stop bumps `desired.configuration_version`,
`effective_configuration_version` can never catch up (no worker is
running to write a new value) — the pre-fix code's `not desired.
enabled` branch would then return `STOPPING` forever, since
`version_reconciled` could never become `True`.

`[F]` **Confirmed resolved, not just documented, as a direct,
verified side effect of the Part 2 fix** — added a second regression
test, `test_derive_state_stopped_not_stopping_when_worker_already_
exited_with_a_stale_version`, reproducing the exact stale-version
scenario (`worker_state="STOPPED"`, `effective_configuration_
version` permanently behind `desired`'s). With the fix in place: the
new top-priority `STOPPED` short-circuit fires before the
`version_reconciled` check is ever reached, so the function now
reports `STOPPED` immediately — correctly — rather than waiting
forever for a reconciliation tick that will never come. Also
verified via a direct, hand-constructed reproduction of
`LIVE-PAPER-1`'s own real field values (stale
`effective_configuration_version=12` vs. `desired.configuration_
version=13`): `derive_live_paper_session_state()` now returns
`LivePaperSessionState.STOPPED`.

**Original "minor, safety-irrelevant" characterization confirmed
accurate** for what it was — nothing about `PaperBroker` exclusivity,
`real_trading_state`, or order safety was ever implicated, only a
UI-facing status label. Documented in `PROJECT_STRATEGY_STATUS.md`'s
`LIVE-PAPER-1` entry as resolved (not "not fixed here" as originally
noted), since it turned out to share the exact same root cause and fix
as Part 2's own bug — genuinely higher-value to fix than to merely
document, once traced.

## Verification

- `tests/unit/application/services/test_live_paper_session.py`: 12
  tests passing before this checkpoint's changes; **14 passing after**
  (2 new regression tests, both proven to fail on the reverted fix
  with the exact live symptom).
- Scoped sweep (`services/`, `infrastructure/persistence/management/`,
  `infrastructure/api/`, filtered to `live_paper`/`supervis`/`worker`):
  **97 passed**, 0 failed.
- Full suite (`pytest -q --reuse-db`, all ~3400 tests): see the
  `full_suite_result` line below, run to completion before commit.

`[F]` Full suite result: **3384 passed, 5 failed** (724.48s). The 5
failures are the exact same 5 pre-existing, unrelated failures
documented at every checkpoint this session (`test_checkpoint_64_52_
database_first_backtest.py`'s 2 tests, `test_api_boundaries.py`'s
infrastructure-free check, and 2 Gainz-reference-file checks) — none
touch `live_paper_session.py` or its tests. **Zero new failures, zero
regressions.** Pass count is up by exactly 1 net test from this
session's prior baseline (3383), matching the 1 net-positive test this
checkpoint added (2 new, no tests removed).

## `MEMORY.md` update — confirmed made

Appended (never rewritten), recording the crash-burst finding, the
session-stop-gap fix, and the state-machine quirk's resolution.

## Governance compliance

- P3: zero DB writes — the only change is a pure function's own logic
  (`derive_live_paper_session_state()`), no migration, no data write.
- P9: no strategy code touched, no registry change.
- No live session launched this checkpoint.
- P11/P16: this summary, the source fix, the 2 new tests,
  `PROJECT_STRATEGY_STATUS.md`, and `MEMORY.md` committed to
  `active-development` only.
