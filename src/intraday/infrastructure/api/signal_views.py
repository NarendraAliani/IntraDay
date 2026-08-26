# File: src/intraday/infrastructure/api/signal_views.py
#
# Checkpoint 62.x: the FIRST read-only API for real, persisted
# strategy signals (`SignalRecord`, `infrastructure/persistence/
# signal_repository.py`) - closes a gap a fresh audit this checkpoint
# found: no signal-listing endpoint existed anywhere in this project,
# which would have forced an "active signal monitor" UI to either
# fabricate rows or go unbuilt. Mirrors `paper_trading_views.py`'s own
# established shape (thin view, translates HTTP <-> repository).
#
# Checkpoint 64.9: the Signal Operations Center needs the FULL chain
# (TradePlan + communication status), not just the bare signal - the
# response now includes both, sourced from the SAME repository's
# already-enriched `EnrichedSignal` (no second query layer, no
# duplicated join logic). A new detail endpoint exposes the full
# communication attempt history for one signal (never fetched for the
# whole list - the list view only needs "current status").
#
# RBAC: read-only, requires `configuration.read` (any authenticated
# user) - matches every other read-only market/signal endpoint in this
# project. No order-placement code path exists in this module.
from __future__ import annotations

import datetime as dt

from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from intraday.infrastructure.persistence.models import CommunicationLedgerRecord
from intraday.infrastructure.persistence.signal_repository import (
    ChannelStatus,
    DjangoSignalRepository,
    EnrichedSignal,
    SignalEvidenceEnrichment,
)


class TradePlanFieldSerializer(serializers.Serializer[dict[str, object]]):
    entry_price = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True)
    stop_loss = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True)
    target_1 = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True)
    target_2 = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True)
    target_3 = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True)
    trailing_stop_loss = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True)
    calculation_method = serializers.CharField(allow_blank=True)


class ChannelStatusSerializer(serializers.Serializer[dict[str, object]]):
    status = serializers.CharField()
    attempted_at = serializers.DateTimeField(allow_null=True)
    delivered_at = serializers.DateTimeField(allow_null=True)
    retry_count = serializers.IntegerField()
    error_message = serializers.CharField(allow_blank=True)


class SignalEvidenceFieldSerializer(serializers.Serializer[dict[str, object]]):
    """Checkpoint 64.81: the explicit, typed evidence-field schema that
    replaces the previous untyped `DictField` payload (Phase 7's "avoid
    generic dict-of-unknown where a canonical identifier is available").

    Deliberately NOT named with an attribute called `fields` anywhere -
    see `SignalEvidenceSerializer` below for why that name is unusable
    on a DRF `Serializer` subclass."""

    # `type: ignore[assignment]` for the exact, already-documented
    # reason `ReadinessCheckSerializer` records (Checkpoint 64.14): a
    # DRF `Serializer` attribute literally named `label` collides with
    # `Field.label` in djangorestframework-stubs, though it is entirely
    # correct at runtime. Suppressed rather than renamed because
    # `"label"` is the EXISTING wire key that 64.18 established and
    # frontend code already reads - renaming it to satisfy a stubs
    # quirk would be a gratuitous breaking change.
    label = serializers.CharField()  # type: ignore[assignment]
    """Free-text, human-facing, strategy-chosen. Unchanged."""
    value = serializers.CharField()
    """The already-computed value, rendered as a string. Unchanged."""
    feature_name = serializers.CharField(allow_null=True)
    """The resolved feature name the strategy itself attributed this row
    to (e.g. `"ema_12"`), or `null` for a genuinely non-feature row such
    as `Price` or `Direction`. Never derived from `label`."""
    field_id = serializers.CharField(allow_null=True)
    """The canonical `FieldDefinition.field_id` (e.g. `"ema"`) that
    `feature_name` resolves to via the feature registry, or `null` when
    there is no feature name or it does not resolve to a registered
    field. This is the key that makes evidence programmatically
    correlatable with the feature registry and with a strategy's
    `required_features`."""


# Checkpoint 64.81: built via `type()` rather than a normal `class`
# statement for one specific reason - this serializer MUST declare a
# field literally named `fields` (that is the existing wire key, set by
# Checkpoint 64.18), and a class-body assignment of that name collides
# with `Serializer.fields` (a `BindingDict` property) at the
# djangorestframework-stubs level. Building the namespace dynamically
# keeps DRF's own `SerializerMetaclass` field collection working exactly
# as it would for a normal class, while giving the type checker nothing
# to object to. This is used ONLY to describe the OpenAPI shape (see
# `evidence` below); it never serializes anything at runtime, so it
# cannot change a single response byte.
SignalEvidenceSerializer = type(
    "SignalEvidenceSerializer",
    (serializers.Serializer,),
    {
        "schema_version": serializers.CharField(),
        "fields": SignalEvidenceFieldSerializer(many=True),
    },
)


