# File: src/intraday/infrastructure/api/backtesting_views.py
#
# DRF views for the Checkpoint 27 backtesting API resource - the
# single-instrument, synchronous "Run Backtest" flow.
#
# Checkpoint 63.x follow-up: originally this view ran EVERY request
# against the deterministic `FixtureHistoricalMarketDataRepository`
# (Jan 2026, `NSE:FIXTURE01` only) - a genuinely different, unrelated
# data source from the DB-first historical-run panel, meaning any real
# instrument/date typed here always failed with "no bars available."
# Debugged and fixed: `NSE:FIXTURE01` (the literal deterministic
# fixture instrument, still used by the reproducibility test suite)
# keeps using the fixture repository unchanged; every OTHER instrument
# now goes through the SAME DB-first coverage/fetch/persist pipeline
# `HistoricalBacktestRunOrchestrator` uses (`HistoricalDataPreparationService`
# + `DjangoHistoricalBarRepository`) before scanning - so this
# single-instrument flow and the multi-instrument historical-run panel
# are now backed by the same real architecture, not two disconnected
# systems. Neither path ever touches live market data or a broker -
# see `tests/unit/architecture/test_backtesting_sample_bar_boundary.py`,
# which this file remains outside the scope of (it only scans
# `research.backtesting`/`application.services.backtesting`, both
# still untouched).
from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from intraday.application.contracts.backtesting import (
    BacktestResultSerializer,
    BacktestRunRequestSerializer,
)
from intraday.application.contracts.errors import ApiErrorSerializer
from intraday.application.services.backtesting import BacktestingService
from intraday.application.services.errors import ResourceNotFoundError
from intraday.application.services.historical_data_coverage import HistoricalDataCoverageService
from intraday.application.services.historical_data_preparation import (
    HistoricalDataPreparationService,
)
from intraday.application.services.market_data import HistoricalMarketDataService
from intraday.application.services.research_data_gate import ResearchDataGateService
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe
from intraday.infrastructure.api.errors import invalid_configuration, not_found, unknown_strategy
from intraday.infrastructure.api.permissions import IsConfigurationOperator
from intraday.infrastructure.market_data_providers.fixtures import (
    SYNTHETIC_INSTRUMENT_ID,
    FixtureHistoricalMarketDataRepository,
)
from intraday.infrastructure.market_data_providers.synthetic_historical import (
    SyntheticHistoricalBarProvider,
)
from intraday.infrastructure.persistence.historical_bar_repository import (
    DjangoHistoricalBarRepository,
)
from intraday.infrastructure.persistence.repositories import DjangoBacktestResultRepository
from intraday.research.backtesting.contracts import BacktestConfiguration, PositionSizingMode
from intraday.research.backtesting.errors import (
    InsufficientHistoricalDataError,
    InvalidBacktestConfigurationError,
)
from intraday.research.backtesting.serialization import to_json_dict
from intraday.trading_engine.strategy_execution.errors import (
    InvalidParameterValueError,
    MissingRequiredParameterError,
    UnknownFieldReferenceError,
    UnknownParameterError,
    UnknownStrategyError,
)
from intraday.trading_engine.strategy_execution.registry import build_default_registry

_REGISTRY = build_default_registry()


def _service(instrument_id: InstrumentId) -> BacktestingService:
    repository: FixtureHistoricalMarketDataRepository | DjangoHistoricalBarRepository
    if instrument_id == SYNTHETIC_INSTRUMENT_ID:
        # The deterministic fixture flow, unchanged - still what the
        # reproducibility/cost-model test suite exercises. No
        # `HistoricalBar.provenance` concept exists for this fixture
        # repository, so no `research_gate` is wired for it - Checkpoint
        # 66.1 scopes the eligibility gate to genuine DB-backed
        # historical data only, never the deterministic test fixture.
        repository = FixtureHistoricalMarketDataRepository()
        return BacktestingService(
            market_data=HistoricalMarketDataService(repository=repository),
            registry=_REGISTRY,
            repository=DjangoBacktestResultRepository(),
        )
    django_repository = DjangoHistoricalBarRepository()
    # Checkpoint 66.2 Part 1/2: `for_database_backed_research()` — not
    # the plain dataclass constructor — is now the ONLY way this real,
    # DB-backed branch may build a `BacktestingService`. `research_gate`
    # is a required keyword there, so this call site can no longer
    # silently regress to omitting it (66.1's optional field is still
    # correct for the fixture branch above, but this branch is genuine
    # production research data and must never bypass the gate).
    return BacktestingService.for_database_backed_research(
        market_data=HistoricalMarketDataService(repository=django_repository),
        registry=_REGISTRY,
        repository=DjangoBacktestResultRepository(),
        # Checkpoint 66.1: every REAL, DB-backed single-instrument
        # backtest now reads bars through the research-eligibility gate
        # (Part 3/4/12) - completeness + provenance are enforced before
        # `run_backtest()` ever sees a bar.
        research_gate=ResearchDataGateService(
            repository=django_repository,
            coverage_service=HistoricalDataCoverageService(repository=django_repository),
        ),
    )


