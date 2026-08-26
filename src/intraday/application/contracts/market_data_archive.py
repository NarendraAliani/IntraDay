# File: src/intraday/application/contracts/market_data_archive.py
#
# Checkpoint 64.83: the EXPLICIT, TYPED wire contracts for the read-only
# archive and reconciliation query surface. Phase 9 forbids
# `Dict[str, Any]` for these primary responses, so every nested shape is
# a declared serializer and the generated OpenAPI document and frontend
# TypeScript carry real named types rather than opaque objects.
#
# Vocabulary is REUSED verbatim from the existing domain, never
# reinvented: field names match
# `application.repositories.market_data_archive.ArchiveDayRecord`
# (64.73) and `domain.market_data.reconciliation.ReconciliationReport`
# (64.79). A caller that understands those understands these.
#
# THE NULL RULE, enforced by tests: `null` means "this platform does not
# have this value", `0` means "this platform measured zero". They are
# never interchanged. `expected_bar_count` is `null` - not `0` - for a
# timeframe whose bar boundaries do not align with the NSE session,
# because no defensible expected count exists for it (see
# `archive.is_completeness_supported`), and a `0` there would read as
# "nothing was expected", which is a different and false claim.
from __future__ import annotations

from rest_framework import serializers


class ArchiveCellSerializer(serializers.Serializer[dict[str, object]]):
    """One archived (symbol, timeframe, data_source) cell of one trading
    date - the persisted 64.73 projection, read back unchanged."""

    trading_date = serializers.DateField()
    symbol = serializers.CharField()
    timeframe = serializers.CharField()
    data_source = serializers.CharField(allow_null=True)
    """`null` when the ingestion that produced this cell recorded no
    provenance (every row written before migration 0029). Deliberately
    not defaulted to a plausible provider name."""

    archive_status = serializers.CharField()
    """One of `NOT_OBSERVED` / `IN_PROGRESS` / `PARTIAL` / `COMPLETE` /
    `FAILED` - `domain.market_data.archive.ArchiveStatus`, unchanged.
    `COMPLETE` is the ONLY value entitling a consumer to treat the day
    as a whole-session series."""
    reason = serializers.CharField()
    """The machine-readable WHY behind `archive_status`, e.g.
    `"missing_bars:374"`, `"session_not_closed"`, `"non_trading_day"`."""

    completeness_supported = serializers.BooleanField()
    """`false` for TICK/DAY/30m/1h, whose bar boundaries do not align
    with the 09:15-15:30 IST session. Such a cell can NEVER be
    `COMPLETE`, and its counts below are `null`."""

    expected_bar_count = serializers.IntegerField(allow_null=True)
    """`null` when `completeness_supported` is false - see the null rule
    in this module's header."""
    closed_bar_count = serializers.IntegerField()
    forming_bar_count = serializers.IntegerField()
    missing_bar_count = serializers.IntegerField(allow_null=True)
    """`null` when completeness is unsupported: "how many are missing"
    is unanswerable without an expected series."""
    duplicate_bar_count = serializers.IntegerField()
    quote_observation_count = serializers.IntegerField()

    first_observation = serializers.DateTimeField(allow_null=True)
    last_observation = serializers.DateTimeField(allow_null=True)

    reconciliation_status = serializers.CharField()
    """What the STORED row claims: `NOT_RECONCILED` / `RECONCILED` /
    `MISMATCH`. This is the archive's own record, NOT the result of
    running a comparison - for that, call the reconciliation endpoint.
    The two are separate claims and are never merged.
    `archive_status: "COMPLETE"` together with
    `reconciliation_status: "NOT_RECONCILED"` is a VALID and currently
    universal combination: complete is not validated."""
    reconciled_at = serializers.DateTimeField(allow_null=True)
    """Checkpoint 64.84: `null` until a comparison has ACTUALLY run for
    this cell. Never stamped merely because a persistence API was
    called - `NOT_RECONCILED` always leaves this `null`."""
    computed_at = serializers.DateTimeField(allow_null=True)

    reconciliation_outcome = serializers.CharField()
    """Checkpoint 64.84: the EXACT persisted verdict -
    `domain.market_data.reconciliation.ReconciliationOutcome`:
    `NOT_RECONCILED` / `PASS` / `PARTIAL` / `FAIL`. `reconciliation_status`
    above is its coarse three-valued projection, in which `PARTIAL`
    appears as `NOT_RECONCILED`; read this field when that distinction
    matters."""
    reconciliation_reason = serializers.CharField()
    """The WHY behind the persisted outcome, e.g.
    `"no_reference_bars_available"`. Empty string when no reconciliation
    has been persisted. Distinct from `reason`, which explains
    `archive_status`."""
    reconciliation_evidence_source = serializers.CharField(allow_null=True)
    """WHERE the persisted verdict's reference series came from. `null`
    when no reconciliation has been persisted for this cell. The only
    source wired up today is Dhan's historical-candle REST API, which is
    NOT independent of Dhan's live feed."""


