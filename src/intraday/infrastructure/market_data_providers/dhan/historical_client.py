# File: src/intraday/infrastructure/market_data_providers/dhan/historical_client.py
#
# Real Dhan historical-candle REST client - the piece
# `synthetic_historical.py`'s own docstring named as the gap ("Building
# a genuine Dhan historical-candle REST adapter is real, separate
# broker-integration work... that this checkpoint's PoC scope does not
# include"). Closes it.
#
# ---------------------------------------------------------------------------
# Authoritative source (fetched directly from Dhan's own official
# documentation, https://dhanhq.co/docs/v2/historical-data/ - never
# invented, mirroring `client.py`'s own "confirmed via direct research"
# discipline)
# ---------------------------------------------------------------------------
# Daily Historical Charts API
#   URL:      POST https://api.dhan.co/v2/charts/historical
#   Headers:  access-token: {JWT}, client-id: {Client ID},
#             Content-Type: application/json
#   Body:     {"securityId": str, "exchangeSegment": str,
#              "instrument": "EQUITY", "fromDate": "YYYY-MM-DD",
#              "toDate": "YYYY-MM-DD"}
#   Response: {"open": [float,...], "high": [...], "low": [...],
#              "close": [...], "volume": [int,...],
#              "timestamp": [int,...]}  - parallel arrays, one entry per
#              bar; timestamp is Unix epoch SECONDS.
#
# Intraday Historical Charts API
#   URL:      POST https://api.dhan.co/v2/charts/intraday
#   Headers:  access-token: {JWT}, client-id: {Client ID},
#             Content-Type: application/json, Accept: application/json
#   Body:     {"securityId": str, "exchangeSegment": str,
#              "instrument": "EQUITY", "interval": "1"|"5"|"15"|"25"|"60",
#              "fromDate": "YYYY-MM-DD HH:MM:SS",
#              "toDate": "YYYY-MM-DD HH:MM:SS"}
#   Response: same parallel-array shape as the daily endpoint.
#   Documented limit: max 90 days of data per single request - this
#   client chunks a longer range into <=90-day windows itself, so
#   callers never have to know about that limit.
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

DHAN_DAILY_HISTORICAL_ENDPOINT = "https://api.dhan.co/v2/charts/historical"
DHAN_INTRADAY_HISTORICAL_ENDPOINT = "https://api.dhan.co/v2/charts/intraday"
_REQUEST_TIMEOUT_SECONDS = 30.0
_EQUITY_INSTRUMENT = "EQUITY"
_INTRADAY_MAX_WINDOW_DAYS = 90
_INDIA_STANDARD_TIME = ZoneInfo("Asia/Kolkata")
# Checkpoint 65.25 diagnostic finding: Dhan's `/v2/charts/intraday`
# `fromDate`/`toDate` fields are documented as plain "YYYY-MM-DD HH:MM:SS"
# strings with no timezone marker - Dhan interprets that wall-clock time
# as IST (it is an India-only broker; there is no other sensible
# reading). This client's `from_time`/`to_time` are UTC-aware `datetime`s
# (the domain layer's `ensure_utc` contract everywhere else); formatting
# them with a bare `.strftime(...)` printed the raw UTC clock digits
# with no IST conversion, silently asking Dhan for a session-start-hours
# window instead of the intended one. Proved conclusively this
# checkpoint by making the identical raw REST call both ways for
# RELIANCE/2026-08-28/1m: the un-converted request returned only 45 raw
# candles (03:45-04:29 UTC = 09:15-09:59 IST - exactly the ~44-bar
# truncation seen in every prior ingestion batch); the IST-converted
# request for the *same* UTC window returned 358 raw candles. Converting
# to IST before formatting is therefore the fix, not a workaround.


class DhanHistoricalDataError(Exception):
    """Base class for every non-2xx/malformed outcome this client
    translates - mirrors `client.py`'s own `DhanMarketQuoteError`
    hierarchy so callers handle both Dhan clients the same way."""


class DhanHistoricalAuthenticationError(DhanHistoricalDataError):
    """The configured Dhan credentials were rejected (HTTP 401/403)."""


class DhanHistoricalConnectionError(DhanHistoricalDataError):
    """Network failure, timeout, or an unexpected non-2xx status."""


class DhanHistoricalMalformedResponseError(DhanHistoricalDataError):
    """The response was 2xx but did not match the documented parallel-
    array shape - never silently treated as "no data.\" """


@dataclass(frozen=True, slots=True)
class DhanHistoricalCandle:
    """One raw (still Dhan-shaped) OHLCV candle - domain `Bar`
    conversion happens one layer up, in `dhan_historical_provider.py`,
    the same separation `DhanQuoteObservation` uses for live quotes."""

    timestamp: datetime  # UTC
    open: float
    high: float
    low: float
    close: float
    volume: int


