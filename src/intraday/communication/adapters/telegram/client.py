# File: src/intraday/communication/adapters/telegram/client.py
#
# Checkpoint 22: a minimal Telegram Bot API client - connectivity check
# and explicit test-message send only. No notification routing, no
# message templates, no severity levels (Checkpoint 22 §18: "do not
# build a giant notification framework").
#
# Authoritative source: the public Telegram Bot API
# (https://core.telegram.org/bots/api), a stable, widely-documented API
# requiring no further per-checkpoint research to confirm field names -
# `getMe` (GET, no parameters) validates a bot token without sending
# anything (Checkpoint 22 §16's "prefer a safe connectivity/permission
# check"); `sendMessage` (POST, `chat_id` + `text`) sends a real message
# and is therefore only ever called on explicit user action, never
# automatically (Checkpoint 22 §16).
from __future__ import annotations

import time

import httpx

from intraday.communication.contracts.connectivity import ConnectivityCheckResult

_TELEGRAM_API_BASE = "https://api.telegram.org"
_REQUEST_TIMEOUT_SECONDS = 10.0


def check_telegram_connectivity(bot_token: str) -> ConnectivityCheckResult:
    """`GET /bot<token>/getMe` - confirms the bot token is valid without
    sending any message to any channel."""
    started = time.monotonic()
    try:
        response = httpx.get(
            f"{_TELEGRAM_API_BASE}/bot{bot_token}/getMe", timeout=_REQUEST_TIMEOUT_SECONDS
        )
    except httpx.TimeoutException:
        return ConnectivityCheckResult(
            success=False,
            status="CONNECTION_ERROR",
            safe_error="Connection to Telegram timed out.",
            latency_ms=int((time.monotonic() - started) * 1000),
        )
    except httpx.HTTPError:
        return ConnectivityCheckResult(
            success=False,
            status="CONNECTION_ERROR",
            safe_error="Could not reach Telegram.",
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    latency_ms = int((time.monotonic() - started) * 1000)

    if response.status_code == 200:
        return ConnectivityCheckResult(
            success=True, status="CONNECTED", safe_error="", latency_ms=latency_ms
        )
    if response.status_code in (401, 404):
        return ConnectivityCheckResult(
            success=False,
            status="AUTHENTICATION_FAILED",
            safe_error="Telegram rejected the configured bot token.",
            latency_ms=latency_ms,
        )
    return ConnectivityCheckResult(
        success=False,
        status="CONNECTION_ERROR",
        safe_error=f"Telegram returned an unexpected response (HTTP {response.status_code}).",
        latency_ms=latency_ms,
    )


def send_telegram_test_message(bot_token: str, channel_id: str) -> ConnectivityCheckResult:
    """`POST /bot<token>/sendMessage` - sends a real, visible test
    message. Only ever invoked by an explicit, separate user action
    (Checkpoint 22 §16) - never called automatically or as part of
    `check_telegram_connectivity()`/a page-load status check."""
    return _send_message(
        bot_token,
        channel_id,
        "IntraDay: this is a test message confirming your Telegram "
        "notification channel is connected.",
    )


def send_telegram_message(bot_token: str, channel_id: str, text: str) -> ConnectivityCheckResult:
    """Checkpoint 37 Part 3/7: sends an ARBITRARY, caller-rendered
    message (a signal/execution communication) - the generic send path
    the communication engine's Telegram provider adapter uses. Distinct
    from `send_telegram_test_message()` above only in that the text is
    supplied by the caller (already rendered by
    `communication.contracts.templates.render_message()`) rather than
    fixed - same endpoint, same error handling, no new API surface."""
    return _send_message(bot_token, channel_id, text)


def _send_message(bot_token: str, channel_id: str, text: str) -> ConnectivityCheckResult:
    started = time.monotonic()
    try:
        response = httpx.post(
            f"{_TELEGRAM_API_BASE}/bot{bot_token}/sendMessage",
            json={"chat_id": channel_id, "text": text},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException:
        return ConnectivityCheckResult(
            success=False,
            status="CONNECTION_ERROR",
            safe_error="Connection to Telegram timed out.",
            latency_ms=int((time.monotonic() - started) * 1000),
        )
    except httpx.HTTPError:
        return ConnectivityCheckResult(
            success=False,
            status="CONNECTION_ERROR",
            safe_error="Could not reach Telegram.",
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    latency_ms = int((time.monotonic() - started) * 1000)

    if response.status_code == 200:
        return ConnectivityCheckResult(
            success=True, status="CONNECTED", safe_error="", latency_ms=latency_ms
        )
    if response.status_code in (401, 403):
        return ConnectivityCheckResult(
            success=False,
            status="AUTHENTICATION_FAILED",
            safe_error="Telegram rejected the configured bot token or channel.",
            latency_ms=latency_ms,
        )
    return ConnectivityCheckResult(
        success=False,
        status="CONNECTION_ERROR",
        safe_error=f"Telegram returned an unexpected response (HTTP {response.status_code}).",
        latency_ms=latency_ms,
    )
