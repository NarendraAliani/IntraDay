# File: src/intraday/infrastructure/api/watchlist_market_data_views.py
#
# CHECKPOINT-WATCHLIST-A, Phase A of WATCHLIST_REDESIGN_ROADMAP.md: ONE
# thin, read-only endpoint resolving price/change%/volume/sparkline for
# every instrument in a saved watchlist. Per the roadmap's own explicit
# architecture reasoning: NO new domain/application service - this view
# composes `DjangoHistoricalBarRepository`, `DjangoAggregatedBarRepository`,
# `ResearchDataGateService`, `LiveMarketDataService`, and
# `DjangoWorkerRuntimeStatusRepository` directly, exactly like
# `coverage_preview_view`'s own established shape.
#
# LIVE/HISTORICAL SPLIT (roadmap Part 1 item 4): a watchlist, unlike
# the Screener, must have a working default with NO live infrastructure
# running at all. The envelope `mode` is "LIVE" only when a lightweight
# `WorkerRuntimeStatus.worker_state == "RUNNING"` check passes (never
# the full `evaluate_live_paper_readiness()` gate, which also considers
# the kill switch/session status - irrelevant to a read-only price
# display). "HISTORICAL" is the always-available default.
#
# HONEST DATA-COVERAGE LABELING (reused verbatim from
# CHECKPOINT-SCANNER-B's own `screening_views.py`): daily-bar data
# (change%/sparkline/historical price) is resolved through the REAL
# `ResearchDataGateService`. A `ResearchDataRejectedError` is reported
# as its own `gate_status="NOT_GATE_VERIFIED"` with the gate's own real
# rejection detail - never silently skipped, never a fabricated price.
from __future__ import annotations

import datetime as dt

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from intraday.application.contracts.errors import ApiErrorSerializer
from intraday.application.contracts.watchlist_market_data import (
    WatchlistMarketDataResponseSerializer,
)
from intraday.application.services.errors import ResourceNotFoundError
from intraday.application.services.historical_data_coverage import HistoricalDataCoverageService
from intraday.application.services.live_market_data import LiveMarketDataService
from intraday.application.services.research_data_gate import (
    ResearchDataGateService,
    ResearchDataRejectedError,
)
from intraday.application.services.watchlist import WatchlistService
from intraday.domain.instrument.contracts import make_instrument_id, parse_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.session.calendar import INDIA_STANDARD_TIME
from intraday.domain.shared_kernel.contracts import Exchange, InstrumentId, Timeframe
from intraday.infrastructure.api.errors import not_found, unexpected
from intraday.infrastructure.persistence.historical_bar_repository import (
    DjangoHistoricalBarRepository,
)
from intraday.infrastructure.persistence.live_market_data_repositories import (
    DjangoAggregatedBarRepository,
    DjangoLiveQuoteRepository,
    DjangoMarketDataHealthRepository,
)
from intraday.infrastructure.persistence.repositories import DjangoWatchlistRepository
from intraday.infrastructure.persistence.worker_runtime_status_repository import (
    DjangoWorkerRuntimeStatusRepository,
)

logger = structlog.get_logger(__name__)

_SEGMENT_EQ = "EQ"
_DEFAULT_PROVIDER = "dhan"
_SPARKLINE_TRADING_DAYS = 5
# Wide enough calendar window to reliably contain at least
# `_SPARKLINE_TRADING_DAYS` trading days even across a long weekend or
# a multi-day holiday block - never a literal 5-calendar-day window
# (the roadmap's own explicit "no literal 7-day label" reasoning).
_SPARKLINE_LOOKBACK_CALENDAR_DAYS = 21


def _watchlist_service() -> WatchlistService:
    return WatchlistService(repository=DjangoWatchlistRepository())


def _live_market_data_service() -> LiveMarketDataService:
    return LiveMarketDataService(
        quote_repository=DjangoLiveQuoteRepository(),
        health_repository=DjangoMarketDataHealthRepository(),
    )


def _instrument_id(raw: str) -> InstrumentId:
    exchange_str, _, symbol = raw.partition(":")
    return make_instrument_id(Exchange(exchange_str), symbol)


def _now() -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC)


