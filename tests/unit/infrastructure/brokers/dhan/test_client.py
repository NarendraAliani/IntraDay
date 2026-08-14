# tests/unit/infrastructure/brokers/dhan/test_client.py
#
# Checkpoint 22: unit coverage for the Dhan read-only connectivity
# client - HTTP status -> ConnectionStatus mapping, and proof it only
# ever calls the documented GET /v2/profile endpoint (never an order/
# trading endpoint). All HTTP calls are mocked - no real network access.
from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

from intraday.infrastructure.brokers.dhan.client import (
    DHAN_PROFILE_ENDPOINT,
    check_dhan_connectivity,
)


def _mock_response(status_code: int) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    return response


def test_success_maps_to_connected() -> None:
    with patch("httpx.get", return_value=_mock_response(200)):
        result = check_dhan_connectivity("client-id", "fake-token")

    assert result.success is True
    assert result.status == "CONNECTED"
    assert result.safe_error == ""


def test_http_401_maps_to_authentication_failed() -> None:
    with patch("httpx.get", return_value=_mock_response(401)):
        result = check_dhan_connectivity("client-id", "fake-bad-token")

    assert result.success is False
    assert result.status == "AUTHENTICATION_FAILED"
    assert "fake-bad-token" not in result.safe_error


def test_http_403_maps_to_token_expired() -> None:
    with patch("httpx.get", return_value=_mock_response(403)):
        result = check_dhan_connectivity("client-id", "fake-token")

    assert result.status == "TOKEN_EXPIRED"


def test_unexpected_status_maps_to_connection_error() -> None:
    with patch("httpx.get", return_value=_mock_response(500)):
        result = check_dhan_connectivity("client-id", "fake-token")

    assert result.status == "CONNECTION_ERROR"


def test_timeout_maps_to_connection_error_and_does_not_raise() -> None:
    with patch("httpx.get", side_effect=httpx.TimeoutException("timed out")):
        result = check_dhan_connectivity("client-id", "fake-token")

    assert result.success is False
    assert result.status == "CONNECTION_ERROR"


def test_network_error_maps_to_connection_error_and_does_not_raise() -> None:
    with patch("httpx.get", side_effect=httpx.ConnectError("unreachable")):
        result = check_dhan_connectivity("client-id", "fake-token")

    assert result.success is False
    assert result.status == "CONNECTION_ERROR"


def test_only_calls_the_documented_profile_endpoint_never_an_order_endpoint() -> None:
    with patch("httpx.get", return_value=_mock_response(200)) as mock_get:
        check_dhan_connectivity("client-id", "fake-token")

    called_url = mock_get.call_args[0][0]
    assert called_url == DHAN_PROFILE_ENDPOINT
    assert "order" not in called_url.lower()
    assert "position" not in called_url.lower()


def test_access_token_is_sent_only_as_a_header_never_in_the_url_or_body() -> None:
    with patch("httpx.get", return_value=_mock_response(200)) as mock_get:
        check_dhan_connectivity("client-id", "fake-secret-token-value")

    url = mock_get.call_args[0][0]
    kwargs = mock_get.call_args[1]
    assert "fake-secret-token-value" not in url
    assert kwargs["headers"]["access-token"] == "fake-secret-token-value"
