# tests/unit/infrastructure/api/test_market_data_api.py
#
# Checkpoint 23: full vertical-slice API coverage for the read-only live
# market-data endpoints - mirrors test_settings_api.py's own established
# pattern (Checkpoint 22): real Django test Client against the real
# URLconf, requires_postgres-gated, outbound Dhan HTTP mocked at the
# infrastructure client boundary. Every credential value is an
# obviously-fake placeholder.
from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from intraday.infrastructure.api.permissions import CONFIGURATION_OPERATOR_GROUP
from intraday.infrastructure.market_data_providers.dhan.client import (
    DhanAuthenticationError,
    DhanConnectionError,
    DhanQuoteFetchResult,
    DhanQuoteObservation,
)
from intraday.infrastructure.market_data_providers.dhan.instruments import DhanInstrument
from intraday.infrastructure.persistence.provider_settings_repositories import (
    DjangoDhanCredentialRepository,
)
from tests.postgres_utils import requires_postgres

READER_USERNAME = "market_data_reader"  # noqa: S105
OPERATOR_USERNAME = "market_data_operator"  # noqa: S105
PASSWORD = "correct-horse-battery-staple"  # noqa: S105

RELIANCE = DhanInstrument(symbol="RELIANCE", security_id=2885)


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


def _configure_dhan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DHAN_CLIENT_ID", raising=False)
    monkeypatch.delenv("DHAN_ACCESS_TOKEN", raising=False)
    DjangoDhanCredentialRepository().save(
        client_id="1000000123",
        access_token="fake-test-token-not-real",  # noqa: S106
        enabled=True,
        actor="test-setup",
        actor_user_id=1,
        request_id="00000000-0000-0000-0000-000000000000",
    )


# --- Authentication / authorization ----------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_session_requires_authentication() -> None:
    client = Client()

    response = client.get("/api/v1/config/market-data/session/")

    assert response.status_code == 401


@requires_postgres
@pytest.mark.django_db
def test_session_allowed_for_authenticated_reader() -> None:
    client = _client_as_reader()

    response = client.get("/api/v1/config/market-data/session/")

    assert response.status_code == 200
    body = response.json()
    # Checkpoint 39: SessionStatus is now holiday/weekend-aware
    # (CLOSING/HOLIDAY added) - this test runs against the REAL current
    # date, which may genuinely be a weekend or NSE holiday when the
    # suite runs, so every valid status must be accepted here. Fixed-
    # date behavior (e.g. "is 2026-01-26 correctly HOLIDAY") is proven
    # deterministically in tests/unit/domain/session/test_calendar.py
    # instead - this endpoint test only proves the API wires the real
    # session engine through correctly, not a specific status value.
    assert body["status"] in ("PRE_OPEN", "OPEN", "CLOSING", "CLOSED", "HOLIDAY")
    assert body["exchange"] == "NSE"


@requires_postgres
@pytest.mark.django_db
def test_health_allowed_for_authenticated_reader() -> None:
    client = _client_as_reader()

    response = client.get("/api/v1/config/market-data/health/")

    assert response.status_code == 200
    assert response.json()["state"] == "DISCONNECTED"  # never refreshed yet


@requires_postgres
@pytest.mark.django_db
def test_quotes_allowed_for_authenticated_reader_and_empty_before_any_refresh() -> None:
    client = _client_as_reader()

    response = client.get("/api/v1/config/market-data/quotes/")

    assert response.status_code == 200
    assert response.json() == []


@requires_postgres
@pytest.mark.django_db
def test_refresh_forbidden_for_reader_without_operator_capability() -> None:
    client = _client_as_reader()

    response = client.post("/api/v1/config/market-data/refresh/")

    assert response.status_code == 403


# --- Refresh: read-vs-write separation, no live call from GET reads --------


@requires_postgres
@pytest.mark.django_db
def test_reading_session_health_or_quotes_never_calls_dhan() -> None:
    client = _client_as_reader()

    with patch("intraday.infrastructure.api.market_data_views.fetch_quotes") as mock_fetch:
        client.get("/api/v1/config/market-data/session/")
        client.get("/api/v1/config/market-data/health/")
        client.get("/api/v1/config/market-data/quotes/")

    mock_fetch.assert_not_called()


# --- Refresh: unconfigured, success, auth failure, connection failure ------


