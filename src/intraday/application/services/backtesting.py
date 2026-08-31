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
from intraday.application.services.research_data_gate import ResearchDataGateService
from intraday.application.services.strategy_execution import compute_feature_series
from intraday.domain.instrument.contracts import parse_instrument_id
from intraday.domain.session.resolver import CASH_EQUITY_SEGMENT
from intraday.research.backtesting import (
    StrategyConfigurationValues,
    StrategyRegistry,
    coerce_configuration_values,
)
from intraday.research.backtesting.contracts import (
    BacktestConfiguration,
    BacktestResult,
    DataQualityDisclosure,
    DataQualityLabel,
)
from intraday.research.backtesting.cost_model import (
    CostModel,
    FlatPercentageCostModel,
    verified_nse_cash_equity_intraday_cost_model,
)
from intraday.research.backtesting.engine import run_backtest
from intraday.research.backtesting.errors import InvalidBacktestConfigurationError
from intraday.research.backtesting.serialization import to_json_dict

FLAT_PERCENTAGE = "FLAT_PERCENTAGE"
INDIAN_CASH_EQUITY_INTRADAY = "INDIAN_CASH_EQUITY_INTRADAY"
COST_MODEL_NAMES = (FLAT_PERCENTAGE, INDIAN_CASH_EQUITY_INTRADAY)

TRANSACTION_COST_ASSUMPTION_FLAT = (
    "Brokerage modeled as a flat percentage of notional value on both entry and "
    "exit (MODEL ASSUMPTION - not a verified Indian brokerage/STT/GST formula)."
)
TRANSACTION_COST_ASSUMPTION_INDIAN = (
    "VERIFIED NSE cash-equity intraday statutory/exchange schedule (STT, exchange "
    "transaction charges, SEBI turnover fees, GST, stamp duty) - see "
    "docs/architecture/BACKTESTING_ARCHITECTURE.md's source table. Brokerage itself "
    "remains a configurable, broker-representative default, not a verified rate."
)
SLIPPAGE_ASSUMPTION = (
    "Slippage modeled as a flat percentage price adjustment against the trader "
    "on every fill (MODEL ASSUMPTION - not a verified microstructure/liquidity model)."
)


