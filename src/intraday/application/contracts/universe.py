# File: src/intraday/application/contracts/universe.py
#
# Wire-facing contract for the universe API resource (Checkpoint 8).
# Represents `application.config_schema.records.UniverseRecord`
# (Checkpoint 8), wrapping `domain.universe.Universe` (Checkpoint 5).
from __future__ import annotations

from rest_framework import serializers


class UniverseMemberSerializer(serializers.Serializer[None]):
    """Mirrors `domain.universe.UniverseMember` — `instrument_id` is the
    domain-owned, broker-neutral identity (e.g. "NSE:RELIANCE"), never a
    broker token (Checkpoint 5)."""

    instrument_id = serializers.CharField()
    status = serializers.CharField()


class UniverseResponseSerializer(serializers.Serializer[None]):
    """Response shape for a universe version. `is_active` is computed by
    the view — see `RiskConfigurationResponseSerializer`'s docstring for
    the same rationale."""

    universe_id = serializers.CharField()
    version = serializers.CharField()
    exchange = serializers.CharField()
    members = UniverseMemberSerializer(many=True)
    created_at = serializers.DateTimeField()
    is_active = serializers.BooleanField()
