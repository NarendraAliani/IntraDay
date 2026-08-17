# File: src/intraday/infrastructure/api/active_loop_runtime.py
#
# Checkpoint 40 Part 3-7: the composition root that turns "a caller
# manually invokes evaluate_and_submit()" into "one function a
# scheduler (Celery task, see src/intraday/celery.py) can call
# repeatedly, safely." Lives in `infrastructure/api/`, matching the
# exact precedent `paper_trading_runtime.py`/
# `paper_reconciliation_runtime.py` already established (Decision 153):
# this module composes concrete infrastructure
# (`PaperBroker`/`DjangoPaperLedgerRepository`/communication providers)
# and would break `.importlinter` contract 6 if placed in
# `application/services/` instead.
#
# HONEST, DOCUMENTED LIMITATION (Checkpoint 40's own explicit
# requirement, Part 23; STILL TRUE after Checkpoint 52 - see below):
# `run_active_loop_tick()` itself does NOT connect to any live
# market-data source. It still requires the CALLER to supply `bars` -
# there is no Dhan WebSocket client in this codebase yet (see
# `docs/architecture/ACTIVE_PRODUCT_GAP_REGISTER.md`).
#
# Checkpoint 52 ADDS `run_active_loop_tick_from_source()` - a thin
# wrapper that pulls bars from any `application.repositories.
# live_market_data.BarSource` (the new canonical, technology-neutral
# boundary) and forwards them to `run_active_loop_tick()` unchanged.
# This is the SHAPE a real Dhan-tick-driven feed would plug into; the
# ONLY concrete `BarSource` this checkpoint implements is
# `infrastructure/market_data_providers/replay/
# DeterministicReplayBarSource` - explicitly, repeatedly labelled
# REPLAY, never live-market-data evidence. Building a real Dhan-backed
# `BarSource` remains a separate, undone, NAMED dependency.
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from intraday.application.repositories.live_market_data import BarSource
from intraday.application.services.paper_signal_execution import PaperSignalExecutionService
from intraday.application.services.paper_trading import PaperTradingService
from intraday.application.services.signal_communication import SignalCommunicationService
from intraday.application.services.strategy_execution import build_coordinator
from intraday.domain.market_data.contracts import Bar
from intraday.domain.session.calendar import session_for_instant
from intraday.domain.session.contracts import SessionStatus
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe
from intraday.infrastructure.api.paper_trading_runtime import (
    get_paper_trading_service,
    get_signal_communication_service,
)
from intraday.infrastructure.persistence.paper_ledger_repository import (
    DjangoPaperLedgerRepository,
)
from intraday.infrastructure.persistence.signal_repository import DjangoSignalRepository
from intraday.trading_engine.strategy_execution.contracts import StrategyConfigurationValues
from intraday.trading_engine.strategy_execution.registry import build_default_registry

DEFAULT_QUANTITY = Decimal("1")


@dataclass(frozen=True, slots=True)
class ActiveLoopTickOutcome:
    """What one scheduler invocation actually did - always returned,
    never raised for an ordinary "nothing to do" outcome (market
    closed, no bars supplied), so a caller (a Celery task, a test) can
    always tell what happened without inspecting logs."""

    ran: bool
    skipped_reason: str | None
    session_status: SessionStatus


def run_active_loop_tick(
    *,
    instrument_id: InstrumentId,
    strategy_id: str,
    configuration: StrategyConfigurationValues,
    bars: tuple[Bar, ...],
    quantity: Decimal = DEFAULT_QUANTITY,
    data_quality_is_stale: bool = False,
    now: dt.datetime | None = None,
) -> ActiveLoopTickOutcome:
    """The ONE function a scheduler calls repeatedly. Session-gates
    itself (Checkpoint 40 Part 13 - "the worker must not start trading
    on HOLIDAY... must not generate normal entry signals outside
    OPEN"), then evaluates the strategy against `bars` using a
    RESTART-SAFE dedup set reloaded from the durable ledger every
    single call (Checkpoint 39's `load_processed_signal_ids()`) - no
    in-memory state survives between calls, matching how a REAL Celery
    worker process would actually be invoked (a fresh task execution
    each tick, not a long-lived object)."""
    clock = now or dt.datetime.now(tz=dt.UTC)
    session = session_for_instant(clock)

    if session.status is not SessionStatus.OPEN:
        return ActiveLoopTickOutcome(
            ran=False,
            skipped_reason=f"market_session_not_open:{session.status.value}",
            session_status=session.status,
        )

    if not bars:
        return ActiveLoopTickOutcome(
            ran=False, skipped_reason="no_bars_supplied", session_status=session.status
        )

    ledger = DjangoPaperLedgerRepository()
    trading_service: PaperTradingService = get_paper_trading_service()
    communication: SignalCommunicationService = get_signal_communication_service()

    registry = build_default_registry()
    registry.activate(strategy_id)
    coordinator = build_coordinator(registry)

    service = PaperSignalExecutionService(
        coordinator=coordinator,
        paper_trading_service=trading_service,
        quantity=quantity,
        communication=communication,
        signal_recorder=DjangoSignalRepository(),
    )

    already_processed = ledger.load_processed_signal_ids()

    service.evaluate_and_submit(
        bars=bars,
        instrument_id=instrument_id,
        strategy_id=strategy_id,
        configuration=configuration,
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=data_quality_is_stale,
        already_processed_signal_ids=already_processed,
        already_submitted_idempotency_keys=frozenset(),
    )

    return ActiveLoopTickOutcome(ran=True, skipped_reason=None, session_status=session.status)


def run_active_loop_tick_from_source(
    *,
    source: BarSource,
    instrument_id: InstrumentId,
    timeframe: Timeframe,
    strategy_id: str,
    configuration: StrategyConfigurationValues,
    quantity: Decimal = DEFAULT_QUANTITY,
    data_quality_is_stale: bool = False,
    now: dt.datetime | None = None,
) -> ActiveLoopTickOutcome:
    """Checkpoint 52: the scheduler-shaped entry point that no longer
    requires the CALLER to manually slice/assemble `bars` on every
    invocation - it pulls them from `source` (any `BarSource`) itself,
    then delegates to `run_active_loop_tick()` unchanged (never
    reimplements its session-gating, dedup, or order-submission logic).

    Safe to call repeatedly with an advancing `now`/clock, exactly the
    calling pattern a real scheduled task (Celery Beat) would use - the
    underlying `run_active_loop_tick()` call's own idempotency
    (already-processed signal IDs, already-submitted order idempotency
    keys) is what prevents the SAME historical bars, re-supplied by
    `source` on every call, from ever acting twice."""
    clock = now or dt.datetime.now(tz=dt.UTC)
    bars = source.get_bars(instrument_id=instrument_id, timeframe=timeframe, as_of=clock)
    return run_active_loop_tick(
        instrument_id=instrument_id,
        strategy_id=strategy_id,
        configuration=configuration,
        bars=bars,
        quantity=quantity,
        data_quality_is_stale=data_quality_is_stale,
        now=clock,
    )
