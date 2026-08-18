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

from datetime import UTC, datetime
from decimal import Decimal

import structlog
from celery import shared_task

from intraday.application.services.backtesting import BacktestingService
from intraday.application.services.historical_backtest_run import HistoricalBacktestRunOrchestrator
from intraday.application.services.historical_data_coverage import HistoricalDataCoverageService
from intraday.application.services.historical_data_preparation import (
    HistoricalBarProvider,
    HistoricalDataPreparationService,
)
from intraday.application.services.market_data import HistoricalMarketDataService
from intraday.application.services.market_data_sync_run import MarketDataSyncRunOrchestrator
from intraday.application.services.provider_settings import DhanSettingsService
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
from intraday.infrastructure.market_data_providers.dhan.historical_provider import (
    DhanHistoricalBarProvider,
)
from intraday.infrastructure.market_data_providers.dhan.instrument_master import (
    DhanInstrumentMasterProvider,
)
from intraday.infrastructure.market_data_providers.synthetic_historical import (
    SyntheticHistoricalBarProvider,
)
from intraday.infrastructure.persistence.historical_backtest_run_repository import (
    DjangoBacktestRunRepository,
)
from intraday.infrastructure.persistence.historical_bar_repository import (
    DjangoHistoricalBarRepository,
)
from intraday.infrastructure.persistence.market_data_sync_run_repository import (
    DjangoMarketDataSyncRunRepository,
)
from intraday.infrastructure.persistence.provider_settings_repositories import (
    DjangoDhanCredentialRepository,
)
from intraday.infrastructure.persistence.repositories import DjangoBacktestResultRepository
from intraday.trading_engine.strategy_execution.contracts import StrategyConfigurationValues
from intraday.trading_engine.strategy_execution.registry import build_default_registry

logger = structlog.get_logger(__name__)


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


_HISTORICAL_RUN_REGISTRY = build_default_registry()


def _select_historical_bar_provider() -> HistoricalBarProvider:
    """A REAL bug this fixes, found from a live report: every backtest
    ran on `SyntheticHistoricalBarProvider` - deterministic, seeded,
    FAKE OHLCV - never real market history, regardless of whether the
    operator had genuinely connected their Dhan account (Settings page
    showing "Connected" implied nothing about backtest data quality).
    `DhanHistoricalBarProvider` (a genuine `/v2/charts/historical` +
    `/v2/charts/intraday` REST adapter) is now used whenever Dhan
    credentials are actually configured - the SAME credential source
    `market_data_ingestion_runtime.py` already uses for live quotes, so
    "Connected" on the Settings page now means what it says for
    backtesting too.

    HONEST FALLBACK, not silently masked: with no Dhan credentials
    configured (this project's default dev/test environment - no
    `DHAN_CLIENT_ID`/`DHAN_ACCESS_TOKEN` and no saved credential row),
    this falls back to the synthetic provider so the DB-first pipeline
    (coverage, fetch, persist, scan) remains exercisable without live
    broker credentials - identical in spirit to `dispatch_historical_
    backtest_run`'s own worker-liveness fallback just above."""
    credentials = DhanSettingsService(
        repository=DjangoDhanCredentialRepository()
    ).effective_credentials()
    if credentials is None:
        return SyntheticHistoricalBarProvider()
    client_id, access_token = credentials
    return DhanHistoricalBarProvider(
        client_id=client_id,
        access_token=access_token,
        instrument_master=DhanInstrumentMasterProvider(),
    )


def build_historical_backtest_orchestrator() -> HistoricalBacktestRunOrchestrator:
    """Wires the DB-first orchestrator with its real Django-backed
    dependencies - see `_select_historical_bar_provider()`'s own
    docstring for which historical-data provider this actually uses and
    why."""
    bar_repository = DjangoHistoricalBarRepository()
    return HistoricalBacktestRunOrchestrator(
        run_repository=DjangoBacktestRunRepository(),
        preparation=HistoricalDataPreparationService(
            coverage=HistoricalDataCoverageService(repository=bar_repository),
            provider=_select_historical_bar_provider(),
            writer=bar_repository,
        ),
        backtesting=BacktestingService(
            market_data=HistoricalMarketDataService(repository=bar_repository),
            registry=_HISTORICAL_RUN_REGISTRY,
            repository=DjangoBacktestResultRepository(),
        ),
    )


@shared_task(name="intraday.infrastructure.api.run_historical_backtest_run")  # type: ignore[untyped-decorator]
def run_historical_backtest_run_task(run_id: str) -> str:
    """Checkpoint 63.x: dispatched (`.delay()`) by
    `create_historical_backtest_run_view` so a `BacktestRun`'s
    progress is genuinely pollable from a running background job -
    `CELERY_TASK_ALWAYS_EAGER=True` in the test settings module runs
    this synchronously in-process for tests, while a real deployment
    dispatches it to a Celery worker exactly like `active_loop_tick`/
    `market_data_ingestion_tick` already are."""
    orchestrator = build_historical_backtest_orchestrator()
    try:
        orchestrator.run(run_id)
    except Exception as exc:  # noqa: BLE001 - a run must always end in a terminal, reported state
        DjangoBacktestRunRepository().update(
            run_id,
            status="FAILED",
            phase="FAILED",
            error_message=str(exc),
            completed_at=datetime.now(tz=UTC),
        )
        raise
    return "completed"


