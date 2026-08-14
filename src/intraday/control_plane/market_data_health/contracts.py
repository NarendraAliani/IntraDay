# File: src/intraday/control_plane/market_data_health/contracts.py
#
# Checkpoint 23: technology-neutral market-data health vocabulary.
# Supervisory/observational only - no signal, no trading decision, no
# order code imported or implied anywhere in this module (Checkpoint 23
# §2's absolute safety boundary; also this bounded context's own
# documented "must not depend on strategy logic").
#
# State model (Checkpoint 23 §9's explicit list): CONNECTED_FRESH is the
# only "everything is fine" state - every other state names a specific,
# distinguishable problem so a human reading the Live Market Data
# Monitor never has to infer "why" from a generic red icon.
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime


class MarketDataHealthState(enum.Enum):
    """Checkpoint 23 §9's explicit state list, adopted verbatim."""

    CONNECTED_FRESH = "CONNECTED_FRESH"
    CONNECTED_STALE = "CONNECTED_STALE"
    DISCONNECTED = "DISCONNECTED"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    ERROR = "ERROR"
    MARKET_CLOSED = "MARKET_CLOSED"


@dataclass(frozen=True, slots=True)
class MarketDataHealthSnapshot:
    """A point-in-time read of market-data health - what
    `evaluator.evaluate_health()` produces and what
    `infrastructure/api` serializes for the read-only API. Never
    contains a credential, a raw provider error body, or anything
    signal/order-related.

    `reconnect_count` and `subscription_active` exist for a future
    WebSocket-based adapter (Checkpoint 23 §6's "if WebSocket is
    used..." branch) - this checkpoint's REST-polling adapter (see
    docs/architecture/LIVE_MARKET_DATA_ARCHITECTURE.md for why REST
    polling, not WebSocket, was chosen) has no reconnect/subscription
    concept of its own, so these are always `0`/`False` here, not
    fabricated values implying a capability that does not exist yet.
    """

    state: MarketDataHealthState
    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_error_safe: str
    freshness_age_seconds: float | None
    consecutive_failures: int
    reconnect_count: int
    subscription_active: bool
