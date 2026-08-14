# File: src/intraday/application/services/backtesting.py
#
# Checkpoint 27 Part 2/24: the ONLY orchestration point that runs a
# backtest. Structurally limited to fixture/historical data - depends
# solely on `HistoricalMarketDataService` (the exact Checkpoint 18/26
# pattern), never on `infrastructure.persistence.live_market_data_repositories`,
# `application.services.bar_aggregation`, or any Dhan module. Proven
# mechanically by
# tests/unit/architecture/test_backtesting_sample_bar_boundary.py.
#
# STRATEGY/FEATURE REUSE: strategies come from the SAME `StrategyRegistry`
# Checkpoint 26 built; feature computation is the SAME
# `compute_feature_series` dispatcher `application.services.
# strategy_execution` already defines - imported and reused here, not
# duplicated.
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

from intraday.application.repositories import BacktestResultRepository
from intraday.application.services.errors import ResourceNotFoundError
from intraday.application.services.market_data import HistoricalMarketDataService
from intraday.application.services.strategy_execution import compute_feature_series
from intraday.research.backtesting import StrategyConfigurationValues, StrategyRegistry
from intraday.research.backtesting.contracts import (
    BacktestConfiguration,
    BacktestResult,
    DataQualityDisclosure,
    DataQualityLabel,
)
from intraday.research.backtesting.engine import run_backtest
from intraday.research.backtesting.serialization import to_json_dict

TRANSACTION_COST_ASSUMPTION = (
    "Brokerage modeled as a flat percentage of notional value on both entry and "
    "exit (MODEL ASSUMPTION - not a verified Indian brokerage/STT/GST formula; "
    "no authoritative source was available to verify against this checkpoint)."
)
SLIPPAGE_ASSUMPTION = (
    "Slippage modeled as a flat percentage price adjustment against the trader "
    "on every fill (MODEL ASSUMPTION - not a verified microstructure/liquidity model)."
)
SURVIVORSHIP_BIAS_NOTE = (
    "The historical/fixture data this platform uses does not track delisted or "
    "inactive securities - any backtest universe drawn from currently-listed "
    "instruments only carries survivorship-bias risk. Not institutional-grade."
)
MISSING_BAR_NOTE = (
    "Bars are used exactly as returned by the historical data source; no gap-"
    "filling, interpolation, or synthetic bar is ever fabricated."
)


@dataclass
class BacktestingService:
    market_data: HistoricalMarketDataService
    registry: StrategyRegistry
    repository: BacktestResultRepository

    def run(
        self,
        config: BacktestConfiguration,
        strategy_values: dict[str, object],
        *,
        created_by: str,
    ) -> BacktestResult:
        strategy = self.registry.get(config.strategy_id)
        strategy_config = StrategyConfigurationValues(
            strategy_id=config.strategy_id,
            specification_version=config.specification_version,
            code_version=config.code_version,
            configuration_version=config.configuration_version,
            values=strategy_values,
        )
        bars = self.market_data.get_bars(
            config.instrument_id, config.timeframe, config.start, config.end
        )
        data_quality = DataQualityDisclosure(
            data_source="HistoricalMarketDataRepository (fixture/historical only)",
            data_quality=DataQualityLabel.FIXTURE_OR_HISTORICAL,
            bar_count=len(bars),
            missing_bar_note=MISSING_BAR_NOTE,
            transaction_cost_assumption=TRANSACTION_COST_ASSUMPTION,
            slippage_assumption=SLIPPAGE_ASSUMPTION,
            survivorship_bias_note=SURVIVORSHIP_BIAS_NOTE,
        )
        result = run_backtest(
            bars,
            strategy,
            strategy_config,
            config,
            compute_feature_series,
            data_quality=data_quality,
            generated_at=_dt.datetime.now(tz=_dt.UTC),
        )
        self.repository.save(
            result.backtest_id,
            config.strategy_id,
            to_json_dict(result),
            created_by=created_by,
            created_at=result.generated_at,
        )
        return result

    def get_result(self, backtest_id: str) -> dict[str, object]:
        payload = self.repository.get(backtest_id)
        if payload is None:
            raise ResourceNotFoundError(f"no backtest result found for {backtest_id!r}")
        return payload

    def list_results(self, strategy_id: str) -> tuple[dict[str, object], ...]:
        self.registry.get(strategy_id)  # raises UnknownStrategyError if absent
        return self.repository.list_for_strategy(strategy_id)
