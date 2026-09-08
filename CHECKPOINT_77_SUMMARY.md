# CHECKPOINT 77 — Summary

Scope: Part 1 resolves `CHECKPOINT_76`'s preset-vs-baseline gap; Part
2 is a full readiness pre-flight against
`FIRST_LIVE_PAPER_VALIDATION_PROCEDURE.md`'s own Success Criteria;
Part 3 reports readiness plainly. **No live session was launched, no
`ScannerConfiguration` activated, no broker-order code path called.**
No code changes, no parameter changes, no registry change. Gainz/VWAP
tuning both remain paused (untouched this checkpoint).

```
part_1_finding: ema_crossover/sma_trend_filter DEFAULTS exactly match
                the documented baseline; atr_volatility_breakout's
                DEFAULTS also match, but NONE of its 3 saved presets do
part_2_critical_finding: the REAL live signal-evaluation path
                          constructs an EMPTY StrategyConfigurationValues
                          for every strategy - confirmed by direct code
                          trace, not assumed - this would make every
                          strategy evaluation fail (KeyError) the
                          instant a live session actually ran
readiness_verdict: NOT READY - a genuine, previously-undiscovered code
                   gap, not a data/credential/config issue
memory_md_updated: YES - confirmed below
project_strategy_status_updated: YES - confirmed below
commit: (recorded below)
blockers: [the empty-configuration gap in signal_pipeline_runtime.py]
```

## Part 1 — Preset vs. documented-baseline comparison

`[F]` Compared each of the 3 registered strategies' `parameter_schema()`
DEFAULT values directly against `FIRST_LIVE_PAPER_VALIDATION_
PROCEDURE.md` §3's own stated baseline ("12/26 EMA, 30/0.75% SMA,
14/2.0/... ATR"):

| Strategy | Schema defaults | Documented baseline | Match? |
|---|---|---|---|
| `ema_crossover` | `fast_lookback=12, slow_lookback=26` | 12/26 | **Exact match** |
| `sma_trend_filter` | `lookback=30, band_percent=0.75` | 30/0.75% | **Exact match** |
| `atr_volatility_breakout` | `lookback=14, atr_multiplier=2.0, stop=1.0, target_1=1.5, target_2=2.5, target_3=3.5, trailing=1.0` | 14/2.0/... | **Exact match** |

**All 3 strategies' raw schema defaults already match the documented
baseline exactly — a clean, good outcome, reported plainly rather than
searched for a problem that isn't there.**

**But the 3 SAVED presets this session's own walk-forward checkpoints
used do NOT all match**, checked directly against the real DB:

- `ema_conservative`: `{fast_lookback: 12, slow_lookback: 26}` —
  identical to the schema default.
- `sma_conservative`: `{lookback: 30, band_percent: "0.75"}` —
  identical to the schema default.
- `atr_aggresive` (the preset `68.4`/`70`/`71` actually used): `{lookback:
  10, atr_multiplier: "1.2", target_1: "2.0", target_2: "3",
  target_3: "5", stop_loss: "1.2", trailing_stop: "1.2"}` — **every
  single value differs from both the schema default and the documented
  baseline.** Checked the other 2 saved ATR presets too
  (`atr_Balanced`, `atr_Conservative`) — **neither matches the
  documented baseline exactly either** (both share the default's
  `lookback=14`/`stop=1.0`/`trailing=1.0`, but diverge on
  `atr_multiplier`/`target_3`).

**What a first session should actually use, stated plainly**: the raw
schema defaults — i.e., **no saved preset selected at all** for any of
the 3 strategies. `ema_conservative`/`sma_conservative` happen to be
safe, exact-match choices if a named preset must be selected, but for
`atr_volatility_breakout`, **none of the 3 existing saved presets is
the documented baseline** — this session's own `atr_aggresive` runs
(`68.4`/`70`/`71`, including the session's single best positive result
in `70`) used a materially different, more aggressive configuration
than the document's own "never a custom, unvalidated parameter set"
instruction permits for a first session.

## Part 2 — Readiness pre-flight

### Verifiable now, without a live session

`[F]` **Dhan credential**: `effective_credentials()` returns a real
`(client_id, access_token)` pair.
`evaluate_dhan_token_lifecycle()` (the SAME pure, no-network function
`live_paper_readiness_checklist.py` itself uses) called directly:
`state=VALID`, `expires_at=2026-09-09 10:17:40 UTC` — roughly 22 hours
from this checkpoint's own run time. **READY.**

