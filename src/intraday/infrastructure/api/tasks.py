# File: src/intraday/infrastructure/api/tasks.py
#
# Checkpoint 40 Part 4/7: the FIRST real Celery task in this codebase -
# `celery.py`'s own original docstring said real tasks belong to their
# owning bounded context; this is that task, for the paper active loop
# (`infrastructure/api/active_loop_runtime.py`).
#
# HONEST, DOCUMENTED LIMITATION: this task still requires the CALLER
# (a Celery beat schedule entry, a management command, or - today -
# only a test) to supply `bars` as task arguments. No Dhan WebSocket
# client exists in this codebase (see
# docs/research/ACTIVE_PRODUCT_READINESS_AUDIT.md, "Dhan status") -
# there is therefore nothing that could push live bars INTO this task
# automatically yet. What this task proves is that the REST of the
# active loop (session gating, restart-safe dedup, strategy evaluation,
# communication, risk, paper execution) is genuinely invocable as one
# scheduler-shaped unit of work - the "given bars, do everything"
# half of automation, not the "get bars without a human" half (that
# remains the named, tracked external blocker).
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from celery import shared_task

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.api.active_loop_runtime import run_active_loop_tick
from intraday.infrastructure.api.emergency_square_off_trigger import (
    check_and_trigger_automatic_square_off,
)
from intraday.infrastructure.api.market_data_ingestion_runtime import (
    run_market_data_ingestion_tick,
)
from intraday.trading_engine.strategy_execution.contracts import StrategyConfigurationValues


@shared_task(name="intraday.infrastructure.api.active_loop_tick")  # type: ignore[untyped-decorator]
def active_loop_tick(
    *,
    exchange: str,
    symbol: str,
    strategy_id: str,
    configuration_version: str,
    bar_payloads: list[dict[str, str]],
    quantity: str = "1",
    now_override: str | None = None,
) -> str:
    """Celery-serializable wrapper around `run_active_loop_tick()` -
    plain JSON-friendly arguments only (no `Bar`/`InstrumentId` objects
    cross the task boundary, matching Celery's own JSON-serializer
    default this project already configures). Returns a short status
    string rather than a rich object, since Celery task results are
    themselves serialized and this project has no result-backend
    consumer yet that needs more.

    `now_override` (ISO 8601, optional) exists ONLY so a test can prove
    session-gating deterministically without depending on the real
    wall clock at test-run time - a real scheduled invocation never
    supplies it, always using the genuine current instant."""
    instrument_id = make_instrument_id(Exchange(exchange), symbol)
    bars = tuple(
        Bar(
            instrument_id=instrument_id,
            timeframe=Timeframe(payload["timeframe"]),
            timestamp=datetime.fromisoformat(payload["timestamp"]),
            open=Decimal(payload["open"]),
            high=Decimal(payload["high"]),
            low=Decimal(payload["low"]),
            close=Decimal(payload["close"]),
            volume=Decimal(payload.get("volume", "0")),
        )
        for payload in bar_payloads
    )
    configuration = StrategyConfigurationValues(strategy_id, "v1", "v1", configuration_version, {})

    outcome = run_active_loop_tick(
        instrument_id=instrument_id,
        strategy_id=strategy_id,
        configuration=configuration,
        bars=bars,
        quantity=Decimal(quantity),
        now=datetime.fromisoformat(now_override) if now_override else None,
    )
    if not outcome.ran:
        return f"skipped:{outcome.skipped_reason}"
    return "ran"


@shared_task(name="intraday.infrastructure.api.market_data_ingestion_tick")  # type: ignore[untyped-decorator]
def market_data_ingestion_tick(*, now_override: str | None = None) -> str:
    """Checkpoint 41 Part 3/7: the task the Celery Beat schedule below
    actually invokes on a cadence - THE piece Checkpoint 40 lacked.
    Wraps `run_market_data_ingestion_tick()` (fetch real Dhan quotes ->
    aggregate -> promotion-gate -> trigger the active loop for every
    genuinely promoted bar), reported via a short status string for the
    same reason `active_loop_tick` is."""
    outcome = run_market_data_ingestion_tick(
        now=datetime.fromisoformat(now_override) if now_override else None
    )
    if not outcome.ran:
        return f"skipped:{outcome.skipped_reason}"
    return (
        f"ran:bars_aggregated={outcome.bars_aggregated}"
        f":bars_promoted={outcome.bars_promoted}"
        f":active_loop_invocations={outcome.active_loop_invocations}"
    )


@shared_task(name="intraday.infrastructure.api.emergency_square_off_check_tick")  # type: ignore[untyped-decorator]
def emergency_square_off_check_tick(*, now_override: str | None = None) -> str:
    """Checkpoint 47 Part 4: an INDEPENDENT scheduled task, separate
    from `market_data_ingestion_tick` - the whole point being that
    kill-switch safety must not wait on (or depend on the success of)
    market-data ingestion, which may itself be the failed subsystem an
    emergency square-off exists to protect against. Supplies NO
    caller-side prices (`current_prices={}`) - relying entirely on
    `run_emergency_square_off()`'s own Checkpoint 47 Part 4 fallback to
    `PaperBroker`'s last recorded price, so this task has no dependency
    on a fresh quote fetch having just succeeded."""
    outcome = check_and_trigger_automatic_square_off(
        current_prices={}, now=datetime.fromisoformat(now_override) if now_override else None
    )
    if not outcome.kill_switch_engaged:
        return "not_engaged"
    if outcome.already_handled:
        return "already_handled"
    assert outcome.square_off is not None  # narrows for the f-string below
    return (
        f"handled:positions_closed={outcome.square_off.positions_closed}"
        f":positions_failed={len(outcome.square_off.positions_failed)}"
        f":zero_exposure_confirmed={outcome.zero_exposure_confirmed}"
    )
