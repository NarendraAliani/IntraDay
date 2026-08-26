# File: src/intraday/infrastructure/api/market_data_archive_views.py
#
# Checkpoint 64.83: the READ-ONLY archive + reconciliation query surface.
#
# WHY IT EXISTS: 64.73 built the daily archive and 64.79 built the
# reconciliation comparator, but neither was reachable over HTTP. 64.82's
# own task report named this honestly - every correlation trace carried
# `market_data_outcome_status: "ARCHIVE_API_NOT_IMPLEMENTED"` because no
# archive API existed to consult. These two endpoints close exactly that
# gap and nothing more.
#
# WHY ONLY TWO ENDPOINTS: the directive asks for the smallest composable
# set, preferring filtering over endpoint proliferation. A separate
# `/archive/{date}/{symbol}/` route would return a strict subset of what
# `/archive/{date}/?symbol=X` already returns, at identical query cost,
# while adding a second contract and a second OpenAPI schema to keep
# consistent. `symbol` and `timeframe` are therefore QUERY filters on one
# day resource, and the response echoes the applied filters so a caller
# can never mistake a filtered subset for a whole day.
#
# THIS IS A READ MODEL, NOT A SOURCE OF TRUTH. The archive endpoint
# reads the existing 64.73 `MarketDataArchiveDay` projection through the
# existing repository. The reconciliation endpoint calls the existing
# 64.79 `MarketDataReconciliationService`, which writes NOTHING. No
# status is recomputed, no verdict is invented, and no value is
# defaulted to a plausible guess - see the null rule in
# `application/contracts/market_data_archive.py`.
#
# RBAC (Phase 8): GET-only, `IsAuthenticated`, identical to the 64.82
# correlation surface. No new auth mechanism, no new capability token,
# no write method anywhere.
from __future__ import annotations

from datetime import UTC, date, datetime

from django.utils.dateparse import parse_date
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from intraday.application.contracts.errors import ApiErrorSerializer
from intraday.application.contracts.market_data_archive import (
    ArchiveDayResponseSerializer,
    ReconciliationDayResponseSerializer,
)
from intraday.application.repositories.market_data_archive import ArchiveDayRecord
from intraday.application.services.market_data_archive import MarketDataArchiveService
from intraday.application.services.market_data_reconciliation import (
    MarketDataReconciliationService,
)
from intraday.domain.market_data.reconciliation import ReconciliationReport
from intraday.domain.session.calendar import is_trading_day
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.persistence.market_data_archive_repository import (
    DjangoMarketDataArchiveRepository,
)
from intraday.infrastructure.persistence.market_data_reference_repository import (
    DjangoHistoricalReferenceBarRepository,
)

_EXCHANGE = Exchange.NSE

# The one timeframe reconciliation defaults to. Not a hidden preference:
# 1m is the only timeframe this platform's live aggregation actually
# produces today, and the reconciliation service reconciles ONE timeframe
# per call by design (64.79). The applied value is echoed in the
# response, so the default is never silent.
_DEFAULT_RECONCILIATION_TIMEFRAME = Timeframe.ONE_MINUTE


def _bad_request(message: str) -> Response:
    return Response(
        {"error_code": "invalid_request", "message": message},
        status=status.HTTP_400_BAD_REQUEST,
    )


def _parse_trading_date(raw: str) -> date | None:
    try:
        return parse_date(raw)
    except ValueError:
        return None


def _parse_timeframe(raw: str | None) -> Timeframe | None | str:
    """Returns the `Timeframe`, `None` when absent, or the offending
    string when it names no timeframe this platform models. A bad
    filter is a 400, never a silently-ignored filter that would make a
    filtered response look like an unfiltered one."""
    if raw is None or raw == "":
        return None
    try:
        return Timeframe(raw)
    except ValueError:
        return raw


def _cell_data(record: ArchiveDayRecord) -> dict[str, object]:
    """`ArchiveDayRecord` -> wire shape.

    The null rule lives here: when `completeness_supported` is false, no
    defensible expected-bar series exists for the timeframe, so
    `expected_bar_count` and `missing_bar_count` are `null` rather than
    the stored `0` - which would read as "nothing was expected and
    nothing is missing", a claim this platform cannot make.
    """
    supported = record.completeness_supported
    return {
        "trading_date": record.trading_date,
        "symbol": record.instrument_symbol,
        "timeframe": record.timeframe.value,
        "data_source": record.data_source or None,
        "archive_status": record.status.value,
        "reason": record.reason,
        "completeness_supported": supported,
        "expected_bar_count": record.expected_bar_count if supported else None,
        "closed_bar_count": record.closed_bar_count,
        "forming_bar_count": record.forming_bar_count,
        "missing_bar_count": record.missing_bar_count if supported else None,
        "duplicate_bar_count": record.duplicate_bar_count,
        "quote_observation_count": record.quote_observation_count,
        "first_observation": record.first_observation_at,
        "last_observation": record.last_observation_at,
        "reconciliation_status": record.reconciliation_status.value,
        "reconciled_at": record.reconciled_at,
        "computed_at": record.computed_at,
        # Checkpoint 64.84: the persisted verdict, exposed ALONGSIDE the
        # stored status rather than replacing it - the two remain
        # separate claims, and `archive_status` is never consulted to
        # derive either of them.
        "reconciliation_outcome": record.reconciliation_outcome.value,
        "reconciliation_reason": record.reconciliation_reason,
        # `null`, not `""`: no reconciliation has been persisted, which
        # is a different claim from "reconciled against an unnamed
        # source". Same null rule as the counts above.
        "reconciliation_evidence_source": record.reconciliation_evidence_source or None,
    }


