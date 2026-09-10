# File: src/intraday/application/contracts/screening.py
#
# CHECKPOINT-SCANNER-B, Phase B of SCANNER_BUILDER_ROADMAP.md: wire-
# facing contracts for the read-only, Historical-mode-only discretionary
# screening endpoint. Mirrors `backtesting.py`'s own
# `CoveragePreviewRequestSerializer`/`...ResponseSerializer` shape (the
# established "read-only preview, no persistence" pattern this project
# already has) rather than inventing a new request/response idiom.
from __future__ import annotations

from rest_framework import serializers


class ScreeningConditionRequestSerializer(serializers.Serializer[None]):
    field_id = serializers.CharField()
    operator = serializers.ChoiceField(choices=[">", "<", ">=", "<=", "=="])
    # Accepted as a string on the wire — the view parses it as a Decimal
    # constant if it looks numeric, otherwise passes it through as-is
    # (a field-vs-field reference or a literal categorical constant,
    # exactly the two cases `domain.screening.contracts.ScreeningCondition.comparison`
    # and `evaluate_condition()` already resolve — see the view's own
    # `_parse_comparison()` for the parse, not duplicated here).
    comparison = serializers.CharField()


class ScreeningEvaluateRequestSerializer(serializers.Serializer[None]):
    conditions = ScreeningConditionRequestSerializer(many=True, allow_empty=False)
    combinator = serializers.ChoiceField(choices=["AND", "OR"])
    instrument_ids = serializers.ListField(child=serializers.CharField(), min_length=1)
    timeframe = serializers.CharField()
    start_date = serializers.DateField()
    end_date = serializers.DateField()


class ScreeningInstrumentResultSerializer(serializers.Serializer[None]):
    instrument_id = serializers.CharField()
    # HONEST labeling (this checkpoint's own explicit requirement): an
    # instrument whose requested range is not gate-verified is reported
    # as its own distinct status, never silently folded into "no match" -
    # a trader must be able to tell "I checked and it didn't match" apart
    # from "I couldn't actually check this."
    status = serializers.ChoiceField(choices=["MATCHED", "NO_MATCH", "NOT_GATE_VERIFIED"])
    matched_condition_details = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )
    # Populated ONLY when status == "NOT_GATE_VERIFIED" - the real,
    # underlying `ResearchDataRejectedError` reason/detail, the exact
    # same gate every backtest/research consumer in this project already
    # relies on (`ResearchDataGateService`), never a screening-specific
    # re-implementation of "is this data trustworthy."
    coverage_detail = serializers.CharField(required=False, allow_blank=True, default="")


class ScreeningEvaluateResponseSerializer(serializers.Serializer[None]):
    mode = serializers.CharField()  # always "HISTORICAL" in this phase - see the view's own comment
    results = ScreeningInstrumentResultSerializer(many=True)
    matched_count = serializers.IntegerField()
    evaluated_count = serializers.IntegerField()
    not_gate_verified_count = serializers.IntegerField()


__all__ = [
    "ScreeningConditionRequestSerializer",
    "ScreeningEvaluateRequestSerializer",
    "ScreeningInstrumentResultSerializer",
    "ScreeningEvaluateResponseSerializer",
]
