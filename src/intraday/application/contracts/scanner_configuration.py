# File: src/intraday/application/contracts/scanner_configuration.py
#
# Checkpoint 64.4: wire-facing contracts for the live scanner control
# plane - the DESIRED configuration an operator sets, and the combined
# desired+effective response the UI reads. Validation reuses the
# existing `StrategyRegistry`/`Timeframe` vocabulary at the view layer
# - this module carries no duplicated strategy-parameter schema.
from __future__ import annotations

from rest_framework import serializers


class ScannerConfigurationUpdateRequestSerializer(serializers.Serializer[None]):
    enabled = serializers.BooleanField()
    timeframe = serializers.CharField()
    universe_mode = serializers.ChoiceField(choices=["ALL_CONFIGURED", "SELECTED", "WATCHLIST"])
    selected_instrument_ids = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )
    selected_watchlist_name = serializers.CharField(required=False, default="", allow_blank=True)
    selected_strategy_ids = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )


class ScannerConfigurationStateSerializer(serializers.Serializer[dict[str, object]]):
    """Shared shape for both the DESIRED and EFFECTIVE halves of the
    response - Checkpoint 64.4's own explicit "the UI must never lie"
    requirement is met by showing both side by side, never merged into
    one ambiguous state."""

    timeframe = serializers.CharField()
    universe_mode = serializers.CharField(required=False, allow_blank=True)
    universe_requested_count = serializers.IntegerField()
    universe_subscribed_count = serializers.IntegerField()
    strategy_ids = serializers.ListField(child=serializers.CharField())
    configuration_version = serializers.IntegerField()
    enabled = serializers.BooleanField(required=False)


class ScannerConfigurationResponseSerializer(serializers.Serializer[dict[str, object]]):
    provider = serializers.CharField()
    desired = ScannerConfigurationStateSerializer()
    effective = ScannerConfigurationStateSerializer()
    status = serializers.ChoiceField(choices=["EFFECTIVE", "APPLYING", "DEGRADED", "STOPPED"])
    """`EFFECTIVE` - desired and effective configuration_version match
    and the universe was fully subscribed. `APPLYING` - the worker
    hasn't reconciled the latest desired version yet (or has never run
    at all). `DEGRADED` - reconciled, but the effective universe is
    narrower than requested (e.g. an unresolvable instrument).
    `STOPPED` - desired.enabled is False."""
    requested_by = serializers.CharField()
    requested_at = serializers.DateTimeField(allow_null=True)


__all__ = [
    "ScannerConfigurationUpdateRequestSerializer",
    "ScannerConfigurationStateSerializer",
    "ScannerConfigurationResponseSerializer",
]
