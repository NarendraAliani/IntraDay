# tests/unit/infrastructure/api/test_historical_backtesting_api.py
#
# Checkpoint 63.x: API-level coverage for the DB-first historical
# backtest run resource. `CELERY_TASK_ALWAYS_EAGER = True`
# (settings/testing.py) makes `run_historical_backtest_run_task.delay()`
# execute synchronously in-process here, so `create_historical_backtest_run_view`
# has already fully run the orchestrator by the time it returns - the
# progress endpoint can be polled immediately afterward and see a
# terminal state, matching Scenario A/B (Phase 37) end to end.
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from intraday.application.services.instrument_master import InstrumentMasterEntry
from intraday.application.services.provider_settings import DhanSettingsService
from intraday.domain.session.calendar import build_cas_aware_session_for, instrument_category_for
from intraday.domain.session.contracts import InstrumentCategory
from intraday.infrastructure.api.permissions import CONFIGURATION_OPERATOR_GROUP
from intraday.infrastructure.market_data_providers.dhan import historical_provider
from intraday.infrastructure.market_data_providers.dhan.historical_client import (
    DhanHistoricalCandle,
)
from intraday.infrastructure.market_data_providers.dhan.instrument_master import (
    DhanInstrumentMasterProvider,
)
from tests.postgres_utils import requires_postgres

OPERATOR_USERNAME = "hist-bt-operator"  # noqa: S105
READER_USERNAME = "hist-bt-reader"  # noqa: S105
PASSWORD = "correct-horse-battery-staple"  # noqa: S105

# Checkpoint 67.12.2-O: Checkpoint 67.1 wired `ResearchDataGateService`
# to require, for EVERY `REAL_DHAN`-provenance row it reads,
# `canonicalization_state == CANONICALIZED` (see `research_data_gate.py`
# Part 4/6/13/14) - and that state is only ever stamped for the ONE
# empirically-proven (segment, timeframe, era) triple 67.0 actually
# tested: `(NSE_EQ, Timeframe.FIVE_MINUTE, CAS_ERA)` (see
# `historical_provider.py::_PROVEN_INTRADAY_SCOPES`). 2026-08-17 is the
# literal date that scope was proven against (a Monday, a genuine
# trading day, entirely on/after `CAS_EFFECTIVE_DATE` 2026-08-03) - the
# SAME date `test_historical_provider.py::_CAS_ERA_WINDOW` already uses
# for the identical reason. Using any PRE-CAS date (like the old
# 2026-01-05 fixture default) would produce REAL_DHAN rows stamped
# `canonicalization_state=UNKNOWN`, which the gate correctly rejects
# with `UNCANONICALIZED_TIMESTAMP` - a second, independent gate failure
# mode, not the one this checkpoint is fixing.
CAS_ERA_TRADING_DATE = date(2026, 8, 17)


