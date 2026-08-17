# File: src/intraday/application/services/historical_backtest_run.py
#
# Checkpoint 63.x Phase 9: the orchestration service implementing the
# mandatory 16-step sequence, one instrument at a time, mutating a
# `BacktestRun` row (via `BacktestRunRepository`) as REAL work
# completes — this is the "progress engine" of Phase 13: there is no
# timer anywhere in this file, every `run_repository.update()` call
# follows an action that actually happened (a coverage check completed,
# a fetch completed, a scan completed).
#
# Architecture guarantee this whole checkpoint exists to prove: for
# EVERY instrument, `run()` calls `HistoricalDataPreparationService.
# prepare()` (DB-first coverage/fetch/persist/verify) BEFORE ever
# calling `self.backtesting.run()` — and `self.backtesting` (a
# `BacktestingService` INJECTED at construction time, see
# `infrastructure.api.tasks.build_historical_backtest_orchestrator`) is
# always wired with a DB-backed `HistoricalMarketDataRepository`, never
# the synthetic provider directly; this orchestrator never imports or
# constructs infrastructure itself (`application must not depend on
# infrastructure` — the same import-linter contract every other
# application service in this codebase respects). `research.
# backtesting`'s own import-boundary test
# (`test_backtesting_sample_bar_boundary.py`) already proves
# `research.backtesting` cannot reach a live/API module; this
# orchestrator is the second, complementary proof, at the application
# layer, that a HISTORICAL run's data path is API -> DB -> Scanner,
# never API -> Scanner directly (see this module's own tests,
# `tests/unit/application/services/test_historical_backtest_run_orchestrator.py`).
#
# LIVE/BACKTEST PARITY (Phase 10): `BacktestingService` itself
# (`application.services.backtesting`, Checkpoint 27) is used
# UNMODIFIED — only the `HistoricalMarketDataRepository` it is
# constructed with differs (DB-backed here vs. the fixture repository
# elsewhere). Strategy lookup, feature computation, and `run_backtest()`
# are the exact same code path as every other backtest in this project.
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

