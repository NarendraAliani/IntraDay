# File: src/intraday/communication/adapters/discord/client.py
#
# Checkpoint 22: a minimal Discord webhook client - connectivity check
# and explicit test-message send only.
#
# Authoritative source: Discord's public webhook API
# (https://discord.com/developers/docs/resources/webhook). A webhook
# URL (`https://discord.com/api/webhooks/{id}/{token}`) IS the
# credential - Discord's documented `GET` on that exact URL returns the
# webhook's own metadata if valid (404 otherwise), which is the
# connectivity check this client performs WITHOUT posting anything
# (Checkpoint 22 §16's "prefer a safe connectivity/permission check").
# `POST` to the same URL with a JSON body sends a real message and is
# only ever called on explicit user action.
from __future__ import annotations

import time

import httpx

from intraday.communication.contracts.connectivity import ConnectivityCheckResult

_REQUEST_TIMEOUT_SECONDS = 10.0


def check_discord_connectivity(webhook_url: str) -> ConnectivityCheckResult:
    """`GET <webhook_url>` - confirms the webhook exists and is valid
    without posting any message."""
    started = time.monotonic()
    try:
        response = httpx.get(webhook_url, timeout=_REQUEST_TIMEOUT_SECONDS)
    except httpx.TimeoutException:
        return ConnectivityCheckResult(
            success=False,
            status="CONNECTION_ERROR",
            safe_error="Connection to Discord timed out.",
            latency_ms=int((time.monotonic() - started) * 1000),
        )
    except httpx.HTTPError:
        return ConnectivityCheckResult(
            success=False,
            status="CONNECTION_ERROR",
            safe_error="Could not reach Discord.",
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    latency_ms = int((time.monotonic() - started) * 1000)

    if response.status_code == 200:
        return ConnectivityCheckResult(
            success=True, status="CONNECTED", safe_error="", latency_ms=latency_ms
        )
    if response.status_code == 401 or response.status_code == 404:
        return ConnectivityCheckResult(
            success=False,
            status="AUTHENTICATION_FAILED",
            safe_error="Discord rejected the configured webhook URL.",
            latency_ms=latency_ms,
        )
    return ConnectivityCheckResult(
        success=False,
        status="CONNECTION_ERROR",
        safe_error=f"Discord returned an unexpected response (HTTP {response.status_code}).",
        latency_ms=latency_ms,
    )


def send_discord_message_with_id(
    webhook_url: str, text: str
) -> tuple[bool, str | None, str | None, str | None, bool]:
    """Checkpoint 38 Part 8: Discord's webhook POST returns 204 No
    Content (no body, no message ID) UNLESS the documented `?wait=true`
    query parameter is used, in which case it returns 200 with the full
    message object JSON (including `id`) - Discord's own official
    behavior (https://discord.com/developers/docs/resources/webhook,
    "Execute Webhook", `wait` query parameter). This function uses
    `?wait=true` specifically to capture that ID, closing Checkpoint
    37's named gap. Returns `(success, provider_message_id, error_code,
    error_message, is_retryable)`."""
    try:
        response = httpx.post(
            f"{webhook_url}?wait=true",
            json={"content": text},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException:
        return False, None, "CONNECTION_ERROR", "Connection to Discord timed out.", True
    except httpx.HTTPError:
        return False, None, "CONNECTION_ERROR", "Could not reach Discord.", True

    if response.status_code == 200:
        try:
            body = response.json()
        except ValueError:
            body = {}
        message_id = str(body["id"]) if isinstance(body, dict) and "id" in body else None
        return True, message_id, None, None, False
    if response.status_code == 204:
        # wait=true should always return 200 on success, but tolerate a
        # bare 204 defensively - success, just no ID available.
        return True, None, None, None, False

    if response.status_code in (401, 404):
        return (
            False,
            None,
            "AUTHENTICATION_FAILED",
            "Discord rejected the configured webhook URL.",
            False,
        )
    if response.status_code == 429 or response.status_code >= 500:
        return (
            False,
            None,
            "TRANSIENT_ERROR",
            f"Discord returned a transient error (HTTP {response.status_code}).",
            True,
        )
    return (
        False,
        None,
        "CONNECTION_ERROR",
        f"Discord returned an unexpected response (HTTP {response.status_code}).",
        False,
    )


def send_discord_test_message(webhook_url: str) -> ConnectivityCheckResult:
    """`POST <webhook_url>` - sends a real, visible test message to the
    configured channel. Only ever invoked by an explicit, separate user
    action (Checkpoint 22 §17)."""
    return _post_message(
        webhook_url,
        "IntraDay: this is a test message confirming your Discord "
        "notification channel is connected.",
    )


def send_discord_message(webhook_url: str, text: str) -> ConnectivityCheckResult:
    """Checkpoint 37 Part 3/7: sends an ARBITRARY, caller-rendered
    message - the generic send path the communication engine's Discord
    provider adapter uses. See the Telegram equivalent's docstring for
    the shared rationale."""
    return _post_message(webhook_url, text)


def _post_message(webhook_url: str, text: str) -> ConnectivityCheckResult:
    started = time.monotonic()
    try:
        response = httpx.post(
            webhook_url,
            json={"content": text},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException:
        return ConnectivityCheckResult(
            success=False,
            status="CONNECTION_ERROR",
            safe_error="Connection to Discord timed out.",
            latency_ms=int((time.monotonic() - started) * 1000),
        )
    except httpx.HTTPError:
        return ConnectivityCheckResult(
            success=False,
            status="CONNECTION_ERROR",
            safe_error="Could not reach Discord.",
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    latency_ms = int((time.monotonic() - started) * 1000)

    # Discord returns 204 No Content on a successful webhook post.
    if response.status_code in (200, 204):
        return ConnectivityCheckResult(
            success=True, status="CONNECTED", safe_error="", latency_ms=latency_ms
        )
    if response.status_code in (401, 404):
        return ConnectivityCheckResult(
            success=False,
            status="AUTHENTICATION_FAILED",
            safe_error="Discord rejected the configured webhook URL.",
            latency_ms=latency_ms,
        )
    return ConnectivityCheckResult(
        success=False,
        status="CONNECTION_ERROR",
        safe_error=f"Discord returned an unexpected response (HTTP {response.status_code}).",
        latency_ms=latency_ms,
    )