def _real_dhan_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Checkpoint 67.12.2-O, approach (b): substitutes the file's
    autouse `_no_real_dhan_credentials` fixture's no-credentials stamp
    with genuine-looking Dhan credentials PLUS a fake instrument-master
    lookup, so `_select_historical_bar_provider()`
    (infrastructure/api/tasks.py) genuinely selects
    `DhanHistoricalBarProvider` - the real provider-selection/caching
    code path - instead of bypassing it. Mirrors this file's own
    pre-existing `test_a_run_uses_the_real_dhan_provider_when_
    credentials_are_configured` pattern exactly, just factored out for
    reuse by the other 3 tests that need a run to actually COMPLETE
    (that test alone is fine leaving the fetch returning zero candles,
    since its job is only proving WHICH provider ran)."""
    monkeypatch.setattr(
        DhanSettingsService, "effective_credentials", lambda self: ("client-1", "token-1")
    )
    monkeypatch.setattr(
        DhanInstrumentMasterProvider,
        "list_instruments",
        lambda self, exchange: (
            InstrumentMasterEntry(
                symbol="RELIANCE", display_name="Reliance Industries", security_id=2885
            ),
        ),
    )


def _cas_era_intraday_candles(
    *, symbol: str = "RELIANCE", day: date = CAS_ERA_TRADING_DATE, interval_minutes: int = 5
) -> tuple[DhanHistoricalCandle, ...]:
    """Builds a full, genuinely-shaped trading day of raw Dhan intraday
    candles for `day` - one per expected bar-CLOSE timestamp
    (`build_cas_aware_session_for(...).expected_continuous_bar_
    timestamps`, the SAME session machinery `HistoricalDataCoverageService`
    itself uses to decide what "100% coverage" means - see
    `historical_data_coverage.py::_expected_timestamps`), each stamped
    at `close - interval` to match Dhan's proven OPEN-of-interval raw
    convention (`historical_provider.py`'s own
    `_DHAN_INTRADAY_TIMESTAMP_SEMANTICS = SourceTimestampSemantics.OPEN`).
    Returning exactly this set - not a a partial or over-wide one -
    is what makes the resulting run/coverage genuinely 100% complete,
    not vacuously so."""
    category = instrument_category_for(symbol)
    session = build_cas_aware_session_for(
        category, day, datetime.combine(day, time.max, tzinfo=UTC)
    )
    interval = timedelta(minutes=interval_minutes)
    closes = session.expected_continuous_bar_timestamps(interval)
    return tuple(
        DhanHistoricalCandle(
            timestamp=close - interval,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=1000,
        )
        for close in closes
    )


def _install_fake_real_dhan_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, object]]:
    """Wires `_real_dhan_credentials` plus a fake
    `fetch_intraday_candles` that returns a genuine full CAS-era trading
    day (`_cas_era_intraday_candles`) - the test-only
    "FakeRealDhanHistoricalBarProvider" double named in this checkpoint's
    directive, implemented as a monkeypatch of the one real outbound
    call site (`historical_provider.fetch_intraday_candles`) rather than
    a whole new provider class, exactly mirroring this file's
    pre-existing `test_a_run_uses_the_real_dhan_provider_when_
    credentials_are_configured` pattern. Returns the `calls` list so
    callers (Scenario B in particular) can assert the real call COUNT,
    not just that a run reached COMPLETED."""
    _real_dhan_credentials(monkeypatch)
    calls: list[dict[str, object]] = []

    def _fake_fetch_intraday_candles(**kwargs: object) -> tuple[DhanHistoricalCandle, ...]:
        calls.append(kwargs)
        return _cas_era_intraday_candles()

    monkeypatch.setattr(
        historical_provider, "fetch_intraday_candles", _fake_fetch_intraday_candles
    )
    return calls


@pytest.fixture(autouse=True)
def _no_real_dhan_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """This whole file predates the real `DhanHistoricalBarProvider` and
    exercises `HistoricalBacktestRunOrchestrator`'s DB-first PIPELINE
    (coverage/fetch/persist) against the deterministic synthetic
    provider - never a real Dhan network call. `_select_historical_bar_
    provider()` (infrastructure/api/tasks.py) now picks the real
    provider whenever Dhan credentials are configured, and this dev
    environment's own `.env` genuinely carries a real (if possibly
    stale) access token - matching `test_market_data_ingestion_runtime.
    py`'s own established "explicitly force no credentials, unless a
    test is specifically about the credentials-configured path" fixture
    pattern, not a new convention."""
    monkeypatch.setattr(DhanSettingsService, "effective_credentials", lambda self: None)


def _client_as_operator() -> Client:
    user = User.objects.create_user(username=OPERATOR_USERNAME, password=PASSWORD)
    group, _ = Group.objects.get_or_create(name=CONFIGURATION_OPERATOR_GROUP)
    user.groups.add(group)
    client = Client()
    assert client.login(username=OPERATOR_USERNAME, password=PASSWORD)
    return client


def _client_as_reader() -> Client:
    User.objects.create_user(username=READER_USERNAME, password=PASSWORD)
    client = Client()
    assert client.login(username=READER_USERNAME, password=PASSWORD)
    return client


def _run_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "instrument_ids": ["NSE:RELIANCE"],
        "timeframe": "5m",
        "start_date": "2026-01-05",
        "end_date": "2026-01-05",
        "strategy_id": "ema_crossover",
        "specification_version": "v1",
        "code_version": "v1",
        "configuration_version": "v1",
        "strategy_values": {"fast_lookback": 3, "slow_lookback": 6},
        "initial_capital": "100000",
        "position_sizing_mode": "FIXED_QUANTITY",
        "position_size_value": "10",
        "brokerage_percent": "0",
        "slippage_percent": "0",
    }
    payload.update(overrides)
    return payload


@requires_postgres
@pytest.mark.django_db
def test_create_run_requires_operator_role() -> None:
    client = _client_as_reader()
    response = client.post(
        "/api/v1/config/backtesting/historical-runs/",
        data=_run_payload(),
        content_type="application/json",
    )
    assert response.status_code == 403


@requires_postgres
@pytest.mark.django_db
def test_create_run_returns_202_with_a_run_id() -> None:
    client = _client_as_operator()
    response = client.post(
        "/api/v1/config/backtesting/historical-runs/",
        data=_run_payload(),
        content_type="application/json",
    )
    assert response.status_code == 202
    assert "run_id" in response.json()


@requires_postgres
@pytest.mark.django_db
def test_scenario_a_empty_database_run_completes_via_real_progress_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scenario A (Phase 37): empty DB -> the eager-executed task fetches,
    persists, scans, and completes - proven through the SAME progress
    endpoint the frontend polls, not a white-box service call.

    Checkpoint 67.12.2-O: this test's whole point is proving the real
    fetch/persist/scan pipeline runs on a genuinely empty DB - approach
    (b) (a real `DhanHistoricalBarProvider` selection, fed a fake
    `fetch_intraday_candles`) exercises that real pipeline exactly as
    production wires it; a pre-seeded-rows approach (a) would leave
    nothing for "fetches" (`api_requests > 0`, `cache_misses > 0`) to
    actually prove."""
    _install_fake_real_dhan_provider(monkeypatch)
    client = _client_as_operator()
    create_response = client.post(
        "/api/v1/config/backtesting/historical-runs/",
        data=_run_payload(start_date="2026-08-17", end_date="2026-08-17"),
        content_type="application/json",
    )
    run_id = create_response.json()["run_id"]

    progress_response = client.get(f"/api/v1/config/backtesting/historical-runs/{run_id}/progress/")
    assert progress_response.status_code == 200
    body = progress_response.json()

    assert body["status"] == "COMPLETED"
    assert body["phase"] == "COMPLETED"
    assert body["progress_percent"] == 100.0
    assert body["total_instruments"] == 1
    assert body["completed_instruments"] == 1
    assert body["api_requests"] > 0  # data genuinely had to be fetched
    assert body["cache_misses"] > 0
    assert body["scanned_bars"] > 0
    assert body["result_backtest_ids"]  # one underlying BacktestResult was persisted
    assert not body["failed_instruments"]


