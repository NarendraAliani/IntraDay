# File: src/intraday/application/contracts/worker_runtime_status.py
#
# Checkpoint 64.3: wire-facing contract for the read-only worker
# runtime-status API - the operator-facing "is the live worker actually
# healthy" surface. Never a credential, never a raw provider response
# body - only the same safe, already-derived facts
# `MarketDataWatchdogSnapshot` itself carries, plus the two state
# names (`worker_state`/`token_state`) an operator needs to make sense
# of `watchdog_state`.
from __future__ import annotations

from rest_framework import serializers


class WorkerRuntimeStatusResponseSerializer(serializers.Serializer[dict[str, object]]):
    provider = serializers.CharField()
    worker_state = serializers.CharField()
    token_state = serializers.CharField()
    watchdog_state = serializers.CharField()
    last_packet_at = serializers.DateTimeField(allow_null=True)
    last_bar_at = serializers.DateTimeField(allow_null=True)
    packet_age_seconds = serializers.FloatField(allow_null=True)
    bar_age_seconds = serializers.FloatField(allow_null=True)
    reconnect_count = serializers.IntegerField()
    consecutive_failures = serializers.IntegerField()
    subscribed_instrument_count = serializers.IntegerField()
    last_error_safe = serializers.CharField()
    updated_at = serializers.DateTimeField(allow_null=True)
    is_configured = serializers.BooleanField()
    """`False` when no worker has ever reported status for this
    provider (the worker process has never run) - distinct from
    `worker_state=STOPPED`, which means it HAS run and cleanly
    stopped."""


__all__ = ["WorkerRuntimeStatusResponseSerializer"]
