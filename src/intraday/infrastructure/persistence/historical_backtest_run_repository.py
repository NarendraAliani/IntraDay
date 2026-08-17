# File: src/intraday/infrastructure/persistence/historical_backtest_run_repository.py
#
# Checkpoint 63.x: Django ORM implementation of `BacktestRunRepository`.
from __future__ import annotations

from datetime import date
from decimal import Decimal

from intraday.application.repositories.historical_backtest_run import BacktestRunSnapshot
from intraday.infrastructure.persistence.models import BacktestRun


def _to_snapshot(row: BacktestRun) -> BacktestRunSnapshot:
    return BacktestRunSnapshot(
        run_id=row.run_id,
        status=row.status,
        phase=row.phase,
        created_at=row.created_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
        created_by=row.created_by,
        start_date=row.start_date,
        end_date=row.end_date,
        timeframe=row.timeframe,
        instrument_ids=tuple(row.instrument_ids),
        strategy_id=row.strategy_id,
        specification_version=row.specification_version,
        code_version=row.code_version,
        configuration_version=row.configuration_version,
        strategy_values=dict(row.strategy_values),
        cost_model_name=row.cost_model_name,
        initial_capital=row.initial_capital,
        position_sizing_mode=row.position_sizing_mode,
        position_size_value=row.position_size_value,
        brokerage_percent=row.brokerage_percent,
        slippage_percent=row.slippage_percent,
        total_instruments=row.total_instruments,
        completed_instruments=row.completed_instruments,
        total_bars=row.total_bars,
        scanned_bars=row.scanned_bars,
        signals_generated=row.signals_generated,
        cache_hits=row.cache_hits,
        cache_misses=row.cache_misses,
        api_requests=row.api_requests,
        failed_instruments=tuple(row.failed_instruments),
        result_backtest_ids=dict(row.result_backtest_ids),
        error_message=row.error_message,
        progress_percent=float(row.progress_percent),
        current_instrument=row.current_instrument,
        current_strategy=row.current_strategy,
        current_timestamp=row.current_timestamp,
        message=row.message,
    )


class DjangoBacktestRunRepository:
    def create(
        self,
        run_id: str,
        *,
        created_by: str,
        start_date: date,
        end_date: date,
        timeframe: str,
        instrument_ids: list[str],
        strategy_id: str,
        specification_version: str,
        code_version: str,
        configuration_version: str,
        strategy_values: dict[str, object],
        cost_model_name: str,
        initial_capital: Decimal,
        position_sizing_mode: str,
        position_size_value: Decimal,
        brokerage_percent: Decimal,
        slippage_percent: Decimal,
        total_instruments: int,
    ) -> None:
        BacktestRun.objects.create(
            run_id=run_id,
            created_by=created_by,
            start_date=start_date,
            end_date=end_date,
            timeframe=timeframe,
            instrument_ids=instrument_ids,
            strategy_id=strategy_id,
            specification_version=specification_version,
            code_version=code_version,
            configuration_version=configuration_version,
            strategy_values=strategy_values,
            cost_model_name=cost_model_name,
            initial_capital=initial_capital,
            position_sizing_mode=position_sizing_mode,
            position_size_value=position_size_value,
            brokerage_percent=brokerage_percent,
            slippage_percent=slippage_percent,
            total_instruments=total_instruments,
            status="QUEUED",
            phase="QUEUED",
        )

    def update(self, run_id: str, **fields: object) -> None:
        BacktestRun.objects.filter(run_id=run_id).update(**fields)

    def get(self, run_id: str) -> BacktestRunSnapshot | None:
        row = BacktestRun.objects.filter(run_id=run_id).first()
        return _to_snapshot(row) if row is not None else None

    def list_recent(self, limit: int = 20) -> tuple[BacktestRunSnapshot, ...]:
        rows = BacktestRun.objects.all()[:limit]
        return tuple(_to_snapshot(row) for row in rows)


__all__ = ["DjangoBacktestRunRepository"]
