# File: src/intraday/application/contracts/audit.py
#
# Wire-facing (transport) contract for the Checkpoint 12 audit read API.
# Represents `control_plane.audit.events.AuditEvent` - schema-only, same
# pattern as risk.py/universe.py/strategy.py.
from __future__ import annotations

from rest_framework import serializers


class AuditEventResponseSerializer(serializers.Serializer[None]):
    """Response shape for one durable audit record. Read-only by
    construction - this serializer is never used to validate/deserialize
    a request body; there is no write endpoint for audit events."""

    actor = serializers.CharField()
    action = serializers.CharField()
    resource_type = serializers.CharField()
    resource_id = serializers.CharField()
    version = serializers.CharField()
    previous_version = serializers.CharField(allow_null=True)
    outcome = serializers.ChoiceField(choices=["activated", "already_active", "rejected"])
    occurred_at = serializers.DateTimeField()
    request_id = serializers.CharField()
