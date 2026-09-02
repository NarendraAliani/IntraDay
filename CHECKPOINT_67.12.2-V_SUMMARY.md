# Checkpoint 67.12.2-V — Confirm/Close the Unmocked Real-Dhan-Call Risk

```
checkpoint: 67.12.2-V
verdict: RISK_CONFIRMED_AND_FIXED
mocking_gap_found: YES
could_reach_real_dhan_under_normal_conditions: YES
fix_applied: YES (autouse no-credentials default + fake-provider double, matching the established 67.12.2-L/O pattern)
commit: (recorded below)
blockers: []
```

## A. What the test does and doesn't mock (Part 1)

`[F]` Read `tests/unit/infrastructure/api/test_backtesting_api.py` in
full, before any change. The file (Checkpoint 27's original API test
file) mocks **only** Django auth (`User`/`Group`/`Client.login`) and
uses the real Django test client against the real view stack. It
mocked **nothing** related to Dhan: no `DhanSettingsService.
effective_credentials` override, no `fetch_intraday_candles` fake, no
network boundary of any kind — confirmed via a direct grep for
`autouse|effective_credentials|monkeypatch|DhanSettingsService|
fetch_intraday_candles` in the file, which returned zero matches
before this checkpoint's fix.

This is a **separate, older file** from
`test_historical_backtesting_api.py` (Checkpoint 63.x-era vs. the
67.12.2-L/O-era file), which already has an autouse
`_no_real_dhan_credentials` fixture specifically for this reason —
that protection was never ported to this file.

`[F]` **Why it received `401`s tonight, confirmed precisely**: the
test runs against a fresh, empty `test_intraday` Postgres database
(pytest-django's own per-run test database), which has no
`DhanCredential` row of its own — the real, currently-valid DB-stored
credential lives only in the actual dev database. With no DB-stored
row, `effective_credentials()`
(`application/services/provider_settings.py:146-159`) falls back to
the `.env` file's `DHAN_ACCESS_TOKEN`, which is the long-expired token
already documented earlier in this session (expired 2026-07-25). Dhan
correctly rejected that expired token with `401`. **This was never a
test-side guard working as intended — it was luck.**

## B. The actual risk (Part 2)

`[F]` Checked for any other mechanism that might already gate this
test out of normal execution:
- `@requires_postgres`/`@pytest.mark.django_db`: DB-only gates,
  unrelated to network access.
- `tests/conftest.py`: no network-blocking fixture, no credential
  stub, nothing Dhan-related at all.
- `pytest-socket` (or any equivalent network-blocking plugin): **not a
  project dependency** — confirmed via `import pytest_socket` failing
  in the venv, and no reference in `pyproject.toml`.

**Conclusion: `could_reach_real_dhan_under_normal_conditions: YES`.**
This is a genuine, not hypothetical, gap: if a developer's local
`.env` happens to hold a currently-valid `DHAN_ACCESS_TOKEN` (entirely
plausible — the same file this session already found holds one
sometimes-valid token), or a future CI environment configures one for
any reason, this exact, unmodified test — running inside what is
supposed to be a fast, network-free unit-test sweep — makes a real
`POST https://api.dhan.co/v2/charts/intraday` request against
production Dhan, using real quota, with no test-side awareness that
this happened. `401` tonight was a coincidence of an expired
credential, not a safety property of the test.

## C. Fix applied (Part 3)

Applied the exact pattern already established and proven in
`test_historical_backtesting_api.py` (67.12.2-L/O), duplicated into
this file rather than shared, matching this project's existing
per-file helper-duplication convention:

1. New autouse `_no_real_dhan_credentials` fixture — every test in
   this file now gets `DhanSettingsService.effective_credentials`
   monkeypatched to return `None` by default, forcing
   `_select_historical_bar_provider()` to the synthetic fallback,
   never a real Dhan connection. Confirmed this cannot affect
   `test_run_backtest_against_fixture_instrument_still_uses_the_
   deterministic_fixture` — `FIXTURE01` matches `SYNTHETIC_INSTRUMENT_ID`
   and short-circuits `_prepare_if_needed` before any provider
   selection is ever reached (verified directly in
   `fixtures.py:26`).
2. `_real_dhan_credentials()` + `_install_fake_real_dhan_provider()` —
   the one test that genuinely needs a completed, non-fixture run
   (`test_run_backtest_against_a_real_instrument_is_db_first_not_
   fixture_only`) now opts in explicitly, monkeypatching **only** the
   one real outbound call site
   (`historical_provider.fetch_intraday_candles`) to return a genuine,
   full CAS-era trading day (via `build_cas_aware_session_for` — the
   same machinery `HistoricalDataCoverageService` itself uses, so the
   returned data is genuinely complete, not vacuously so). Everything
   downstream of that one call site (coverage, persistence, the
   research gate) runs for real, unmodified.
3. Added `assert len(calls) == 1` — explicit, direct proof of exactly
   one (fake) provider call and, by construction, zero real ones: the
   real HTTP client is never invoked at all, so there is nothing left
   that could reach the network.

**Verified, not assumed**:
- `[F]` Full file re-run: **8/8 pass** (up from 7/8 — the previously-
  `401`-failing test now passes deterministically).
- `[F]` Captured output for the fixed test, greped for
  `HTTP Request|dhan.co|401|200`: **zero matches** — no network
  activity logged at all, compared to the 3 real `POST .../v2/charts/
  intraday` calls this same test logged before the fix.
- `[F]` Broader established sweep (`tests/unit/infrastructure/
  persistence/` + `market_data_providers/` + `application/services/` +
  `test_historical_backtesting_api.py` + this file): **750 passed /
  750 total**, zero failures — up from 742, no regression anywhere.

**No assertions were weakened** — the test still proves exactly what
it was written to prove (a real, non-fixture instrument completes via
the DB-first pipeline, `bar_count > 0`), now additionally proving zero
real network reachability, which it never proved before.

## D. Readiness for tomorrow

**This closes cleanly and does not change tomorrow's readiness in any
negative way** — if anything, it removes a previously-unrecognized
risk. No migration-execution or timestamp-semantics code was touched.
The fix is entirely test-infrastructure, confined to one file. Nothing
here blocks or delays tomorrow's live session.
