# File: src/intraday/application/contracts/risk.py
#
# Wire-facing (transport) contract for the risk-configuration API
# resource (Checkpoint 8). Represents
# `application.config_schema.records.RiskConfigurationRecord`
# (Checkpoint 7), itself wrapping `domain.risk.RiskLimits` (Checkpoint
# 5) — never the other way around; this serializer is not the domain
# contract and the domain contract does not know this serializer exists.
from __future__ import annotations

from rest_framework import serializers


class RiskLimitsSerializer(serializers.Serializer[None]):
    """Mirrors `domain.risk.RiskLimits`'s three fields — same NUMERIC(14,2)
    precision as `infrastructure/persistence/models.py`'s
    `RiskConfigurationVersion`, so a value that round-trips through the
    API matches exactly what's stored."""

    max_intraday_loss = serializers.DecimalField(max_digits=14, decimal_places=2)
    max_position_size = serializers.DecimalField(max_digits=14, decimal_places=2)
    max_per_trade_risk = serializers.DecimalField(max_digits=14, decimal_places=2)


class RiskConfigurationResponseSerializer(serializers.Serializer[None]):
    """Response shape for a risk-configuration version. `is_active` is
    computed by the view (by comparing against the service's
    `get_active()` result), not stored on the domain/application record
    itself — "active" is a query-time relationship, not a property of
    the immutable version."""

    risk_configuration_id = serializers.CharField()
    version = serializers.CharField()
    limits = RiskLimitsSerializer()
    created_at = serializers.DateTimeField()
    is_active = serializers.BooleanField()
