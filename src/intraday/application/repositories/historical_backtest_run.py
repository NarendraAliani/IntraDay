# File: src/intraday/application/repositories/historical_backtest_run.py
#
# Checkpoint 63.x: the `BacktestRun` persistence Protocol — deliberately
# a narrow, mutable "job state" interface (unlike every other repository
# in this codebase, which is either append-only or upsert-by-identity),
# because a `BacktestRun` genuinely IS a long-lived, progressively-
# mutated record: the whole point of Phase 13's progress engine is that
# `update()` is called repeatedly as real orchestrator work completes,
# and `get()` is what the progress API polls.
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True, slots=True)
class BacktestRunSnapshot:
    run_id: str
    status: str
    phase: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    created_by: str
    start_date: date
    end_date: date
    timeframe: str
    instrument_ids: tuple[str, ...]
    strategy_id: str
    specification_version: str
    code_version: str
    configuration_version: str
    strategy_values: dict[str, object]
    cost_model_name: str
    initial_capital: Decimal
    position_sizing_mode: str
    position_size_value: Decimal
    brokerage_percent: Decimal
    slippage_percent: Decimal
    total_instruments: int
    completed_instruments: int
    total_bars: int
    scanned_bars: int
    signals_generated: int
    cache_hits: int
    cache_misses: int
    api_requests: int
    failed_instruments: tuple[dict[str, str], ...]
    result_backtest_ids: dict[str, str]
    error_message: str
    progress_percent: float
    current_instrument: str
    current_strategy: str
    current_timestamp: datetime | None
    message: str


class BacktestRunRepository(Protocol):
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
    ) -> None: ...

    def update(self, run_id: str, **fields: object) -> None:
        """Partial update of any `BacktestRun` field by name — the
        orchestrator's one write path for progress reporting."""
        ...

    def get(self, run_id: str) -> BacktestRunSnapshot | None: ...

    def list_recent(self, limit: int = 20) -> tuple[BacktestRunSnapshot, ...]: ...
