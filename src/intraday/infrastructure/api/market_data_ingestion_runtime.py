# File: src/intraday/infrastructure/api/market_data_ingestion_runtime.py
#
# Checkpoint 41 Part 3/7/10: the scheduler-invocable market-data
# ingestion tick - "Celery Beat scheduling is NOT an external
# blocker... implement it" (Checkpoint 41's explicit correction to
# Checkpoint 40). Reuses `market_data_views.py::refresh()`'s EXACT
# fetch -> record -> aggregate composition (never a second, parallel
# ingestion path) and adds what a scheduled tick needs beyond a manual
# button click: session gating (never poll outside OPEN), the
# TRADING_GRADE_BAR promotion gate (Checkpoint 40) applied to the
# newly-closed bars, and - only for a genuinely promoted bar -
# triggering `active_loop_runtime.run_active_loop_tick()`.
#
# HONEST, DOCUMENTED LIMITATION: this still calls Dhan's REST quote
# endpoint (Checkpoint 23's `fetch_quotes()`), not a WebSocket feed -
# no WebSocket client exists in this codebase yet (a named, tracked
# gap - see `docs/research/ACTIVE_SYSTEM_OPERATIONAL_BENCHMARK.md`).
# Without real Dhan credentials configured, this tick skips cleanly
# (`credentials_not_configured`) exactly like the existing manual
# refresh button does - it does NOT fabricate data to demonstrate
# activity.
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

import structlog

from intraday.application.services.bar_aggregation import BarAggregationService
from intraday.application.services.live_market_data import LiveMarketDataService
from intraday.application.services.provider_settings import DhanSettingsService
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.aggregation import AggregatedBar, BarQualityGrade, BarStatus
from intraday.domain.market_data.contracts import Quote
from intraday.domain.market_data.promotion import evaluate_bar_promotion
from intraday.domain.session.calendar import session_for_instant
from intraday.domain.session.contracts import SessionStatus
from intraday.domain.shared_kernel.contracts import Exchange
from intraday.infrastructure.api.active_loop_runtime import run_active_loop_tick
from intraday.infrastructure.market_data_providers.dhan.client import (
    DhanAuthenticationError,
    DhanConnectionError,
    DhanMalformedResponseError,
    DhanQuoteObservation,
    fetch_quotes,
)
from intraday.infrastructure.market_data_providers.dhan.instruments import observation_universe
from intraday.infrastructure.persistence.live_market_data_repositories import (
    DjangoAggregatedBarRepository,
    DjangoLiveQuoteRepository,
    DjangoMarketDataHealthRepository,
)
from intraday.infrastructure.persistence.provider_settings_repositories import (
    DjangoDhanCredentialRepository,
)
from intraday.trading_engine.strategy_execution.contracts import StrategyConfigurationValues

logger = structlog.get_logger(__name__)

DEFAULT_STRATEGY_ID = "ema_crossover"
DEFAULT_QUANTITY = Decimal("1")


@dataclass(frozen=True, slots=True)
class IngestionTickOutcome:
    ran: bool
    skipped_reason: str | None
    session_status: SessionStatus
    bars_aggregated: int = 0
    bars_promoted: int = 0
    active_loop_invocations: int = 0


def _observation_to_quote(observation: DhanQuoteObservation) -> Quote:
    """Mirrors `market_data_views.py::_observation_to_quote()` exactly
    - the same, one, canonical Dhan-observation-to-domain-Quote
    conversion, never a second parallel mapping."""
    return Quote(
        instrument_id=make_instrument_id(Exchange.NSE, observation.instrument.symbol),
        timestamp=observation.source_timestamp,
        last_price=observation.last_price,
    )


