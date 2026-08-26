# File: src/intraday/infrastructure/api/strategy_configuration_views.py
#
# DRF views for the Checkpoint 26 strategy-configuration API resource.
# Mirrors strategy_views.py's structure. The frontend's dependent
# dropdowns (Strategy -> Version -> Field -> Parameter controls) consume
# these endpoints exclusively - no duplicated option list exists in
# frontend code (Part 4/6).
from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from intraday.application.config_schema.records import StrategyConfigurationSnapshot
from intraday.application.contracts.errors import ApiErrorSerializer
from intraday.application.contracts.strategy_configuration import (
    FieldDefinitionSerializer,
    StrategyConfigurationResponseSerializer,
    StrategyConfigurationSaveRequestSerializer,
    StrategySchemaSerializer,
    StrategySummarySerializer,
)
from intraday.application.repositories import DuplicateVersionError
from intraday.application.services.errors import ResourceNotFoundError
from intraday.application.services.strategy_configuration import StrategyConfigurationService
from intraday.infrastructure.api.errors import (
    duplicate_version,
    invalid_configuration,
    not_found,
    unknown_strategy,
)
from intraday.infrastructure.api.permissions import IsConfigurationOperator
from intraday.infrastructure.persistence.repositories import DjangoStrategyConfigurationRepository
from intraday.signal_intelligence.feature_engine.field_registry import (
    get_field,
    list_fields,
    resolve_feature_name,
)
from intraday.trading_engine.strategy_execution.contracts import (
    StrategyConfigurationValues,
    coerce_configuration_values,
)
from intraday.trading_engine.strategy_execution.errors import (
    InvalidParameterValueError,
    MissingRequiredParameterError,
    UnknownFieldReferenceError,
    UnknownParameterError,
    UnknownStrategyError,
)
from intraday.trading_engine.strategy_execution.registry import build_default_registry

# Process-local, built once per worker - registration is a code-deploy-
# time fact (Checkpoint 26 Part 8's own reasoning), not per-request
# state. The frontend never maintains a separate strategy list; this
# registry (via the endpoints below) is the single source of truth.
_REGISTRY = build_default_registry()


def _service() -> StrategyConfigurationService:
    return StrategyConfigurationService(
        repository=DjangoStrategyConfigurationRepository(), registry=_REGISTRY
    )


def _resolved_required_features(
    snapshot: StrategyConfigurationSnapshot,
) -> list[dict[str, object]] | None:
    """Checkpoint 64.81 Phase 1: exposes `Strategy.required_features(
    config)` with canonical field identity attached.

    The calculation itself is NOT touched, reimplemented, or second-
    guessed - the strategy's own method is called with the
    configuration's own stored values, and its result is only resolved
    (feature name -> registry `field_id`) and presented.

    THE LIMITATION Phase 1 asks to be documented explicitly: this cannot
    be resolved for EVERY strategy configuration, and pretending
    otherwise would fabricate data. `required_features()` is specified
    over a VALIDATED configuration and reads values directly (e.g.
    `require_int(config.values, "fast_lookback")` in
    `ema_crossover`), so it legitimately raises when a stored
    configuration's values are missing a parameter or hold a type the
    strategy's CURRENT schema no longer accepts - a real possibility,
    since stored configurations are immutable while strategy code
    continues to evolve. Rather than swallow that into a misleading
    empty list (which would assert "needs no features") or invent
    plausible-looking feature names, this returns `None` and the API
    reports `required_features: null`.

    `DECIMAL`-typed values are coerced first via the platform's own
    `coerce_configuration_values()` - the SAME function
    `StrategyConfigurationService.save_configuration()` and
    `BacktestingService.run()` already call before validating - because
    values round-tripped through JSON storage arrive as `str`/`float`,
    never as `Decimal`. Reusing that function rather than re-coercing
    locally is what keeps this read path consistent with the write path.
    """
    try:
        strategy = _REGISTRY.get(snapshot.strategy_id)
    except UnknownStrategyError:
        return None

    try:
        values = coerce_configuration_values(
            strategy.parameter_schema(), dict(snapshot.parameter_values)
        )
        config = StrategyConfigurationValues(
            strategy_id=snapshot.strategy_id,
            specification_version=snapshot.specification_version,
            code_version=snapshot.code_version,
            configuration_version=snapshot.configuration_version,
            values=values,
        )
        feature_names = strategy.required_features(config)
    except Exception:  # noqa: BLE001 - deliberate honest-absence boundary
        # Every failure mode collapses to the same honest answer: this
        # configuration's required features cannot be determined. The
        # exception is deliberately not surfaced as a 500 - listing
        # configurations must not break because one stored row no
        # longer satisfies a strategy's current schema.
        return None

    resolved: list[dict[str, object]] = []
    for feature_name in feature_names:
        resolution = resolve_feature_name(feature_name)
        definition = get_field(resolution.field_id) if resolution.field_id is not None else None
        resolved.append(
            {
                "feature_name": resolution.feature_name,
                "field_id": resolution.field_id,
                "display_name": definition.display_name if definition is not None else None,
                "parameters": list(resolution.parameters),
            }
        )
    return resolved