def _worker_is_running() -> bool:
    """Lightweight Live-mode availability check, per the roadmap's own
    explicit recommendation - NOT the full
    `evaluate_live_paper_readiness()` gate."""
    record = DjangoWorkerRuntimeStatusRepository().get(_DEFAULT_PROVIDER)
    return record is not None and record.worker_state == "RUNNING"


def _last_bar_per_trading_date(bars: tuple[Bar, ...]) -> list[Bar]:
    """Reduces a chronological series of intraday bars to one "daily
    close" per trading date (IST) - the LAST bar observed for each
    date, since `bars` is already chronological (the gate's own
    `ensure_chronological` guarantee). Returned oldest-date first."""
    last_by_date: dict[object, Bar] = {}
    for bar in bars:
        trading_date = bar.timestamp.astimezone(INDIA_STANDARD_TIME).date()
        last_by_date[trading_date] = bar
    return [last_by_date[trading_date] for trading_date in sorted(last_by_date)]


def _resolve_instrument_row(
    raw_id: str,
    instrument_id: InstrumentId,
    *,
    mode: str,
    gate: ResearchDataGateService,
    aggregated_bar_repository: DjangoAggregatedBarRepository,
    live_quotes_by_instrument: dict[InstrumentId, object],
    now: dt.datetime,
) -> dict[str, object]:
    exchange, symbol = parse_instrument_id(instrument_id)

    row: dict[str, object] = {
        "instrument_id": raw_id,
        "gate_status": "OK",
        "coverage_detail": "",
        "price": None,
        "price_source": "",
        "change_percent": None,
        "volume": None,
        "volume_basis": "",
        "sparkline": [],
        "as_of": "",
        "is_stale": False,
    }

    # --- Daily closes derived from gate-verified 5-minute bars: change%,
    # sparkline, and the HISTORICAL price/volume fallback - all gated
    # through the real ResearchDataGateService, exactly the trusted-data
    # boundary `screening_views.py` already established.
    #
    # `Timeframe.DAY` is NOT usable here: `HistoricalDataCoverageService`
    # (confirmed directly, not assumed) computes ZERO expected timestamps
    # for a 1-day bar duration on a CAS-aware continuous-trading session
    # (the duration never fits inside `continuous_trading_open ->
    # continuous_trading_close`), so a `Timeframe.DAY` gate call would
    # always reject as `NO_DATA`. The one granularity this project's own
    # migration checkpoints (83 onward) actually populate and gate-verify
    # is `FIVE_MINUTE` - so each trading day's own last 5-minute bar close
    # is used as that day's close, the same convention an end-of-day chart
    # would use.
    end = now
    start = end - dt.timedelta(days=_SPARKLINE_LOOKBACK_CALENDAR_DAYS)
    try:
        eligible = gate.get_research_eligible_bars(
            instrument_id,
            Timeframe.FIVE_MINUTE,
            start,
            end,
            exchange=exchange,
            segment=_SEGMENT_EQ,
            symbol=symbol,
        )
        daily_closes = _last_bar_per_trading_date(eligible.bars)
        recent_closes = daily_closes[-_SPARKLINE_TRADING_DAYS:]
        latest_bar = recent_closes[-1] if recent_closes else None
        prior_bar = recent_closes[-2] if len(recent_closes) >= 2 else None

        row["sparkline"] = [bar.close for bar in recent_closes]
        if latest_bar is not None:
            row["price"] = latest_bar.close
            row["price_source"] = "HISTORICAL"
            row["volume"] = latest_bar.volume
            row["volume_basis"] = "HISTORICAL_DAY"
            row["as_of"] = f"{latest_bar.timestamp.date().isoformat()} close"
        if latest_bar is not None and prior_bar is not None and prior_bar.close:
            row["change_percent"] = (
                (latest_bar.close - prior_bar.close) / prior_bar.close * 100
            )
    except ResearchDataRejectedError as exc:
        row["gate_status"] = "NOT_GATE_VERIFIED"
        row["coverage_detail"] = f"{exc.reason.value}: {exc}"

    # --- Live overlay: only when the envelope is genuinely LIVE AND a
    # fresh quote actually exists for THIS instrument - falls back
    # silently to the historical row above otherwise (never an error,
    # per the roadmap's own "must work with zero live infrastructure"
    # requirement).
    if mode == "LIVE":
        quote = live_quotes_by_instrument.get(instrument_id)
        if quote is not None:
            age_seconds = (now - quote.timestamp).total_seconds()
            row["price"] = quote.last_price
            row["price_source"] = "LIVE"
            row["as_of"] = quote.timestamp.isoformat()
            row["is_stale"] = age_seconds > 60.0
            session_volume = _session_to_date_volume(
                aggregated_bar_repository, instrument_id, now=now
            )
            if session_volume is not None:
                row["volume"] = session_volume
                row["volume_basis"] = "SESSION_TO_DATE"

    return row


