# File: src/intraday/application/services/market_data_sync_run.py
#
# Follow-up to Checkpoint 63.x: the orchestration service behind the
# Settings page's manual "fetch real historical data into the database"
# trigger. Deliberately the SIMPLER sibling of
# `historical_backtest_run.py`'s `HistoricalBacktestRunOrchestrator` -
# same per-combination, real-progress-only mutation discipline, but no
# scan/strategy step: this run exists purely to populate `HistoricalBar`
# via `HistoricalDataPreparationService.prepare()`, the SAME service the
# backtest orchestrator already depends on (never a second, parallel
# fetch path).
#
# MULTI-TIMEFRAME DESIGN (an explicit, approved decision, not a default):
# a run covers every (instrument_id, timeframe) COMBINATION from its own
# `instrument_ids x timeframes` cross product, with ONE combined
# progress bar - `total_combinations`/`completed_combinations` count
# combinations, not instruments. One bad combination never aborts the
# rest of the run (same discipline `HistoricalBacktestRunOrchestrator`
# established).
from __future__ import annotations

import datetime as _dt
import itertools
from dataclasses import dataclass

from intraday.application.repositories.market_data_sync_run import MarketDataSyncRunRepository
from intraday.application.services.historical_data_preparation import (
    HistoricalDataPreparationService,
    PreparationStatus,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.session.calendar import build_session_for
from intraday.domain.shared_kernel.contracts import Exchange, InstrumentId, Timeframe


def _instrument_id_from_str(raw: str) -> InstrumentId:
    exchange_str, _, symbol = raw.partition(":")
    return make_instrument_id(Exchange(exchange_str), symbol)


def range_bounds(start_date: _dt.date, end_date: _dt.date) -> tuple[_dt.datetime, _dt.datetime]:
    """Same UTC-instant range computation `historical_backtest_run.py`'s
    own `range_bounds` uses - not duplicated logic, just not importable
    from there without crossing this service's own module boundary, so
    mirrored verbatim (both are one-line wrappers over
    `domain.session.calendar.build_session_for`)."""
    now = _dt.datetime.now(tz=_dt.UTC)
    start_session = build_session_for(start_date, now)
    end_session = build_session_for(end_date, now)
    return start_session.market_open, end_session.market_close


@dataclass
class MarketDataSyncRunOrchestrator:
    run_repository: MarketDataSyncRunRepository
    preparation: HistoricalDataPreparationService

    def run(self, run_id: str) -> None:
        snapshot = self.run_repository.get(run_id)
        if snapshot is None:
            raise ValueError(f"no MarketDataSyncRun found for run_id={run_id!r}")

        self.run_repository.update(
            run_id, status="RUNNING", started_at=_dt.datetime.now(tz=_dt.UTC)
        )

        start, end = range_bounds(snapshot.start_date, snapshot.end_date)

        cache_hits = 0
        bars_fetched = 0
        bars_persisted = 0
        api_requests = 0
        failed_combinations: list[dict[str, str]] = []
        completed = 0

        for raw_instrument_id, raw_timeframe in itertools.product(
            snapshot.instrument_ids, snapshot.timeframes
        ):
            try:
                instrument_id = _instrument_id_from_str(raw_instrument_id)
                timeframe = Timeframe(raw_timeframe)
                self.run_repository.update(
                    run_id,
                    current_instrument=raw_instrument_id,
                    current_timeframe=raw_timeframe,
                    message=f"Fetching {raw_instrument_id} ({raw_timeframe})",
                )

                outcome = self.preparation.prepare(instrument_id, timeframe, start, end)
                cache_hits += outcome.cache_hits
                bars_fetched += outcome.bars_fetched
                bars_persisted += outcome.bars_persisted
                api_requests += outcome.api_requests
                completed += 1

                if outcome.status in (PreparationStatus.FAILED, PreparationStatus.NOT_AVAILABLE):
                    failed_combinations.append(
                        {
                            "instrument_id": raw_instrument_id,
                            "timeframe": raw_timeframe,
                            "reason": outcome.error_message or "historical data unavailable",
                        }
                    )

                self.run_repository.update(
                    run_id,
                    cache_hits=cache_hits,
                    bars_fetched=bars_fetched,
                    bars_persisted=bars_persisted,
                    api_requests=api_requests,
                    completed_combinations=completed,
                    failed_combinations=failed_combinations,
                    progress_percent=round(
                        (completed / max(snapshot.total_combinations, 1)) * 100, 2
                    ),
                    message=f"Completed {raw_instrument_id} ({raw_timeframe})",
                )
            except Exception as exc:  # noqa: BLE001 - one bad combination must never abort the whole run (same discipline as HistoricalBacktestRunOrchestrator)
                completed += 1
                failed_combinations.append(
                    {
                        "instrument_id": raw_instrument_id,
                        "timeframe": raw_timeframe,
                        "reason": str(exc),
                    }
                )
                self.run_repository.update(
                    run_id,
                    completed_combinations=completed,
                    failed_combinations=failed_combinations,
                    progress_percent=round(
                        (completed / max(snapshot.total_combinations, 1)) * 100, 2
                    ),
                    message=(
                        f"Unexpected error fetching {raw_instrument_id} "
                        f"({raw_timeframe}) - skipped"
                    ),
                )
                continue

        if not failed_combinations:
            final_status = "COMPLETED"
        elif len(failed_combinations) < snapshot.total_combinations:
            final_status = "PARTIAL"
        else:
            final_status = "FAILED"

        self.run_repository.update(
            run_id,
            status=final_status,
            completed_at=_dt.datetime.now(tz=_dt.UTC),
            progress_percent=100.0,
            message=f"Market data sync {final_status.lower()}",
        )


__all__ = ["MarketDataSyncRunOrchestrator", "range_bounds"]