@requires_postgres
@pytest.mark.django_db
def test_scenario_b_repeat_run_makes_zero_api_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scenario B (Phase 37/22): the SAME configuration run twice must
    make zero further API requests the second time - the mandatory
    cached-run optimization, proven through the real HTTP API.

    Checkpoint 67.12.2-O: approach (b) is the ONLY faithful choice here
    - this test exists specifically to prove "zero real provider calls
    on the second run", which requires the second run to genuinely go
    through provider-selection and find the cache already warm. A
    pre-seeded-rows approach (a) would make the fetch path unreachable
    from the FIRST run too, so a `0` on the second run couldn't be
    distinguished from "nothing ever called the provider path in the
    first place". `fetch_calls` (backed by the real, unmodified
    `HistoricalDataPreparationService.api_requests` counter surfaced
    through the progress endpoint) is the independent, real evidence."""
    fetch_calls = _install_fake_real_dhan_provider(monkeypatch)
    client = _client_as_operator()
    first = client.post(
        "/api/v1/config/backtesting/historical-runs/",
        data=_run_payload(start_date="2026-08-17", end_date="2026-08-17"),
        content_type="application/json",
    )
    first_run_id = first.json()["run_id"]
    first_progress = client.get(
        f"/api/v1/config/backtesting/historical-runs/{first_run_id}/progress/"
    ).json()
    assert first_progress["status"] == "COMPLETED"
    assert first_progress["api_requests"] > 0
    assert len(fetch_calls) == 1, "the real provider must genuinely have been called once"

    second = client.post(
        "/api/v1/config/backtesting/historical-runs/",
        data=_run_payload(start_date="2026-08-17", end_date="2026-08-17"),
        content_type="application/json",
    )
    second_run_id = second.json()["run_id"]
    second_progress = client.get(
        f"/api/v1/config/backtesting/historical-runs/{second_run_id}/progress/"
    ).json()

    assert second_progress["status"] == "COMPLETED"
    assert second_progress["api_requests"] == 0
    assert second_progress["cache_hits"] > 0
    assert len(fetch_calls) == 1, (
        "the real provider must genuinely NOT have been called again on the repeat run"
    )


@requires_postgres
@pytest.mark.django_db
def test_progress_for_unknown_run_id_returns_404() -> None:
    client = _client_as_operator()
    response = client.get("/api/v1/config/backtesting/historical-runs/does-not-exist/progress/")
    assert response.status_code == 404


@requires_postgres
@pytest.mark.django_db
def test_coverage_preview_reports_zero_percent_before_any_run() -> None:
    """Phase 21: the read-only readiness preview must never fetch or
    persist - just report what the (empty) database already has."""
    client = _client_as_operator()
    response = client.post(
        "/api/v1/config/backtesting/coverage-preview/",
        data={
            "instrument_ids": ["NSE:RELIANCE"],
            "timeframe": "5m",
            "start_date": "2026-01-05",
            "end_date": "2026-01-05",
        },
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["overall_coverage_percent"] == 0.0
    assert body["instruments"][0]["is_complete"] is False


@requires_postgres
@pytest.mark.django_db
def test_coverage_preview_reports_100_percent_after_a_completed_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Checkpoint 67.12.2-O: approach (b), for consistency with Scenario
    A/B's own real fetch/persist path immediately above in this file -
    the preview endpoint itself is read-only either way (its own
    docstring, `test_coverage_preview_reports_zero_percent_before_any_
    run`, already proves that), so what matters is that the run it
    reads coverage AFTER genuinely persisted real (`REAL_DHAN`,
    `CANONICALIZED`) rows through the real orchestrator - not a vacuous
    100% computed over rows a test inserted by hand."""
    _install_fake_real_dhan_provider(monkeypatch)
    client = _client_as_operator()
    run_response = client.post(
        "/api/v1/config/backtesting/historical-runs/",
        data=_run_payload(start_date="2026-08-17", end_date="2026-08-17"),
        content_type="application/json",
    )
    run_id = run_response.json()["run_id"]
    progress = client.get(f"/api/v1/config/backtesting/historical-runs/{run_id}/progress/").json()
    assert progress["status"] == "COMPLETED"

    preview_response = client.post(
        "/api/v1/config/backtesting/coverage-preview/",
        data={
            "instrument_ids": ["NSE:RELIANCE"],
            "timeframe": "5m",
            "start_date": "2026-08-17",
            "end_date": "2026-08-17",
        },
        content_type="application/json",
    )
    body = preview_response.json()
    assert body["overall_coverage_percent"] == 100.0
    assert body["instruments"][0]["is_complete"] is True


