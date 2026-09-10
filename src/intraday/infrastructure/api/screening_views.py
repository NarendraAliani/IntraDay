# File: src/intraday/infrastructure/api/screening_views.py
#
# CHECKPOINT-SCANNER-B, Phase B of SCANNER_BUILDER_ROADMAP.md: ONE
# read-only screening endpoint, Historical mode only. Rule + instrument
# universe + date range in, matches out - NO persistence of the rule
# itself (that is Phase D's own concern), NO write of any kind.
#
# ARCHITECTURE BOUNDARY (mechanically enforced, see
# tests/unit/architecture/test_adhoc_screening_boundary.py, extended
# this checkpoint to cover this file too): this view NEVER imports
# `Strategy`/`StrategyRegistry`/`StrategyExecutionCoordinator`/
# `PaperBroker`/`ScannerConfiguration` - it composes ONLY
# `AdhocScreeningService`/`evaluate_condition` (Checkpoint-Scanner-A),
# `ResearchDataGateService` (the SAME trusted-data gate every backtest/
# research consumer in this project already relies on), and the
# existing, read-only `DjangoHistoricalBarRepository`.
#
# HONEST DATA-COVERAGE LABELING (this checkpoint's own explicit
# requirement): a requested instrument's range is run through the REAL
# `ResearchDataGateService` first. A `ResearchDataRejectedError` is
# reported as its own `NOT_GATE_VERIFIED` status with the gate's own
# real rejection detail - never silently skipped, never folded into a
# generic "no match." Only a genuinely gate-verified instrument's bars
# ever reach `AdhocScreeningService.screen()`.
from __future__ import annotations

from decimal import Decimal, InvalidOperation

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from intraday.application.contracts.errors import ApiErrorSerializer
from intraday.application.contracts.screening import (
    ScreeningEvaluateRequestSerializer,
    ScreeningEvaluateResponseSerializer,
)
from intraday.application.services.adhoc_screening import AdhocScreeningService
from intraday.application.services.historical_backtest_run import range_bounds
from intraday.application.services.historical_data_coverage import HistoricalDataCoverageService
from intraday.application.services.research_data_gate import (
    ResearchDataGateService,
    ResearchDataRejectedError,
)
from intraday.domain.instrument.contracts import make_instrument_id, parse_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.screening.contracts import (
    ComparisonOperator,
    RuleCombinator,
    ScreeningCondition,
    ScreeningRule,
)
from intraday.domain.shared_kernel.contracts import Exchange, InstrumentId, Timeframe
from intraday.infrastructure.api.errors import invalid_configuration, unexpected
from intraday.infrastructure.persistence.historical_bar_repository import (
    DjangoHistoricalBarRepository,
)

logger = structlog.get_logger(__name__)

_SEGMENT_EQ = "EQ"


def _instrument_id(raw: str) -> InstrumentId:
    exchange_str, _, symbol = raw.partition(":")
    return make_instrument_id(Exchange(exchange_str), symbol)


def _parse_comparison(raw: str) -> Decimal | str:
    """A comparison target arrives on the wire as a plain string -
    resolved to a `Decimal` constant if it parses as one (the field-vs-
    constant case), otherwise passed through unchanged as a `str` (the
    field-vs-field / categorical-constant case `evaluate_condition`
    itself already disambiguates - see that function's own docstring).
    Never guesses beyond this: `Decimal(raw)` either succeeds or it
    doesn't, no partial-numeric-string special-casing."""
    try:
        return Decimal(raw)
    except InvalidOperation:
        return raw


@extend_schema(
    request=ScreeningEvaluateRequestSerializer,
    responses={
        200: ScreeningEvaluateResponseSerializer,
        400: OpenApiResponse(ApiErrorSerializer),
    },
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def evaluate_screening_rule_view(request: Request) -> Response:
    """Historical mode only (Phase B's own explicit scope - Live mode,
    reading `AggregatedBarObservation`, is Phase C's own concern). A
    read-only, synchronous evaluation - this project's screening
    universe (4-6 symbols) makes a background task/polling mechanism
    (the shape `create_historical_backtest_run_view` needs) genuinely
    unnecessary here; a request completes in well under a second even
    across the full requested range."""
    serializer = ScreeningEvaluateRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    try:
        timeframe = Timeframe(data["timeframe"])
    except ValueError as exc:
        return invalid_configuration(exc)

    conditions: list[ScreeningCondition] = []
    for raw_condition in data["conditions"]:
        try:
            conditions.append(
                ScreeningCondition(
                    field_id=raw_condition["field_id"],
                    operator=ComparisonOperator(raw_condition["operator"]),
                    comparison=_parse_comparison(raw_condition["comparison"]),
                )
            )
        except ValueError as exc:
            return invalid_configuration(exc)
    try:
        rule = ScreeningRule(
            conditions=tuple(conditions), combinator=RuleCombinator(data["combinator"])
        )
    except ValueError as exc:
        return invalid_configuration(exc)

    resolved_instrument_ids: list[InstrumentId] = []
    for raw_id in data["instrument_ids"]:
        try:
            resolved_instrument_ids.append(_instrument_id(raw_id))
        except (KeyError, ValueError) as exc:
            return invalid_configuration(exc)

    start, end = range_bounds(data["start_date"], data["end_date"])

    bar_repository = DjangoHistoricalBarRepository()
    coverage_service = HistoricalDataCoverageService(repository=bar_repository)
    gate = ResearchDataGateService(coverage_service=coverage_service, repository=bar_repository)

    bars_by_instrument: dict[str, tuple[Bar, ...]] = {}
    not_gate_verified: dict[str, str] = {}
    try:
        for instrument_id in resolved_instrument_ids:
            exchange, symbol = parse_instrument_id(instrument_id)
            try:
                eligible = gate.get_research_eligible_bars(
                    instrument_id,
                    timeframe,
                    start,
                    end,
                    exchange=exchange,
                    segment=_SEGMENT_EQ,
                    symbol=symbol,
                )
                bars_by_instrument[str(instrument_id)] = eligible.bars
            except ResearchDataRejectedError as exc:
                not_gate_verified[str(instrument_id)] = f"{exc.reason.value}: {exc}"

        matches = AdhocScreeningService().screen(
            rule,
            tuple(bars_by_instrument.keys()),
            timeframe,
            bars_by_instrument,
        )
    except Exception as exc:  # noqa: BLE001 - never let a raw exception become an opaque 500 page
        logger.error("screening.unexpected_error", error=repr(exc))
        return unexpected(exc)

    matched_ids = {m.instrument_id for m in matches}
    matches_by_id = {m.instrument_id: m for m in matches}

    results = []
    for raw_id in data["instrument_ids"]:
        if raw_id in not_gate_verified:
            results.append(
                {
                    "instrument_id": raw_id,
                    "status": "NOT_GATE_VERIFIED",
                    "matched_condition_details": [],
                    "coverage_detail": not_gate_verified[raw_id],
                }
            )
        elif raw_id in matched_ids:
            results.append(
                {
                    "instrument_id": raw_id,
                    "status": "MATCHED",
                    "matched_condition_details": list(
                        matches_by_id[raw_id].matched_condition_details
                    ),
                    "coverage_detail": "",
                }
            )
        else:
            results.append(
                {
                    "instrument_id": raw_id,
                    "status": "NO_MATCH",
                    "matched_condition_details": [],
                    "coverage_detail": "",
                }
            )

    return Response(
        {
            "mode": "HISTORICAL",
            "results": results,
            "matched_count": len(matched_ids),
            "evaluated_count": len(bars_by_instrument),
            "not_gate_verified_count": len(not_gate_verified),
        }
    )