def _a_celery_worker_is_actually_listening() -> bool:
    """A SECOND real bug this fixes, found from a live report AFTER the
    first `.delay()`-failure fallback below: `.delay()` only raises if
    the broker itself is unreachable (bad URL, connection refused). If
    the broker (Redis) IS reachable but simply has no worker process
    consuming it - exactly this project's actual situation; no Celery
    worker runs as part of its normal dev flow - `.delay()` succeeds
    silently, the message sits published on the queue forever, and the
    `BacktestRun` row stays at `QUEUED`/0% permanently, with no error
    anywhere to signal it. A "did the publish call raise" check can
    never detect this failure mode. `app.control.ping()` (a short,
    real round-trip asking any live worker to respond) is the only way
    to actually know before committing to the async path - not a
    fixed sleep or a guess."""
    try:
        from intraday.celery import app as celery_app

        return bool(celery_app.control.ping(timeout=0.5))
    except Exception:  # noqa: BLE001 - any inspection failure means "assume no worker"
        return False


def dispatch_historical_backtest_run(run_id: str) -> None:
    """Checkpoint 63.x: dispatches `run_historical_backtest_run_task` for
    `run_id`, preferring the real, asynchronous Celery path (`.delay()`,
    a message published to the configured broker for a worker to pick
    up) exactly like `active_loop_tick`/`market_data_ingestion_tick`
    already do in production - but ONLY when a worker is actually
    verified alive (see `_a_celery_worker_is_actually_listening`'s own
    docstring for the real bug that requires this check, not just a
    try/except around `.delay()` itself).

    A REAL BUG this also fixes: `run_historical_backtest_run_task`
    re-raises after recording a FAILED `BacktestRun` (correct for a
    real Celery worker - it needs the exception for its own retry/
    monitoring), but when this function's own synchronous fallback
    below calls that task directly, that re-raise used to propagate
    all the way up through the view with no handler, producing an
    unhandled Django 500 instead of the clean `202 {run_id}` response
    the caller already has every reason to expect (the run row was
    created successfully; its own FAILED status is what polling exists
    to reveal). The fallback call below swallows the exception here -
    once it's already durably recorded on the `BacktestRun` row, this
    function's job (get the work started, one way or another) is done.

    HONEST FALLBACK: this project has no Celery worker process running
    as part of its normal development flow (no `REDIS_URL` is set by
    default - `settings/base.py`). Rather than requiring every
    developer to stand up Redis + a worker just to exercise this PoC
    feature, running with no live worker falls back to running the
    task inline, synchronously, in the SAME process - identical in
    effect to what `CELERY_TASK_ALWAYS_EAGER=True` already does for
    tests. A real deployment with a configured broker AND a running
    worker is unaffected: the ping succeeds, `.delay()` dispatches, and
    the task runs asynchronously as designed, exactly as intended."""
    if _a_celery_worker_is_actually_listening():
        try:
            run_historical_backtest_run_task.delay(run_id)
            return
        except Exception as delay_exc:  # noqa: BLE001 - falls through to the synchronous path below
            logger.warning(
                "historical_backtest_run.delay_failed_despite_live_worker",
                run_id=run_id,
                error=repr(delay_exc),
            )

    try:
        run_historical_backtest_run_task(run_id)
    except Exception as inner_exc:  # noqa: BLE001 - already recorded as FAILED on the BacktestRun row
        logger.warning(
            "historical_backtest_run.synchronous_fallback_failed",
            run_id=run_id,
            error=repr(inner_exc),
        )


def build_market_data_sync_orchestrator() -> MarketDataSyncRunOrchestrator:
    """Wires the manual data-sync orchestrator - the Settings page's
    "fetch real Dhan data into the database" trigger. Deliberately
    reuses `_select_historical_bar_provider()` (the same real-vs-
    synthetic selection the backtest path uses) and
    `HistoricalDataPreparationService` (the same coverage/fetch/persist
    pipeline) - never a second, parallel fetch implementation."""
    bar_repository = DjangoHistoricalBarRepository()
    return MarketDataSyncRunOrchestrator(
        run_repository=DjangoMarketDataSyncRunRepository(),
        preparation=HistoricalDataPreparationService(
            coverage=HistoricalDataCoverageService(repository=bar_repository),
            provider=_select_historical_bar_provider(),
            writer=bar_repository,
        ),
    )


@shared_task(name="intraday.infrastructure.api.run_market_data_sync_run")  # type: ignore[untyped-decorator]
def run_market_data_sync_run_task(run_id: str) -> str:
    """Dispatched by `create_market_data_sync_run_view` - same eager-in-
    tests / real-worker-in-production behavior `run_historical_backtest_
    run_task` has."""
    orchestrator = build_market_data_sync_orchestrator()
    try:
        orchestrator.run(run_id)
    except Exception as exc:  # noqa: BLE001 - a run must always end in a terminal, reported state
        DjangoMarketDataSyncRunRepository().update(
            run_id, status="FAILED", message=str(exc), completed_at=datetime.now(tz=UTC)
        )
        raise
    return "completed"


def dispatch_market_data_sync_run(run_id: str) -> None:
    """Same real/synchronous-fallback dispatch discipline as
    `dispatch_historical_backtest_run` above - see that function's own
    docstring for the two real bugs (worker-liveness, re-raise-through-
    the-fallback) this mirrors the fix for."""
    if _a_celery_worker_is_actually_listening():
        try:
            run_market_data_sync_run_task.delay(run_id)
            return
        except Exception as delay_exc:  # noqa: BLE001 - falls through to the synchronous path below
            logger.warning(
                "market_data_sync_run.delay_failed_despite_live_worker",
                run_id=run_id,
                error=repr(delay_exc),
            )

    try:
        run_market_data_sync_run_task(run_id)
    except Exception as inner_exc:  # noqa: BLE001 - already recorded as FAILED on the MarketDataSyncRun row
        logger.warning(
            "market_data_sync_run.synchronous_fallback_failed",
            run_id=run_id,
            error=repr(inner_exc),
        )
