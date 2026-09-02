# tests/unit/infrastructure/api/test_backtesting_api.py
#
# Endpoint tests for the Checkpoint 27 backtesting API resource. Mirrors
# test_strategy_configuration_api.py's auth pattern.
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from intraday.application.services.instrument_master import InstrumentMasterEntry
from intraday.application.services.provider_settings import DhanSettingsService
from intraday.domain.session.calendar import build_cas_aware_session_for, instrument_category_for
from intraday.infrastructure.api.permissions import CONFIGURATION_OPERATOR_GROUP
from intraday.infrastructure.market_data_providers.dhan import historical_provider
from intraday.infrastructure.market_data_providers.dhan.historical_client import (
    DhanHistoricalCandle,
)
from intraday.infrastructure.market_data_providers.dhan.instrument_master import (
    DhanInstrumentMasterProvider,
)
from tests.postgres_utils import requires_postgres

READER_USERNAME = "bt-reader"  # noqa: S105
OPERATOR_USERNAME = "bt-operator"  # noqa: S105
PASSWORD = "correct-horse-battery-staple"  # noqa: S105

# Checkpoint 67.12.2-V: this file predates Checkpoint 67.12.2-L's fix to
# `_prepare_if_needed` (which now selects `DhanHistoricalBarProvider`
# whenever real Dhan credentials happen to be reachable, instead of
# always constructing `SyntheticHistoricalBarProvider()`), and had NO
# credential/network mocking of any kind - unlike
# `test_historical_backtesting_api.py` (67.12.2-L/O), which gained an
# autouse `_no_real_dhan_credentials` fixture specifically to prevent
# this. Confirmed as a real, not hypothetical, gap: this file's own
# `test_run_backtest_against_a_real_instrument_is_db_first_not_fixture_only`
# received real 401 responses from `https://api.dhan.co/v2/charts/
# intraday` tonight only because the test DB (a fresh, empty
# `test_intraday` created per run) has no DhanCredential row of its
# own, so `effective_credentials()` fell back to the stale `.env`
# token - NOT because of any test-side guard. A developer with a valid
# `.env` token, or a future CI environment with one configured, would
# make this exact, unmodified test reach the real production Dhan API
# on every ordinary unit-test run. No pytest marker, no
# `conftest.py` fixture, and no network-blocking plugin
# (`pytest-socket` is not a project dependency) already prevented this.
#
# Fixed with the SAME pattern already established and proven in
# `test_historical_backtesting_api.py` - an autouse fixture that always
# stamps deterministic, obviously-fake credentials (never real ones,
# never read from `.env`/the DB), so this file's one test that needs a
# real, non-fixture instrument to reach `COMPLETED` gets a fake
# `fetch_intraday_candles` returning genuinely CAS-aware-shaped data
# instead - proving the DB-first pipeline this test was written for,
# with zero real network reachability, ever.
CAS_ERA_TRADING_DATE = date(2026, 8, 17)


@pytest.fixture(autouse=True)
def _no_real_dhan_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """FAIL-CLOSED default for every test in this file:
    `_select_historical_bar_provider()` sees no credentials and falls
    back to `SyntheticHistoricalBarProvider()`, never a real outbound
    Dhan call - mirrors `test_historical_backtesting_api.py`'s own
    fixture of the same name exactly. `test_run_backtest_against_
    fixture_instrument_still_uses_the_deterministic_fixture` never
    reaches this code path at all (`FIXTURE01` short-circuits
    `_prepare_if_needed` before any provider selection), so this
    fixture cannot affect it."""
    monkeypatch.setattr(DhanSettingsService, "effective_credentials", lambda self: None)


