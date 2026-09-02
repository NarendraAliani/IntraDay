checkpoint: 67.12.2-O
verdict: ALL_4_RESTORED_AND_MEANINGFUL
per_test_approach: { scenario_a: b, scenario_b: b, coverage_preview: b, decimal_param: b }
per_test_reasoning_sound: YES
full_sweep_result: 733/733
commit: 67551f99f1ea2447aa5b0bda699a5d49c65a0f3f
blockers: []

## A. Per-test intent and chosen approach

1. **`test_scenario_a_empty_database_run_completes_via_real_progress_state`** — exists to prove
   the DB-first pipeline (coverage -> fetch -> persist -> scan) genuinely runs end to end on an
   empty database, observed through the real progress endpoint (`api_requests > 0`,
   `cache_misses > 0`, `scanned_bars > 0`). Approach **(b)**: pre-seeding rows (approach a) would
   make "fetches happened" unobservable — there would be nothing left to fetch. Only exercising
   the real provider-selection path proves this.

2. **`test_scenario_b_repeat_run_makes_zero_api_requests`** — exists to prove the mandatory
   cached-run optimization: a second identical run makes **zero** further provider calls.
   Approach **(b)**, per the checkpoint directive's own reasoning: approach (a) would make the
   fetch path unreachable on the *first* run too, so "0 calls on the second run" could not be
   distinguished from "the provider path was never wired to anything in the first place."

3. **`test_coverage_preview_reports_100_percent_after_a_completed_run`** — exists to prove the
   read-only coverage-preview endpoint reflects a real 100%-complete run. Approach **(b)**, chosen
   for consistency with the real fetch/persist path used immediately above in the same file — the
   preview endpoint itself is already independently proven read-only by the sibling
   `..._reports_zero_percent_before_any_run` test, so what mattered here was that the "100%" being
   read back came from real orchestrator-persisted rows, not a hand-inserted fixture.

4. **`test_a_decimal_typed_strategy_parameter_sent_as_a_json_string_succeeds`** — exists to prove
   the JSON-string-Decimal coercion survives "end to end" (the test's own docstring's word),
   through validation, a real fetch, persistence, and strategy execution to `COMPLETED`. Approach
   **(b)**: a pre-seeded approach would still prove the coercion, but would understate the "end to
   end" claim the test itself makes.

All 4 use the same new reusable fixture, `_install_fake_real_dhan_provider()`: it substitutes real
Dhan credentials + a fake `DhanInstrumentMasterProvider.list_instruments` (exactly mirroring this
file's own pre-existing `test_a_run_uses_the_real_dhan_provider_when_credentials_are_configured`
pattern — a real precedent in this file, not invented for this checkpoint), then monkeypatches the
ONE real outbound call site, `historical_provider.fetch_intraday_candles`, to return a genuine full
CAS-era trading day's worth of raw candles (`_cas_era_intraday_candles`), built from the same
`build_cas_aware_session_for(...).expected_continuous_bar_timestamps` session machinery
`HistoricalDataCoverageService` itself uses to define "100% coverage" — so the resulting bars are
genuinely complete, not merely present.

## B. Implementation

Root cause requiring more than a credentials swap: `ResearchDataGateService` (wired by Checkpoint
67.1) requires every `REAL_DHAN`-provenance row to ALSO have
`canonicalization_state == CANONICALIZED` — and that state is stamped ONLY for the one
empirically-proven `(NSE_EQ, Timeframe.FIVE_MINUTE, CAS_ERA)` scope
(`historical_provider.py::_PROVEN_INTRADAY_SCOPES`, Checkpoint 67.0/67.5/67.6). The file's old
fixture default date, `2026-01-05`, is PRE-CAS (before `CAS_EFFECTIVE_DATE` 2026-08-03) — using it
with real-Dhan-provenance rows would still fail the gate, just with `UNCANONICALIZED_TIMESTAMP`
instead of `INELIGIBLE_PROVENANCE`. All 4 tests were moved to `2026-08-17` — the literal date
`test_historical_provider.py::_CAS_ERA_WINDOW` already uses for the identical reason, a genuine
trading Monday entirely in the CAS era.

Changed file: `tests/unit/infrastructure/api/test_historical_backtesting_api.py` only — new
imports, module-level helpers (`CAS_ERA_TRADING_DATE`, `_real_dhan_credentials`,
`_cas_era_intraday_candles`, `_install_fake_real_dhan_provider`), and the 4 failing tests updated
to call the fixture and use the CAS-era date. No production file touched.

## C. Proof each test meaningfully exercises its original property

- **Scenario A**: asserts (unchanged) `api_requests > 0`, `cache_misses > 0`, `scanned_bars > 0`,
  `result_backtest_ids` non-empty, `completed_instruments == 1` — all computed by the real,
  unmodified `HistoricalDataPreparationService`/orchestrator from the real fake-provider call, not
  hard-coded.
- **Scenario B**: independently tracks `fetch_calls` (the actual Python calls into the fake
  `fetch_intraday_candles`) alongside the framework's own `api_requests` counter — asserts
  `len(fetch_calls) == 1` after the first run and **still** `== 1` (not incremented) after the
  second, proving the second run's `api_requests == 0` reflects a real cache hit, not an unreached
  code path.
- **Coverage preview**: the preceding run persists real `REAL_DHAN`/`CANONICALIZED` rows through
  the unmodified orchestrator; the preview endpoint's `100.0%`/`is_complete=True` is computed by
  `HistoricalDataCoverageService` reading those same rows back from Postgres — a real
  computation, not a vacuous one (the sibling `..._reports_zero_percent_before_any_run` test in
  the same file already proves the endpoint doesn't fabricate 100% for an empty DB).
- **Decimal parameter**: the run genuinely reaches `COMPLETED` via the real fetch -> persist ->
  strategy-execution pipeline with `sma_trend_filter` and `band_percent="0.02"` sent as a JSON
  string — `not failed_instruments` is asserted against real orchestrator output, not a mock.

## D. Final sweep result

- `test_historical_backtesting_api.py` standalone: **14 passed** (all tests in the file, including
  the 4 redesigned ones and the 10 already-passing ones — zero regressions within the file).
- Full combined sweep (`tests/unit/infrastructure/persistence/` +
  `tests/unit/infrastructure/market_data_providers/` + `tests/unit/application/services/` +
  `tests/unit/infrastructure/api/test_historical_backtesting_api.py`): **733 passed / 733 total**
  (up from 67.12.2-N's baseline of 729/733 — the 4 previously-failing tests are now genuinely
  fixed, zero new regressions anywhere in the sweep).

No production code (`research_data_gate.py`, `provenance.py`, `tasks.py`,
`backtesting_views.py`) was touched — HALT condition not triggered.