def _session_to_date_volume(
    repository: DjangoAggregatedBarRepository, instrument_id: InstrumentId, *, now: dt.datetime
) -> object | None:
    """Best-effort sum of today's already-aggregated bar volumes for
    ONE instrument, reusing `get_recent()` exactly as it already exists
    (no new repository method) - filtered/summed in Python since the
    existing Protocol has no per-instrument, per-day query. `limit=500`
    is the same bar-aggregation table shared across the whole
    watchlist's own universe, so this is a genuine best-effort figure,
    not a guaranteed-complete session total - see
    WATCHLIST_REDESIGN_ROADMAP.md's own "honest complications" section."""
    today = now.date()
    bars = repository.get_recent(timeframe=Timeframe.ONE_MINUTE, limit=500)
    matching = [
        bar
        for bar in bars
        if bar.instrument_id == instrument_id and bar.interval_start.date() == today
    ]
    if not matching:
        return None
    total = matching[0].volume
    for bar in matching[1:]:
        total = total + bar.volume
    return total


@extend_schema(
    responses={
        200: WatchlistMarketDataResponseSerializer,
        404: OpenApiResponse(ApiErrorSerializer),
    }
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def watchlist_market_data_view(request: Request, name: str) -> Response:
    """Read-only. Never fetches, never persists - reports only what
    `HistoricalBar`/`AggregatedBarObservation`/`LiveQuoteObservation`
    already have for each instrument in the named watchlist."""
    owner = request.user.get_username()
    try:
        instrument_raw_ids = _watchlist_service().get(name, owner)
    except ResourceNotFoundError as exc:
        return not_found(exc)

    now = _now()
    mode = "LIVE" if _worker_is_running() else "HISTORICAL"

    bar_repository = DjangoHistoricalBarRepository()
    coverage_service = HistoricalDataCoverageService(repository=bar_repository)
    gate = ResearchDataGateService(coverage_service=coverage_service, repository=bar_repository)
    aggregated_bar_repository = DjangoAggregatedBarRepository()

    live_quotes_by_instrument: dict[InstrumentId, object] = {}
    if mode == "LIVE":
        for quote in _live_market_data_service().get_quotes():
            live_quotes_by_instrument[quote.instrument_id] = quote

    results = []
    try:
        for raw_id in instrument_raw_ids:
            try:
                instrument_id = _instrument_id(raw_id)
            except (KeyError, ValueError):
                results.append(
                    {
                        "instrument_id": raw_id,
                        "gate_status": "NOT_GATE_VERIFIED",
                        "coverage_detail": f"unparseable instrument id: {raw_id!r}",
                        "price": None,
                        "price_source": "",
                        "change_percent": None,
                        "volume": None,
                        "volume_basis": "",
                        "sparkline": [],
                        "as_of": "",
                        "is_stale": False,
                    }
                )
                continue
            results.append(
                _resolve_instrument_row(
                    raw_id,
                    instrument_id,
                    mode=mode,
                    gate=gate,
                    aggregated_bar_repository=aggregated_bar_repository,
                    live_quotes_by_instrument=live_quotes_by_instrument,
                    now=now,
                )
            )
    except Exception as exc:  # noqa: BLE001 - never let a raw exception become an opaque 500 page
        logger.error("watchlist_market_data.unexpected_error", error=repr(exc))
        return unexpected(exc)

    return Response({"watchlist_name": name, "mode": mode, "results": results})
