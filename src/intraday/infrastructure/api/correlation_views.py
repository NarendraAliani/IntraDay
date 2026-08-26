# File: src/intraday/infrastructure/api/correlation_views.py
#
# Checkpoint 64.82: the READ-ONLY correlation query surface.
#
# WHY IT EXISTS: Checkpoint 64.81 made the traceability chain
# mechanically joinable (scan_run_id, strategy_version_identifier,
# PaperTradeRecord.signal_id, evidence field_id), but there was no way
# to TRAVERSE it over HTTP - a researcher had to page the signals API,
# then the orders API, then the trades API, and re-join by hand on the
# client. These views do that traversal server-side, in bounded queries,
# using only relationships already stored.
#
# WHY ONLY FOUR ENDPOINTS: the directive lists six candidates and asks
# for the SMALLEST set giving complete traversal with minimal
# duplication. `signals/{id}/orders/` and `signals/{id}/trades/` are
# deliberately NOT built: both are strict subsets of
# `signals/{id}/trace/`, which already returns `orders[]` and `trades[]`
# in the same round trip and at the same cost. Adding them would create
# two more contracts, two more OpenAPI schemas, and two more things to
# keep consistent, for zero information a caller cannot already get.
# `trades/{id}/trace/` (the "optional" candidate) IS built, because
# outcome -> decision is a genuinely different traversal direction that
# no other endpoint provides.
#
# RBAC (Phase 10): every view is GET-only and `IsAuthenticated`, exactly
# matching the read-only `signal_views` / `paper_trading_views` /
# `strategy_configuration_views` endpoints these responses are composed
# from. No new auth mechanism, no new capability token. The data
# returned is the SAME data those endpoints already expose to any
# authenticated user - this checkpoint changes the shape of the answer,
# never who may ask. No credential, token, secret, or stack trace is
# reachable from any response here (no such field is read).
#
# THIS API EXPOSES RECORDED RELATIONSHIPS. IT DOES NOT ESTABLISH
# CAUSALITY BEYOND THE RELATIONSHIPS ALREADY REPRESENTED IN THE DOMAIN.
from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from intraday.application.contracts.correlation import (
    CorrelationScanRunTraceResponseSerializer,
    CorrelationStrategyTraceResponseSerializer,
    CorrelationTraceSerializer,
    CorrelationTradeTraceResponseSerializer,
)
from intraday.application.contracts.errors import ApiErrorSerializer
from intraday.application.contracts.research import ResearchReportSerializer
from intraday.application.services.errors import ResourceNotFoundError
from intraday.infrastructure.persistence.research_correlation import (
    MIN_SAMPLE_SIZE,
    build_research_observations,
    compute_traceability_coverage,
    feature_interaction_analysis,
    feature_outcome_analysis,
    symbol_robustness_analysis,
    time_of_day_analysis,
)
from intraday.infrastructure.api.errors import not_found
from intraday.infrastructure.api.strategy_configuration_views import (
    _resolved_required_features,
)
from intraday.infrastructure.persistence.correlation_repository import (
    CorrelationScanRunTraceView,
    CorrelationTraceView,
    DjangoCorrelationRepository,
)
from intraday.infrastructure.persistence.repositories import (
    DjangoStrategyConfigurationRepository,
)


def _trace_data(trace: CorrelationTraceView) -> dict[str, object]:
    return {
        "signal_id": trace.signal_id,
        "strategy_id": trace.strategy_id,
        "strategy_version_identifier": trace.strategy_version_identifier,
        "scan_run_id": trace.scan_run_id,
        "instrument_id": trace.instrument_id,
        "direction": trace.direction,
        "price": trace.price,
        "timeframe": trace.timeframe,
        "signal_timestamp": trace.signal_timestamp,
        "risk_status": trace.risk_status,
        "order_status": trace.order_status,
        "evidence": [
            {
                "label": f.label,
                "value": f.value,
                "feature_name": f.feature_name,
                "field_id": f.field_id,
            }
            for f in trace.evidence
        ],
        "evidence_schema_version": trace.evidence_schema_version,
        "orders": [
            {
                "order_id": o.order_id,
                "instrument_id": o.instrument_id,
                "side": o.side,
                "order_type": o.order_type,
                "quantity": o.quantity,
                "filled_quantity": o.filled_quantity,
                "status": o.status,
                "created_at": o.created_at,
            }
            for o in trace.orders
        ],
        "trades": [
            {
                "trade_id": t.trade_id,
                "instrument_id": t.instrument_id,
                "direction": t.direction,
                "order_ids": list(t.order_ids),
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "quantity": t.quantity,
                "realized_pnl": t.realized_pnl,
                "costs": t.costs,
                "opened_at": t.opened_at,
                "closed_at": t.closed_at,
            }
            for t in trace.trades
        ],
        "realized_pnl": trace.realized_pnl,
        "market_data_outcome_status": trace.market_data_outcome_status,
    }