@requires_postgres
@pytest.mark.django_db
def test_refresh_when_dhan_unconfigured_returns_disconnected_and_calls_no_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DHAN_CLIENT_ID", raising=False)
    monkeypatch.delenv("DHAN_ACCESS_TOKEN", raising=False)
    client = _client_as_operator()

    with patch("intraday.infrastructure.api.market_data_views.fetch_quotes") as mock_fetch:
        response = client.post("/api/v1/config/market-data/refresh/")

    assert response.status_code == 200
    assert response.json()["state"] == "DISCONNECTED"
    mock_fetch.assert_not_called()


@requires_postgres
@pytest.mark.django_db
def test_refresh_success_persists_quotes_and_reports_connected_fresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime
    from decimal import Decimal

    _configure_dhan(monkeypatch)
    client = _client_as_operator()

    fake_result = DhanQuoteFetchResult(
        observations=(
            DhanQuoteObservation(
                instrument=RELIANCE,
                last_price=Decimal("1234.56"),
                source_timestamp=datetime.now(tz=UTC),
                open=None,
                high=None,
                low=None,
                close=None,
            ),
        ),
        fetched_at=datetime.now(tz=UTC),
        latency_ms=100,
    )

    with patch(
        "intraday.infrastructure.api.market_data_views.fetch_quotes", return_value=fake_result
    ) as mock_fetch:
        refresh_response = client.post("/api/v1/config/market-data/refresh/")

    assert refresh_response.status_code == 200
    mock_fetch.assert_called_once()

    quotes_response = client.get("/api/v1/config/market-data/quotes/")
    assert quotes_response.status_code == 200
    body = quotes_response.json()
    assert len(body) == 1
    assert body[0]["symbol"] == "RELIANCE"
    assert body[0]["last_price"] == "1234.5600"


@requires_postgres
@pytest.mark.django_db
def test_refresh_authentication_failure_reports_sanitized_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_dhan(monkeypatch)
    client = _client_as_operator()

    with patch(
        "intraday.infrastructure.api.market_data_views.fetch_quotes",
        side_effect=DhanAuthenticationError("Dhan rejected the configured Client ID/Access Token."),
    ):
        response = client.post("/api/v1/config/market-data/refresh/")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "AUTHENTICATION_FAILED"
    assert "fake-test-token-not-real" not in response.content.decode()