def _configuration_to_response(snapshot: StrategyConfigurationSnapshot) -> dict[str, object]:
    return {
        "strategy_id": snapshot.strategy_id,
        "specification_version": snapshot.specification_version,
        "code_version": snapshot.code_version,
        "configuration_version": snapshot.configuration_version,
        "values": snapshot.parameter_values,
        "created_at": snapshot.created_at,
        "created_by": snapshot.created_by,
        "required_features": _resolved_required_features(snapshot),
    }


@extend_schema(responses={200: FieldDefinitionSerializer(many=True)})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def field_registry(request: Request) -> Response:
    """Checkpoint 26 Part 4/6: the single canonical source the frontend's
    Field dropdown consumes - no duplicated option array exists in
    frontend code."""
    body = [
        {
            "field_id": f.field_id,
            "display_name": f.display_name,
            "category": f.category.value,
            "data_type": f.data_type.value,
            "source": f.source,
            "timeframe_support": f.timeframe_support,
            "required_inputs": list(f.required_inputs),
            "availability": f.availability.value,
            "version": f.version,
            "description": f.description,
        }
        for f in list_fields()
    ]
    return Response(body)


@extend_schema(responses={200: StrategySummarySerializer(many=True)})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_strategies(request: Request) -> Response:
    """Checkpoint 26 Part 8: the authoritative strategy list - the
    frontend's Strategy dropdown consumes this, never a hardcoded array."""
    body = [
        {
            "strategy_id": s.strategy_id,
            "display_name": s.display_name,
            "specification_version": s.specification_version,
            "code_version": s.code_version,
            "is_active": _REGISTRY.is_active(s.strategy_id),
        }
        for s in _REGISTRY.list()
    ]
    return Response(body)


@extend_schema(responses={200: StrategySchemaSerializer, 404: OpenApiResponse(ApiErrorSerializer)})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def strategy_schema(request: Request, strategy_id: str) -> Response:
    """Checkpoint 26 Part 5/13: the single canonical parameter schema the
    generic frontend renderer consumes - no per-strategy React form."""
    try:
        strategy = _REGISTRY.get(strategy_id)
    except UnknownStrategyError as exc:
        return unknown_strategy(exc)
    schema = strategy.parameter_schema()
    body = {
        "strategy_id": schema.strategy_id,
        "parameters": [
            {
                "parameter_id": p.parameter_id,
                "label": p.label,
                "parameter_type": p.parameter_type.value,
                "required": p.required,
                "default": p.default,
                "minimum": str(p.minimum) if p.minimum is not None else None,
                "maximum": str(p.maximum) if p.maximum is not None else None,
                "allowed_values": list(p.allowed_values),
                "field_category": p.field_category,
                "depends_on": list(p.depends_on),
                "help_text": p.help_text,
            }
            for p in schema.parameters
        ],
    }
    return Response(body)


@extend_schema(
    request=StrategyConfigurationSaveRequestSerializer,
    responses={
        201: StrategyConfigurationResponseSerializer,
        400: OpenApiResponse(ApiErrorSerializer),
        404: OpenApiResponse(ApiErrorSerializer),
        409: OpenApiResponse(ApiErrorSerializer),
    },
)
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsConfigurationOperator])
def save_configuration(request: Request, strategy_id: str) -> Response:
    request_serializer = StrategyConfigurationSaveRequestSerializer(data=request.data)
    request_serializer.is_valid(raise_exception=True)
    data = request_serializer.validated_data

    service = _service()
    try:
        snapshot = service.save_configuration(
            strategy_id,
            data["specification_version"],
            data["code_version"],
            data["configuration_version"],
            dict(data["values"]),
            created_by=request.user.get_username(),
        )
    except UnknownStrategyError as exc:
        return unknown_strategy(exc)
    except (
        InvalidParameterValueError,
        MissingRequiredParameterError,
        UnknownParameterError,
        UnknownFieldReferenceError,
    ) as exc:
        return invalid_configuration(exc)
    except DuplicateVersionError as exc:
        return duplicate_version(exc)

    return Response(_configuration_to_response(snapshot), status=201)


@extend_schema(responses={200: StrategyConfigurationResponseSerializer(many=True)})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_configurations(request: Request, strategy_id: str) -> Response:
    service = _service()
    try:
        snapshots = service.list_configurations(strategy_id)
    except UnknownStrategyError as exc:
        return unknown_strategy(exc)
    return Response([_configuration_to_response(s) for s in snapshots])


@extend_schema(
    responses={
        200: StrategyConfigurationResponseSerializer,
        404: OpenApiResponse(ApiErrorSerializer),
    }
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_configuration(
    request: Request,
    strategy_id: str,
    specification_version: str,
    code_version: str,
    configuration_version: str,
) -> Response:
    service = _service()
    try:
        snapshot = service.get_configuration(
            strategy_id, specification_version, code_version, configuration_version
        )
    except ResourceNotFoundError as exc:
        return not_found(exc)
    return Response(_configuration_to_response(snapshot))
