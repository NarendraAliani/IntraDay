# File: src/intraday/application/contracts/strategy_configuration.py
#
# Wire-facing contracts for the Checkpoint 26 strategy-configuration API
# resource. Mirrors application/contracts/strategy.py's structure. The
# single canonical source of parameter metadata is
# `trading_engine.strategy_execution.contracts.ParameterDefinition`/
# `StrategyParameterSchema` and `signal_intelligence.feature_engine.
# field_registry.FieldDefinition` - these serializers only describe the
# WIRE SHAPE of that data, never a second copy of it (Part 4).
#
# `source`/`label`/`required`/`help_text` below are declared serializer
# fields that happen to share a name with an attribute
# `rest_framework.fields.Field` (the common base of `Serializer` itself)
# already defines (Field.source/.label/.required/.help_text). This is
# safe at runtime - DRF's `SerializerMetaclass` pulls declared `Field`
# instances into `_declared_fields` before the class body's plain
# attribute lookup ever matters - but mypy's static type-checker flags
# it as an incompatible override. `# type: ignore[assignment]` is the
# correct, narrow suppression (not `strict = False`), matching this
# project's "explain every ignore" convention.
from __future__ import annotations

from rest_framework import serializers


class FieldDefinitionSerializer(serializers.Serializer[None]):
    field_id = serializers.CharField()
    display_name = serializers.CharField()
    category = serializers.CharField()
    data_type = serializers.CharField()
    source = serializers.CharField()  # type: ignore[assignment]
    timeframe_support = serializers.CharField()
    required_inputs = serializers.ListField(child=serializers.CharField())
    availability = serializers.CharField()
    version = serializers.CharField()
    description = serializers.CharField()


class ParameterDefinitionSerializer(serializers.Serializer[None]):
    parameter_id = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    parameter_type = serializers.CharField()
    required = serializers.BooleanField()  # type: ignore[assignment]
    default = serializers.JSONField(allow_null=True)
    minimum = serializers.JSONField(allow_null=True)
    maximum = serializers.JSONField(allow_null=True)
    allowed_values = serializers.ListField(child=serializers.CharField())
    field_category = serializers.CharField(allow_null=True)
    depends_on = serializers.ListField(child=serializers.CharField())
    help_text = serializers.CharField(allow_blank=True)  # type: ignore[assignment]


class StrategySummarySerializer(serializers.Serializer[None]):
    strategy_id = serializers.CharField()
    display_name = serializers.CharField()
    specification_version = serializers.CharField()
    code_version = serializers.CharField()
    is_active = serializers.BooleanField()


class StrategySchemaSerializer(serializers.Serializer[None]):
    strategy_id = serializers.CharField()
    parameters = ParameterDefinitionSerializer(many=True)


class StrategyConfigurationSaveRequestSerializer(serializers.Serializer[None]):
    specification_version = serializers.CharField()
    code_version = serializers.CharField()
    configuration_version = serializers.CharField()
    values = serializers.JSONField()


class StrategyConfigurationResponseSerializer(serializers.Serializer[None]):
    strategy_id = serializers.CharField()
    specification_version = serializers.CharField()
    code_version = serializers.CharField()
    configuration_version = serializers.CharField()
    values = serializers.JSONField()
    created_at = serializers.DateTimeField()
    created_by = serializers.CharField()
