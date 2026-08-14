# File: src/intraday/communication/contracts/connectivity.py
#
# Checkpoint 22: the smallest genuinely-justified shared abstraction
# this checkpoint introduces (Checkpoint 22 §18) - a provider-agnostic
# connectivity-check RESULT shape shared by the two concrete
# communication adapters (Telegram, Discord), satisfied structurally by
# each without either importing the other or a common base class. NOT a
# `CommunicationProvider` framework, NOT a notification-sending
# abstraction (no message templates, no severity levels, no routing) -
# this checkpoint only needs "did the connectivity check succeed, and if
# not, why (safely)?" Future WhatsApp support (explicitly NOT
# implemented - Checkpoint 22 §18) would satisfy this exact same shape.
#
# Dhan (`infrastructure/brokers/dhan/client.py`) deliberately defines
# its own, separate `DhanConnectivityResult` rather than importing this
# one - Dhan is a broker (a different bounded context,
# `infrastructure/brokers`), not a communication provider, and importing
# a `communication/contracts` type from `infrastructure/brokers` would
# blur that boundary for a four-field dataclass not worth sharing across
# it.
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConnectivityCheckResult:
    """The outcome of one read-only connectivity probe against a
    provider - never a trading/order call, never a message-send
    (Checkpoint 22 §11/§16: "the first connectivity check must be
    read-only"). `safe_error` is a human-readable, ALREADY-sanitized
    message - the client producing this result is responsible for never
    including a token/secret/webhook URL in it (Checkpoint 22 §24)."""

    success: bool
    status: str  # one of ProviderConnectionStatus's STATUS_CHOICES values
    safe_error: str
    latency_ms: int
