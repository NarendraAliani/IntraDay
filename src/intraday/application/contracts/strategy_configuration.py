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


class RequiredFeatureSerializer(serializers.Serializer[None]):
    """Checkpoint 64.81: ONE feature a strategy configuration genuinely
    requires, expressed with canonical identity - closing Checkpoint
    64.80-F3's gap 1 (`required_features(config)` existed but was never
    exposed, so Features -> Strategy was only PARTIAL).

    `Strategy.required_features()` itself is completely unchanged; this
    only RESOLVES and PRESENTS what it already returns."""

    feature_name = serializers.CharField()
    """Exactly what `required_features(config)` returned, verbatim
    (e.g. `"ema_12"`). Note this is a PARAMETERIZED feature name, not a
    registry `field_id` - the distinction that made programmatic
    correlation impossible before this checkpoint."""
    field_id = serializers.CharField(allow_null=True)
    """The canonical `FieldDefinition.field_id` (e.g. `"ema"`) that
    `feature_name` resolves to, or `null` when it does not resolve to a
    registered field. Resolved by the platform's own feature-name parse,
    never guessed from a display label."""
    display_name = serializers.CharField(allow_null=True)
    """The registered field's `display_name` (e.g. `"Exponential Moving
    Average"`), or `null` when `field_id` is `null`. Presentation only -
    never an identifier."""
    parameters = serializers.ListField(child=serializers.IntegerField())
    """The numeric parameters baked into `feature_name` (e.g. `[12]` for
    `"ema_12"`, `[12, 26, 9]` for `"macd_hist_12_26_9"`, `[]` for a
    parameterless feature)."""


class StrategyConfigurationResponseSerializer(serializers.Serializer[None]):
    strategy_id = serializers.CharField()
    specification_version = serializers.CharField()
    code_version = serializers.CharField()
    configuration_version = serializers.CharField()
    values = serializers.JSONField()
    created_at = serializers.DateTimeField()
    created_by = serializers.CharField()
    required_features = RequiredFeatureSerializer(many=True, allow_null=True)
    """Checkpoint 64.81: the features THIS configuration's own stored
    values actually require, resolved by calling the strategy's own
    `required_features(config)`.

    `null` - never a fabricated or empty list - when the resolution
    cannot honestly be performed for this configuration. That is a real
    case, not a theoretical one: `required_features()` is defined over a
    VALIDATED configuration and reads its values directly (e.g.
    `require_int(config.values, "fast_lookback")`), so a stored
    configuration whose values are incomplete or no longer satisfy the
    strategy's current schema raises rather than returning a list. An
    empty list would falsely assert "this strategy needs no features";
    `null` honestly says "this could not be resolved". See
    `_resolved_required_features()` in `strategy_configuration_views.py`
    for the exact boundary."""