def _prepare_if_needed(config: BacktestConfiguration) -> None:
    """DB-first preparation for any REAL instrument (never the
    deterministic fixture, which needs no fetching). Mirrors exactly
    what `HistoricalBacktestRunOrchestrator` does for the multi-
    instrument panel - the same coverage-check/fetch-missing/persist/
    verify sequence, just for one instrument inline instead of a
    polled background run, since this view is deliberately still
    synchronous (Checkpoint 27's original design).

    Checkpoint 65.12 note (65.01's root-cause bug #2): this still
    unconditionally constructs `SyntheticHistoricalBarProvider()` for
    every non-fixture instrument, because NO real Dhan historical-
    candle adapter exists in this codebase yet — there is nothing else
    to select between (Part F: building one is out of this
    checkpoint's offline, data-foundation scope). What 65.12 fixes is
    the SILENT part of the bug: `SyntheticHistoricalBarProvider` now
    declares `provenance = PROVENANCE_SYNTHETIC_TEST`
    (`domain.market_data.provenance`) and
    `HistoricalDataPreparationService` stamps every bar it writes with
    that label honestly, instead of the previous undifferentiated
    `source="API_FETCH"` that looked identical to genuine data. The
    day a real adapter exists, selecting it here (mirroring the
    `SYNTHETIC_INSTRUMENT_ID` branch in `_service()` above) is the
    smallest remaining change — no repository, service, or backtest
    code needs to change again."""
    if config.instrument_id == SYNTHETIC_INSTRUMENT_ID:
        return
    bar_repository = DjangoHistoricalBarRepository()
    preparation = HistoricalDataPreparationService(
        coverage=HistoricalDataCoverageService(repository=bar_repository),
        provider=SyntheticHistoricalBarProvider(),
        writer=bar_repository,
    )
    preparation.prepare(config.instrument_id, config.timeframe, config.start, config.end)


@extend_schema(
    request=BacktestRunRequestSerializer,
    responses={
        200: BacktestResultSerializer,
        400: OpenApiResponse(ApiErrorSerializer),
        404: OpenApiResponse(ApiErrorSerializer),
    },
)
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsConfigurationOperator])
def run_backtest_view(request: Request) -> Response:
    request_serializer = BacktestRunRequestSerializer(data=request.data)
    request_serializer.is_valid(raise_exception=True)
    data = request_serializer.validated_data

    try:
        timeframe = Timeframe(data["timeframe"])
    except ValueError as exc:
        return invalid_configuration(exc)

    try:
        config = BacktestConfiguration(
            instrument_id=data["instrument_id"],
            timeframe=timeframe,
            start=data["start"],
            end=data["end"],
            strategy_id=data["strategy_id"],
            specification_version=data["specification_version"],
            code_version=data["code_version"],
            configuration_version=data["configuration_version"],
            initial_capital=data["initial_capital"],
            position_sizing_mode=PositionSizingMode(data["position_sizing_mode"]),
            position_size_value=data["position_size_value"],
            brokerage_percent=data["brokerage_percent"],
            slippage_percent=data["slippage_percent"],
        )
    except InvalidBacktestConfigurationError as exc:
        return invalid_configuration(exc)

    _prepare_if_needed(config)
    service = _service(config.instrument_id)
    try:
        result = service.run(
            config,
            dict(data["strategy_values"]),
            created_by=request.user.get_username(),
            cost_model_name=data["cost_model_name"],
        )
    except UnknownStrategyError as exc:
        return unknown_strategy(exc)
    except (
        InvalidParameterValueError,
        MissingRequiredParameterError,
        UnknownParameterError,
        UnknownFieldReferenceError,
        InsufficientHistoricalDataError,
        InvalidBacktestConfigurationError,
    ) as exc:
        return invalid_configuration(exc)

    return Response(to_json_dict(result))


@extend_schema(responses={200: BacktestResultSerializer, 404: OpenApiResponse(ApiErrorSerializer)})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_backtest_result(request: Request, backtest_id: str) -> Response:
    # Read-only: never touches `.market_data`, so which repository
    # `_service()` wires it with is irrelevant here.
    service = _service(SYNTHETIC_INSTRUMENT_ID)
    try:
        payload = service.get_result(backtest_id)
    except ResourceNotFoundError as exc:
        return not_found(exc)
    return Response(payload)


@extend_schema(responses={200: BacktestResultSerializer(many=True)})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_backtest_results(request: Request, strategy_id: str) -> Response:
    service = _service(SYNTHETIC_INSTRUMENT_ID)
    try:
        payloads = service.list_results(strategy_id)
    except UnknownStrategyError as exc:
        return unknown_strategy(exc)
    return Response(list(payloads))