def _reconciliation_cell_data(report: ReconciliationReport) -> dict[str, object]:
    ohlc = tuple(m for m in report.mismatches if m.field_name != "volume")
    volume = tuple(m for m in report.mismatches if m.field_name == "volume")
    compare_volume = report.tolerance.compare_volume
    return {
        "trading_date": report.identity.trading_date,
        "symbol": report.instrument_symbol,
        "timeframe": report.timeframe.value,
        "reconciliation_status": report.outcome.value,
        "reason": report.reason,
        "evidence_source": report.evidence_source,
        # `expected_bar_count` is 0 from the domain both when the
        # timeframe is unsupported AND, in principle, when the session
        # is empty; the reason string carries the unsupported case
        # explicitly, so it is the honest discriminator here.
        "expected_bar_count": (
            None
            if report.reason.startswith("completeness_unsupported_timeframe")
            else report.expected_bar_count
        ),
        "observed_count": report.observed_bar_count,
        "reference_count": report.reference_bar_count,
        "matched_count": report.matched_bar_count,
        "missing_observed_count": len(report.observed_missing_timestamps),
        "missing_reference_count": len(report.reference_missing_timestamps),
        "duplicate_observed_count": len(report.observed_duplicate_timestamps),
        "duplicate_reference_count": len(report.reference_duplicate_timestamps),
        "unmatched_observed_count": len(report.unmatched_observed_timestamps),
        "unmatched_reference_count": len(report.unmatched_reference_timestamps),
        "ohlc_mismatch_count": len(ohlc),
        "volume_compared": compare_volume,
        # `null`, not `0`: volume was not compared at all, which is a
        # different claim from "volume was compared and agreed".
        "volume_mismatch_count": len(volume) if compare_volume else None,
        "timestamp_tolerance_seconds": int(report.tolerance.timestamp.total_seconds()),
        "price_tolerance": report.tolerance.price,
        "observed_first_timestamp": report.observed_first_timestamp,
        "observed_last_timestamp": report.observed_last_timestamp,
        "reference_first_timestamp": report.reference_first_timestamp,
        "reference_last_timestamp": report.reference_last_timestamp,
        "mismatches": [
            {
                "timestamp": m.timestamp,
                "field_name": m.field_name,
                "observed": m.observed,
                "reference": m.reference,
            }
            for m in report.mismatches
        ],
    }


