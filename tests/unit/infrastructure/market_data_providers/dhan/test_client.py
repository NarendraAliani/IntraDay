# tests/unit/infrastructure/market_data_providers/dhan/test_client.py
#
# Checkpoint 23: unit coverage for the read-only Dhan market-quote
# client - HTTP status/shape -> typed exception mapping, timestamp
# normalization, and proof it only ever calls the documented quote
# endpoint. All HTTP calls are mocked - no real network access, no real
# credential anywhere in this file (every value is an obviously-fake
# placeholder).
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import httpx
import pytest

from intraday.infrastructure.market_data_providers.dhan.client import (
    DHAN_QUOTE_ENDPOINT,
    DhanAuthenticationError,
    DhanConnectionError,
    DhanMalformedResponseError,
    fetch_quotes,
)
from intraday.infrastructure.market_data_providers.dhan.instruments import DhanInstrument

RELIANCE = DhanInstrument(symbol="RELIANCE", security_id=2885)
TCS = DhanInstrument(symbol="TCS", security_id=11536)


def _mock_response(status_code: int, json_body: object = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body
    return response


def _valid_body(security_id: int, last_price: float, last_trade_time: str) -> dict[str, object]:
    return {
        "data": {
            "NSE_EQ": {
                str(security_id): {
                    "last_price": last_price,
                    "last_trade_time": last_trade_time,
                    "ohlc": {"open": 100.0, "high": 105.0, "low": 99.0, "close": 101.0},
                }
            }
        },
        "status": "success",
    }


def test_valid_response_parses_into_observations() -> None:
    body = _valid_body(2885, 1234.56, "14/08/2026 12:30:00")
    with patch("httpx.post", return_value=_mock_response(200, body)):
        result = fetch_quotes(
            client_id="fake-client-id", access_token="fake-token", instruments=(RELIANCE,)
        )

    assert len(result.observations) == 1
    observation = result.observations[0]
    assert observation.instrument.symbol == "RELIANCE"
    assert observation.last_price == Decimal("1234.56")
    assert observation.open == Decimal("100.0")


def test_source_timestamp_converted_from_ist_to_utc() -> None:
    # 12:30:00 IST == 07:00:00 UTC
    body = _valid_body(2885, 1234.56, "14/08/2026 12:30:00")
    with patch("httpx.post", return_value=_mock_response(200, body)):
        result = fetch_quotes(
            client_id="fake-client-id", access_token="fake-token", instruments=(RELIANCE,)
        )

    assert result.observations[0].source_timestamp == datetime(2026, 8, 14, 7, 0, tzinfo=UTC)


def test_dhan_placeholder_no_trade_timestamp_falls_back_to_fetch_instant() -> None:
    """Dhan's own documented placeholder for "no trade yet today"."""
    body = _valid_body(2885, 1234.56, "01/01/1980 00:00:00")
    with patch("httpx.post", return_value=_mock_response(200, body)):
        result = fetch_quotes(
            client_id="fake-client-id", access_token="fake-token", instruments=(RELIANCE,)
        )

    # Falls back to "now," not the 1980 placeholder.
    assert result.observations[0].source_timestamp.year >= 2026


def test_http_401_raises_authentication_error() -> None:
    with (
        patch("httpx.post", return_value=_mock_response(401)),
        pytest.raises(DhanAuthenticationError),
    ):
        fetch_quotes(
            client_id="fake-client-id", access_token="fake-bad-token", instruments=(RELIANCE,)
        )


def test_http_403_raises_authentication_error() -> None:
    with (
        patch("httpx.post", return_value=_mock_response(403)),
        pytest.raises(DhanAuthenticationError),
    ):
        fetch_quotes(client_id="fake-client-id", access_token="fake-token", instruments=(RELIANCE,))


def test_unexpected_status_raises_connection_error() -> None:
    with patch("httpx.post", return_value=_mock_response(500)), pytest.raises(DhanConnectionError):
        fetch_quotes(client_id="fake-client-id", access_token="fake-token", instruments=(RELIANCE,))


def test_timeout_raises_connection_error_not_a_raw_httpx_exception() -> None:
    with (
        patch("httpx.post", side_effect=httpx.TimeoutException("timed out")),
        pytest.raises(DhanConnectionError),
    ):
        fetch_quotes(client_id="fake-client-id", access_token="fake-token", instruments=(RELIANCE,))


def test_network_error_raises_connection_error() -> None:
    with (
        patch("httpx.post", side_effect=httpx.ConnectError("unreachable")),
        pytest.raises(DhanConnectionError),
    ):
        fetch_quotes(client_id="fake-client-id", access_token="fake-token", instruments=(RELIANCE,))


def test_malformed_json_raises_malformed_response_error() -> None:
    response = MagicMock()
    response.status_code = 200
    response.json.side_effect = ValueError("not json")
    with patch("httpx.post", return_value=response), pytest.raises(DhanMalformedResponseError):
        fetch_quotes(client_id="fake-client-id", access_token="fake-token", instruments=(RELIANCE,))


def test_missing_segment_key_raises_malformed_response_error() -> None:
    body = {"data": {}, "status": "success"}
    with (
        patch("httpx.post", return_value=_mock_response(200, body)),
        pytest.raises(DhanMalformedResponseError),
    ):
        fetch_quotes(client_id="fake-client-id", access_token="fake-token", instruments=(RELIANCE,))


def test_non_positive_last_price_raises_malformed_response_error() -> None:
    body = _valid_body(2885, -5.0, "14/08/2026 12:30:00")
    with (
        patch("httpx.post", return_value=_mock_response(200, body)),
        pytest.raises(DhanMalformedResponseError),
    ):
        fetch_quotes(client_id="fake-client-id", access_token="fake-token", instruments=(RELIANCE,))


def test_only_calls_the_documented_quote_endpoint_never_an_order_endpoint() -> None:
    body = _valid_body(2885, 1234.56, "14/08/2026 12:30:00")
    with patch("httpx.post", return_value=_mock_response(200, body)) as mock_post:
        fetch_quotes(client_id="fake-client-id", access_token="fake-token", instruments=(RELIANCE,))

    called_url = mock_post.call_args[0][0]
    assert called_url == DHAN_QUOTE_ENDPOINT
    assert "order" not in called_url.lower()
    assert "position" not in called_url.lower()


def test_access_token_is_sent_only_as_a_header_never_in_the_body() -> None:
    body = _valid_body(2885, 1234.56, "14/08/2026 12:30:00")
    with patch("httpx.post", return_value=_mock_response(200, body)) as mock_post:
        fetch_quotes(
            client_id="fake-client-id",
            access_token="fake-secret-token-value",
            instruments=(RELIANCE,),
        )

    kwargs = mock_post.call_args[1]
    assert kwargs["headers"]["access-token"] == "fake-secret-token-value"
    assert "fake-secret-token-value" not in str(kwargs["json"])


def test_multiple_instruments_all_parsed() -> None:
    body: dict[str, object] = {
        "data": {
            "NSE_EQ": {
                "2885": {
                    "last_price": 1234.56,
                    "last_trade_time": "14/08/2026 12:30:00",
                },
                "11536": {
                    "last_price": 3456.78,
                    "last_trade_time": "14/08/2026 12:30:05",
                },
            }
        },
        "status": "success",
    }
    with patch("httpx.post", return_value=_mock_response(200, body)):
        result = fetch_quotes(
            client_id="fake-client-id", access_token="fake-token", instruments=(RELIANCE, TCS)
        )

    symbols = {observation.instrument.symbol for observation in result.observations}
    assert symbols == {"RELIANCE", "TCS"}