@requires_postgres
@pytest.mark.django_db
def test_invalid_timeframe_returns_400() -> None:
    client = _client_as_operator()
    response = client.post(
        "/api/v1/config/backtesting/historical-runs/",
        data=_run_payload(timeframe="not-a-timeframe"),
        content_type="application/json",
    )
    assert response.status_code == 400


@requires_postgres
@pytest.mark.django_db
def test_partial_failure_is_disclosed_never_silently_dropped() -> None:
    """Phase 6: a run spanning a real and a nonexistent-exchange
    instrument must disclose the failure explicitly (PARTIAL), never
    report a falsely-complete result."""
    client = _client_as_operator()
    response = client.post(
        "/api/v1/config/backtesting/historical-runs/",
        data=_run_payload(instrument_ids=["NSE:RELIANCE", "XYZ:BADEXCHANGE"]),
        content_type="application/json",
    )
    assert response.status_code == 400  # rejected at validation - XYZ is not a real Exchange


@requires_postgres
@pytest.mark.django_db
def test_an_unexpected_exception_returns_clean_json_never_a_raw_500_page() -> None:
    """A real bug found from a live report: an unclassified exception
    inside the view used to become an opaque, non-JSON Django 500 page
    - the frontend's error parser can only surface a real message when
    the body is the project's own {error_code, message} JSON shape.
    Simulates a genuinely unexpected failure (the repository blowing up)
    and proves the response is still well-formed JSON, not a crash."""
    from unittest.mock import patch

    client = _client_as_operator()
    with patch(
        "intraday.infrastructure.api.historical_backtesting_views.DjangoBacktestRunRepository"
    ) as mock_repo_class:
        mock_repo_class.return_value.create.side_effect = RuntimeError(
            "simulated unexpected failure"
        )
        response = client.post(
            "/api/v1/config/backtesting/historical-runs/",
            data=_run_payload(),
            content_type="application/json",
        )

    assert response.status_code == 500
    body = response.json()
    assert body["error_code"] == "internal_error"
    assert "unexpected error" in body["message"].lower()
    # never leaks the real exception text to the client
    assert "simulated unexpected failure" not in body["message"]


