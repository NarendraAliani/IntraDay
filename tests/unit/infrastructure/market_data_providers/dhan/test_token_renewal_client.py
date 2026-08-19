# tests/unit/infrastructure/market_data_providers/dhan/test_token_renewal_client.py
#
# Checkpoint 64.1: unit coverage for the real Dhan `/v2/RenewToken`
# REST client - HTTP status/shape -> typed exception mapping. All HTTP
# calls are mocked - no real network access, no real credential
# anywhere in this file.
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from intraday.infrastructure.market_data_providers.dhan.token_renewal_client import (
    DHAN_RENEW_TOKEN_ENDPOINT,
    DhanTokenRenewalConnectionError,
    DhanTokenRenewalRejectedError,
    renew_dhan_token,
)


def _mock_response(status_code: int, json_body: object = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body
    return response


def test_a_successful_renewal_returns_the_new_token() -> None:
    with patch("httpx.post", return_value=_mock_response(200, {"accessToken": "new-fake-token"})):
        result = renew_dhan_token(client_id="fake-client-id", current_access_token="old-fake-token")

    assert result.new_access_token == "new-fake-token"  # noqa: S105 - test fixture, not a secret


def test_calls_the_documented_endpoint_with_the_documented_headers() -> None:
    with patch(
        "httpx.post", return_value=_mock_response(200, {"accessToken": "new-fake-token"})
    ) as mock_post:
        renew_dhan_token(client_id="fake-client-id", current_access_token="old-fake-token")

    args, kwargs = mock_post.call_args
    assert args[0] == DHAN_RENEW_TOKEN_ENDPOINT
    assert kwargs["headers"]["access-token"] == "old-fake-token"
    assert kwargs["headers"]["dhanClientId"] == "fake-client-id"


def test_an_expired_or_rejected_token_raises_rejected_never_a_connection_error() -> None:
    # Dhan's own documented behavior: renewing an already-expired token
    # returns an error, not a successful new token.
    with (
        patch("httpx.post", return_value=_mock_response(401)),
        pytest.raises(DhanTokenRenewalRejectedError),
    ):
        renew_dhan_token(client_id="x", current_access_token="x")


def test_missing_access_token_field_in_a_200_response_raises_rejected() -> None:
    with (
        patch("httpx.post", return_value=_mock_response(200, {"status": "ok"})),
        pytest.raises(DhanTokenRenewalRejectedError),
    ):
        renew_dhan_token(client_id="x", current_access_token="x")


def test_unexpected_status_raises_connection_error() -> None:
    with (
        patch("httpx.post", return_value=_mock_response(500)),
        pytest.raises(DhanTokenRenewalConnectionError),
    ):
        renew_dhan_token(client_id="x", current_access_token="x")
