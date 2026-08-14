# tests/unit/communication/adapters/telegram/test_client.py
#
# Checkpoint 22: unit coverage for the Telegram Bot API client -
# connectivity check (getMe) vs. explicit test-message send (sendMessage)
# stay two distinct, separately-invoked operations; HTTP status mapping
# for both. All HTTP calls are mocked.
from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

from intraday.communication.adapters.telegram.client import (
    check_telegram_connectivity,
    send_telegram_test_message,
)


def _mock_response(status_code: int) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    return response


def test_check_connectivity_success_maps_to_connected() -> None:
    with patch("httpx.get", return_value=_mock_response(200)):
        result = check_telegram_connectivity("fake-bot-token")

    assert result.success is True
    assert result.status == "CONNECTED"


def test_check_connectivity_invalid_token_maps_to_authentication_failed() -> None:
    with patch("httpx.get", return_value=_mock_response(401)):
        result = check_telegram_connectivity("fake-bad-token")

    assert result.status == "AUTHENTICATION_FAILED"
    assert "fake-bad-token" not in result.safe_error


def test_check_connectivity_never_sends_a_message() -> None:
    """`getMe` takes no parameters and posts nothing - proven by asserting
    only `httpx.get` (never `httpx.post`) is invoked."""
    with (
        patch("httpx.get", return_value=_mock_response(200)) as mock_get,
        patch("httpx.post") as mock_post,
    ):
        check_telegram_connectivity("fake-bot-token")

    mock_get.assert_called_once()
    mock_post.assert_not_called()


def test_check_connectivity_timeout_does_not_raise() -> None:
    with patch("httpx.get", side_effect=httpx.TimeoutException("timed out")):
        result = check_telegram_connectivity("fake-bot-token")

    assert result.success is False
    assert result.status == "CONNECTION_ERROR"


def test_send_test_message_success() -> None:
    with patch("httpx.post", return_value=_mock_response(200)):
        result = send_telegram_test_message("fake-bot-token", "-100123456")

    assert result.success is True
    assert result.status == "CONNECTED"


def test_send_test_message_bot_token_never_appears_in_request_body() -> None:
    with patch("httpx.post", return_value=_mock_response(200)) as mock_post:
        send_telegram_test_message("fake-secret-bot-token", "-100123456")

    body = mock_post.call_args[1]["json"]
    assert "fake-secret-bot-token" not in str(body)