def run_market_data_ingestion_tick(*, now: dt.datetime | None = None) -> IngestionTickOutcome:
    """The one function a Celery Beat schedule entry calls. Session-
    gates itself (never polls outside `OPEN`), then: fetch real quotes
    -> persist -> aggregate bars -> promotion-gate every newly closed
    bar -> for each genuinely `TRADING_GRADE_BAR`, trigger the active
    loop. Every stage is honestly reported in the returned outcome,
    never silently skipped without a reason."""
    clock = now or dt.datetime.now(tz=dt.UTC)
    session = session_for_instant(clock)

    if session.status is not SessionStatus.OPEN:
        return IngestionTickOutcome(
            ran=False,
            skipped_reason=f"market_session_not_open:{session.status.value}",
            session_status=session.status,
        )

    dhan_service = DhanSettingsService(repository=DjangoDhanCredentialRepository())
    credentials = dhan_service.effective_credentials()
    if credentials is None:
        logger.info("market_data_ingestion.skipped", reason="not_configured")
        return IngestionTickOutcome(
            ran=False, skipped_reason="credentials_not_configured", session_status=session.status
        )

    client_id, access_token = credentials
    live_service = LiveMarketDataService(
        quote_repository=DjangoLiveQuoteRepository(),
        health_repository=DjangoMarketDataHealthRepository(),
    )

    try:
        result = fetch_quotes(
            client_id=client_id, access_token=access_token, instruments=observation_universe()
        )
    except DhanAuthenticationError as exc:
        live_service.record_refresh_failure(checked_at=clock, error_safe=str(exc))
        logger.info("market_data_ingestion.failed", reason="authentication")
        return IngestionTickOutcome(
            ran=False, skipped_reason="authentication_failed", session_status=session.status
        )
    except (DhanConnectionError, DhanMalformedResponseError) as exc:
        live_service.record_refresh_failure(checked_at=clock, error_safe=str(exc))
        logger.info("market_data_ingestion.failed", reason="connection_or_malformed")
        return IngestionTickOutcome(
            ran=False,
            skipped_reason="connection_or_malformed_response",
            session_status=session.status,
        )

    quotes = tuple(_observation_to_quote(observation) for observation in result.observations)
    live_service.record_refresh_success(quotes, fetched_at=result.fetched_at)

    bar_service = BarAggregationService(
        quote_repository=DjangoLiveQuoteRepository(),
        bar_repository=DjangoAggregatedBarRepository(),
    )
    aggregation_result = bar_service.aggregate_and_persist(as_of=clock)
    closed_bars = [b for b in aggregation_result.bars if b.status is BarStatus.CLOSED]

    promoted_count = 0
    active_loop_invocations = 0
    connection_is_healthy = True  # this tick itself just completed a successful HTTP round trip

    by_instrument: dict[str, list[AggregatedBar]] = {}
    for bar in sorted(closed_bars, key=lambda b: b.interval_end):
        by_instrument.setdefault(str(bar.instrument_id), []).append(bar)

    for bars_for_instrument in by_instrument.values():
        preceding: list[AggregatedBar] = []
        for bar in bars_for_instrument:
            promotion = evaluate_bar_promotion(
                bar=bar,
                session=session,
                preceding_bars=tuple(preceding),
                connection_is_healthy=connection_is_healthy,
                now=clock,
            )
            preceding.append(bar)
            if promotion.grade is not BarQualityGrade.TRADING_GRADE_BAR:
                continue
            promoted_count += 1

            configuration = StrategyConfigurationValues(DEFAULT_STRATEGY_ID, "v1", "v1", "v1", {})
            run_active_loop_tick(
                instrument_id=bar.instrument_id,
                strategy_id=DEFAULT_STRATEGY_ID,
                configuration=configuration,
                # The FULL closed-bar history up to and including this
                # bar (not just this one bar) - the strategy coordinator
                # needs warm-up history (e.g. EMA lookback periods) to
                # evaluate correctly, exactly like every other caller of
                # evaluate_and_submit() in this codebase supplies a full
                # series, never a single bar.
                bars=tuple(b.to_bar() for b in preceding),
                quantity=DEFAULT_QUANTITY,
                now=clock,
            )
            active_loop_invocations += 1

    logger.info(
        "market_data_ingestion.completed",
        instrument_count=len(quotes),
        bars_aggregated=len(closed_bars),
        bars_promoted=promoted_count,
        active_loop_invocations=active_loop_invocations,
    )

    return IngestionTickOutcome(
        ran=True,
        skipped_reason=None,
        session_status=session.status,
        bars_aggregated=len(closed_bars),
        bars_promoted=promoted_count,
        active_loop_invocations=active_loop_invocations,
    )