from intraday.application.repositories.historical_backtest_run import BacktestRunRepository
from intraday.application.services.backtesting import BacktestingService
from intraday.application.services.historical_data_preparation import (
    HistoricalDataPreparationService,
    PreparationStatus,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.session.calendar import build_session_for
from intraday.domain.shared_kernel.contracts import Exchange, InstrumentId, Timeframe
from intraday.research.backtesting.contracts import BacktestConfiguration, PositionSizingMode
from intraday.research.backtesting.errors import (
    InsufficientHistoricalDataError,
    InvalidBacktestConfigurationError,
)


def _instrument_id_from_str(raw: str) -> InstrumentId:
    exchange_str, _, symbol = raw.partition(":")
    return make_instrument_id(Exchange(exchange_str), symbol)


def range_bounds(start_date: _dt.date, end_date: _dt.date) -> tuple[_dt.datetime, _dt.datetime]:
    """The full UTC instant range a historical run's start/end DATES
    cover: the first day's market_open through the last day's
    market_close, per `domain.session.calendar`'s own NSE-hours
    computation - no separate hour convention invented here."""
    now = _dt.datetime.now(tz=_dt.UTC)
    start_session = build_session_for(start_date, now)
    end_session = build_session_for(end_date, now)
    return start_session.market_open, end_session.market_close


@dataclass
class HistoricalBacktestRunOrchestrator:
    run_repository: BacktestRunRepository
    preparation: HistoricalDataPreparationService
    backtesting: BacktestingService

    def run(self, run_id: str) -> None:
        snapshot = self.run_repository.get(run_id)
        if snapshot is None:
            raise ValueError(f"no BacktestRun found for run_id={run_id!r}")

        self.run_repository.update(
            run_id,
            status="RUNNING",
            phase="ANALYZING_DATA_COVERAGE",
            started_at=_dt.datetime.now(tz=_dt.UTC),
        )

        timeframe = Timeframe(snapshot.timeframe)
        start, end = range_bounds(snapshot.start_date, snapshot.end_date)

        cache_hits = 0
        cache_misses = 0
        api_requests = 0
        total_bars = 0
        scanned_bars = 0
        signals_generated = 0
        failed_instruments: list[dict[str, str]] = []
        result_backtest_ids: dict[str, str] = {}
        completed = 0

        for raw_instrument_id in snapshot.instrument_ids:
            instrument_id = _instrument_id_from_str(raw_instrument_id)
            self.run_repository.update(
                run_id,
                current_instrument=raw_instrument_id,
                current_strategy=snapshot.strategy_id,
                phase="ANALYZING_DATA_COVERAGE",
                message=f"Checking database coverage for {raw_instrument_id}",
            )

            outcome = self.preparation.prepare(instrument_id, timeframe, start, end)
            cache_hits += outcome.cache_hits
            api_requests += outcome.api_requests
            if outcome.bars_fetched:
                cache_misses += outcome.bars_fetched
                self.run_repository.update(
                    run_id,
                    phase="FETCHING_HISTORICAL_DATA",
                    message=f"Fetched {outcome.bars_fetched} missing bars for {raw_instrument_id}",
                )
                self.run_repository.update(run_id, phase="VALIDATING_DATA")
                self.run_repository.update(
                    run_id,
                    phase="PERSISTING_DATA",
                    message=f"Persisted {outcome.bars_persisted} bars for {raw_instrument_id}",
                )

            self.run_repository.update(
                run_id, cache_hits=cache_hits, cache_misses=cache_misses, api_requests=api_requests
            )

            if outcome.status in (PreparationStatus.FAILED, PreparationStatus.NOT_AVAILABLE):
                failed_instruments.append(
                    {
                        "instrument_id": raw_instrument_id,
                        "reason": outcome.error_message or "historical data unavailable",
                    }
                )
                completed += 1
                self.run_repository.update(
                    run_id,
                    completed_instruments=completed,
                    failed_instruments=failed_instruments,
                    progress_percent=round(
                        (completed / max(snapshot.total_instruments, 1)) * 100, 2
                    ),
                    message=f"Data unavailable for {raw_instrument_id} - skipped",
                )
                continue

            self.run_repository.update(
                run_id, phase="PREPARING_SCAN", message=f"Preparing scan for {raw_instrument_id}"
            )

            self.run_repository.update(
                run_id,
                phase="SCANNING",
                message=f"Scanning {raw_instrument_id} with {snapshot.strategy_id}",
            )
            config = BacktestConfiguration(
                instrument_id=instrument_id,
                timeframe=timeframe,
                start=start,
                end=end,
                strategy_id=snapshot.strategy_id,
                specification_version=snapshot.specification_version,
                code_version=snapshot.code_version,
                configuration_version=snapshot.configuration_version,
                initial_capital=snapshot.initial_capital,
                position_sizing_mode=PositionSizingMode(snapshot.position_sizing_mode),
                position_size_value=snapshot.position_size_value,
                brokerage_percent=snapshot.brokerage_percent,
                slippage_percent=snapshot.slippage_percent,
            )

            try:
                result = self.backtesting.run(
                    config,
                    dict(snapshot.strategy_values),
                    created_by=snapshot.created_by,
                    cost_model_name=snapshot.cost_model_name,
                )
            except (InvalidBacktestConfigurationError, InsufficientHistoricalDataError) as exc:
                failed_instruments.append({"instrument_id": raw_instrument_id, "reason": str(exc)})
                completed += 1
                self.run_repository.update(
                    run_id,
                    completed_instruments=completed,
                    failed_instruments=failed_instruments,
                    progress_percent=round(
                        (completed / max(snapshot.total_instruments, 1)) * 100, 2
                    ),
                )
                continue

            bar_count = result.data_quality.bar_count
            total_bars += bar_count
            scanned_bars += bar_count
            signals_generated += len(result.trades)
            result_backtest_ids[raw_instrument_id] = result.backtest_id
            completed += 1

            self.run_repository.update(
                run_id,
                phase="CALCULATING_RESULTS",
                total_bars=total_bars,
                scanned_bars=scanned_bars,
                signals_generated=signals_generated,
                result_backtest_ids=result_backtest_ids,
                completed_instruments=completed,
                progress_percent=round((completed / max(snapshot.total_instruments, 1)) * 100, 2),
                message=f"Completed {raw_instrument_id}: {len(result.trades)} trade(s)",
            )

        self.run_repository.update(run_id, phase="FINALIZING")

        if not failed_instruments:
            final_status = "COMPLETED"
        elif len(failed_instruments) < snapshot.total_instruments:
            final_status = "PARTIAL"
        else:
            final_status = "FAILED"

        self.run_repository.update(
            run_id,
            status=final_status,
            phase=final_status,
            completed_at=_dt.datetime.now(tz=_dt.UTC),
            progress_percent=100.0,
            message=f"Backtest run {final_status.lower()}",
        )


__all__ = ["HistoricalBacktestRunOrchestrator"]
