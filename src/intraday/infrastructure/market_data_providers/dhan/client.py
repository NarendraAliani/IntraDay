# File: src/intraday/infrastructure/market_data_providers/dhan/client.py
#
# Checkpoint 23: read-only live market-quote client. Calls exactly one
# Dhan endpoint - `POST /v2/marketfeed/quote` (the Market Quote API's
# "full quote" variant, confirmed via direct research of Dhan's own
# official documentation during this checkpoint - chosen over the
# narrower `/marketfeed/ltp` because it is the only variant that
# includes `last_trade_time`, this checkpoint's required SOURCE
# timestamp - Checkpoint 23 §6's "preserve source timestamps... never
# leak Dhan-specific concepts into domain/").
#
# ---------------------------------------------------------------------------
# Why REST polling, not WebSocket (Checkpoint 23 §6's explicit "choose the
# approach... and explain the decision")
# ---------------------------------------------------------------------------
# See docs/architecture/LIVE_MARKET_DATA_ARCHITECTURE.md for the full
# reasoning; summarized here: this Django/WSGI application has no
# already-running persistent process a WebSocket client could safely
# live inside (the ASGI entrypoint - asgi.py - is an unused Checkpoint-1
# stub, and no Celery worker/beat schedule exists yet in this
# repository). Introducing one now, purely to support Checkpoint 23,
# would mean building brand-new long-lived-process infrastructure under
# a checkpoint explicitly scoped to "the smallest production-safe
# implementation." A single-shot, rate-limited, explicit-trigger REST
# call is the smaller, safer, more testable increment - and Dhan's own
# documented rate limit (1000 instruments per request, 1 request/second)
# comfortably accommodates this checkpoint's four-symbol universe.
#
# ---------------------------------------------------------------------------
# Authoritative source (confirmed via direct research of Dhan's official
# documentation during this checkpoint - never invented)
# ---------------------------------------------------------------------------
#   URL:      https://api.dhan.co/v2/marketfeed/quote
#   Method:   POST
#   Headers:  access-token: {JWT}, client-id: {Client ID},
#             Content-Type: application/json, Accept: application/json
#   Body:     {"NSE_EQ": [<security_id>, ...]}  (up to 1000 instruments)
#   Rate limit: 1 request/second (Dhan's own documented limit)
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import httpx

from intraday.domain.session.calendar import INDIA_STANDARD_TIME
from intraday.infrastructure.market_data_providers.dhan.instruments import (
    NSE_EQ_SEGMENT,
    DhanInstrument,
)

DHAN_QUOTE_ENDPOINT = "https://api.dhan.co/v2/marketfeed/quote"
_REQUEST_TIMEOUT_SECONDS = 10.0


class DhanMarketQuoteError(Exception):
    """Base class for every non-2xx/malformed outcome this client
    translates - callers never need to catch a raw `httpx` exception or
    parse a raw response body themselves."""


class DhanAuthenticationError(DhanMarketQuoteError):
    """The configured Dhan credentials were rejected (HTTP 401/403)."""


class DhanConnectionError(DhanMarketQuoteError):
    """Network failure, timeout, or an unexpected non-2xx status."""


class DhanMalformedResponseError(DhanMarketQuoteError):
    """The response was 2xx but did not match the documented shape -
    never silently treated as "no data," always surfaced explicitly
    (mirrors `domain/market_data/quality.py`'s "reject, never silently
    reorder/drop" policy at this checkpoint's own infrastructure
    boundary)."""


@dataclass(frozen=True, slots=True)
class DhanQuoteObservation:
    """One instrument's raw (but already-typed) observation from Dhan -
    still Dhan-shaped (security_id, not InstrumentId) - normalization
    into the domain `Quote` contract happens one layer up in
    `application/services/live_market_data.py`, which has both this
    type and `DhanInstrument`'s symbol available to build a proper
    `InstrumentId`."""

    instrument: DhanInstrument
    last_price: Decimal
    source_timestamp: datetime  # UTC - converted from Dhan's IST last_trade_time
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None


@dataclass(frozen=True, slots=True)
class DhanQuoteFetchResult:
    observations: tuple[DhanQuoteObservation, ...]
    fetched_at: datetime  # UTC, this process's own clock
    latency_ms: int