@extend_schema_field(SignalEvidenceSerializer(allow_null=True))
class _EvidenceField(serializers.DictField):
    """Checkpoint 64.81: a `DictField` at RUNTIME (so the response shape
    is byte-for-byte what 64.18 established) that documents itself as the
    typed `SignalEvidence` schema in OpenAPI.

    The annotation MUST live on the class, not on an instance. DRF
    deep-copies declared fields when a serializer is instantiated, and
    `Field.__deepcopy__` rebuilds the field from its recorded
    `_args`/`_kwargs` - silently discarding any attribute set on the
    instance, including the `_spectacular_annotation` that
    `extend_schema_field` attaches. Decorating the class makes the
    annotation survive that copy, which is the difference between the
    generated contract carrying a real typed schema and falling back to
    an opaque `additionalProperties: {}` object."""


class SignalResponseSerializer(serializers.Serializer[dict[str, object]]):
    signal_id = serializers.CharField()
    strategy_id = serializers.CharField()
    instrument_id = serializers.CharField()
    direction = serializers.CharField()
    price = serializers.DecimalField(max_digits=18, decimal_places=4)
    timeframe = serializers.CharField()
    signal_timestamp = serializers.DateTimeField()
    risk_status = serializers.CharField()
    risk_reason = serializers.CharField(allow_blank=True)
    order_status = serializers.CharField(allow_blank=True)
    created_at = serializers.DateTimeField()
    # Checkpoint 64.9: `None` (never a fabricated value) when the
    # evaluating strategy produced no TradePlan - the UI shows
    # "Not provided" for exactly this case.
    trade_plan = TradePlanFieldSerializer(allow_null=True)
    telegram = ChannelStatusSerializer(allow_null=True)
    discord = ChannelStatusSerializer(allow_null=True)
    # Checkpoint 64.18: `None` (never a fabricated value) when no
    # evidence was persisted for this signal (a strategy with no
    # registered describer, or a signal predating this checkpoint).
    # Checkpoint 64.81: still a `DictField` at the OUTER level, for the
    # exact reason documented since 64.18 - a DRF `Serializer` subclass
    # cannot declare an attribute literally named `fields` without
    # colliding with `Serializer.fields` (a `BindingDict` property) at
    # the mypy/djangorestframework-stubs level. What DID change is that
    # the inner field objects are now an explicit, typed, documented
    # schema (`SignalEvidenceFieldSerializer`) instead of anonymous
    # `{label, value}` dicts, and that schema is attached to the
    # generated OpenAPI document via the `@extend_schema_field`-style
    # override on the view (see `_evidence_data`'s own payload).
    # Wire shape: `{"schema_version": str, "fields": [
    #   {"label": str, "value": str, "feature_name": str|null,
    #    "field_id": str|null}]}`.
    evidence = _EvidenceField(allow_null=True)
    # Checkpoint 64.81: the scanner run that produced this signal
    # (`ScannerScanProgress.scan_id`), or `null` when the signal was
    # genuinely not produced by a tracked scanner run - a real,
    # supported workflow (replay sessions, REST-ingestion ticks, direct
    # service calls), never a fabricated identity.
    scan_run_id = serializers.CharField(allow_null=True)
    # Checkpoint 64.81: the flattened
    # `"{spec}:{code}:{config}"` identity of the strategy version that
    # produced this signal - the SAME representation
    # `AuditLogEntry.version_identifier` already uses, so a signal (and
    # any paper trade reached through it) joins to the activation audit
    # trail. `null` for signals recorded before this checkpoint.
    strategy_version_identifier = serializers.CharField(allow_null=True)


class SignalListResponseSerializer(serializers.Serializer[dict[str, object]]):
    items = SignalResponseSerializer(many=True)
    total_count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()


class CommunicationAttemptSerializer(serializers.Serializer[dict[str, object]]):
    communication_id = serializers.CharField()
    channel = serializers.CharField()
    provider = serializers.CharField()
    delivery_status = serializers.CharField()
    attempted_at = serializers.DateTimeField(allow_null=True)
    retry_count = serializers.IntegerField()
    error_message = serializers.CharField(allow_blank=True)
    created_at = serializers.DateTimeField()


class SignalCommunicationHistoryResponseSerializer(serializers.Serializer[dict[str, object]]):
    signal_id = serializers.CharField()
    attempts = CommunicationAttemptSerializer(many=True)


def _channel_status_data(status: ChannelStatus | None) -> dict[str, object] | None:
    if status is None:
        return None
    return {
        "status": status.status,
        "attempted_at": status.attempted_at,
        "delivered_at": status.delivered_at,
        "retry_count": status.retry_count,
        "error_message": status.error_message,
    }


