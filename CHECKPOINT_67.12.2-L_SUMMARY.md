# CHECKPOINT 67.12.2-L — CLOSE THE SYNTHETIC-VS-REAL BACKTEST DATA LOOP

```
checkpoint: 67.12.2-L
verdict: GATE_CONFIRMED_SAFE_AND_PROVIDER_FIXED
gate_filters_synthetic_data: YES (evidence: see A below)
provider_selection_fixed: YES
failure_mode_honest: YES (with one non-blocking finding — see C)
full_sweep_result: 719/719 (715 baseline + 4 new tests added by this checkpoint; 0 failures, 0 errors)
commit: <filled in after commit>
blockers: []
```

---

## A. Gate-filtering evidence (Part 1–2)

**Part 1 — static trace.**

1. `src/intraday/domain/market_data/provenance.py:57-63` — `is_research_eligible(provenance)` returns `provenance == PROVENANCE_REAL_DHAN` (`"REAL_DHAN"`), full stop. `PROVENANCE_SYNTHETIC_TEST = "SYNTHETIC_TEST"` and `PROVENANCE_UNKNOWN = "UNKNOWN"` both fail this check — neither passes.
2. `SyntheticHistoricalBarProvider` (`infrastructure/market_data_providers/synthetic_historical.py:93`) declares `provenance: str = field(default=PROVENANCE_SYNTHETIC_TEST, init=False)` — every bar it produces is honestly labeled `SYNTHETIC_TEST`, a different string than `REAL_DHAN`, by construction.
3. `ResearchDataGateService.get_research_eligible_bars()` (`application/services/research_data_gate.py:209-229`) — for the WHOLE requested range, one `repository.get_bars_with_provenance()` call, then an unconditional loop over **every** returned row (`for provenanced_bar in provenanced:` — no flag, no opt-out, no per-call-site branch) checking `is_research_eligible(provenanced_bar.provenance)`. Any ineligible row raises `ResearchDataRejectedError(INELIGIBLE_PROVENANCE, ...)` — the whole range rejected outright, nothing silently dropped or relabeled.
4. Call path from a real `RESEARCH` run: `backtesting_views.py::run_backtest_view` (line 190-193) → `_service()` (line 100-112, real branch) constructs `BacktestingService.for_database_backed_research(..., research_gate=ResearchDataGateService(repository=DjangoHistoricalBarRepository(), ...))` → `BacktestingService.run()` (`application/services/backtesting.py:186-206`): `if self.research_gate is not None:` branch (which is ALWAYS true for this construction path, confirmed by 67.12.2-B) calls `self.research_gate.get_research_eligible_bars(...)` and binds its `.bars` — `ResearchDataRejectedError` is left to propagate uncaught (line 190-195's own comment). There is no code path in `run()` that reads `HistoricalBar` directly when `research_gate` is set.
5. Conclusion from static trace alone: the filter applies to **every** bar read for a `RESEARCH` run through this path, unconditionally — not gated behind a flag or limited to some call sites.

**Part 2 — the test that actually settles it.**

New file `tests/unit/application/services/test_checkpoint_67_12_2_L_gate_filters_synthetic.py`, `test_gate_rejects_a_real_research_backtest_reading_only_synthetic_data`:

- Populates real `HistoricalBar` rows via the real, unmodified `HistoricalDataPreparationService` + `SyntheticHistoricalBarProvider()` (exactly what `_prepare_if_needed` produced before this checkpoint's Part 3 fix) — independently confirmed via direct Django ORM query that every persisted row carries `provenance == "SYNTHETIC_TEST"`.
- Drives a real `RESEARCH`-mode backtest through the REAL, unmodified `BacktestingService.for_database_backed_research()` factory with a REAL `ResearchDataGateService` wired to the REAL `DjangoHistoricalBarRepository` against the real PostgreSQL test database — no fake repository, no gate mock, no shortcut.
- **Observed result: `ResearchDataRejectedError` was raised, with `.reason is ResearchRejectionReason.INELIGIBLE_PROVENANCE` and `.detail` containing `"SYNTHETIC_TEST"`.** This is the SAFE outcome — zero eligible bars returned to the backtest engine, a clear typed rejection, no silent pass-through.
- A control test (`test_gate_allows_the_same_shape_of_request_when_provenance_is_real_dhan`) proves the SAME range/instrument, with rows genuinely relabeled `REAL_DHAN` + `CANONICALIZATION_STATE_CANONICALIZED` + proven `OPEN` semantics, DOES pass the gate and the backtest completes (`result.data_quality.bar_count > 0`) — ruling out "the rejection above was really an unrelated coverage bug that rejects everything."

**Verdict: `gate_filters_synthetic_data: YES`, CONFIRMED (not merely HIGH-CONFIDENCE) — both a full static trace with `file:line` citations and a real end-to-end Postgres-backed test through the unmodified production construction path agree.**

This is the single most important fact from this checkpoint: "the gate is always constructed" (67.12.2-B) and "the gate actually filters synthetic data" are BOTH true, and were previously two separate, unverified claims — this checkpoint closes that gap with a real, reproducible test, not an inference.

---

## B. Provider-selection fix (Part 3)

Applied, since Part 2 confirmed the SAFE outcome.

**Change** (`src/intraday/infrastructure/api/backtesting_views.py`):
- Import added: `from intraday.infrastructure.api.tasks import _select_historical_bar_provider`.
- Removed the now-unused `from intraday.infrastructure.market_data_providers.synthetic_historical import SyntheticHistoricalBarProvider` import.
- `_prepare_if_needed()`'s body: `provider=SyntheticHistoricalBarProvider()` → `provider=_select_historical_bar_provider()` — the exact same selector `build_historical_backtest_orchestrator()` (`tasks.py`) already uses for the multi-instrument panel. No circular import (`tasks.py` does not import `backtesting_views.py`) — confirmed by a real Django `setup()` + import smoke test.
- Docstring rewritten to state plainly that `DhanHistoricalBarProvider` genuinely exists and is now selected when Dhan credentials are configured, and that the prior "no real provider exists" claim (carried from 65.12, already flagged stale by 67.12.2-B) was false.

**Proof test** (`test_prepare_if_needed_now_uses_the_real_provider_selector_and_gate_passes`):
- Monkeypatches `backtesting_views._select_historical_bar_provider` (the exact name the fixed code now calls) to a test-local fake satisfying the same `HistoricalBarProvider` Protocol `DhanHistoricalBarProvider` does (`provenance = REAL_DHAN`, `canonicalization_state_for` → `CANONICALIZED`, `source_timestamp_semantics_for` → proven `OPEN`) — no real Dhan network call; `DhanHistoricalBarProvider`'s own internals are already covered, unmodified, by `test_historical_provider.py`.
- Calls the real `_prepare_if_needed(config)` once → `fetch_call_count == 1`, DB rows confirmed `provenance == REAL_DHAN`.
- Runs the real `BacktestingService.for_database_backed_research().run()` against those rows → succeeds (`result.data_quality.bar_count > 0`) — the gate now passes real-provider data through, previously-synthetic-only instrument included.
- Calls `_prepare_if_needed(config)` a second time for the identical range → `fetch_call_count` stays `1` — zero further provider calls, mirroring the established 67.12.2-J/K cache-hit invariant pattern.

---

## C. Failure-mode honesty check (Part 4)

**Observed behavior (a real finding, not an assumption):** `HistoricalDataPreparationService.prepare()` already catches provider exceptions internally with a bounded retry (`MAX_FETCH_ATTEMPTS = 3`, `historical_data_preparation.py:144-155`) and, on exhaustion, returns a `PreparationOutcome` with `status=PreparationStatus.NOT_AVAILABLE` (or `PARTIAL` if some prior range was already cached) rather than raising. `_prepare_if_needed()` (`backtesting_views.py`) calls `preparation.prepare(...)` and **discards the returned outcome entirely** (never inspects `.status`), so no exception propagates out of `_prepare_if_needed` on a provider failure — with or without this checkpoint's fix.

This means the correct framing of "does a provider failure silently fall back to synthetic data" is: **no** — nothing in `_prepare_if_needed` or `HistoricalDataPreparationService` ever constructs a second, different provider on failure; a failed fetch simply leaves the range under-populated (or empty) in the DB. Proven by `test_prepare_if_needed_propagates_provider_failure_never_silently_falls_back`:
- A failing real-provider fake (`HistoricalBarProviderUnavailableError` on every `fetch()` call) is wired in; `_prepare_if_needed(config)` returns normally (per the finding above), `fetch_call_count == MAX_FETCH_ATTEMPTS == 3` (bounded retry confirmed), and **zero** `HistoricalBar` rows are persisted — no synthetic-labeled data appeared under the real provider's name.
- The subsequent real `RESEARCH` backtest call through `BacktestingService.for_database_backed_research().run()` then hits the gate's own completeness check and raises `ResearchDataRejectedError` with `.reason` in `{NO_DATA, INCOMPLETE_COVERAGE}` — a loud, typed rejection surfaces to the caller, never a silently-produced result using fabricated data.

**Non-blocking finding, reported per Part 4's own instruction ("if it reveals an actual silent-fallback risk, do not fix it inline — report it"):** `_prepare_if_needed` discarding `PreparationOutcome` entirely means the single-instrument synchronous view has no way to distinguish "prepared successfully" from "provider failed, range is incomplete" BEFORE calling `service.run()` — it relies entirely on the downstream gate (for real, DB-backed instruments) or on `run_backtest`'s own insufficient-data handling (for the fixture path) to surface the failure. This is NOT a silent-fallback-to-synthetic-data risk (verified above: no fallback occurs), but it IS a missed opportunity for an earlier, more specific error message to the caller (today's surfaced error is `ResearchDataRejectedError: NO_DATA`/`INCOMPLETE_COVERAGE`, not something like "the Dhan provider failed 3 times: <reason>"). Recommended for a dedicated, narrowly-scoped follow-up checkpoint (see E) — out of THIS checkpoint's scope per Part 4's explicit instruction not to redesign failure handling inline.

**`failure_mode_honest: YES`** — no silent fallback to synthetic data exists; the finding above is a UX/diagnosability gap, not a safety gap.

---

## D. Final sweep result

Ran `tests/unit/infrastructure/persistence/` + `tests/unit/infrastructure/market_data_providers/` + `tests/unit/application/services/` (the exact 67.12.2-K baseline scope) standalone:

```
719 passed, 2 warnings in 127.96s
```

715 (67.12.2-K baseline) + 4 new tests added by this checkpoint (`test_checkpoint_67_12_2_L_gate_filters_synthetic.py`) = 719. **Zero regressions, zero failures, zero errors** — confirmed by direct comparison against the stated 715/715 baseline.

A broader combined run that ALSO included `tests/unit/infrastructure/api/test_historical_backtesting_api.py` (not part of the stated baseline scope, but touched adjacent territory) showed 4 pre-existing failures (`test_scenario_a_empty_database_run_completes_via_real_progress_state`, `test_scenario_b_repeat_run_makes_zero_api_requests`, `test_coverage_preview_reports_100_percent_after_a_completed_run`, `test_a_decimal_typed_strategy_parameter_sent_as_a_json_string_succeeds`) plus 4 transient `ERROR`s from Postgres test-DB teardown contention when many files run together. **Both were independently verified NOT caused by this checkpoint**: `git stash` (reverting this checkpoint's changes) reproduced the exact same 4 `test_historical_backtesting_api.py` failures against the unmodified baseline, and the 4 `ERROR` entries' underlying tests pass cleanly (7/7) when run in isolation — confirming they were pre-existing/environmental, not a regression this checkpoint introduced. These pre-existing failures are reported here for completeness, not claimed as fixed or in-scope.

---

## E. Recommended next checkpoint

**67.12.2-M — Surface `_prepare_if_needed`'s discarded `PreparationOutcome` as a specific, actionable error before `service.run()` is even attempted.** Today (both before and after this checkpoint's fix) a provider failure in `_prepare_if_needed` is invisible until the downstream gate's generic `NO_DATA`/`INCOMPLETE_COVERAGE` rejection surfaces from `service.run()` — correct and safe (Part 4 above), but not diagnosable: an operator sees "no data available," not "the Dhan provider failed 3 times: <the actual error>." A narrowly-scoped fix would have `_prepare_if_needed` inspect the returned `PreparationOutcome.status`/`.error_message` and raise (or return via the existing `InsufficientHistoricalDataError`/similar error-response path `run_backtest_view` already handles) a specific, honest message before ever constructing `BacktestingService`. Also worth investigating in the same or a sibling checkpoint: the 4 pre-existing `test_historical_backtesting_api.py` failures noted in Part D (unrelated to this checkpoint, but real and currently unaddressed).
