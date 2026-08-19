# File: src/intraday/infrastructure/market_data_providers/dhan/token_renewal_client.py
#
# Checkpoint 64.1: real Dhan `RenewToken` REST client - verified
# directly against Dhan's own official authentication documentation
# this checkpoint (never invented).
#
# ---------------------------------------------------------------------------
# Authoritative source (fetched directly, https://dhanhq.co/docs/v2/authentication/)
# ---------------------------------------------------------------------------
#   URL:      POST https://api.dhan.co/v2/RenewToken
#   Headers:  access-token: {current JWT}, dhanClientId: {Client ID}
#
# CRITICAL, DOCUMENTED LIMITATION - the reason this is called ONLY from
# the EXPIRING_SOON state, never EXPIRED: "This only renews tokens which
# are active. If you try to renew an expired token, it will return an
# error." An already-EXPIRED token cannot be renewed via this endpoint
# at all - that path is, correctly, `OPERATOR_ACTION_REQUIRED` (manual
# re-login), not an automatic retry loop against an endpoint documented
# to reject it. Dhan's docs also state this only works for tokens
# "generated from Dhan Web" - `tokenConsumerType` in this project's own
# configured token was found to be `SELF` (Checkpoint 64's own JWT-claim
# inspection) - whether that qualifies is NOT independently verifiable
# without a real, currently-active token to test against (this
# environment's only configured token is already expired). This client
# is built and unit-tested against the documented response shape; it
# has NEVER been exercised against a real, still-active Dhan token -
# named explicitly, not hidden.
from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

DHAN_RENEW_TOKEN_ENDPOINT = "https://api.dhan.co/v2/RenewToken"  # noqa: S105 - a URL, not a password
_REQUEST_TIMEOUT_SECONDS = 15.0


class DhanTokenRenewalError(Exception):
    """Base class for every non-2xx/malformed outcome this client
    translates - mirrors `client.py`'s own `DhanMarketQuoteError`
    hierarchy so every Dhan client in this project fails the same way."""


class DhanTokenRenewalRejectedError(DhanTokenRenewalError):
    """Dhan rejected the renewal request itself (401/403, or a 2xx body
    without a new token) - per Dhan's own documented limitation, this
    is the EXPECTED outcome for an already-expired token, never treated
    as a transport failure."""


class DhanTokenRenewalConnectionError(DhanTokenRenewalError):
    """Network failure, timeout, or an unexpected non-2xx/non-401/403
    status."""


@dataclass(frozen=True, slots=True)
class DhanTokenRenewalResult:
    new_access_token: str
    renewed_at_epoch_seconds: float


def renew_dhan_token(*, client_id: str, current_access_token: str) -> DhanTokenRenewalResult:
    """One `POST /v2/RenewToken` call. Never called automatically for a
    token already known EXPIRED (see module docstring) - the caller
    (`token_lifecycle.py`'s own renewal orchestration) is responsible
    for only invoking this from `EXPIRING_SOON`."""
    try:
        response = httpx.post(
            DHAN_RENEW_TOKEN_ENDPOINT,
            headers={
                "access-token": current_access_token,
                "dhanClientId": client_id,
                "Accept": "application/json",
            },
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException as exc:
        raise DhanTokenRenewalConnectionError("Connection to Dhan timed out.") from exc
    except httpx.HTTPError as exc:
        raise DhanTokenRenewalConnectionError("Could not reach Dhan.") from exc

    if response.status_code in (401, 403):
        raise DhanTokenRenewalRejectedError(
            "Dhan rejected the token renewal request (token not active/renewable)."
        )
    if response.status_code != 200:
        raise DhanTokenRenewalConnectionError(
            f"Dhan returned an unexpected response (HTTP {response.status_code})."
        )

    try:
        body = response.json()
        new_token = body["accessToken"]
    except (ValueError, KeyError, TypeError) as exc:
        raise DhanTokenRenewalRejectedError(
            "Dhan's renewal response did not contain a new access token."
        ) from exc
    if not isinstance(new_token, str) or not new_token:
        raise DhanTokenRenewalRejectedError("Dhan's renewal response had an empty access token.")

    return DhanTokenRenewalResult(new_access_token=new_token, renewed_at_epoch_seconds=time.time())


__all__ = [
    "DhanTokenRenewalResult",
    "DhanTokenRenewalError",
    "DhanTokenRenewalRejectedError",
    "DhanTokenRenewalConnectionError",
    "renew_dhan_token",
    "DHAN_RENEW_TOKEN_ENDPOINT",
]
