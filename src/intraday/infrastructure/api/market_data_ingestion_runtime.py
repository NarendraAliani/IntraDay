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
from intraday.domain.market_data.aggregation import BarStatus
from intraday.domain.market_data.contracts import Quote
from intraday.domain.session.calendar import session_for_instant
from intraday.domain.session.contracts import SessionStatus, TradingSession
from intraday.domain.shared_kernel.contracts import Exchange
from intraday.infrastructure.api.emergency_square_off_trigger import (
    check_and_trigger_automatic_square_off,
)
from intraday.infrastructure.api.paper_reconciliation_runtime import reconcile_paper_state
from intraday.infrastructure.api.paper_trading_runtime import get_paper_broker
from intraday.infrastructure.api.position_monitor_runtime import (
    PositionMonitorTickOutcome,
    run_position_monitor_tick,
)
from intraday.infrastructure.api.signal_pipeline_runtime import promote_bars_and_trigger_signals
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
from intraday.infrastructure.persistence.paper_ledger_repository import (
    DjangoPaperLedgerRepository,
)
from intraday.infrastructure.persistence.provider_settings_repositories import (
    DjangoDhanCredentialRepository,
)
from intraday.infrastructure.scheduling.distributed_lock import acquire

logger = structlog.get_logger(__name__)

DEFAULT_STRATEGY_ID = "ema_crossover"
DEFAULT_QUANTITY = Decimal("1")


INGESTION_LOCK_NAME = "market-data-ingestion-tick"


@dataclass(frozen=True, slots=True)
class IngestionTickOutcome:
    ran: bool
    skipped_reason: str | None
    session_status: SessionStatus
    bars_aggregated: int = 0
    bars_promoted: int = 0
    active_loop_invocations: int = 0
    reconciliation_divergence_count: int | None = None
    """`None` when reconciliation was not run this tick (nothing was
    promoted, so there is nothing new to reconcile); an integer
    (possibly 0) once it was."""
    positions_evaluated: int = 0
    exits_triggered: int = 0


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

    with acquire(INGESTION_LOCK_NAME) as lock_acquired:
        if not lock_acquired:
            # Checkpoint 42 Part 10: another tick (a slow-running
            # previous invocation, or a second worker) already holds
            # this lock - skip rather than run concurrently. This is
            # an ORDINARY outcome for a scheduled tick, not an error.
            logger.info("market_data_ingestion.skipped", reason="lock_held_by_another_tick")
            return IngestionTickOutcome(
                ran=False, skipped_reason="lock_held_by_another_tick", session_status=session.status
            )
        return _run_locked(session=session, clock=clock)


def _run_locked(*, session: TradingSession, clock: dt.datetime) -> IngestionTickOutcome:
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

    # Checkpoint 44 Part 3/4 (closing POS-003, named by Checkpoint 43's
    # own gap register): position monitoring now runs EVERY tick using
    # the freshly-fetched quote prices, independent of whether this
    # tick also produced a new signal - an open position must be
    # watched on every price update, not only on ticks that happen to
    # coincide with a fresh entry.
    current_prices = {str(q.instrument_id): q.last_price for q in quotes}
    try:
        monitor_outcome = run_position_monitor_tick(current_prices=current_prices, now=clock)
    except Exception:  # noqa: BLE001 - position monitoring must never break ingestion
        logger.exception("market_data_ingestion.position_monitor_failed")
        monitor_outcome = PositionMonitorTickOutcome(
            positions_evaluated=0, exits_triggered=0, exit_decisions=()
        )
    if monitor_outcome.exits_triggered > 0:
        logger.info(
            "market_data_ingestion.position_exits_triggered",
            exits_triggered=monitor_outcome.exits_triggered,
        )

    # Checkpoint 46 Part 2: THE named P0 gap from Checkpoint 45's own
    # register - a HALTED kill switch now automatically drives the
    # system toward zero open exposure, every tick, idempotently (a
    # no-op after the first tick that handles a given halt event).
    # Cheap and safe to call unconditionally - it internally checks
    # whether the kill switch is even engaged before doing anything.
    try:
        square_off_outcome = check_and_trigger_automatic_square_off(
            current_prices=current_prices, now=clock
        )
        if square_off_outcome.kill_switch_engaged and not square_off_outcome.already_handled:
            logger.warning(
                "market_data_ingestion.automatic_square_off_ran",
                zero_exposure_confirmed=square_off_outcome.zero_exposure_confirmed,
            )
    except Exception:  # noqa: BLE001 - must never break ingestion, but always logged
        logger.exception("market_data_ingestion.automatic_square_off_check_failed")

    bar_service = BarAggregationService(
        quote_repository=DjangoLiveQuoteRepository(),
        bar_repository=DjangoAggregatedBarRepository(),
    )
    aggregation_result = bar_service.aggregate_and_persist(as_of=clock)
    closed_bar_count = sum(1 for b in aggregation_result.bars if b.status is BarStatus.CLOSED)

    # Checkpoint 64.2: this promotion-gate -> strategy/signal/risk/
    # paper trigger sequence is now shared with the live WebSocket
    # worker (`signal_pipeline_runtime.py`) - never a second,
    # duplicated implementation of this same logic.
    pipeline_outcome = promote_bars_and_trigger_signals(
        aggregation_result,
        session=session,
        clock=clock,
        # This tick itself just completed a successful HTTP round trip
        # - that IS the connection-health signal for the REST path.
        connection_is_healthy=True,
        strategy_id=DEFAULT_STRATEGY_ID,
        quantity=DEFAULT_QUANTITY,
    )
    promoted_count = pipeline_outcome.promoted_count
    active_loop_invocations = pipeline_outcome.active_loop_invocations

    reconciliation_divergence_count: int | None = None
    if active_loop_invocations > 0 or monitor_outcome.exits_triggered > 0:
        # Checkpoint 42 Part 11: reconciliation runs automatically
        # "after order/fill events" - a tick that actually submitted a
        # paper order is exactly that trigger. Never lets a
        # reconciliation failure mask the ingestion tick's own success -
        # logged, not re-raised, mirroring `market_data_views.py::refresh()`'s
        # own "aggregation must never break refresh" precedent.
        try:
            report = reconcile_paper_state(
                broker=get_paper_broker(), ledger=DjangoPaperLedgerRepository(), now=clock
            )
            reconciliation_divergence_count = report.total_divergence_count
            logger.info(
                "market_data_ingestion.reconciliation_completed",
                divergence_count=reconciliation_divergence_count,
            )
        except Exception:  # noqa: BLE001 - reconciliation must never break ingestion
            logger.exception("market_data_ingestion.reconciliation_failed")

    logger.info(
        "market_data_ingestion.completed",
        instrument_count=len(quotes),
        bars_aggregated=closed_bar_count,
        bars_promoted=promoted_count,
        active_loop_invocations=active_loop_invocations,
    )

    return IngestionTickOutcome(
        ran=True,
        skipped_reason=None,
        session_status=session.status,
        bars_aggregated=closed_bar_count,
        bars_promoted=promoted_count,
        active_loop_invocations=active_loop_invocations,
        reconciliation_divergence_count=reconciliation_divergence_count,
        positions_evaluated=monitor_outcome.positions_evaluated,
        exits_triggered=monitor_outcome.exits_triggered,
    )