def fetch_quotes(
    *, client_id: str, access_token: str, instruments: tuple[DhanInstrument, ...]
) -> DhanQuoteFetchResult:
    """Performs exactly one `POST /v2/marketfeed/quote` call for
    `instruments` (all assumed NSE_EQ - this checkpoint's only
    supported segment). Never raises for network/auth/malformed-shape
    problems without wrapping them in one of this module's own
    exception types first - the caller (application layer) always
    catches `DhanMarketQuoteError`, never a raw `httpx`/`KeyError`."""
    security_ids = [instrument.security_id for instrument in instruments]
    by_security_id = {instrument.security_id: instrument for instrument in instruments}

    started = time.monotonic()
    try:
        response = httpx.post(
            DHAN_QUOTE_ENDPOINT,
            headers={
                "access-token": access_token,
                "client-id": client_id,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={NSE_EQ_SEGMENT: security_ids},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException as exc:
        raise DhanConnectionError("Connection to Dhan timed out.") from exc
    except httpx.HTTPError as exc:
        raise DhanConnectionError("Could not reach Dhan.") from exc

    latency_ms = int((time.monotonic() - started) * 1000)

    if response.status_code in (401, 403):
        raise DhanAuthenticationError("Dhan rejected the configured Client ID/Access Token.")
    if response.status_code != 200:
        raise DhanConnectionError(
            f"Dhan returned an unexpected response (HTTP {response.status_code})."
        )

    try:
        body = response.json()
        segment_data = body["data"][NSE_EQ_SEGMENT]
    except (ValueError, KeyError, TypeError) as exc:
        raise DhanMalformedResponseError(
            "Dhan's quote response did not match the documented shape."
        ) from exc

    observations: list[DhanQuoteObservation] = []
    for security_id_str, payload in segment_data.items():
        try:
            security_id = int(security_id_str)
            instrument = by_security_id[security_id]
            observations.append(_parse_observation(instrument, payload))
        except (KeyError, ValueError, InvalidOperation, TypeError) as exc:
            raise DhanMalformedResponseError(
                f"Dhan's quote response contained a malformed entry for "
                f"security_id={security_id_str!r}."
            ) from exc

    return DhanQuoteFetchResult(
        observations=tuple(observations),
        fetched_at=datetime.now(tz=UTC),
        latency_ms=latency_ms,
    )


def _parse_observation(
    instrument: DhanInstrument, payload: dict[str, object]
) -> DhanQuoteObservation:
    last_price = Decimal(str(payload["last_price"]))
    if last_price <= 0:
        raise DhanMalformedResponseError(
            f"Dhan reported a non-positive last_price for {instrument.symbol}."
        )

    source_timestamp = _parse_dhan_timestamp(str(payload.get("last_trade_time", "")))

    ohlc = payload.get("ohlc")
    open_ = high = low = close = None
    if isinstance(ohlc, dict):
        open_ = _optional_decimal(ohlc.get("open"))
        high = _optional_decimal(ohlc.get("high"))
        low = _optional_decimal(ohlc.get("low"))
        close = _optional_decimal(ohlc.get("close"))

    return DhanQuoteObservation(
        instrument=instrument,
        last_price=last_price,
        source_timestamp=source_timestamp,
        open=open_,
        high=high,
        low=low,
        close=close,
    )


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    decimal_value = Decimal(str(value))
    return decimal_value if decimal_value > 0 else None


def _parse_dhan_timestamp(raw: str) -> datetime:
    """Dhan's `last_trade_time` is documented as `DD/MM/YYYY HH:MM:SS`,
    India-local wall-clock time (Dhan is an India-only broker; no
    provider documentation suggests otherwise) - converted to UTC here,
    the one place this conversion happens, matching
    `domain/session/calendar.py`'s own "one place" IST/UTC boundary
    discipline. Falls back to this process's own fetch instant if the
    field is missing/unparseable (e.g. Dhan's own documented placeholder
    `"01/01/1980 00:00:00"` for an instrument with no trade yet today) -
    never fabricates a plausible-looking but wrong timestamp."""
    try:
        naive = datetime.strptime(raw, "%d/%m/%Y %H:%M:%S")
    except ValueError:
        return datetime.now(tz=UTC)
    if naive.year <= 1980:
        # Dhan's own documented placeholder for "no trade yet" - not a
        # real source timestamp.
        return datetime.now(tz=UTC)
    localized = naive.replace(tzinfo=INDIA_STANDARD_TIME)
    return localized.astimezone(UTC)
