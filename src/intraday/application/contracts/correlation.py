# File: src/intraday/application/contracts/correlation.py
#
# Checkpoint 64.82: the EXPLICIT, TYPED wire contracts for the
# correlation query surface. Phase 9 forbids `Dict[str, Any]` for the
# main correlation response, so every nested shape below is a declared
# serializer - the generated OpenAPI document and the generated frontend
# TypeScript therefore carry real named types, not opaque objects.
#
# Vocabulary is deliberately REUSED, not reinvented: field names match
# `signal_views.SignalResponseSerializer`
# (`signal_id`/`strategy_id`/`instrument_id`/`direction`/`price`/
# `timeframe`/`signal_timestamp`/`risk_status`/`order_status`/
# `scan_run_id`/`strategy_version_identifier`), evidence rows match
# `signal_views.SignalEvidenceFieldSerializer`, and required-feature rows
# match `strategy_configuration.RequiredFeatureSerializer`. A client that
# already understands the signals API understands these responses.
from __future__ import annotations

from rest_framework import serializers


class CorrelationFeatureEvidenceSerializer(serializers.Serializer[dict[str, object]]):
    """One row the STRATEGY ITSELF chose to record as its explanation.

    This is NOT a causal proof and NOT the same thing as a required
    feature - see `CorrelationStrategyTraceResponseSerializer`."""

    # `type: ignore[assignment]` for the reason documented on
    # `signal_views.SignalEvidenceFieldSerializer`: a DRF serializer
    # attribute named `label` collides with `Field.label` in
    # djangorestframework-stubs while being entirely correct at runtime.
    label = serializers.CharField()  # type: ignore[assignment]
    value = serializers.CharField()
    feature_name = serializers.CharField(allow_null=True)
    """Verbatim what the strategy attributed the row to (e.g. `"ema_12"`),
    or `null` for a genuinely non-feature row such as `Price`."""
    field_id = serializers.CharField(allow_null=True)
    """The canonical `FieldDefinition.field_id`, or `null` when the row
    carries no feature name or it resolves to no registered field.
    Legacy pre-64.81 evidence rows are always `null` here - never
    back-filled with a guess."""


class CorrelationOrderSerializer(serializers.Serializer[dict[str, object]]):
    """A paper order reached by EXACT `signal_id` equality."""

    order_id = serializers.CharField()
    instrument_id = serializers.CharField()
    side = serializers.CharField()
    order_type = serializers.CharField()
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4)
    filled_quantity = serializers.DecimalField(max_digits=18, decimal_places=4)
    status = serializers.CharField()
    created_at = serializers.DateTimeField()


class CorrelationTradeSerializer(serializers.Serializer[dict[str, object]]):
    """A completed paper round trip reached by EXACT `signal_id`
    equality."""

    trade_id = serializers.CharField()
    instrument_id = serializers.CharField()
    direction = serializers.CharField()
    order_ids = serializers.ListField(child=serializers.CharField())
    entry_price = serializers.DecimalField(max_digits=18, decimal_places=4)
    exit_price = serializers.DecimalField(max_digits=18, decimal_places=4)
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4)
    realized_pnl = serializers.DecimalField(max_digits=18, decimal_places=4)
    costs = serializers.DecimalField(max_digits=18, decimal_places=4)
    opened_at = serializers.DateTimeField()
    closed_at = serializers.DateTimeField()


