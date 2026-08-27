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
    # Checkpoint 64.93: the DESIRED notification-channel selection
    # ("telegram", "discord", ...) - validated server-side (view layer)
    # against the existing Telegram/Discord settings registry, never
    # trusted as-is (Part L: backend validation is never optional).
    selected_notification_channels = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )


class NotificationChannelSerializer(serializers.Serializer[dict[str, object]]):
    """Checkpoint 64.93 Part D: ONE row of the notification-channel
    registry - reuses the EXISTING `TelegramSettingsService`/
    `DiscordSettingsService` truth (Checkpoint 22), never a duplicated
    channel-configuration model. `configured` and `enabled` are kept
    distinct on the wire exactly as the checkpoint brief requires: a
    channel can be `configured=True, enabled=False` (credentials saved,
    delivery switched off) or, honestly, `configured=False` regardless
    of `enabled` (a channel is never "operational" without credentials,
    no matter what its enabled flag says)."""

    channel_id = serializers.CharField()
    display_name = serializers.CharField()
    configured = serializers.BooleanField()
    enabled = serializers.BooleanField()


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
    # Checkpoint 64.93: on `desired`, exactly what the operator selected.
    # On `effective`, the subset that is genuinely operational right now
    # (selected AND configured AND enabled in the real Telegram/Discord
    # settings) - computed at read time, never stored twice.
    notification_channels = serializers.ListField(child=serializers.CharField(), required=False)


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
    "NotificationChannelSerializer",
]