@requires_postgres
@pytest.mark.django_db
def test_refresh_connection_failure_reports_error_state(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_dhan(monkeypatch)
    client = _client_as_operator()

    with patch(
        "intraday.infrastructure.api.market_data_views.fetch_quotes",
        side_effect=DhanConnectionError("Could not reach Dhan."),
    ):
        response = client.post("/api/v1/config/market-data/refresh/")

    assert response.status_code == 200
    assert response.json()["state"] == "ERROR"


@requires_postgres
@pytest.mark.django_db
def test_refresh_is_debounced_within_a_few_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import UTC, datetime

    _configure_dhan(monkeypatch)
    client = _client_as_operator()

    fake_result = DhanQuoteFetchResult(
        observations=(), fetched_at=datetime.now(tz=UTC), latency_ms=50
    )

    with patch(
        "intraday.infrastructure.api.market_data_views.fetch_quotes", return_value=fake_result
    ) as mock_fetch:
        first = client.post("/api/v1/config/market-data/refresh/")
        second = client.post("/api/v1/config/market-data/refresh/")

    assert first.status_code == 200
    assert second.status_code == 429
    mock_fetch.assert_called_once()


# --- Trading safety: never calls an order/position endpoint ----------------


@requires_postgres
@pytest.mark.django_db
def test_refresh_never_imports_or_calls_a_broker_gateway_order_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Static proof, not just a runtime mock assertion: the view module
    that performs the refresh has no import of `domain.broker` or any
    trading_engine module at all."""
    import ast

    import intraday.infrastructure.api.market_data_views as module

    source = module.__file__
    assert source is not None
    with open(source, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())

    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    assert not any("trading_engine" in name for name in imported_modules)
    assert not any("domain.broker" in name for name in imported_modules)
    assert not any("signal_intelligence" in name for name in imported_modules)


# --- Checkpoint 24A: read-only bars endpoint + refresh->aggregation chain --


@requires_postgres
@pytest.mark.django_db
def test_bars_requires_authentication() -> None:
    client = Client()

    response = client.get("/api/v1/config/market-data/bars/")

    assert response.status_code == 401


@requires_postgres
@pytest.mark.django_db
def test_bars_allowed_for_authenticated_reader_and_empty_before_any_refresh() -> None:
    client = _client_as_reader()

    response = client.get("/api/v1/config/market-data/bars/")

    assert response.status_code == 200
    assert response.json() == []


@requires_postgres
@pytest.mark.django_db
def test_reading_bars_never_calls_dhan() -> None:
    client = _client_as_reader()

    with patch("intraday.infrastructure.api.market_data_views.fetch_quotes") as mock_fetch:
        client.get("/api/v1/config/market-data/bars/")

    mock_fetch.assert_not_called()


@requires_postgres
@pytest.mark.django_db
def test_successful_refresh_aggregates_and_persists_bars(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import UTC, datetime
    from decimal import Decimal

    _configure_dhan(monkeypatch)
    client = _client_as_operator()

    fake_result = DhanQuoteFetchResult(
        observations=(
            DhanQuoteObservation(
                instrument=RELIANCE,
                last_price=Decimal("1234.56"),
                source_timestamp=datetime.now(tz=UTC),
                open=None,
                high=None,
                low=None,
                close=None,
            ),
        ),
        fetched_at=datetime.now(tz=UTC),
        latency_ms=100,
    )

    with patch(
        "intraday.infrastructure.api.market_data_views.fetch_quotes", return_value=fake_result
    ):
        refresh_response = client.post("/api/v1/config/market-data/refresh/")
    assert refresh_response.status_code == 200

    bars_response = client.get("/api/v1/config/market-data/bars/")
    assert bars_response.status_code == 200
    body = bars_response.json()
    assert len(body) == 1
    assert body[0]["symbol"] == "RELIANCE"
    assert body[0]["status"] in ("FORMING", "CLOSED")
    assert body[0]["timeframe"] == "1m"


@requires_postgres
@pytest.mark.django_db
def test_bars_endpoint_filters_by_symbol(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import UTC, datetime
    from decimal import Decimal

    _configure_dhan(monkeypatch)
    client = _client_as_operator()
    tcs = DhanInstrument(symbol="TCS", security_id=11536)

    fake_result = DhanQuoteFetchResult(
        observations=(
            DhanQuoteObservation(
                instrument=RELIANCE,
                last_price=Decimal("1234.56"),
                source_timestamp=datetime.now(tz=UTC),
                open=None,
                high=None,
                low=None,
                close=None,
            ),
            DhanQuoteObservation(
                instrument=tcs,
                last_price=Decimal("3456.78"),
                source_timestamp=datetime.now(tz=UTC),
                open=None,
                high=None,
                low=None,
                close=None,
            ),
        ),
        fetched_at=datetime.now(tz=UTC),
        latency_ms=100,
    )

    with patch(
        "intraday.infrastructure.api.market_data_views.fetch_quotes", return_value=fake_result
    ):
        client.post("/api/v1/config/market-data/refresh/")

    response = client.get("/api/v1/config/market-data/bars/?symbol=TCS")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["symbol"] == "TCS"


@requires_postgres
@pytest.mark.django_db
def test_bar_aggregation_failure_never_masks_a_successful_refresh_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bug in bar aggregation must never make the refresh endpoint
    itself report failure - the quote fetch/save already succeeded and
    that must remain the reported outcome."""
    from datetime import UTC, datetime
    from decimal import Decimal

    _configure_dhan(monkeypatch)
    client = _client_as_operator()

    fake_result = DhanQuoteFetchResult(
        observations=(
            DhanQuoteObservation(
                instrument=RELIANCE,
                last_price=Decimal("1234.56"),
                source_timestamp=datetime.now(tz=UTC),
                open=None,
                high=None,
                low=None,
                close=None,
            ),
        ),
        fetched_at=datetime.now(tz=UTC),
        latency_ms=100,
    )

    with (
        patch(
            "intraday.infrastructure.api.market_data_views.fetch_quotes",
            return_value=fake_result,
        ),
        patch(
            "intraday.infrastructure.api.market_data_views._bar_service",
            side_effect=RuntimeError("simulated aggregation bug"),
        ),
    ):
        response = client.post("/api/v1/config/market-data/refresh/")

    assert response.status_code == 200
    body = response.json()
    # The refresh (quote fetch/save) itself genuinely succeeded - the
    # health state must reflect that, never a failure state, regardless
    # of the simulated aggregation bug above. Deliberately NOT asserting
    # an exact state like "CONNECTED_FRESH": that would make this test's
    # result depend on the real wall-clock market session at whatever
    # instant it happens to run (a pre-existing defect this fix
    # corrects - found because the suite was run outside NSE market
    # hours, surfacing that MARKET_CLOSED is an equally legitimate,
    # equally non-failure outcome the original assertion didn't allow
    # for). A failure state here would mean the exception thrown after
    # the successful save incorrectly overwrote that success.
    assert body["state"] not in (
        "AUTHENTICATION_FAILED",
        "ERROR",
        "DISCONNECTED",
    )
    assert body["last_success_at"] is not None
    assert body["consecutive_failures"] == 0


@requires_postgres
@pytest.mark.django_db
def test_bars_endpoint_never_leaks_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import UTC, datetime
    from decimal import Decimal

    _configure_dhan(monkeypatch)
    client = _client_as_operator()

    fake_result = DhanQuoteFetchResult(
        observations=(
            DhanQuoteObservation(
                instrument=RELIANCE,
                last_price=Decimal("1234.56"),
                source_timestamp=datetime.now(tz=UTC),
                open=None,
                high=None,
                low=None,
                close=None,
            ),
        ),
        fetched_at=datetime.now(tz=UTC),
        latency_ms=100,
    )
    with patch(
        "intraday.infrastructure.api.market_data_views.fetch_quotes", return_value=fake_result
    ):
        client.post("/api/v1/config/market-data/refresh/")

    response = client.get("/api/v1/config/market-data/bars/")

    assert "fake-test-token-not-real" not in response.content.decode()


@requires_postgres
@pytest.mark.django_db
def test_recent_bars_never_imports_trading_or_signal_code() -> None:
    import ast

    import intraday.infrastructure.api.market_data_views as module

    source = module.__file__
    assert source is not None
    with open(source, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())

    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    assert not any("trading_engine" in name for name in imported_modules)
    assert not any("signal_intelligence" in name for name in imported_modules)


@requires_postgres
@pytest.mark.django_db
def test_list_instruments_returns_real_symbols_from_the_scrip_master() -> None:
    """Follow-up to Checkpoint 63.x: proves the endpoint returns the
    provider's real symbols (never the caller's own free text), with an
    explicit data_source disclosure."""
    client = _client_as_reader()
    with patch(
        "intraday.infrastructure.api.market_data_views.DhanInstrumentMasterProvider"
    ) as mock_provider_class:
        mock_provider_class.return_value.list_symbols.return_value = ("RELIANCE", "TCS")
        response = client.get("/api/v1/config/market-data/instruments/?exchange=NSE")

    assert response.status_code == 200
    body = response.json()
    assert body["exchange"] == "NSE"
    assert body["instrument_ids"] == ["NSE:RELIANCE", "NSE:TCS"]
    assert body["data_source"] == "DHAN_SCRIP_MASTER"


@requires_postgres
@pytest.mark.django_db
def test_list_instruments_degrades_honestly_when_the_scrip_master_is_unavailable() -> None:
    """Never a 500, never a silently-empty-but-labeled-success list -
    the failure is explicit in the response body."""
    from intraday.infrastructure.market_data_providers.dhan.instrument_master import (
        InstrumentMasterUnavailableError,
    )

    client = _client_as_reader()
    with patch(
        "intraday.infrastructure.api.market_data_views.DhanInstrumentMasterProvider"
    ) as mock_provider_class:
        mock_provider_class.return_value.list_symbols.side_effect = (
            InstrumentMasterUnavailableError("network unreachable")
        )
        response = client.get("/api/v1/config/market-data/instruments/?exchange=NSE")

    assert response.status_code == 200
    body = response.json()
    assert body["instrument_ids"] == []
    assert body["data_source"] == "UNAVAILABLE"


@requires_postgres
@pytest.mark.django_db
def test_list_instruments_rejects_an_unknown_exchange() -> None:
    client = _client_as_reader()
    response = client.get("/api/v1/config/market-data/instruments/?exchange=XYZ")
    assert response.status_code == 400