def _build_cost_model(config: BacktestConfiguration, cost_model_name: str) -> CostModel:
    if cost_model_name == FLAT_PERCENTAGE:
        return FlatPercentageCostModel(config.brokerage_percent, config.slippage_percent)
    if cost_model_name == INDIAN_CASH_EQUITY_INTRADAY:
        return verified_nse_cash_equity_intraday_cost_model(
            slippage_percent=config.slippage_percent
        )
    raise InvalidBacktestConfigurationError(
        f"unknown cost_model_name {cost_model_name!r}: must be one of {COST_MODEL_NAMES}"
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
    # Checkpoint 66.1: OPTIONAL research-data eligibility gate
    # (`application.services.research_data_gate.ResearchDataGateService`).
    # Defaults to `None` so every EXISTING caller/test that constructs
    # `BacktestingService` with only `market_data`/`registry`/`repository`
    # (fixture repositories, synthetic-provider engine-correctness tests,
    # etc. — see this class's own module docstring: fixture/historical
    # data only) keeps its EXACT prior behavior with zero code changes.
    # When a caller DOES provide `research_gate` (wired at the real,
    # DB-backed production construction sites —
    # `infrastructure.api.backtesting_views._service()` and
    # `infrastructure.api.tasks.build_historical_backtest_orchestrator()`
    # — see those two call sites for the actual wiring), `run()` reads
    # bars THROUGH the gate instead of directly through `market_data`,
    # so a real backtest can only ever see TRUSTED RESEARCH DATA (Part 7)
    # — never a raw, unvetted `HistoricalBar` row. Any future Gainz
    # backtest entry point that goes through this same `run()` and is
    # constructed with `research_gate` set automatically inherits the
    # identical gate (Part 13) — no separate wiring required.
    research_gate: ResearchDataGateService | None = None

    @classmethod
    def for_database_backed_research(
        cls,
        *,
        market_data: HistoricalMarketDataService,
        registry: StrategyRegistry,
        repository: BacktestResultRepository,
        research_gate: ResearchDataGateService,
    ) -> "BacktestingService":
        """Checkpoint 66.2 Part 1/2: the ONLY constructor a real,
        DB-backed production call site may use — currently exactly
        `infrastructure.api.backtesting_views._service()`'s DB branch
        and `infrastructure.api.tasks.build_historical_backtest_orchestrator()`
        (any future Gainz entry point included, Part 10/13). Unlike the
        plain dataclass constructor above (kept ONLY for the
        deterministic fixture/test engine path — see `research_gate`'s
        own field docstring for exactly why it must stay optional
        there), `research_gate` here is a REQUIRED, non-Optional
        keyword argument — a caller cannot even spell a gate-less call
        to this constructor. The explicit `is None` check below is a
        second, structural belt-and-braces guard against a caller that
        (incorrectly) still passes `research_gate=None` positionally
        through legacy code — it fails LOUD, at construction time,
        rather than allowing `run()` to silently fall back to reading
        raw `HistoricalBar` rows. This is deliberately a NAMED factory,
        not a runtime heuristic (Part 2's explicit prohibition on things
        like `if symbol == "FIXTURE01"`) — which construction path a
        caller uses is an explicit, reviewable choice made once at
        wiring time, never inferred from a request's own data."""
        if research_gate is None:
            raise TypeError(
                "BacktestingService.for_database_backed_research() requires a "
                "non-None research_gate — a production, DB-backed backtest must "
                "never bypass the research-eligibility gate. Use the plain "
                "BacktestingService(...) constructor only for the deterministic "
                "fixture/test engine path (see its module docstring)."
            )
        return cls(
            market_data=market_data,
            registry=registry,
            repository=repository,
            research_gate=research_gate,
        )

    def run(
        self,
        config: BacktestConfiguration,
        strategy_values: dict[str, object],
        *,
        created_by: str,
        cost_model_name: str = FLAT_PERCENTAGE,
    ) -> BacktestResult:
        strategy = self.registry.get(config.strategy_id)
        # A REAL bug found from a live report: `strategy_values` arrives
        # here straight from an API request (JSON has no native Decimal
        # type), so any DECIMAL-typed parameter is still a bare str/
        # float at this point - `coerce_configuration_values()` is the
        # one place that gap is closed, BEFORE strategy execution ever
        # sees these values (see its own docstring for the full
        # account). INTEGER values need no coercion - a JSON number
        # without a decimal point already decodes to a native `int`.
        coerced_values = coerce_configuration_values(strategy.parameter_schema(), strategy_values)
        strategy_config = StrategyConfigurationValues(
            strategy_id=config.strategy_id,
            specification_version=config.specification_version,
            code_version=config.code_version,
            configuration_version=config.configuration_version,
            values=coerced_values,
        )
        cost_model = _build_cost_model(config, cost_model_name)
        if self.research_gate is not None:
            # Checkpoint 66.1 Part 3/4/12: bars are read THROUGH the
            # research-eligibility gate — completeness and provenance
            # have already been enforced by the time `bars` is bound
            # below. `ResearchDataRejectedError` is intentionally left
            # to propagate uncaught (not swallowed/downgraded here) —
            # a rejected research request is a genuine configuration
            # error for the caller to see, exactly like
            # `InvalidBacktestConfigurationError` elsewhere in this
            # method.
            exchange, symbol = parse_instrument_id(config.instrument_id)
            eligible = self.research_gate.get_research_eligible_bars(
                config.instrument_id,
                config.timeframe,
                config.start,
                config.end,
                exchange=exchange,
                segment=CASH_EQUITY_SEGMENT,
                symbol=symbol,
            )
            bars = eligible.bars
        else:
            bars = self.market_data.get_bars(
                config.instrument_id, config.timeframe, config.start, config.end
            )
        cost_assumption = (
            TRANSACTION_COST_ASSUMPTION_INDIAN
            if cost_model_name == INDIAN_CASH_EQUITY_INTRADAY
            else TRANSACTION_COST_ASSUMPTION_FLAT
        )
        data_quality = DataQualityDisclosure(
            data_source="HistoricalMarketDataRepository (fixture/historical only)",
            data_quality=DataQualityLabel.FIXTURE_OR_HISTORICAL,
            bar_count=len(bars),
            missing_bar_note=MISSING_BAR_NOTE,
            transaction_cost_assumption=cost_assumption,
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
            cost_model=cost_model,
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
