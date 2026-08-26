# File: src/intraday/application/contracts/research.py
#
# Checkpoint 64.89: typed wire contracts for the read-only RESEARCH
# report - traceability coverage, feature/outcome analysis, feature
# interaction, symbol robustness, time-of-day - built entirely on top of
# `infrastructure.persistence.research_correlation`, which itself reads only
# through the existing `DjangoCorrelationRepository`. No new persistence.
#
# Every numeric research result carries `observation_count` and `status`
# (`OK`/`INSUFFICIENT_SAMPLE`/`NO_DATA`) alongside its value fields, so a
# client can never mistake an unpopulated `null` metric for a zero.
from __future__ import annotations

from rest_framework import serializers


class ResearchTraceabilityCoverageSerializer(serializers.Serializer[dict[str, object]]):
    total_signals = serializers.IntegerField()
    signals_with_evidence = serializers.IntegerField()
    signals_with_orders = serializers.IntegerField()
    signals_with_trades = serializers.IntegerField()
    signals_with_realized_outcome = serializers.IntegerField()
    evidence_coverage_pct = serializers.FloatField(allow_null=True)
    order_coverage_pct = serializers.FloatField(allow_null=True)
    trade_coverage_pct = serializers.FloatField(allow_null=True)
    outcome_coverage_pct = serializers.FloatField(allow_null=True)


class ResearchFeatureOutcomeSerializer(serializers.Serializer[dict[str, object]]):
    field_id = serializers.CharField()
    observation_count = serializers.IntegerField()
    status = serializers.CharField()
    mean_outcome = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True)
    median_outcome = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True)
    win_rate = serializers.FloatField(allow_null=True)
    loss_rate = serializers.FloatField(allow_null=True)
    expectancy = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True)
    profit_factor = serializers.FloatField(allow_null=True)


class ResearchFeatureInteractionSerializer(serializers.Serializer[dict[str, object]]):
    field_id_a = serializers.CharField()
    field_id_b = serializers.CharField()
    observation_count = serializers.IntegerField()
    status = serializers.CharField()
    mean_outcome = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True)


class ResearchSymbolOutcomeSerializer(serializers.Serializer[dict[str, object]]):
    instrument_id = serializers.CharField()
    observation_count = serializers.IntegerField()
    status = serializers.CharField()
    mean_outcome = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True)
    win_rate = serializers.FloatField(allow_null=True)


class ResearchTimeOfDaySerializer(serializers.Serializer[dict[str, object]]):
    bucket = serializers.CharField()
    observation_count = serializers.IntegerField()
    status = serializers.CharField()
    mean_outcome = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True)
    win_rate = serializers.FloatField(allow_null=True)


class ResearchReportSerializer(serializers.Serializer[dict[str, object]]):
    """The full research report. Descriptive only - see the module
    docstring on `research_correlation.py`. Nothing in this response is a
    causal claim, a strategy parameter, or a production threshold."""

    min_sample_size = serializers.IntegerField()
    traceability_coverage = ResearchTraceabilityCoverageSerializer()
    feature_outcome = ResearchFeatureOutcomeSerializer(many=True)
    feature_interaction = ResearchFeatureInteractionSerializer(many=True)
    symbol_robustness = ResearchSymbolOutcomeSerializer(many=True)
    time_of_day = ResearchTimeOfDaySerializer(many=True)


__all__ = [
    "ResearchTraceabilityCoverageSerializer",
    "ResearchFeatureOutcomeSerializer",
    "ResearchFeatureInteractionSerializer",
    "ResearchSymbolOutcomeSerializer",
    "ResearchTimeOfDaySerializer",
    "ResearchReportSerializer",
]
