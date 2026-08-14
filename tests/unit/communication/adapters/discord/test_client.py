# tests/unit/communication/adapters/discord/test_client.py
#
# Checkpoint 22: unit coverage for the Discord webhook client -
# connectivity check (GET, no message posted) vs. explicit test-message
# send (POST) stay two distinct operations. All HTTP calls are mocked.
from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

from intraday.communication.adapters.discord.client import (
    check_discord_connectivity,
    send_discord_test_message,
)

FAKE_WEBHOOK_URL = "https://discord.com/api/webhooks/fake/token-value"


def _mock_response(status_code: int) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    return response


def test_check_connectivity_success_maps_to_connected() -> None:
    with patch("httpx.get", return_value=_mock_response(200)):
        result = check_discord_connectivity(FAKE_WEBHOOK_URL)

    assert result.success is True
    assert result.status == "CONNECTED"


def test_check_connectivity_invalid_webhook_maps_to_authentication_failed() -> None:
    with patch("httpx.get", return_value=_mock_response(404)):
        result = check_discord_connectivity(FAKE_WEBHOOK_URL)

    assert result.success is False
    assert result.status in ("AUTHENTICATION_FAILED", "CONNECTION_ERROR")


def test_check_connectivity_never_posts_a_message() -> None:
    with (
        patch("httpx.get", return_value=_mock_response(200)) as mock_get,
        patch("httpx.post") as mock_post,
    ):
        check_discord_connectivity(FAKE_WEBHOOK_URL)

    mock_get.assert_called_once()
    mock_post.assert_not_called()


def test_send_test_message_success() -> None:
    with patch("httpx.post", return_value=_mock_response(204)):
        result = send_discord_test_message(FAKE_WEBHOOK_URL)

    assert result.success is True


def test_check_connectivity_timeout_does_not_raise() -> None:
    with patch("httpx.get", side_effect=httpx.TimeoutException("timed out")):
        result = check_discord_connectivity(FAKE_WEBHOOK_URL)

    assert result.success is False
    assert result.status == "CONNECTION_ERROR"
