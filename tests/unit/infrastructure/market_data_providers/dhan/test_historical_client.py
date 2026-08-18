# tests/unit/infrastructure/market_data_providers/dhan/test_historical_client.py
#
# Unit coverage for the real Dhan historical-candle REST client - HTTP
# status/shape -> typed exception mapping, parallel-array -> candle
# parsing, and the intraday >90-day chunking. All HTTP calls are
# mocked - no real network access, no real credential anywhere in this
# file (mirrors `test_client.py`'s own discipline).
from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

import pytest

from intraday.infrastructure.market_data_providers.dhan.historical_client import (
    DHAN_DAILY_HISTORICAL_ENDPOINT,
    DHAN_INTRADAY_HISTORICAL_ENDPOINT,
    DhanHistoricalAuthenticationError,
    DhanHistoricalConnectionError,
    DhanHistoricalMalformedResponseError,
    fetch_daily_candles,
    fetch_intraday_candles,
)


def _mock_response(status_code: int, json_body: object = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body
    return response


def _valid_body() -> dict[str, object]:
    return {
        "open": [100.0, 101.0],
        "high": [102.0, 103.0],
        "low": [99.0, 100.0],
        "close": [101.0, 102.0],
        "volume": [1000, 1100],
        "timestamp": [1704067200, 1704153600],  # 2024-01-01, 2024-01-02 UTC midnight
    }


def test_daily_candles_parse_from_the_documented_parallel_array_shape() -> None:
    with patch("httpx.post", return_value=_mock_response(200, _valid_body())):
        candles = fetch_daily_candles(
            client_id="fake-client-id",
            access_token="fake-token",
            security_id=2885,
            exchange_segment="NSE_EQ",
            from_date=date(2024, 1, 1),
            to_date=date(2024, 1, 2),
        )

    assert len(candles) == 2
    assert candles[0].open == 100.0
    assert candles[0].timestamp == datetime(2024, 1, 1, tzinfo=UTC)
    assert candles[1].close == 102.0


def test_daily_candles_call_the_documented_endpoint_with_the_documented_body() -> None:
    with patch("httpx.post", return_value=_mock_response(200, _valid_body())) as mock_post:
        fetch_daily_candles(
            client_id="fake-client-id",
            access_token="fake-token",
            security_id=2885,
            exchange_segment="NSE_EQ",
            from_date=date(2024, 1, 1),
            to_date=date(2024, 1, 2),
        )

    args, kwargs = mock_post.call_args
    assert args[0] == DHAN_DAILY_HISTORICAL_ENDPOINT
    assert kwargs["json"] == {
        "securityId": "2885",
        "exchangeSegment": "NSE_EQ",
        "instrument": "EQUITY",
        "fromDate": "2024-01-01",
        "toDate": "2024-01-02",
    }
    assert kwargs["headers"]["access-token"] == "fake-token"
    assert kwargs["headers"]["client-id"] == "fake-client-id"


def test_authentication_error_maps_401() -> None:
    with (
        patch("httpx.post", return_value=_mock_response(401)),
        pytest.raises(DhanHistoricalAuthenticationError),
    ):
        fetch_daily_candles(
            client_id="x",
            access_token="x",
            security_id=1,
            exchange_segment="NSE_EQ",
            from_date=date(2024, 1, 1),
            to_date=date(2024, 1, 2),
        )


def test_unexpected_status_maps_to_connection_error() -> None:
    with (
        patch("httpx.post", return_value=_mock_response(500)),
        pytest.raises(DhanHistoricalConnectionError),
    ):
        fetch_daily_candles(
            client_id="x",
            access_token="x",
            security_id=1,
            exchange_segment="NSE_EQ",
            from_date=date(2024, 1, 1),
            to_date=date(2024, 1, 2),
        )


def test_mismatched_array_lengths_raise_malformed_response() -> None:
    body = _valid_body()
    body["open"] = [100.0]  # now shorter than the other arrays
    with (
        patch("httpx.post", return_value=_mock_response(200, body)),
        pytest.raises(DhanHistoricalMalformedResponseError),
    ):
        fetch_daily_candles(
            client_id="x",
            access_token="x",
            security_id=1,
            exchange_segment="NSE_EQ",
            from_date=date(2024, 1, 1),
            to_date=date(2024, 1, 2),
        )


def test_missing_expected_field_raises_malformed_response() -> None:
    with (
        patch("httpx.post", return_value=_mock_response(200, {"open": []})),
        pytest.raises(DhanHistoricalMalformedResponseError),
    ):
        fetch_daily_candles(
            client_id="x",
            access_token="x",
            security_id=1,
            exchange_segment="NSE_EQ",
            from_date=date(2024, 1, 1),
            to_date=date(2024, 1, 2),
        )


def test_intraday_candles_use_the_documented_endpoint_and_interval() -> None:
    with patch("httpx.post", return_value=_mock_response(200, _valid_body())) as mock_post:
        candles = fetch_intraday_candles(
            client_id="fake-client-id",
            access_token="fake-token",
            security_id=2885,
            exchange_segment="NSE_EQ",
            interval_minutes=5,
            from_time=datetime(2024, 1, 1, 9, 15),
            to_time=datetime(2024, 1, 1, 15, 30),
        )

    assert len(candles) == 2
    args, kwargs = mock_post.call_args
    assert args[0] == DHAN_INTRADAY_HISTORICAL_ENDPOINT
    assert kwargs["json"]["interval"] == "5"
    assert kwargs["json"]["fromDate"] == "2024-01-01 09:15:00"
    assert kwargs["json"]["toDate"] == "2024-01-01 15:30:00"


def test_intraday_candles_chunk_a_range_longer_than_90_days_into_multiple_requests() -> None:
    with patch("httpx.post", return_value=_mock_response(200, _valid_body())) as mock_post:
        fetch_intraday_candles(
            client_id="fake-client-id",
            access_token="fake-token",
            security_id=2885,
            exchange_segment="NSE_EQ",
            interval_minutes=1,
            from_time=datetime(2024, 1, 1, 0, 0, 0),
            to_time=datetime(2024, 6, 1, 0, 0, 0),  # ~152 days > 90-day limit
        )

    assert mock_post.call_count == 2  # two <=90-day windows