def _headers(*, client_id: str, access_token: str) -> dict[str, str]:
    return {
        "access-token": access_token,
        "client-id": client_id,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _post(
    url: str, *, client_id: str, access_token: str, body: Mapping[str, object]
) -> dict[str, object]:
    try:
        response = httpx.post(
            url,
            headers=_headers(client_id=client_id, access_token=access_token),
            json=body,
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException as exc:
        raise DhanHistoricalConnectionError("Connection to Dhan timed out.") from exc
    except httpx.HTTPError as exc:
        raise DhanHistoricalConnectionError("Could not reach Dhan.") from exc

    if response.status_code in (401, 403):
        raise DhanHistoricalAuthenticationError(
            "Dhan rejected the configured Client ID/Access Token."
        )
    if response.status_code != 200:
        raise DhanHistoricalConnectionError(
            f"Dhan returned an unexpected response (HTTP {response.status_code})."
        )
    try:
        return response.json()  # type: ignore[no-any-return]
    except ValueError as exc:
        raise DhanHistoricalMalformedResponseError("Dhan's response was not valid JSON.") from exc


def _candles_from_payload(payload: Mapping[str, object]) -> tuple[DhanHistoricalCandle, ...]:
    try:
        opens = list(payload["open"])  # type: ignore[call-overload]
        highs = list(payload["high"])  # type: ignore[call-overload]
        lows = list(payload["low"])  # type: ignore[call-overload]
        closes = list(payload["close"])  # type: ignore[call-overload]
        volumes = list(payload["volume"])  # type: ignore[call-overload]
        timestamps = list(payload["timestamp"])  # type: ignore[call-overload]
        lengths = {len(opens), len(highs), len(lows), len(closes), len(volumes), len(timestamps)}
        if len(lengths) != 1:
            raise DhanHistoricalMalformedResponseError(
                "Dhan's historical response arrays were not all the same length."
            )
        return tuple(
            DhanHistoricalCandle(
                timestamp=datetime.fromtimestamp(int(timestamps[i]), tz=UTC),
                open=float(opens[i]),
                high=float(highs[i]),
                low=float(lows[i]),
                close=float(closes[i]),
                volume=int(volumes[i]),
            )
            for i in range(len(timestamps))
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DhanHistoricalMalformedResponseError(
            "Dhan's historical response did not match the documented shape."
        ) from exc


def fetch_daily_candles(
    *,
    client_id: str,
    access_token: str,
    security_id: int,
    exchange_segment: str,
    from_date: date,
    to_date: date,
) -> tuple[DhanHistoricalCandle, ...]:
    """One `POST /v2/charts/historical` call - one bar per trading day."""
    body = {
        "securityId": str(security_id),
        "exchangeSegment": exchange_segment,
        "instrument": _EQUITY_INSTRUMENT,
        "fromDate": from_date.isoformat(),
        "toDate": to_date.isoformat(),
    }
    payload = _post(
        DHAN_DAILY_HISTORICAL_ENDPOINT, client_id=client_id, access_token=access_token, body=body
    )
    return _candles_from_payload(payload)


def fetch_intraday_candles(
    *,
    client_id: str,
    access_token: str,
    security_id: int,
    exchange_segment: str,
    interval_minutes: int,
    from_time: datetime,
    to_time: datetime,
) -> tuple[DhanHistoricalCandle, ...]:
    """One or more `POST /v2/charts/intraday` calls, transparently
    chunked into <=90-day windows (Dhan's own documented per-request
    limit) so a caller can request an arbitrarily long range."""
    candles: list[DhanHistoricalCandle] = []
    window_start = from_time
    while window_start < to_time:
        window_end = min(window_start + timedelta(days=_INTRADAY_MAX_WINDOW_DAYS), to_time)
        body = {
            "securityId": str(security_id),
            "exchangeSegment": exchange_segment,
            "instrument": _EQUITY_INSTRUMENT,
            "interval": str(interval_minutes),
            "fromDate": window_start.astimezone(_INDIA_STANDARD_TIME).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "toDate": window_end.astimezone(_INDIA_STANDARD_TIME).strftime("%Y-%m-%d %H:%M:%S"),
        }
        payload = _post(
            DHAN_INTRADAY_HISTORICAL_ENDPOINT,
            client_id=client_id,
            access_token=access_token,
            body=body,
        )
        candles.extend(_candles_from_payload(payload))
        window_start = window_end
    return tuple(candles)


__all__ = [
    "DhanHistoricalCandle",
    "DhanHistoricalDataError",
    "DhanHistoricalAuthenticationError",
    "DhanHistoricalConnectionError",
    "DhanHistoricalMalformedResponseError",
    "fetch_daily_candles",
    "fetch_intraday_candles",
    "DHAN_DAILY_HISTORICAL_ENDPOINT",
    "DHAN_INTRADAY_HISTORICAL_ENDPOINT",
]
