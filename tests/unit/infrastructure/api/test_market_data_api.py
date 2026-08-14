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
    assert body["status"] in ("PRE_OPEN", "OPEN", "CLOSED")
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