`[F]` **`PaperBroker` is the only broker implementation**: grepped
`class .*Broker` across `src/intraday/` — exactly one concrete class,
`PaperBroker` (`infrastructure/brokers/paper/broker.py`). The other 2
hits are Protocols (`BrokerGateway`, `ReplayPaperBroker`), not
implementations. **Confirmed, matches the document's own claim.**

`[F]` **`real_trading_state` structurally `DISABLED`**: read
`live_paper_readiness.py:164` directly —
`real_trading_state="DISABLED"` is a literal, hardcoded string
constant in the readiness-outcome constructor; no configuration flag
anywhere sets it otherwise. **Confirmed structural, not a setting.**

`[F]` **Universe (§3's recommended 3-5 symbols)**: `ScannerConfiguration.
universe_mode` (`"SELECTED"` choice already exists) +
`selected_instrument_ids` (a plain `JSONField`) — configurable via the
existing API/admin with zero new code. **READY, mechanically.**

`[F]` **Telegram/Discord**: not merely configurable — **already
configured and enabled**. `TelegramCredential`/`DiscordCredential`
rows exist in the real DB, both with `enabled=True`. **READY**, beyond
what this checkpoint was asked to confirm (only "configurable" was
required).

### The critical finding — NOT verifiable-as-passing, and genuinely blocking

`[F]` **Traced the real live signal-evaluation code path directly**,
line by line, not assumed: `signal_pipeline_runtime.py::
promote_bars_and_trigger_signals()` constructs
`configuration = StrategyConfigurationValues(strategy_id, "v1", "v1",
"v1", {})` — **a completely EMPTY `values` dict** — for every strategy,
every tick, every instrument. This is passed unchanged through
`run_active_loop_tick()` → `PaperSignalExecutionService.
evaluate_and_submit()` → `StrategyExecutionCoordinator.run()` →
`strategy.evaluate(latest_bar, strategy_features, config)`.

Inside `evaluate()`, every registered strategy calls `require_int`/
`require_decimal(config.values, "some_parameter")` —
`contracts.py:274-292` shows these are RAW dict subscripts
(`value = values[parameter_id]`), with **no default-fill, no fallback
to `parameter_schema()`'s own defaults**. `validate_configuration()`
(the only other place defaults could plausibly be injected) was
checked directly too — it TOLERATES a missing key (skips validating
it) but never writes a default value INTO the dict.

**Net effect, confirmed by tracing the actual code, not assumed**:
with an empty `{}` passed all the way through, the FIRST parameter
lookup inside ANY of the 3 registered strategies' `evaluate()` (e.g.
`ema_crossover`'s `require_int(config.values, "fast_lookback")`) would
raise `KeyError` — caught by `coordinator.run()`'s own
`except Exception` isolation boundary (so the worker process itself
would not crash), but surfacing as a silent `StrategyExecutionFailure`
for every single evaluation. **A live paper session started today
would connect, ingest bars, and run — but would never produce a single
real signal for any of the 3 registered strategies**, regardless of
which preset or defaults are nominally intended.

`[F]` **This gap was checked against the existing test suite directly,
not assumed to be already caught**: `test_active_loop_end_to_end.py`
(the test file that most directly exercises `run_active_loop_tick()`)
constructs its OWN `_config()` helper with REAL, explicit values
(`{"fast_lookback": 3, "slow_lookback": 6}`) — **no existing test in
this codebase exercises the actual empty-`{}` configuration
`signal_pipeline_runtime.py` genuinely constructs in production.** This
is a real, previously-undiscovered gap between what is tested and what
production code actually does — not a config/data/credential issue,
a code issue, out of this checkpoint's own "no code changes" scope to
fix, reported here precisely instead.

### Genuinely cannot be verified without a live session actually running

Per §5 of the document itself, listed honestly rather than guessed at:
scanner progress advancing across polls; at least one complete scan
cycle reaching `COMPLETED`; no stale progress; session state
transitioning `STARTING`→`RUNNING` with `drift == false`; signal/
evidence/risk-decision/paper-order/fill persistence for any REAL
signal (now moot until the finding above is addressed, since no
signal would ever be produced); per-channel Telegram/Discord delivery
status for a real signal; a real Daily Session Report for the session
date. None of these can be confirmed by static inspection — they
require an actual running session.

## Part 3 — Readiness: NOT READY, with a precise reason

**No.** The system is not genuinely ready for a first live paper
session today, per the document's own Success Criteria — not because
of missing credentials, data, or configuration (all of those check
out), but because of a genuine, previously-undiscovered code gap:
**the live signal-evaluation path never actually supplies real
strategy parameter values**, so no registered strategy could ever
produce a signal, making the session's own primary purpose (exercising
the strategy→signal→risk→paper-order→communication pipeline)
impossible to fulfill even though every infrastructure precondition is
met.

**What's missing, stated concretely** (not fixed here, per this
checkpoint's own no-code-changes rule):
1. `signal_pipeline_runtime.py::promote_bars_and_trigger_signals()`
   needs to construct each strategy's `StrategyConfigurationValues`
   with REAL parameter values (either `default_configuration_values()`
   — the existing helper `replay_paper_session.py` already uses for
   exactly this purpose — or a real, resolved saved preset), not an
   empty `{}`.
2. Once that's fixed, per Part 1's own finding: the ACTUAL values used
   should be the raw schema defaults (or the exact-match
   `ema_conservative`/`sma_conservative` presets) for `ema_crossover`/
   `sma_trend_filter`, and — since no existing `atr_volatility_
   breakout` preset matches the documented baseline — either the raw
   schema defaults directly, or a NEW preset created that matches
   `14/2.0/1.0/1.5/2.5/3.5/1.0` exactly, before a first session uses
   that strategy.

**If/when the operator addresses the finding above** (a future
checkpoint's own decision, not this one's), the exact command sequence
`FIRST_LIVE_PAPER_VALIDATION_PROCEDURE.md` §2 itself documents is:
1. Confirm/refresh the Dhan credential (Settings → Dhan) — currently
   `VALID` until `2026-09-09 10:17:40 UTC`.
2. `manage.py run_market_data_worker --provider dhan` (a separate,
   manual OS process — unautomated by design).
3. Confirm Provider Connectivity/Watchdog read `READY` once the worker
   reports `HEALTHY`.
4. Confirm Market State reads `READY` (session genuinely `OPEN`).
5. Set `ScannerConfiguration.universe_mode="SELECTED"` with a 3-5
   symbol universe (e.g. RELIANCE/TCS/HDFCBANK/INFY/ICICIBANK).
6. Set `timeframe="5m"`.
7. Set `selected_strategy_ids` to the 3 registered strategies.
8. Press **START LIVE PAPER SESSION** on the Live Paper Operations
   Console — the backend independently re-verifies `can_start` itself.

**This checkpoint did none of the above** — no `ScannerConfiguration`
row was activated, no session was started, no broker-order code path
was called. This remains the operator's own explicit, separate
decision, and — per this checkpoint's own finding — should wait until
the empty-configuration gap above is addressed, or the operator
accepts running a session that structurally cannot produce a signal
for any registered strategy (a legitimate but different kind of
"session," not what §5's Success Criteria as a whole anticipate).

## `MEMORY.md` and `PROJECT_STRATEGY_STATUS.md` — confirmed updated

`[F]` Appended (never rewrote) a new entry to `MEMORY.md` §3 recording
the preset-vs-baseline finding and, most importantly, the empty-
configuration live-path gap, with the exact file/function chain traced.
`[F]` `PROJECT_STRATEGY_STATUS.md` (the committed living reference)
updated with a new "Paper-trading readiness" section reflecting this
checkpoint's NOT READY verdict and its precise cause, superseding
`CHECKPOINT_76`'s own more provisional "technically ready per the
document" reading — that reading is now known to be incomplete;
readiness has not yet been re-verified against this newly-discovered
gap. **Both confirmed explicitly here, as this checkpoint's own
instruction required.**

## Governance compliance

- No strategy code changes, no parameter changes, no registry change
  — confirmed (`git status --short` shows only this summary,
  `MEMORY.md`, and `PROJECT_STRATEGY_STATUS.md`).
- No live session launch, no `ScannerConfiguration` activation, no
  broker-order code path called — confirmed; every check this
  checkpoint performed was read-only inspection or a pure,
  no-network function call (`evaluate_dhan_token_lifecycle`).
- No Gainz/VWAP tuning — both remain untouched, still paused.
- P11/P16: this summary, `MEMORY.md`, and `PROJECT_STRATEGY_STATUS.md`
  committed to `active-development` only.