class CorrelationTraceSerializer(serializers.Serializer[dict[str, object]]):
    """The full RECORDED lineage of one signal.

    This response exposes recorded relationships. It does not establish
    causality beyond the relationships already represented in the
    domain."""

    signal_id = serializers.CharField()
    strategy_id = serializers.CharField()
    strategy_version_identifier = serializers.CharField(allow_null=True)
    """`null` for signals recorded before version tracking (64.81) -
    never back-filled from the strategy's current active version."""
    scan_run_id = serializers.CharField(allow_null=True)
    """`null` when the signal was genuinely not produced by a tracked
    scanner run (replay sessions and direct service calls are real,
    supported workflows). Timestamp-shaped and preserved verbatim."""
    instrument_id = serializers.CharField()
    direction = serializers.CharField()
    price = serializers.DecimalField(max_digits=18, decimal_places=4)
    timeframe = serializers.CharField(allow_blank=True)
    signal_timestamp = serializers.DateTimeField()
    risk_status = serializers.CharField()
    order_status = serializers.CharField(allow_null=True)
    evidence = CorrelationFeatureEvidenceSerializer(many=True)
    """Empty list when the strategy recorded no evidence. An empty list
    is NOT a claim that no feature was involved."""
    evidence_schema_version = serializers.CharField(allow_null=True)
    orders = CorrelationOrderSerializer(many=True)
    trades = CorrelationTradeSerializer(many=True)
    realized_pnl = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True)
    """Sum over LINKED trades. `null` means "no trade is linked to this
    signal" and is deliberately distinct from `0` (a linked trade that
    broke even)."""
    market_data_outcome_status = serializers.CharField()
    """Checkpoint 64.83 Phase 7: whether ARCHIVED MARKET-DATA EVIDENCE
    exists for the same instrument and trading date as this signal, and
    how complete and how validated it is. One of
    `ARCHIVE_NOT_AVAILABLE` / `ARCHIVE_PARTIAL` /
    `ARCHIVE_COMPLETE_NOT_RECONCILED` / `ARCHIVE_RECONCILED` /
    `ARCHIVE_RECONCILIATION_FAILED`.

    64.82 always returned `"ARCHIVE_API_NOT_IMPLEMENTED"` here because
    no archive API existed; that placeholder is gone, resolved against
    the real 64.73 archive projection.

    THIS IS NOT A CAUSAL CLAIM. It says archived evidence for the same
    (instrument, date) does or does not exist. It does NOT say the
    strategy read that data, that the data produced this signal, or that
    the data caused the realised P&L - the platform stores no link
    between a signal and the specific bars a strategy consumed."""


class CorrelationScanRunTraceResponseSerializer(serializers.Serializer[dict[str, object]]):
    scan_run_id = serializers.CharField()
    signal_count = serializers.IntegerField()
    signals = CorrelationTraceSerializer(many=True)
    strategy_ids = serializers.ListField(child=serializers.CharField())
    """Only strategies genuinely recorded on THIS run's signals."""
    scan_started_at = serializers.DateTimeField(allow_null=True)
    timeframe = serializers.CharField(allow_null=True)
    status = serializers.CharField(allow_null=True)
    run_metadata_available = serializers.BooleanField()
    """`false` when the scanner-progress singleton no longer holds this
    run's id (each run overwrites it). The three fields above are then
    `null` because the platform genuinely does not retain per-run
    scanner history - not because the run failed."""


class CorrelationRequiredFeatureSerializer(serializers.Serializer[dict[str, object]]):
    """Same shape as
    `strategy_configuration.RequiredFeatureSerializer` - reused
    vocabulary, declared separately only so the correlation contract is
    self-contained."""

    feature_name = serializers.CharField()
    field_id = serializers.CharField(allow_null=True)
    display_name = serializers.CharField(allow_null=True)
    parameters = serializers.ListField(child=serializers.IntegerField())


class CorrelationStrategyTraceResponseSerializer(serializers.Serializer[dict[str, object]]):
    strategy_id = serializers.CharField()
    specification_version = serializers.CharField()
    code_version = serializers.CharField()
    configuration_version = serializers.CharField()
    strategy_version_identifier = serializers.CharField()
    required_features = CorrelationRequiredFeatureSerializer(many=True, allow_null=True)
    """What this configuration DECLARES it needs. `null` (never an empty
    list) when it cannot honestly be resolved for this stored
    configuration.

    CRITICAL DISTINCTION, preserved on purpose: a strategy may REQUIRE a
    feature without ever CITING it in a signal's evidence. This list is
    never merged with, and never implies, the `evidence` on the traces
    below."""
    signal_count = serializers.IntegerField()
    signals = CorrelationTraceSerializer(many=True)


class CorrelationTradeTraceResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Reverse lookup: outcome -> decision."""

    trade_id = serializers.CharField()
    signal_id = serializers.CharField(allow_null=True)
    """`null` for a manually-submitted trade, or a trade recorded before
    64.81. The trace stops there - no plausible signal is searched for."""
    trace = CorrelationTraceSerializer(allow_null=True)
    """`null` whenever `signal_id` is `null`, and also in the genuine
    edge case where the linked signal row itself is absent."""


__all__ = [
    "CorrelationFeatureEvidenceSerializer",
    "CorrelationOrderSerializer",
    "CorrelationRequiredFeatureSerializer",
    "CorrelationScanRunTraceResponseSerializer",
    "CorrelationStrategyTraceResponseSerializer",
    "CorrelationTradeSerializer",
    "CorrelationTradeTraceResponseSerializer",
    "CorrelationTraceSerializer",
]