def _scan_run_data(view: CorrelationScanRunTraceView) -> dict[str, object]:
    return {
        "scan_run_id": view.scan_run_id,
        "signal_count": view.signal_count,
        "signals": [_trace_data(t) for t in view.signals],
        "strategy_ids": list(view.strategy_ids),
        "scan_started_at": view.scan_started_at,
        "timeframe": view.timeframe,
        "status": view.status,
        "run_metadata_available": view.run_metadata_available,
    }


@extend_schema(
    responses={
        200: CorrelationTraceSerializer,
        404: OpenApiResponse(response=ApiErrorSerializer),
    }
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def signal_trace(request: Request, signal_id: str) -> Response:
    """Checkpoint 64.82 Phase 3: the complete RECORDED lineage of one
    signal - strategy, exact strategy version, originating scanner run,
    the evidence the strategy itself cited, every paper order and paper
    trade carrying this signal's id, and the realised P&L summed over
    those trades.

    Fixed query cost (five queries as of 64.83) regardless of how many orders,
    trades, or evidence rows exist.

    Missing relationships are `null`/`[]`, never inferred: a signal with
    no scanner run, no recorded version, no evidence, no order, or no
    trade is a real and supported state, and this endpoint reports it as
    such rather than guessing a plausible link."""
    trace = DjangoCorrelationRepository().get_signal_trace(signal_id)
    if trace is None:
        return not_found(ResourceNotFoundError(f"No signal found for signal_id '{signal_id}'"))
    return Response(CorrelationTraceSerializer(_trace_data(trace)).data)


@extend_schema(responses={200: CorrelationScanRunTraceResponseSerializer})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def scan_run_signals(request: Request, scan_run_id: str) -> Response:
    """Checkpoint 64.82 Phase 4: every signal RECORDED against one
    scanner run, each as a full trace.

    `scan_run_id` is the existing timestamp-shaped
    `ScannerScanProgress.scan_id` (written by the worker as
    `clock.isoformat()`), used verbatim - deliberately not redesigned
    into a UUID by this checkpoint.

    Query cost is FIXED (six queries as of 64.83) whether the run produced one
    signal or two hundred - see the `assertNumQueries` test.

    An id that matches nothing returns `signal_count: 0` rather than a
    404: stored data cannot distinguish "this run produced no signals"
    from "this run id never existed", and inventing that distinction
    would be a fabricated fact."""
    trace = DjangoCorrelationRepository().get_scan_run_trace(scan_run_id)
    return Response(CorrelationScanRunTraceResponseSerializer(_scan_run_data(trace)).data)


@extend_schema(
    responses={
        200: CorrelationStrategyTraceResponseSerializer,
        404: OpenApiResponse(response=ApiErrorSerializer),
    }
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def strategy_configuration_trace(
    request: Request,
    strategy_id: str,
    specification_version: str,
    code_version: str,
    configuration_version: str,
) -> Response:
    """Checkpoint 64.82 Phase 6: one stored strategy configuration, the
    features it REQUIRES, and every signal recorded against its exact
    flattened version identity.

    `required_features` reuses `strategy_configuration_views.
    _resolved_required_features()` verbatim - the strategy's own
    `required_features(config)` is called, never reimplemented or
    second-guessed, and `null` is returned when it cannot honestly be
    resolved for this stored configuration.

    THE DISTINCTION THIS ENDPOINT PRESERVES: `required_features` is a
    DECLARATION by the configuration. Each trace's `evidence` is what
    the strategy CHOSE TO CITE for that particular signal. They are
    returned as two separate lists and are never merged - a required
    feature appearing here is not a claim that it caused any signal
    below."""
    snapshot = DjangoStrategyConfigurationRepository().get(
        strategy_id=strategy_id,
        specification_version=specification_version,
        code_version=code_version,
        configuration_version=configuration_version,
    )
    if snapshot is None:
        return not_found(
            ResourceNotFoundError(
                f"No stored configuration '{configuration_version}' for strategy '{strategy_id}'"
            )
        )

    # The SAME flattened `"{spec}:{code}:{config}"` identity
    # `DjangoStrategyVersionRepository.activate()` writes into
    # `AuditLogEntry.version_identifier` and 64.81 records on
    # `SignalRecord` - not a second version scheme.
    identifier = (
        f"{snapshot.specification_version}:{snapshot.code_version}:"
        f"{snapshot.configuration_version}"
    )
    repository = DjangoCorrelationRepository()
    records = repository.get_signals_for_version(identifier)
    traces = repository.build_signal_traces(records)

    return Response(
        CorrelationStrategyTraceResponseSerializer(
            {
                "strategy_id": snapshot.strategy_id,
                "specification_version": snapshot.specification_version,
                "code_version": snapshot.code_version,
                "configuration_version": snapshot.configuration_version,
                "strategy_version_identifier": identifier,
                "required_features": _resolved_required_features(snapshot),
                "signal_count": len(traces),
                "signals": [_trace_data(t) for t in traces],
            }
        ).data
    )


@extend_schema(
    responses={
        200: CorrelationTradeTraceResponseSerializer,
        404: OpenApiResponse(response=ApiErrorSerializer),
    }
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def trade_trace(request: Request, trade_id: str) -> Response:
    """Checkpoint 64.82: the REVERSE traversal - realised outcome back to
    the decision that produced it, via `PaperTradeRecord.signal_id`
    (recorded by 64.81 through an ID join from the trade's own
    `order_ids` to its entry order, never string-matched).

    A manually-submitted trade genuinely has no signal behind it. That
    is reported as `signal_id: null, trace: null` and the traversal
    stops - this endpoint never searches for a plausible signal by
    instrument, timestamp, or price."""
    repository = DjangoCorrelationRepository()
    exists, signal_id = repository.get_trade_signal_id(trade_id)
    if not exists:
        return not_found(ResourceNotFoundError(f"No paper trade found for trade_id '{trade_id}'"))

    trace = repository.get_signal_trace(signal_id) if signal_id is not None else None
    return Response(
        CorrelationTradeTraceResponseSerializer(
            {
                "trade_id": trade_id,
                "signal_id": signal_id,
                "trace": _trace_data(trace) if trace is not None else None,
            }
        ).data
    )


@extend_schema(responses={200: ResearchReportSerializer})
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def research_report(request: Request, *_args: object, **_kwargs: object) -> Response:
    """Checkpoint 64.89: the read-only historical RESEARCH report -
    traceability coverage, feature/outcome analysis, feature interaction,
    symbol robustness, and time-of-day - computed entirely from the
    EXISTING `DjangoCorrelationRepository` traceability read model (no
    new persistence, no second source of truth for signals/trades/
    outcomes/feature values).

    Every result carries `observation_count` and `status`
    (`OK`/`INSUFFICIENT_SAMPLE`/`NO_DATA`); no mean/win-rate/expectancy
    field is populated below `MIN_SAMPLE_SIZE` observations. This is
    DESCRIPTIVE evidence only - see `research_correlation.py`'s module
    docstring. It is never a causal claim, and no result here is, or
    should be treated as, a production strategy parameter."""
    observations = build_research_observations()
    coverage = compute_traceability_coverage()

    return Response(
        ResearchReportSerializer(
            {
                "min_sample_size": MIN_SAMPLE_SIZE,
                "traceability_coverage": {
                    "total_signals": coverage.total_signals,
                    "signals_with_evidence": coverage.signals_with_evidence,
                    "signals_with_orders": coverage.signals_with_orders,
                    "signals_with_trades": coverage.signals_with_trades,
                    "signals_with_realized_outcome": coverage.signals_with_realized_outcome,
                    "evidence_coverage_pct": coverage.evidence_coverage_pct,
                    "order_coverage_pct": coverage.order_coverage_pct,
                    "trade_coverage_pct": coverage.trade_coverage_pct,
                    "outcome_coverage_pct": coverage.outcome_coverage_pct,
                },
                "feature_outcome": [
                    {
                        "field_id": r.field_id,
                        "observation_count": r.observation_count,
                        "status": r.status.value,
                        "mean_outcome": r.mean_outcome,
                        "median_outcome": r.median_outcome,
                        "win_rate": r.win_rate,
                        "loss_rate": r.loss_rate,
                        "expectancy": r.expectancy,
                        "profit_factor": r.profit_factor,
                    }
                    for r in feature_outcome_analysis(observations)
                ],
                "feature_interaction": [
                    {
                        "field_id_a": r.field_id_a,
                        "field_id_b": r.field_id_b,
                        "observation_count": r.observation_count,
                        "status": r.status.value,
                        "mean_outcome": r.mean_outcome,
                    }
                    for r in feature_interaction_analysis(observations)
                ],
                "symbol_robustness": [
                    {
                        "instrument_id": r.instrument_id,
                        "observation_count": r.observation_count,
                        "status": r.status.value,
                        "mean_outcome": r.mean_outcome,
                        "win_rate": r.win_rate,
                    }
                    for r in symbol_robustness_analysis(observations)
                ],
                "time_of_day": [
                    {
                        "bucket": r.bucket.value,
                        "observation_count": r.observation_count,
                        "status": r.status.value,
                        "mean_outcome": r.mean_outcome,
                        "win_rate": r.win_rate,
                    }
                    for r in time_of_day_analysis(observations)
                ],
            }
        ).data
    )
