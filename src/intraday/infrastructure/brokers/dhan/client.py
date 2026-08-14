# File: src/intraday/infrastructure/brokers/dhan/client.py
#
# Checkpoint 22: a minimal, READ-ONLY Dhan connectivity client - NOT the
# full `domain.broker.BrokerGateway` implementation
# (`infrastructure/brokers/dhan/README.md`'s eventual "must implement
# domain/broker contract only" responsibility, deliberately deferred).
# This client has exactly one capability: verify that a client_id +
# access_token pair authenticates successfully against the real DhanHQ
# v2 API, via the exact endpoint Dhan's own documentation recommends for
# integration testing (Checkpoint 22 §11 - "do not call order-placement
# endpoints").
#
# ---------------------------------------------------------------------------
# Authoritative source (Checkpoint 22 §2 - "do not invent Dhan
# authentication fields")
# ---------------------------------------------------------------------------
#
# https://dhanhq.co/docs/v2/authentication/ - confirmed via direct
# fetch of the official documentation during this checkpoint:
#
#   Base URL:  https://api.dhan.co/v2
#   Headers:   access-token: {JWT}
#              dhanClientId: {Client ID}
#
#   "The User Profile endpoint serves as a great test API for you to
#   start integration - requires only the access-token header" -
#   GET /v2/profile is therefore the connectivity check this client
#   performs. It is a read-only account-metadata lookup - never an
#   order, position, or fund-transfer endpoint.
#
# No official Python SDK dependency was added (`dhanhq` on PyPI) -
# this checkpoint's scope is a single authenticated GET request, which
# a general-purpose HTTP client (`httpx`, already a project dependency)
# performs directly against the documented REST endpoint without
# pulling in a full trading SDK's order-placement surface before any
# order capability is authorized.
from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

DHAN_BASE_URL = "https://api.dhan.co/v2"
DHAN_PROFILE_ENDPOINT = f"{DHAN_BASE_URL}/profile"
_REQUEST_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class DhanConnectivityResult:
    """The outcome of one `GET /v2/profile` connectivity probe. `status`
    is one of `ProviderConnectionStatus.STATUS_CHOICES` (Checkpoint 22
    §10/§12) - never a raw HTTP status code or Dhan-specific error
    body. `safe_error` never contains the access token (Checkpoint 22
    §24) - constructed entirely from the HTTP status code and Dhan's own
    documented error semantics, never by echoing response content that
    could itself contain request context."""

    success: bool
    status: str
    safe_error: str
    latency_ms: int


def check_dhan_connectivity(client_id: str, access_token: str) -> DhanConnectivityResult:
    """Performs exactly one read-only HTTP GET against `/v2/profile`.
    Never raises for an ordinary connectivity/authentication failure -
    every reachable outcome (success, bad credentials, network error,
    timeout) is translated into a `DhanConnectivityResult` so the caller
    never needs to catch an httpx exception itself."""
    started = time.monotonic()
    try:
        response = httpx.get(
            DHAN_PROFILE_ENDPOINT,
            headers={"access-token": access_token, "dhanClientId": client_id},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException:
        latency_ms = int((time.monotonic() - started) * 1000)
        return DhanConnectivityResult(
            success=False,
            status="CONNECTION_ERROR",
            safe_error="Connection to Dhan timed out.",
            latency_ms=latency_ms,
        )
    except httpx.HTTPError:
        latency_ms = int((time.monotonic() - started) * 1000)
        return DhanConnectivityResult(
            success=False,
            status="CONNECTION_ERROR",
            safe_error="Could not reach Dhan.",
            latency_ms=latency_ms,
        )

    latency_ms = int((time.monotonic() - started) * 1000)

    if response.status_code == 200:
        return DhanConnectivityResult(
            success=True, status="CONNECTED", safe_error="", latency_ms=latency_ms
        )
    if response.status_code == 401:
        return DhanConnectivityResult(
            success=False,
            status="AUTHENTICATION_FAILED",
            safe_error="Dhan rejected the configured Client ID/Access Token.",
            latency_ms=latency_ms,
        )
    if response.status_code == 403:
        return DhanConnectivityResult(
            success=False,
            status="TOKEN_EXPIRED",
            safe_error="Dhan access token has expired or been revoked.",
            latency_ms=latency_ms,
        )
    return DhanConnectivityResult(
        success=False,
        status="CONNECTION_ERROR",
        safe_error=f"Dhan returned an unexpected response (HTTP {response.status_code}).",
        latency_ms=latency_ms,
    )
