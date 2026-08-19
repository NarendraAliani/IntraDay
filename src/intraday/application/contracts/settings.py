# File: src/intraday/application/contracts/settings.py
#
# Checkpoint 22: wire-facing (transport) contracts for the operational
# provider-settings API. Mirrors `application/contracts/risk.py`'s own
# established pattern - these serializers describe both the OpenAPI
# schema AND the real response shape (routed through `.data`, following
# the Checkpoint 17.2 fix's own precedent for any serializer that
# carries a field type DRF's raw-dict `Response()` would otherwise
# mishandle). NONE of these serializers has a field for a raw secret
# value anywhere (Checkpoint 22 §12/§21) - only booleans, masked
# strings, and status metadata.
from __future__ import annotations

from rest_framework import serializers


class DhanSettingsResponseSerializer(serializers.Serializer[dict[str, object]]):
    client_id_masked = serializers.CharField()
    client_id_source = serializers.ChoiceField(choices=["DATABASE", "ENVIRONMENT", "UNCONFIGURED"])
    access_token_configured = serializers.BooleanField()
    access_token_source = serializers.ChoiceField(
        choices=["DATABASE", "ENVIRONMENT", "UNCONFIGURED"]
    )
    enabled = serializers.BooleanField()
    updated_at = serializers.DateTimeField(allow_null=True)
    updated_by_username = serializers.CharField()
    # Checkpoint 64: computed fresh from the token's own `exp` claim on
    # every read - see DhanSettingsService.get_display()'s own docstring
    # for the real "Connected badge can be stale" bug this closes.
    token_state = serializers.ChoiceField(
        choices=["UNCONFIGURED", "VALID", "EXPIRING_SOON", "EXPIRED", "MALFORMED"]
    )
    token_expires_at = serializers.DateTimeField(allow_null=True)


class TelegramSettingsResponseSerializer(serializers.Serializer[dict[str, object]]):
    channel_id_masked = serializers.CharField()
    channel_id_source = serializers.ChoiceField(choices=["DATABASE", "ENVIRONMENT", "UNCONFIGURED"])
    bot_token_configured = serializers.BooleanField()
    bot_token_source = serializers.ChoiceField(choices=["DATABASE", "ENVIRONMENT", "UNCONFIGURED"])
    enabled = serializers.BooleanField()
    updated_at = serializers.DateTimeField(allow_null=True)
    updated_by_username = serializers.CharField()


class DiscordSettingsResponseSerializer(serializers.Serializer[dict[str, object]]):
    webhook_configured = serializers.BooleanField()
    webhook_source = serializers.ChoiceField(choices=["DATABASE", "ENVIRONMENT", "UNCONFIGURED"])
    enabled = serializers.BooleanField()
    updated_at = serializers.DateTimeField(allow_null=True)
    updated_by_username = serializers.CharField()


class ConnectionStatusResponseSerializer(serializers.Serializer[dict[str, object]]):
    provider = serializers.ChoiceField(choices=["dhan", "telegram", "discord"])
    status = serializers.ChoiceField(
        choices=[
            "NOT_CONFIGURED",
            "CONFIGURED",
            "CONNECTING",
            "CONNECTED",
            "DISCONNECTED",
            "AUTHENTICATION_FAILED",
            "TOKEN_EXPIRED",
            "CONNECTION_ERROR",
            "DISABLED",
        ]
    )
    last_checked_at = serializers.DateTimeField(allow_null=True)
    last_success_at = serializers.DateTimeField(allow_null=True)
    last_failure_at = serializers.DateTimeField(allow_null=True)
    failure_reason_safe = serializers.CharField(allow_blank=True)
    latency_ms = serializers.IntegerField(allow_null=True)


# --- Write (save) request shapes ---------------------------------------------
#
# Every secret field is `required=False, allow_blank=True` - the
# write-only replacement pattern (Checkpoint 22 §21): omitted/blank
# means "leave unchanged," a non-blank value means "replace." Enforced
# at the view layer (infrastructure/api/settings_views.py), which
# translates a blank string into `None` before calling the repository
# (`None` = "no change" at that layer - see
# application/repositories/provider_settings.py's own docstring).


class DhanSettingsSaveRequestSerializer(serializers.Serializer[dict[str, object]]):
    client_id = serializers.CharField(required=False, allow_blank=True)
    access_token = serializers.CharField(required=False, allow_blank=True)
    enabled = serializers.BooleanField(required=False)


class TelegramSettingsSaveRequestSerializer(serializers.Serializer[dict[str, object]]):
    bot_token = serializers.CharField(required=False, allow_blank=True)
    channel_id = serializers.CharField(required=False, allow_blank=True)
    enabled = serializers.BooleanField(required=False)


class DiscordSettingsSaveRequestSerializer(serializers.Serializer[dict[str, object]]):
    webhook_url = serializers.CharField(required=False, allow_blank=True)
    enabled = serializers.BooleanField(required=False)
