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


class RiskLimitsSerializer(serializers.Serializer[dict[str, object]]):
    """Mirrors `domain.risk.RiskLimits`'s three fields — same NUMERIC(14,2)
    precision as `infrastructure/persistence/models.py`'s
    `RiskConfigurationVersion`, so a value that round-trips through the
    API matches exactly what's stored.

    Checkpoint 17.2: unlike every other serializer in this codebase
    (`serializers.Serializer[None]` — declared only for OpenAPI schema
    generation via `@extend_schema`, never actually instantiated with a
    real object), this one and `RiskConfigurationResponseSerializer`
    below ARE now actually used to serialize a real response
    (`infrastructure/api/risk_views.py`'s `_to_response_dict`) — the
    generic parameter reflects that: the real instance passed in is a
    plain `dict[str, object]` (nested dicts for `limits`), never `None`.
    This was the fix for the Decimal-serialized-as-float defect: DRF's
    `Response()` with a raw, un-serialized dict bypasses `DecimalField`/
    `COERCE_DECIMAL_TO_STRING` entirely and falls back to its own
    `JSONEncoder`, which converts `Decimal` to `float` — silently
    reintroducing binary floating-point into a financial-precision
    contract."""

    max_intraday_loss = serializers.DecimalField(max_digits=14, decimal_places=2)
    max_position_size = serializers.DecimalField(max_digits=14, decimal_places=2)
    max_per_trade_risk = serializers.DecimalField(max_digits=14, decimal_places=2)


class RiskConfigurationResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Response shape for a risk-configuration version. `is_active` is
    computed by the view (by comparing against the service's
    `get_active()` result), not stored on the domain/application record
    itself — "active" is a query-time relationship, not a property of
    the immutable version. See `RiskLimitsSerializer`'s docstring for why
    this serializer's generic parameter (and actual usage) differs from
    every sibling serializer in this codebase."""

    risk_configuration_id = serializers.CharField()
    version = serializers.CharField()
    limits = RiskLimitsSerializer()
    created_at = serializers.DateTimeField()
    is_active = serializers.BooleanField()
