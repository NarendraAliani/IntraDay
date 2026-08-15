# File: src/intraday/application/contracts/market_data.py
#
# Checkpoint 23: wire-facing (transport) contracts for the read-only
# live market-data API. Mirrors `application/contracts/settings.py`'s
# own established pattern (Checkpoint 22) - `serializers.Serializer[dict[str,
# object]]` since every one of these is instantiated with real data via
# `.data`, never used for schema-only declaration.
from __future__ import annotations

from rest_framework import serializers


class SessionResponseSerializer(serializers.Serializer[dict[str, object]]):
    session_date = serializers.DateField()
    exchange = serializers.CharField()
    market_open = serializers.DateTimeField()
    market_close = serializers.DateTimeField()
    square_off_deadline = serializers.DateTimeField()
    status = serializers.ChoiceField(choices=["PRE_OPEN", "OPEN", "CLOSED"])


class MarketDataHealthResponseSerializer(serializers.Serializer[dict[str, object]]):
    state = serializers.ChoiceField(
        choices=[
            "CONNECTED_FRESH",
            "CONNECTED_STALE",
            "DISCONNECTED",
            "AUTHENTICATION_FAILED",
            "ERROR",
            "MARKET_CLOSED",
        ]
    )
    last_success_at = serializers.DateTimeField(allow_null=True)
    last_failure_at = serializers.DateTimeField(allow_null=True)
    last_error_safe = serializers.CharField(allow_blank=True)
    freshness_age_seconds = serializers.FloatField(allow_null=True)
    consecutive_failures = serializers.IntegerField()
    reconnect_count = serializers.IntegerField()
    subscription_active = serializers.BooleanField()


class SystemReadinessResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Checkpoint 50 Rule 10: the ONE composed readiness answer -
    `control_plane.system_readiness.contracts.SystemReadinessSnapshot`
    on the wire."""

    state = serializers.ChoiceField(
        choices=["READY", "DEGRADED", "HALTED", "SQUARE_OFF_UNRESOLVED", "FAILED"]
    )
    reasons = serializers.ListField(child=serializers.CharField())
    database_ok = serializers.BooleanField()
    market_data_state = serializers.CharField()
    session_status = serializers.CharField()
    kill_switch_engaged = serializers.BooleanField()
    square_off_unresolved_count = serializers.IntegerField()


class QuoteResponseSerializer(serializers.Serializer[dict[str, object]]):
    symbol = serializers.CharField()
    exchange = serializers.CharField()
    last_price = serializers.DecimalField(max_digits=14, decimal_places=4)
    source_timestamp = serializers.DateTimeField()
    freshness_age_seconds = serializers.FloatField()
    is_stale = serializers.BooleanField()


class BarResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Checkpoint 24A. `status` is always present and explicit
    (FORMING/CLOSED, never implied) - the checkpoint's own requirement
    that a consumer can never mistake an in-progress bar for a closed
    one."""

    symbol = serializers.CharField()
    exchange = serializers.CharField()
    timeframe = serializers.CharField()
    interval_start = serializers.DateTimeField()
    interval_end = serializers.DateTimeField()
    open = serializers.DecimalField(max_digits=14, decimal_places=4)
    high = serializers.DecimalField(max_digits=14, decimal_places=4)
    low = serializers.DecimalField(max_digits=14, decimal_places=4)
    close = serializers.DecimalField(max_digits=14, decimal_places=4)
    status = serializers.ChoiceField(choices=["FORMING", "CLOSED"])
    observation_count = serializers.IntegerField()
    data_source = serializers.CharField()