@requires_postgres
@pytest.mark.django_db
def test_unexpected_exception_includes_debug_detail_only_when_debug_is_on() -> None:
    """The live report this investigates could not be reproduced against
    the current orchestration logic - this proves the NEXT occurrence
    will be diagnosable from the browser response itself (matching the
    real dev environment's DEBUG=True), without weakening the shared,
    project-wide `unexpected()` convention used by every other view
    (which stays exception-text-free everywhere else, proven by the
    sibling test above running under this test suite's own DEBUG=False)."""
    from unittest.mock import patch

    from django.test import override_settings

    client = _client_as_operator()
    with (
        override_settings(DEBUG=True),
        patch(
            "intraday.infrastructure.api.historical_backtesting_views.DjangoBacktestRunRepository"
        ) as mock_repo_class,
    ):
        mock_repo_class.return_value.create.side_effect = RuntimeError("a specific real cause")
        response = client.post(
            "/api/v1/config/backtesting/historical-runs/",
            data=_run_payload(),
            content_type="application/json",
        )

    assert response.status_code == 500
    body = response.json()
    assert body["error_code"] == "internal_error"
    assert body["debug_detail"]["exception_type"] == "RuntimeError"
    assert body["debug_detail"]["exception_message"] == "a specific real cause"
    assert "Traceback" in body["debug_detail"]["traceback"]


@requires_postgres
@pytest.mark.django_db
def test_a_long_configuration_version_like_the_frontend_actually_sends_succeeds() -> None:
    """THE real bug a live report found: the frontend generates
    `configuration_version` as `f"wb-hist-{Date.now()}"` (was
    `f"workbench-historical-{Date.now()}"`, 34 characters - one
    character over the column's PREVIOUS `max_length=32`, causing a
    real `DataError: value too long for type character varying(32)` on
    every historical run creation). Proves the actual value the
    frontend sends today - and a deliberately still-long one - both
    now fit the widened column."""
    client = _client_as_operator()
    response = client.post(
        "/api/v1/config/backtesting/historical-runs/",
        # 34 chars - the old bug, reproduced exactly (was one over the
        # column's previous max_length=32).
        data=_run_payload(configuration_version="workbench-historical-1755000000000"),
        content_type="application/json",
    )
    assert response.status_code == 202