@extend_schema(
    parameters=[
        OpenApiParameter(
            name="symbol",
            description=(
                "Restrict to one instrument symbol (e.g. `RELIANCE`), exactly as archived. "
                "Echoed back as `symbol_filter`."
            ),
            required=False,
            type=str,
        ),
        OpenApiParameter(
            name="timeframe",
            description="Restrict to one timeframe (e.g. `1m`). Echoed back as `timeframe_filter`.",
            required=False,
            type=str,
        ),
    ],
    responses={
        200: ArchiveDayResponseSerializer,
        400: OpenApiResponse(response=ApiErrorSerializer),
    },
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def archive_day(request: Request, trading_date: str) -> Response:
    """Checkpoint 64.83 Phase 3/4: what the archive ACTUALLY holds for
    one NSE trading date, optionally narrowed to one symbol and/or one
    timeframe.

    Reads the existing 64.73 `MarketDataArchiveDay` projection through
    the existing repository - this endpoint recomputes nothing and
    stores nothing.

    A date with no archived cells returns `cells: []` with
    `archive_status: NOT_OBSERVED` rather than a 404: "nothing was
    observed on this day" is a real, reportable state, and for a weekend
    or NSE holiday (`is_trading_day: false`) it is the CORRECT state,
    not a gap. Distinguishing those two is exactly why `is_trading_day`
    is on the wire.

    Query cost is FIXED at one archive query regardless of how many
    symbols the day holds - asserted by `assertNumQueries`.
    """
    parsed = _parse_trading_date(trading_date)
    if parsed is None:
        return _bad_request(f"'{trading_date}' is not a valid ISO-8601 date (YYYY-MM-DD)")

    timeframe = _parse_timeframe(request.query_params.get("timeframe"))
    if isinstance(timeframe, str):
        return _bad_request(f"'{timeframe}' is not a timeframe this platform models")
    symbol = request.query_params.get("symbol") or None

    repository = DjangoMarketDataArchiveRepository()
    service = MarketDataArchiveService(repository, exchange=_EXCHANGE)

    if symbol is None and timeframe is None:
        summary = service.describe_trading_date(trading_date=parsed)
        cells = summary.cells
        day_status = summary.status.value
        symbol_count = summary.symbol_count
        is_trading_day = summary.is_trading_day
    else:
        # The SAME repository method with the SAME indexed filters - a
        # filtered view of one day, never a different query path.
        cells = repository.list_archive_days(
            trading_date=parsed,
            exchange=_EXCHANGE,
            instrument_symbol=symbol,
            timeframe=timeframe,
        )
        unfiltered = service.describe_trading_date(trading_date=parsed)
        # `archive_status` always describes the WHOLE day, never the
        # filtered subset: a caller filtering to one healthy symbol must
        # not see the day reported as healthy.
        day_status = unfiltered.status.value
        symbol_count = unfiltered.symbol_count
        is_trading_day = unfiltered.is_trading_day

    return Response(
        ArchiveDayResponseSerializer(
            {
                "trading_date": parsed,
                "exchange": _EXCHANGE.value,
                "is_trading_day": is_trading_day,
                "archive_status": day_status,
                "symbol_count": symbol_count,
                "cell_count": len(cells),
                "symbol_filter": symbol,
                "timeframe_filter": timeframe.value if timeframe is not None else None,
                "cells": [_cell_data(record) for record in cells],
            }
        ).data
    )


@extend_schema(
    parameters=[
        OpenApiParameter(
            name="symbol",
            description="Reconcile only this instrument symbol. Echoed back as `symbol_filter`.",
            required=False,
            type=str,
        ),
        OpenApiParameter(
            name="timeframe",
            description="Timeframe to reconcile. Defaults to `1m`; the applied value is echoed.",
            required=False,
            type=str,
        ),
    ],
    responses={
        200: ReconciliationDayResponseSerializer,
        400: OpenApiResponse(response=ApiErrorSerializer),
    },
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def reconciliation_day(request: Request, trading_date: str) -> Response:
    """Checkpoint 64.83 Phase 5: the reconciliation evidence for one
    trading date, produced by the EXISTING 64.79
    `MarketDataReconciliationService` - not by a second comparator.

    The service writes nothing, so this endpoint is read-only in the
    strongest sense: calling it can never change what the archive
    claims about a day.

    `PASS` IS NEVER RETURNED BECAUSE THE SERVICE RAN. Against this
    database today every cell returns `NOT_RECONCILED` with reason
    `no_reference_bars_available`, because the only wired reference
    pipeline (Dhan's historical-candle REST API) holds no bars
    overlapping the archived cells. That is the honest result and it is
    reported verbatim.

    A FURTHER LIMITATION, stated on the wire via `evidence_source`: that
    reference pipeline is Dhan, and so is the archive it would check.
    Even a future `PASS` from this source would be Dhan-vs-Dhan
    corroboration and would NOT satisfy TRADING_GRADE_BAR condition 3.
    """
    parsed = _parse_trading_date(trading_date)
    if parsed is None:
        return _bad_request(f"'{trading_date}' is not a valid ISO-8601 date (YYYY-MM-DD)")

    timeframe = _parse_timeframe(request.query_params.get("timeframe"))
    if isinstance(timeframe, str):
        return _bad_request(f"'{timeframe}' is not a timeframe this platform models")
    effective_timeframe = timeframe or _DEFAULT_RECONCILIATION_TIMEFRAME
    symbol = request.query_params.get("symbol") or None

    archive_repository = DjangoMarketDataArchiveRepository()
    reference_repository = DjangoHistoricalReferenceBarRepository()
    service = MarketDataReconciliationService(
        archive_repository, reference_repository, exchange=_EXCHANGE
    )
    as_of = datetime.now(tz=UTC)

    if symbol is None:
        reports = service.reconcile_trading_date(
            trading_date=parsed, timeframe=effective_timeframe, as_of=as_of
        )
    else:
        reports = (
            service.reconcile_cell(
                trading_date=parsed,
                instrument_symbol=symbol,
                timeframe=effective_timeframe,
                as_of=as_of,
            ),
        )

    rollup = MarketDataReconciliationService.summarise(reports)
    return Response(
        ReconciliationDayResponseSerializer(
            {
                "trading_date": parsed,
                "exchange": _EXCHANGE.value,
                "timeframe": effective_timeframe.value,
                "is_trading_day": is_trading_day(parsed),
                "reconciliation_status": rollup.value,
                "evidence_source": reference_repository.describe_source(),
                "cell_count": len(reports),
                "symbol_filter": symbol,
                "cells": [_reconciliation_cell_data(report) for report in reports],
            }
        ).data
    )
