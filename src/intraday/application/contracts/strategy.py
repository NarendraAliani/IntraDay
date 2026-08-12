# File: src/intraday/application/contracts/strategy.py
#
# Wire-facing contract for the strategy-version API resource (Checkpoint
# 8). Represents `application.config_schema.records.StrategyVersionSnapshot`
# (Checkpoint 8), wrapping `domain.strategy.StrategyVersion` (Checkpoint 5).
from __future__ import annotations

from rest_framework import serializers


class StrategyVersionResponseSerializer(serializers.Serializer[None]):
    """Response shape for a strategy version. Identity is the 3-tuple
    (specification_version, code_version, configuration_version), matching
    `domain.strategy.StrategyVersion`'s own shape — `universe_version` may
    differ across otherwise-identical records. `is_active` is computed by
    the view, as in the sibling serializers."""

    strategy_id = serializers.CharField()
    specification_version = serializers.CharField()
    code_version = serializers.CharField()
    configuration_version = serializers.CharField()
    universe_version = serializers.CharField()
    timeframe = serializers.CharField()
    maturity_state = serializers.CharField()
    created_at = serializers.DateTimeField()
    is_active = serializers.BooleanField()