class ArchiveDayResponseSerializer(serializers.Serializer[dict[str, object]]):
    """The whole-day answer to "what does the archive hold for date X?"."""

    trading_date = serializers.DateField()
    exchange = serializers.CharField()
    is_trading_day = serializers.BooleanField()
    """`false` for a weekend or NSE holiday, in which case an empty
    archive is CORRECT rather than an operational gap."""
    archive_status = serializers.CharField()
    """The WORST cell status on the day. A day is `COMPLETE` only when
    every cell on it is - one un-observed symbol can never hide behind a
    majority of healthy ones."""
    symbol_count = serializers.IntegerField()
    cell_count = serializers.IntegerField()
    symbol_filter = serializers.CharField(allow_null=True)
    timeframe_filter = serializers.CharField(allow_null=True)
    """Echo of the applied query filters, so a caller can never mistake
    a filtered subset for the whole day."""
    cells = ArchiveCellSerializer(many=True)


class ReconciliationMismatchSerializer(serializers.Serializer[dict[str, object]]):
    """One field of one bar disagreeing beyond tolerance. Both values
    are kept - "3 bars mismatched" alone would not be actionable."""

    timestamp = serializers.DateTimeField()
    # `type: ignore[assignment]` for the same reason documented on
    # `correlation.CorrelationFeatureEvidenceSerializer.label`: a DRF
    # serializer attribute named `field_name` collides with
    # `Field.field_name` in djangorestframework-stubs while being
    # entirely correct at runtime. The name matches
    # `domain.market_data.reconciliation.BarFieldMismatch.field_name`
    # verbatim and is deliberately not renamed to appease the stub.
    field_name = serializers.CharField()  # type: ignore[assignment]
    observed = serializers.DecimalField(max_digits=20, decimal_places=6)
    reference = serializers.DecimalField(max_digits=20, decimal_places=6)


class ReconciliationCellSerializer(serializers.Serializer[dict[str, object]]):
    """The result of comparing ONE archived (date, symbol, timeframe)
    cell against the independent reference series - the 64.79
    `ReconciliationReport`, read out unchanged."""

    trading_date = serializers.DateField()
    symbol = serializers.CharField()
    timeframe = serializers.CharField()

    reconciliation_status = serializers.CharField()
    """`domain.market_data.reconciliation.ReconciliationOutcome`:
    `NOT_RECONCILED` / `PASS` / `PARTIAL` / `FAIL`. `NOT_RECONCILED` is
    a first-class outcome, not an error - it is the honest answer
    whenever no usable reference series exists. `PASS` is NEVER returned
    merely because the comparison ran."""
    reason = serializers.CharField()
    evidence_source = serializers.CharField()
    """WHERE the reference series came from. Required to be non-empty by
    the domain - an unattributed reference is not evidence.

    IMPORTANT, and the reason this field is mandatory on the wire: the
    only reference pipeline wired up today is Dhan's historical-candle
    REST API, which is NOT independent of Dhan. A `PASS` from this
    source would be Dhan-vs-Dhan corroboration and would NOT satisfy
    TRADING_GRADE_BAR condition 3 (candle authority)."""

    expected_bar_count = serializers.IntegerField(allow_null=True)
    observed_count = serializers.IntegerField()
    reference_count = serializers.IntegerField()
    matched_count = serializers.IntegerField()
    missing_observed_count = serializers.IntegerField()
    missing_reference_count = serializers.IntegerField()
    duplicate_observed_count = serializers.IntegerField()
    duplicate_reference_count = serializers.IntegerField()
    unmatched_observed_count = serializers.IntegerField()
    unmatched_reference_count = serializers.IntegerField()

    ohlc_mismatch_count = serializers.IntegerField()
    volume_compared = serializers.BooleanField()
    """`false` by default and today always: this platform's live bars
    carry `Decimal("0")` volume for any source that never reported
    `cumulative_volume`, so comparing them would report a fabricated
    FAIL. `volume_mismatch_count` is `null` whenever this is `false`."""
    volume_mismatch_count = serializers.IntegerField(allow_null=True)
    timestamp_tolerance_seconds = serializers.IntegerField()
    price_tolerance = serializers.DecimalField(max_digits=12, decimal_places=6)

    observed_first_timestamp = serializers.DateTimeField(allow_null=True)
    observed_last_timestamp = serializers.DateTimeField(allow_null=True)
    reference_first_timestamp = serializers.DateTimeField(allow_null=True)
    reference_last_timestamp = serializers.DateTimeField(allow_null=True)

    mismatches = ReconciliationMismatchSerializer(many=True)


class ReconciliationDayResponseSerializer(serializers.Serializer[dict[str, object]]):
    trading_date = serializers.DateField()
    exchange = serializers.CharField()
    timeframe = serializers.CharField()
    is_trading_day = serializers.BooleanField()
    reconciliation_status = serializers.CharField()
    """The WORST outcome across every cell. An empty set of cells is
    `NOT_RECONCILED`, never `PASS` - "we reconciled nothing" must never
    read as "everything agreed"."""
    evidence_source = serializers.CharField()
    cell_count = serializers.IntegerField()
    symbol_filter = serializers.CharField(allow_null=True)
    cells = ReconciliationCellSerializer(many=True)


__all__ = [
    "ArchiveCellSerializer",
    "ArchiveDayResponseSerializer",
    "ReconciliationCellSerializer",
    "ReconciliationDayResponseSerializer",
    "ReconciliationMismatchSerializer",
]