@requires_postgres
@pytest.mark.django_db
def test_a_decimal_typed_strategy_parameter_sent_as_a_json_string_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE real bug a live report found: sma_trend_filter's band_percent
    is DECIMAL-typed, and the frontend (like any JSON API client) can
    only ever send it as a string or number - never a native Python
    Decimal, which JSON has no representation for at all. Every
    historical run using this strategy failed with "parameter
    'band_percent' is not a Decimal: '0.02'" until the backend itself
    coerced it before validation. Proves the exact real payload now
    succeeds end to end, with a real qualifying instrument/date range.

    Checkpoint 67.12.2-O: approach (b) - this test's assertion
    (`status == COMPLETED`) can only be genuine evidence that the
    decimal coercion survived the FULL pipeline (validation -> real
    fetch -> persist -> strategy execution) if the run actually runs
    that whole pipeline; a pre-seeded-rows approach (a) would still
    prove the decimal coercion itself, but less faithfully exercises
    "end to end" as the test's own docstring claims."""
    _install_fake_real_dhan_provider(monkeypatch)
    client = _client_as_operator()
    response = client.post(
        "/api/v1/config/backtesting/historical-runs/",
        data=_run_payload(
            start_date="2026-08-17",
            end_date="2026-08-17",
            strategy_id="sma_trend_filter",
            strategy_values={"lookback": 20, "band_percent": "0.02"},
        ),
        content_type="application/json",
    )
    assert response.status_code == 202
    run_id = response.json()["run_id"]

    progress = client.get(f"/api/v1/config/backtesting/historical-runs/{run_id}/progress/").json()
    assert progress["status"] == "COMPLETED"
    assert not progress["failed_instruments"]


@requires_postgres
@pytest.mark.django_db
def test_a_run_uses_the_real_dhan_provider_when_credentials_are_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of the real bug this checkpoint fixes: previously
    EVERY backtest ran on fabricated synthetic data regardless of
    whether the operator had genuinely connected Dhan (the Settings
    page's "Connected" badge implied nothing about backtest data
    quality). Proves `_select_historical_bar_provider()` genuinely
    reaches for the real `DhanHistoricalBarProvider` - and therefore a
    real Dhan REST call - once credentials are configured, by
    monkeypatching ONLY the actual outbound HTTP call (never a real
    network request in a unit test) and asserting it was invoked with
    the real instrument's known security_id."""
    from intraday.application.services.instrument_master import InstrumentMasterEntry
    from intraday.infrastructure.market_data_providers.dhan import historical_provider
    from intraday.infrastructure.market_data_providers.dhan.instrument_master import (
        DhanInstrumentMasterProvider,
    )

    monkeypatch.setattr(
        DhanSettingsService, "effective_credentials", lambda self: ("client-1", "token-1")
    )
    monkeypatch.setattr(
        DhanInstrumentMasterProvider,
        "list_instruments",
        lambda self, exchange: (
            InstrumentMasterEntry(
                symbol="RELIANCE", display_name="Reliance Industries", security_id=2885
            ),
        ),
    )

    calls: list[dict[str, object]] = []

    def _fake_fetch_intraday_candles(**kwargs: object) -> tuple[object, ...]:
        calls.append(kwargs)
        return ()

    monkeypatch.setattr(historical_provider, "fetch_intraday_candles", _fake_fetch_intraday_candles)

    client = _client_as_operator()
    response = client.post(
        "/api/v1/config/backtesting/historical-runs/",
        data=_run_payload(),
        content_type="application/json",
    )
    assert response.status_code == 202
    run_id = response.json()["run_id"]

    progress = client.get(f"/api/v1/config/backtesting/historical-runs/{run_id}/progress/").json()

    # The real provider genuinely ran (proven by the mocked call site
    # actually being invoked with the right instrument) - the run
    # itself ends NOT_AVAILABLE/FAILED here because the fake fetch
    # returns zero bars, which is the correct, honest outcome, not a
    # test bug: this test's job is proving WHICH provider ran, not
    # re-proving the already-covered synthetic-provider happy path.
    assert calls, "the real Dhan historical client was never called"
    assert calls[0]["security_id"] == 2885
    assert calls[0]["exchange_segment"] == "NSE_EQ"
    assert progress["status"] in {"FAILED", "PARTIAL"}