def _real_dhan_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Overrides the autouse no-credentials default with genuine-
    looking (never real) Dhan credentials plus a fake instrument-master
    lookup, so `_select_historical_bar_provider()` genuinely selects
    `DhanHistoricalBarProvider` - exactly
    `test_historical_backtesting_api.py::_real_dhan_credentials`,
    duplicated here rather than imported, matching this test suite's
    existing per-file helper-duplication convention."""
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


def _install_fake_real_dhan_provider(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    """Wires `_real_dhan_credentials` plus a fake
    `fetch_intraday_candles` that returns a genuine, full CAS-era
    trading day (one candle per `HistoricalDataCoverageService`'s own
    expected-timestamp set, via `build_cas_aware_session_for` - the
    SAME machinery, not a re-derived approximation) - the real outbound
    call site (`historical_provider.fetch_intraday_candles`) is the
    ONLY thing monkeypatched; everything downstream (coverage,
    persistence, the research gate) runs for real. Returns the calls
    list so a caller can assert on real call count if needed."""
    _real_dhan_credentials(monkeypatch)
    calls: list[dict[str, object]] = []

    def _fake_fetch_intraday_candles(**kwargs: object) -> tuple[DhanHistoricalCandle, ...]:
        calls.append(kwargs)
        category = instrument_category_for("RELIANCE")
        session = build_cas_aware_session_for(
            category, CAS_ERA_TRADING_DATE, datetime.combine(CAS_ERA_TRADING_DATE, time.max, tzinfo=UTC)
        )
        interval = timedelta(minutes=5)
        closes = session.expected_continuous_bar_timestamps(interval)
        return tuple(
            DhanHistoricalCandle(
                timestamp=close - interval, open=100.0, high=101.0, low=99.0, close=100.5, volume=1000
            )
            for close in closes
        )

    monkeypatch.setattr(historical_provider, "fetch_intraday_candles", _fake_fetch_intraday_candles)
    return calls


def _client_as_reader() -> Client:
    User.objects.create_user(username=READER_USERNAME, password=PASSWORD)
    client = Client()
    assert client.login(username=READER_USERNAME, password=PASSWORD)
    return client


def _client_as_operator() -> Client:
    user = User.objects.create_user(username=OPERATOR_USERNAME, password=PASSWORD)
    group, _ = Group.objects.get_or_create(name=CONFIGURATION_OPERATOR_GROUP)
    user.groups.add(group)
    client = Client()
    assert client.login(username=OPERATOR_USERNAME, password=PASSWORD)
    return client


def _run_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "instrument_id": "NSE:FIXTURE01",
        "timeframe": "5m",
        "start": "2026-01-02T03:00:00Z",
        "end": "2026-01-02T06:00:00Z",
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
def test_run_backtest_requires_operator_role() -> None:
    client = _client_as_reader()
    response = client.post(
        "/api/v1/config/backtesting/run/", data=_run_payload(), content_type="application/json"
    )
    assert response.status_code == 403


@requires_postgres
@pytest.mark.django_db
def test_run_backtest_unknown_strategy_returns_404() -> None:
    client = _client_as_operator()
    response = client.post(
        "/api/v1/config/backtesting/run/",
        data=_run_payload(strategy_id="nonexistent"),
        content_type="application/json",
    )
    assert response.status_code == 404


@requires_postgres
@pytest.mark.django_db
def test_run_backtest_invalid_timeframe_returns_400() -> None:
    client = _client_as_operator()
    response = client.post(
        "/api/v1/config/backtesting/run/",
        data=_run_payload(timeframe="not-a-timeframe"),
        content_type="application/json",
    )
    assert response.status_code == 400


@requires_postgres
@pytest.mark.django_db
def test_run_backtest_then_get_and_list_results() -> None:
    client = _client_as_operator()
    run_response = client.post(
        "/api/v1/config/backtesting/run/", data=_run_payload(), content_type="application/json"
    )
    assert run_response.status_code == 200
    body = run_response.json()
    assert "backtest_id" in body
    assert body["configuration"]["strategy_id"] == "ema_crossover"
    assert "trades" in body and isinstance(body["trades"], list)
    assert "equity_curve" in body
    assert "metrics" in body
    assert body["data_quality"]["data_quality"] == "FIXTURE_OR_HISTORICAL"

    backtest_id = body["backtest_id"]
    get_response = client.get(f"/api/v1/config/backtesting/results/{backtest_id}/")
    assert get_response.status_code == 200
    assert get_response.json()["backtest_id"] == backtest_id

    list_response = client.get("/api/v1/config/backtesting/strategies/ema_crossover/results/")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1


@requires_postgres
@pytest.mark.django_db
def test_get_unknown_backtest_result_returns_404() -> None:
    client = _client_as_reader()
    response = client.get("/api/v1/config/backtesting/results/nonexistent/")
    assert response.status_code == 404


@requires_postgres
@pytest.mark.django_db
def test_rerunning_identical_configuration_upserts_same_backtest_id() -> None:
    client = _client_as_operator()
    first = client.post(
        "/api/v1/config/backtesting/run/", data=_run_payload(), content_type="application/json"
    )
    second = client.post(
        "/api/v1/config/backtesting/run/", data=_run_payload(), content_type="application/json"
    )
    assert first.json()["backtest_id"] == second.json()["backtest_id"]
    list_response = client.get("/api/v1/config/backtesting/strategies/ema_crossover/results/")
    assert len(list_response.json()) == 1  # upsert, not a duplicate row


@requires_postgres
@pytest.mark.django_db
def test_run_backtest_against_a_real_instrument_is_db_first_not_fixture_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Checkpoint 63.x follow-up: debugging the reported "no bars
    available for NSE:FIXTURE01" experience - a real instrument/date
    combination (never seen by the fixture repository at all) must now
    succeed via the same DB-first coverage/fetch/persist pipeline the
    multi-instrument historical-run panel uses, not fail outright.

    Checkpoint 67.12.2-V: this test genuinely needs a completed run
    against a real (non-fixture) instrument, so it opts into the fake
    real-Dhan-provider double rather than relying on this file's
    autouse no-credentials default - the ONLY outbound call site
    (`historical_provider.fetch_intraday_candles`) is monkeypatched,
    never the real network. `len(calls) == 1` is the direct proof this
    test makes exactly one (fake) provider call and zero real ones -
    the real HTTP client (`httpx`/Dhan's own SDK) is never invoked at
    all, so there is nothing for it to reach the network with."""
    calls = _install_fake_real_dhan_provider(monkeypatch)
    client = _client_as_operator()
    response = client.post(
        "/api/v1/config/backtesting/run/",
        data=_run_payload(
            instrument_id="NSE:RELIANCE",
            start="2026-08-17T03:45:00Z",
            end="2026-08-17T10:00:00Z",
        ),
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["data_quality"]["bar_count"] > 0
    assert len(calls) == 1, "expected exactly one fake provider call, zero real network reachability"


@requires_postgres
@pytest.mark.django_db
def test_run_backtest_against_fixture_instrument_still_uses_the_deterministic_fixture() -> None:
    """The FIXTURE01 flow's own reproducibility/cost-model tests depend
    on this staying exactly as it was - never routed through the DB-
    first pipeline."""
    client = _client_as_operator()
    response = client.post(
        "/api/v1/config/backtesting/run/", data=_run_payload(), content_type="application/json"
    )
    assert response.status_code == 200
    assert response.json()["data_quality"]["data_source"] == (
        "HistoricalMarketDataRepository (fixture/historical only)"
    )