def _enriched_to_response_data(enriched: EnrichedSignal) -> dict[str, object]:
    record = enriched.record
    plan = enriched.trade_plan
    return {
        "signal_id": record.signal_id,
        "strategy_id": record.strategy_id,
        "instrument_id": record.instrument_id,
        "direction": record.direction,
        "price": record.price,
        "timeframe": record.timeframe,
        "signal_timestamp": record.signal_timestamp,
        "risk_status": record.risk_status,
        "risk_reason": record.risk_reason,
        "order_status": record.order_status,
        "created_at": record.created_at,
        # Checkpoint 64.81: blank in the database means "not produced by
        # a tracked scanner run" - surfaced as an honest `null` on the
        # wire rather than an empty string that a client could mistake
        # for a real run identity.
        "scan_run_id": record.scan_run_id or None,
        # Checkpoint 64.81: the exact strategy version that made this
        # decision. Blank in the database means "recorded before version
        # tracking existed" - surfaced as `null`, never as a guess.
        "strategy_version_identifier": record.strategy_version_identifier or None,
        "trade_plan": (
            {
                "entry_price": plan.entry_price,
                "stop_loss": plan.stop_loss,
                "target_1": plan.target_1,
                "target_2": plan.target_2,
                "target_3": plan.target_3,
                "trailing_stop_loss": plan.trailing_stop_loss,
                "calculation_method": plan.calculation_method,
            }
            if plan is not None
            else None
        ),
        "telegram": _channel_status_data(enriched.telegram),
        "discord": _channel_status_data(enriched.discord),
        "evidence": _evidence_data(enriched.evidence),
    }


def _evidence_data(evidence: SignalEvidenceEnrichment | None) -> dict[str, object] | None:
    if evidence is None:
        return None
    return {
        "schema_version": evidence.schema_version,
        # Checkpoint 64.81: `label`/`value` keep their exact existing
        # keys, content, and order - `feature_name`/`field_id` are added
        # alongside them, so an existing consumer reading only the first
        # two keys is completely unaffected.
        "fields": [
            {
                "label": f.label,
                "value": f.value,
                "feature_name": f.feature_name,
                "field_id": f.field_id,
            }
            for f in evidence.fields
        ],
    }


def _parse_datetime(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed


@extend_schema(
    responses={200: SignalListResponseSerializer},
    parameters=[
        OpenApiParameter("risk_status", str, required=False),
        OpenApiParameter("order_status", str, required=False),
        OpenApiParameter("date_from", str, required=False),
        OpenApiParameter("date_to", str, required=False),
        OpenApiParameter("telegram_status", str, required=False),
        OpenApiParameter("discord_status", str, required=False),
        OpenApiParameter("sort", str, required=False),
    ],
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_signals(request: Request) -> Response:
    """Read-only, server-side paginated list of REAL, persisted
    strategy signals - never a fabricated row. Every filter/sort maps
    to a real query parameter `DjangoSignalRepository.list_signals()`
    actually applies - never a frontend-only filter over an unbounded
    fetch. Each item is enriched with its real TradePlan (`None` when
    the strategy produced none) and current Telegram/Discord delivery
    status (`None` when no attempt exists yet)."""
    try:
        page = int(request.query_params.get("page", "1"))
    except ValueError:
        page = 1
    try:
        page_size = int(request.query_params.get("page_size", "25"))
    except ValueError:
        page_size = 25

    result = DjangoSignalRepository().list_signals(
        page=page,
        page_size=page_size,
        strategy_id=request.query_params.get("strategy_id") or None,
        instrument_id=request.query_params.get("instrument_id") or None,
        timeframe=request.query_params.get("timeframe") or None,
        direction=request.query_params.get("direction") or None,
        risk_status=request.query_params.get("risk_status") or None,
        order_status=request.query_params.get("order_status") or None,
        date_from=_parse_datetime(request.query_params.get("date_from")),
        date_to=_parse_datetime(request.query_params.get("date_to")),
        telegram_status=request.query_params.get("telegram_status") or None,
        discord_status=request.query_params.get("discord_status") or None,
        sort=request.query_params.get("sort", "newest"),
    )

    data = SignalListResponseSerializer(
        {
            "items": [_enriched_to_response_data(item) for item in result.items],
            "total_count": result.total_count,
            "page": result.page,
            "page_size": result.page_size,
        }
    ).data
    return Response(data)


@extend_schema(responses={200: SignalCommunicationHistoryResponseSerializer})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def signal_communication_history(request: Request, signal_id: str) -> Response:
    """Checkpoint 64.9: the FULL communication attempt history (every
    retry, not just the current status) for ONE signal - powers the
    signal detail screen's traceability panel. Reuses the existing
    `CommunicationLedgerRecord` table verbatim - no new persistence."""
    attempts = DjangoSignalRepository().get_signal_communication_history(signal_id)
    data = SignalCommunicationHistoryResponseSerializer(
        {
            "signal_id": signal_id,
            "attempts": [_attempt_data(a) for a in attempts],
        }
    ).data
    return Response(data)


def _attempt_data(attempt: CommunicationLedgerRecord) -> dict[str, object]:
    return {
        "communication_id": attempt.communication_id,
        "channel": attempt.channel,
        "provider": attempt.provider,
        "delivery_status": attempt.delivery_status,
        "attempted_at": attempt.attempted_at,
        "retry_count": attempt.retry_count,
        "error_message": attempt.error_message,
        "created_at": attempt.created_at,
    }
